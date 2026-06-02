# broadcaster.py Audio Router 
# Reads instruments.json and analysers.json to route per-channel audio from capture.py
# to either WSL receiver or Windows analysers based on each analyser's target.


import socket
import struct
import json
import threading
import os
import time
import numpy as np
import sys
import wave
import hashlib
from collections import deque
from math import gcd
from scipy.signal import resample_poly

# Debugging 
DEBUG = False
INFO = True

# AUDIO DEBUGGING information
_record_buffers = {}
_mix_record_lock = threading.Lock() 

# global Sample rate registry
_instrument_sample_rates = {}  # name -> int (Hz)
_sample_rates_lock = threading.Lock()

AUDIO_DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "audio_debug")
os.makedirs(AUDIO_DEBUG_DIR, exist_ok=True)

# implement silence timeout for our mixed queue. 
MAX_QUEUE_SIZE  = 20    # prevent unbounded memory if one channel races ahead
SILENCE_TIMEOUT = 0.15  # seconds — inject silence if channel stalls beyond this

STOP_SENTINEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "broadcaster.stop")


LOCAL_HOST      = "127.0.0.1"
LOCAL_PORT      = 5005

WSL_HOST        = "172.29.28.224"
WSL_PORT        = 5006

WSL_HEAVY_HOST  = "172.29.28.224"
WSL_HEAVY_PORT        = 5008

WINDOWS_HOST = "127.0.0.1"
WINDOWS_PORT = 5007


CONFIG_POLL_INTERVAL = 2.0 


def get_audio_stats(audio_bytes):
    """Calculate RMS and peak levels for audio chunk"""
    audio = np.frombuffer(audio_bytes, dtype=np.float32)
    rms = np.sqrt(np.mean(audio ** 2))
    peak = np.max(np.abs(audio))
    return rms, peak



# Loads both config files and returns them merged into one dict.
def load_config():
    base_dir         = os.path.dirname(os.path.dirname(__file__))
    instruments_path = os.path.join(base_dir, "config", "instruments.json")
    analysers_path      = os.path.join(base_dir, "config", "analysers.json")


    try:
        with open(instruments_path) as f:
            instruments = json.load(f)
        with open(analysers_path) as f:
            analysers = json.load(f)
        return {
            "instruments": instruments.get("instruments", {}),
            "analysers":      analysers.get("analysers", {})
        }
    except FileNotFoundError as e:
        print(f"[broadcaster] Config file not found: {e} — no instruments active")
        sys.stdout.flush()
        return {"instruments": {}, "analysers": {}}
    except json.JSONDecodeError as e:
        print(f"[broadcaster] Config malformed: {e} — no instruments active")
        sys.stdout.flush()
        return {"instruments": {}, "analysers": {}}


# compare current config 
def config_hash(config):
    return hashlib.md5(json.dumps(config, sort_keys=True).encode()).hexdigest()

# only refresh config if config has changed 
def watch_config(config_holder):
    last_hash = None
    while True:
        time.sleep(CONFIG_POLL_INTERVAL)
        new_config = load_config()
        new_hash = config_hash(new_config)
        if new_hash != last_hash:
            config_holder["config"] = new_config
            last_hash = new_hash
            if INFO : 
                print("[broadcaster] Config changed : reloaded.")
                sys.stdout.flush()


# Returns True if analyser should run on the given side ("wsl" or "windows", or "both").

def _target(analysers_config, analyser_id, side):
    cfg = analysers_config.get(analyser_id, {})
    target = cfg.get("target", "")
    return target == side or target == "both"

# builds a lookup table mapping channel_id -> instrument name and analysers split by target
# so broadcaster can instantly look up routing info for each incoming chunk
def build_channel_map(config):
    channel_map = {}
    analysers_config = config.get("analysers", {})

    # Build alphabetical index map (audio + virtual instruments only — matches receiver logic)
    audio_instruments = sorted(
        n for n, inst in config.get("instruments", {}).items()
        if inst.get("type") in ("audio", "virtual")
    )
    instrument_indices = {n: idx for idx, n in enumerate(audio_instruments)}

    # role_index is stored in instruments.json as the single source of truth.
    # The frontend assigns and resequences it on add/delete/role-change.
    if INFO:
        for n, inst in sorted(config.get("instruments", {}).items()):
            if inst.get("type") == "mix":
                continue
            role = inst.get("role", "default")
            role_idx = inst.get("role_index", 0)
            print(f"[broadcaster] role_index: {n:<20} -> {role}/{role_idx}")
        sys.stdout.flush()

    # Build regular instrument routing
    for name, instrument in config.get("instruments", {}).items():
        if not instrument.get("enabled", False):
            continue

        inst_type  = instrument.get("type")
        mix_source = instrument.get("mix_source")

        # Skip internal mix instruments (they're computed, not captured)
        if inst_type == "mix" and mix_source == "internal":
            continue

        audio_device = instrument.get("audio_device", {})
        channel_id   = audio_device.get("channel")
        if channel_id is None:
            continue

        sample_rate      = audio_device.get("sample_rate", 48000)   # ← pulled from config
        active_analysers = instrument.get("analysers", [])
        role             = instrument.get("role", "default")

        channel_map[channel_id] = {
            "name":                name,
            "role":                role,
            "role_index":          instrument.get("role_index", 0),
            "instrument_index":    instrument_indices.get(name, 0),
            "sample_rate":         sample_rate,
            "wsl_analysers":       [m for m in active_analysers if _target(analysers_config, m, "wsl")],
            "wsl_heavy_analysers": [m for m in active_analysers if _target(analysers_config, m, "wsl_heavy")],
            "windows_analysers":   [m for m in active_analysers if _target(analysers_config, m, "windows")],
        }

        # Register sample rate for save_recording
        with _sample_rates_lock:
            _instrument_sample_rates[name] = sample_rate

        if DEBUG:
            print(f"[broadcaster] Channel {channel_id} -> '{name}' @ {sample_rate}Hz"
                  f" | wsl: {channel_map[channel_id]['wsl_analysers']}"
                  f" | windows: {channel_map[channel_id]['windows_analysers']}")
            sys.stdout.flush()

    # Build mix configurations
    mix_configs = {}

    for mix_name, mix_inst in config.get("instruments", {}).items():
        if mix_inst.get("type") != "mix":
            continue
        if not mix_inst.get("enabled", False):
            continue
        if mix_inst.get("mix_source") != "internal":
            continue

        source_instruments = mix_inst.get("source_instruments", [])
        source_channels    = []

        for inst_name in source_instruments:
            for ch_id, ch_info in channel_map.items():
                if ch_info["name"] == inst_name:
                    source_channels.append(ch_id)
                    break

        if INFO:
            print(f"[broadcaster] Mix '{mix_name}' source_channels resolved: {source_channels}")
            sys.stdout.flush()

        if not source_channels:
            print(f"[broadcaster] Mix '{mix_name}' has no valid source channels — skipping")
            sys.stdout.flush()
            continue

        # Mix output rate = highest sample rate among sources (avoids downsampling loss)
        mix_sample_rate = max(channel_map[ch]["sample_rate"] for ch in source_channels)

        # Register mix output rate for save_recording
        with _sample_rates_lock:
            _instrument_sample_rates[mix_name] = mix_sample_rate

        mix_analysers = mix_inst.get("analysers", [])
        mix_configs[mix_name] = {
            "source_channels":     source_channels,
            "sample_rate":         mix_sample_rate,
            "role":                mix_inst.get("role", "mix"),
            "role_index":          mix_inst.get("role_index", 0),
            "instrument_index":    instrument_indices.get(mix_name, 0),
            "buffer": {
                ch: {
                    "queue":      deque(maxlen=MAX_QUEUE_SIZE),
                    "last_seen":  0.0,
                    "chunk_size": None,
                }
                for ch in source_channels
            },
            "analysers":           mix_analysers,
            "wsl_analysers":       [a for a in mix_analysers if _target(analysers_config, a, "wsl")],
            "wsl_heavy_analysers": [a for a in mix_analysers if _target(analysers_config, a, "wsl_heavy")],
            "windows_analysers":   [a for a in mix_analysers if _target(analysers_config, a, "windows")],
        }

        if DEBUG:
            print(f"[broadcaster] Mix '{mix_name}' combines channels {source_channels}"
                  f" @ {mix_sample_rate}Hz"
                  f" | wsl: {mix_configs[mix_name]['wsl_analysers']}"
                  f" | windows: {mix_configs[mix_name]['windows_analysers']}")
            sys.stdout.flush()

    return channel_map, mix_configs



# opens TCP connection to WSL receiver, retries until ready
def connect_to_wsl():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((WSL_HOST, WSL_PORT))
            if INFO : 
                print(f"[broadcaster] Connected to WSL receiver at {WSL_HOST}:{WSL_PORT}")
                sys.stdout.flush()
            return s
        except ConnectionRefusedError:
            print(f"[broadcaster] WSL receiver not ready — retrying in 2s")
            sys.stdout.flush()
            time.sleep(2)


# opens TCP connection to heavy WSL receiver, retries until ready
def connect_to_wsl_heavy():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((WSL_HEAVY_HOST, WSL_HEAVY_PORT))
            if INFO:
                print(f"[broadcaster] Connected to WSL heavy receiver at {WSL_HEAVY_HOST}:{WSL_HEAVY_PORT}")
                sys.stdout.flush()
            return s
        except ConnectionRefusedError:
            print(f"[broadcaster] WSL heavy receiver not ready — retrying in 2s")
            sys.stdout.flush()
            time.sleep(2)

# opens TCP connection to Windows receiver, retries until ready
def connect_to_windows():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((WINDOWS_HOST, WINDOWS_PORT))
            if INFO : 
                print(f"[broadcaster] Connected to Windows receiver at {WINDOWS_HOST}:{WINDOWS_PORT}")
                sys.stdout.flush()
            return s
        except ConnectionRefusedError:
            print(f"[broadcaster] Windows receiver not ready — retrying in 2s")
            sys.stdout.flush()
            time.sleep(2)


# reads exactly n bytes from a socket, looping until complete since TCP may deliver bytes in pieces
def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


# packs instrument name + analysers list + raw PCM into a framed TCP message and sends to a receiver
def send_framed_chunk(sock, instrument_name, analysers, audio_bytes, role="default", instrument_index=0, role_index=0):
    """
    Frame format:
      [4 bytes: header length  (uint32 big-endian)]
      [N bytes: header JSON                       ]
      [4 bytes: audio length   (uint32 big-endian)]
      [K bytes: raw float32 PCM                   ] (Pulse Code Modulation : uncompressed raw audio data)

    Header fields:
      instrument       — instrument name (str)
      analysers        — list of analyser IDs for this destination
      role             — instrument role string for TD OSC paths (e.g. "drums", "piano")
      role_index       — 0-based index within this role (e.g. vocals/0, vocals/1)
      instrument_index — global alphabetical index among audio/virtual instruments (for frontend OSC)
    """
    header = json.dumps({
        "instrument":       instrument_name,
        "analysers":        analysers,
        "role":             role,
        "role_index":       role_index,
        "instrument_index": instrument_index,
    }).encode("utf-8")

    frame = (
        struct.pack(">I", len(header)) +
        header +
        struct.pack(">I", len(audio_bytes)) +
        audio_bytes
    )
    sock.sendall(frame)



# Combine multiple audio chunks into a mixed chunk
def combine_audio(mix_name, chunks_by_channel, target_sr, channel_map):
    """
    Safely mixes audio chunks from multiple channels.
    Resamples each source to target_sr before mixing — handles any direction:
    upsampling (e.g. 44100 -> 48000) and downsampling (e.g. 96000 -> 48000) alike.
    gcd reduction keeps the resample_poly ratio as small as possible for efficiency.
    Trims to shortest after resampling to absorb off-by-one length differences.

    """

    arrays = []
    for ch_id, audio_bytes in chunks_by_channel.items():
        arr    = np.frombuffer(audio_bytes, dtype=np.float32).copy()
        src_sr = channel_map[ch_id]["sample_rate"]

        if src_sr != target_sr:
            g   = gcd(target_sr, src_sr)
            arr = resample_poly(arr, target_sr // g, src_sr // g).astype(np.float32)

        arrays.append(arr)

    # Trim all to shortest (resampling can produce off-by-one lengths)
    min_len = min(len(a) for a in arrays)
    mixed   = np.mean(np.stack([a[:min_len] for a in arrays], axis=0), axis=0)

    with _mix_record_lock:
        _record_buffers.setdefault(mix_name, []).append(mixed.copy())

    return mixed.astype(np.float32).tobytes()

# save broadcaster recording to audio_debug folder
def save_recording():
    with _mix_record_lock:
        if not _record_buffers:
            print("[recorder] Nothing to save.")
            sys.stdout.flush()
            return
        snapshot = {name: list(chunks) for name, chunks in _record_buffers.items()}

    with _sample_rates_lock:
        rates_snapshot = dict(_instrument_sample_rates)

    for name, chunks in snapshot.items():
        all_audio  = np.concatenate(chunks)
        int16_audio = (np.clip(all_audio, -1.0, 1.0) * 32767).astype(np.int16)

        sr = rates_snapshot.get(name, 48000)        # ← per-instrument rate
        if sr == 48000 and name not in rates_snapshot:
            print(f"[recorder] Warning: no sample rate registered for '{name}', defaulting to 48000Hz")
            sys.stdout.flush()

        output_path = os.path.join(AUDIO_DEBUG_DIR, f"debug_{name}.wav")

        with wave.open(output_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(int16_audio.tobytes())

        if INFO:
            duration = len(all_audio) / sr
            print(f"[recorder] Saved {duration:.1f}s @ {sr}Hz -> {output_path}")
            sys.stdout.flush()


# reads chunks from capture.py, looks up instrument routing, forwards to receivers
def handle_capture_connection(conn, config_holder):
    if INFO:
        print("[broadcaster] capture.py connected.")
        sys.stdout.flush()
    wsl_sock        = connect_to_wsl()
    wsl_heavy_sock  = connect_to_wsl_heavy()
    windows_sock    = connect_to_windows()

    last_config = config_holder["config"]
    channel_map, mix_configs = build_channel_map(last_config)

    try:
        while True:
            header = recv_exact(conn, 5)
            if header is None:
                break

            channel_id, data_len = struct.unpack(">BI", header)
            audio_bytes = recv_exact(conn, data_len)
            if audio_bytes is None:
                break

            current_config = config_holder["config"]
            if current_config is not last_config:
                last_config = current_config
                channel_map, mix_configs = build_channel_map(last_config)

            instrument_info = channel_map.get(channel_id)
            if instrument_info is None:
                continue

            rms, peak = get_audio_stats(audio_bytes)
            if rms > 0.01:
                if DEBUG:
                    print(f"[audio] ch{channel_id} ({instrument_info['name']:8s}) RMS={rms:.4f} Peak={peak:.4f}")
                    sys.stdout.flush()

            audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
            with _mix_record_lock:
                _record_buffers.setdefault(instrument_info["name"], []).append(audio_array.copy())

            # ── 1. Route individual instrument ──────────────────────────────
            if instrument_info["windows_analysers"]:
                try:
                    send_framed_chunk(windows_sock, instrument_info["name"], instrument_info["windows_analysers"], audio_bytes, instrument_info["role"], instrument_info["instrument_index"], instrument_info["role_index"])
                except OSError:
                    print("[broadcaster] Lost Windows connection — reconnecting")
                    sys.stdout.flush()
                    windows_sock = connect_to_windows()

            if instrument_info["wsl_analysers"]:
                try:
                    send_framed_chunk(wsl_sock, instrument_info["name"], instrument_info["wsl_analysers"], audio_bytes, instrument_info["role"], instrument_info["instrument_index"], instrument_info["role_index"])
                except OSError:
                    print("[broadcaster] Lost WSL connection — reconnecting")
                    sys.stdout.flush()
                    wsl_sock = connect_to_wsl()

            if instrument_info["wsl_heavy_analysers"]:
                try:
                    send_framed_chunk(wsl_heavy_sock, instrument_info["name"], instrument_info["wsl_heavy_analysers"], audio_bytes, instrument_info["role"], instrument_info["instrument_index"], instrument_info["role_index"])
                except OSError:
                    print("[broadcaster] Lost WSL heavy connection — reconnecting")
                    sys.stdout.flush()
                    wsl_heavy_sock = connect_to_wsl_heavy()

            # ── 2. Mix routing ───────────────────────────────────────────────

            now = time.monotonic()

            for mix_name, mix_config in mix_configs.items():
                if INFO:
                    print(f"[broadcaster] mix loop: ch{channel_id} | sources: {mix_config['source_channels']} | queues: { {ch: len(mix_config['buffer'][ch]['queue']) for ch in mix_config['source_channels']} }")
                    sys.stdout.flush()
                # Enqueue incoming chunk for this channel
                if channel_id in mix_config["source_channels"]:
                    slot = mix_config["buffer"][channel_id]
                    slot["queue"].append(audio_bytes)
                    slot["last_seen"]  = now
                    slot["chunk_size"] = len(audio_bytes)

                # Check if we can fire: every channel either has a queued chunk
                # or has been silent long enough to substitute zeros
                can_fire = True
                for ch in mix_config["source_channels"]:
                    slot      = mix_config["buffer"][ch]
                    has_chunk = len(slot["queue"]) > 0
                    timed_out = (now - slot["last_seen"]) > SILENCE_TIMEOUT and slot["chunk_size"] is not None
                    if not has_chunk and not timed_out:
                        can_fire = False
                        break
                    
                if not can_fire:
                    continue
                
                # Build chunks dict — real audio or silence fill
                chunks = {}
                for ch in mix_config["source_channels"]:
                    slot = mix_config["buffer"][ch]
                    if slot["queue"]:
                        chunks[ch] = slot["queue"].popleft()
                    else:
                        # Channel is silent — contribute zeros of the same byte length
                        chunks[ch] = bytes(slot["chunk_size"])
                        if DEBUG:
                            print(f"[broadcaster] Mix '{mix_name}' ch{ch} silence fill")
                            sys.stdout.flush()

                mixed_audio = combine_audio(
                    mix_name,
                    chunks,
                    mix_config["sample_rate"],
                    channel_map,
                )

                if mix_config["windows_analysers"]:
                    try:
                        send_framed_chunk(windows_sock, mix_name, mix_config["windows_analysers"], mixed_audio, mix_config["role"], mix_config["instrument_index"], mix_config["role_index"])
                    except OSError:
                        print("[broadcaster] Lost Windows connection — reconnecting")
                        sys.stdout.flush()
                        windows_sock = connect_to_windows()

                if mix_config["wsl_analysers"]:
                    try:
                        send_framed_chunk(wsl_sock, mix_name, mix_config["wsl_analysers"], mixed_audio, mix_config["role"], mix_config["instrument_index"], mix_config["role_index"])
                    except OSError:
                        print("[broadcaster] Lost WSL connection — reconnecting")
                        sys.stdout.flush()
                        wsl_sock = connect_to_wsl()

                if mix_config["wsl_heavy_analysers"]:
                    try:
                        send_framed_chunk(wsl_heavy_sock, mix_name, mix_config["wsl_heavy_analysers"], mixed_audio, mix_config["role"], mix_config["instrument_index"], mix_config["role_index"])
                    except OSError:
                        print("[broadcaster] Lost WSL heavy connection — reconnecting")
                        sys.stdout.flush()
                        wsl_heavy_sock = connect_to_wsl_heavy()

    finally:
        if INFO:
            print("[broadcaster] capture.py disconnected.")
            sys.stdout.flush()
        wsl_sock.close()
        wsl_heavy_sock.close()
        windows_sock.close()
        conn.close()



# opens TCP server and accepts incoming capture.py connections
def start_server(config_holder):
    if INFO : 
        print(f"[broadcaster] Listening for capture.py on {LOCAL_HOST}:{LOCAL_PORT}")
        sys.stdout.flush()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((LOCAL_HOST, LOCAL_PORT))
        server.listen(1)

        while True:
            conn, addr = server.accept()
            threading.Thread(
                target=handle_capture_connection,
                args=(conn, config_holder),
                daemon=True,
            ).start()


def watch_stop_sentinel():
    """Polls for a stop sentinel file — when found, saves recording and exits."""
    while True:
        time.sleep(0.5)
        if os.path.exists(STOP_SENTINEL):
            if INFO : 
                print("[broadcaster] Stop sentinel detected — saving recording...")
                sys.stdout.flush()
            try:
                os.remove(STOP_SENTINEL)
            except OSError:
                pass
            save_recording()
            os._exit(0)  # hard exit — kills all threads cleanly

def main():
    # Clean up any leftover sentinel from a previous run
    if os.path.exists(STOP_SENTINEL):
        os.remove(STOP_SENTINEL)

    config_holder = {"config": load_config()}
    if INFO:
        print("[broadcaster] Config loaded.")
        sys.stdout.flush()

    threading.Thread(target=watch_config, args=(config_holder,), daemon=True).start()
    threading.Thread(target=watch_stop_sentinel, daemon=True).start()
    start_server(config_holder)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        if INFO : 
            print("[broadcaster] Stopped.")
            sys.stdout.flush()
        save_recording()