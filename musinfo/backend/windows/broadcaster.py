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

# AUDIO DEBUGGING information
_record_buffers = {}
_mix_sample_rate = 48000  # adjust if yours differs | 44100
_mix_record_lock = threading.Lock()
RECORD_OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug_mix.wav")
STOP_SENTINEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "broadcaster.stop")


LOCAL_HOST      = "127.0.0.1"
LOCAL_PORT      = 5005

WSL_HOST        = "172.29.28.224"
WSL_PORT        = 5006

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
        print(f"[broadcaster] Config loaded.")
        sys.stdout.flush()
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


# builds a lookup table mapping channel_id -> instrument name and analysers split by target
# so broadcaster can instantly look up routing info for each incoming chunk
def build_channel_map(config):
    channel_map  = {}
    analysers_config = config.get("analysers", {})

    # Build regular instrument routing 
    for name, instrument in config.get("instruments", {}).items():
        if not instrument.get("enabled", False):
            continue
        
        # Skip mix instruments (they're handled separately)
        if instrument.get("type") == "mix":
            continue
        
        # Get channel from audio_device
        audio_device = instrument.get("audio_device", {})
        channel_id = audio_device.get("channel")
        
        if channel_id is None:
            continue

        active_analysers = instrument.get("analysers", [])

        channel_map[channel_id] = {
            "name":            name,
            "wsl_analysers":     [m for m in active_analysers if analysers_config.get(m, {}).get("target") == "wsl"],
            "windows_analysers": [m for m in active_analysers if analysers_config.get(m, {}).get("target") == "windows"],
        }
        # FIXED: Replace Unicode arrow with ASCII
        print(f"[broadcaster] Channel {channel_id} -> '{name}' | wsl: {channel_map[channel_id]['wsl_analysers']} | windows: {channel_map[channel_id]['windows_analysers']}")
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
        
        # Find channel_ids of source instruments
        source_instruments = mix_inst.get("source_instruments", [])
        source_channels = []

        for inst_name in source_instruments:
            # Look up the channel_id for this instrument
            for ch_id, ch_info in channel_map.items():
                if ch_info["name"] == inst_name:
                    source_channels.append(ch_id)
                    break
                
        print(f"[broadcaster] Mix '{mix_name}' source_channels resolved: {source_channels}")
        if not source_channels:
            print(f"[broadcaster] Mix '{mix_name}' has no valid source channels — skipping")
            sys.stdout.flush()
            continue
        
        # Split mix analysers by target
        mix_analysers = mix_inst.get("analysers", [])
        mix_configs[mix_name] = {
            "source_channels": source_channels,
            "buffer": {},
            "analysers": mix_analysers,
            "wsl_analysers": [a for a in mix_analysers if analysers_config.get(a, {}).get("target") == "wsl"],
            "windows_analysers": [a for a in mix_analysers if analysers_config.get(a, {}).get("target") == "windows"],
        }

        print(f"[broadcaster] Mix '{mix_name}' combines channels {source_channels} | wsl: {mix_configs[mix_name]['wsl_analysers']} | windows: {mix_configs[mix_name]['windows_analysers']}")
        sys.stdout.flush()
    
    return channel_map, mix_configs


# opens TCP connection to WSL receiver, retries until ready
def connect_to_wsl():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((WSL_HOST, WSL_PORT))
            print(f"[broadcaster] Connected to WSL receiver at {WSL_HOST}:{WSL_PORT}")
            sys.stdout.flush()
            return s
        except ConnectionRefusedError:
            print(f"[broadcaster] WSL receiver not ready — retrying in 2s")
            sys.stdout.flush()
            time.sleep(2)


# opens TCP connection to Windows receiver, retries until ready
def connect_to_windows():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((WINDOWS_HOST, WINDOWS_PORT))
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
def send_framed_chunk(sock, instrument_name, analysers, audio_bytes):
    """
    Frame format:
      [4 bytes: header length  (uint32 big-endian)]
      [N bytes: header JSON                       ]
      [4 bytes: audio length   (uint32 big-endian)]
      [K bytes: raw float32 PCM                   ] (Pulse Code Modulation : uncompressed raw audio data)
      
    """
    header = json.dumps({
        "instrument": instrument_name,
        "analysers":     analysers,
    }).encode("utf-8")

    frame = (
        struct.pack(">I", len(header)) +
        header +
        struct.pack(">I", len(audio_bytes)) +
        audio_bytes
    )
    sock.sendall(frame)

# Combine multiple audio chunks into a mixed chunk
def combine_audio(mix_name, buffers):
    arrays = [np.frombuffer(b, dtype=np.float32) for b in buffers.values()]
    mixed = np.mean(arrays, axis=0)
    with _mix_record_lock:
        _record_buffers.setdefault(mix_name, []).append(mixed.copy())
    return mixed.astype(np.float32).tobytes()

# save broadcaster recording
def save_recording():
    with _mix_record_lock:
        if not _record_buffers:
            print("[recorder] Nothing to save.")
            return
        snapshot = {name: list(chunks) for name, chunks in _record_buffers.items()}

    for name, chunks in snapshot.items():
        all_audio = np.concatenate(chunks)
        int16_audio = (np.clip(all_audio, -1.0, 1.0) * 32767).astype(np.int16)
        
        output_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            f"debug_{name}.wav"
        )
        with wave.open(output_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(_mix_sample_rate)
            wf.writeframes(int16_audio.tobytes())
        
        print(f"[recorder] Saved {len(all_audio) / _mix_sample_rate:.1f}s -> {output_path}")
        sys.stdout.flush()


# reads chunks from capture.py, looks up instrument routing, forwards to receivers
def handle_capture_connection(conn, config_holder):
    print("[broadcaster] capture.py connected.")
    sys.stdout.flush()
    wsl_sock = connect_to_wsl()
    windows_sock = connect_to_windows()

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


            # Log audio stats when audio is present
            rms, peak = get_audio_stats(audio_bytes)
            if rms > 0.01:  # Only log when there's actual audio
                print(f"[audio] ch{channel_id} ({instrument_info['name']:8s}) RMS={rms:.4f} Peak={peak:.4f}")
                sys.stdout.flush()
 

            # Record this instrument's audio
            audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
            with _mix_record_lock:
                _record_buffers.setdefault(instrument_info["name"], []).append(audio_array.copy())

            # ──── 1. Route individual instrument ────────────────────────────
            if instrument_info["windows_analysers"]:
                try:
                    send_framed_chunk(windows_sock, instrument_info["name"], instrument_info["windows_analysers"], audio_bytes)
                except OSError:
                    print("[broadcaster] Lost Windows connection — reconnecting")
                    sys.stdout.flush()
                    windows_sock = connect_to_windows()

            if instrument_info["wsl_analysers"]:
                try:
                    send_framed_chunk(wsl_sock, instrument_info["name"], instrument_info["wsl_analysers"], audio_bytes)
                except OSError:
                    print("[broadcaster] Lost WSL connection — reconnecting")
                    sys.stdout.flush()
                    wsl_sock = connect_to_wsl()

            # ──── 2. Check if this channel is part of any mix ───────────────
            for mix_name, mix_config in mix_configs.items():
                if channel_id in mix_config["source_channels"]:
                    mix_config["buffer"][channel_id] = audio_bytes
            
                    # Only flush when ALL source channels have contributed
                    if len(mix_config["buffer"]) == len(mix_config["source_channels"]):
                        mixed_audio = combine_audio(mix_name, mix_config["buffer"])
                        mix_config["buffer"] = {}  # clear for next round
            
                        if mix_config["windows_analysers"]:
                            try:
                                send_framed_chunk(windows_sock, mix_name, mix_config["windows_analysers"], mixed_audio)
                            except OSError:
                                print("[broadcaster] Lost Windows connection — reconnecting")
                                sys.stdout.flush()
                                windows_sock = connect_to_windows()
            
                        if mix_config["wsl_analysers"]:
                            try:
                                send_framed_chunk(wsl_sock, mix_name, mix_config["wsl_analysers"], mixed_audio)
                            except OSError:
                                print("[broadcaster] Lost WSL connection — reconnecting")
                                sys.stdout.flush()
                                wsl_sock = connect_to_wsl()
                        

    finally:
        print("[broadcaster] capture.py disconnected.")
        sys.stdout.flush()
        wsl_sock.close()
        windows_sock.close()
        conn.close()


# reloads config files every CONFIG_POLL_INTERVAL seconds so changes take effect without restarting
def watch_config(config_holder):
    while True:
        time.sleep(CONFIG_POLL_INTERVAL)
        config_holder["config"] = load_config()
        print("[broadcaster] Config refreshed.")
        sys.stdout.flush()
        


# opens TCP server and accepts incoming capture.py connections
def start_server(config_holder):
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
    threading.Thread(target=watch_config, args=(config_holder,), daemon=True).start()
    threading.Thread(target=watch_stop_sentinel, daemon=True).start()
    start_server(config_holder)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[broadcaster] Stopped.")
        sys.stdout.flush()
        save_recording()