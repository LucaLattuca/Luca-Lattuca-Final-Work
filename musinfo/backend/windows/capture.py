# capture.py — Audio Capture + TCP Streamer (Windows side)
# Loads instruments.json, captures enabled channels, streams to broadcaster.py

import os
os.environ["SD_ENABLE_ASIO"] = "1"
import socket
import struct
import queue
import threading
import numpy as np
import sounddevice as sd
import json
import time as time_module


BROADCASTER_HOST = "127.0.0.1"
BROADCASTER_PORT = 5005

# Thread lock for socket operations (multiple devices sending simultaneously)
socket_lock = threading.Lock()

def resolve_device_id(name: str, host_api: str) -> tuple[int, int]:
    """
    Resolve a stable device index by matching name + host API.
    Returns (device_id, actual_sample_rate).
    Falls back gracefully if the stored host_api changed.
    """
    devices  = sd.query_devices()
    hostapis = sd.query_hostapis()

    # Build a map of hostapi name -> index
    api_index = {a["name"]: i for i, a in enumerate(hostapis)}
    wanted_api = api_index.get(host_api)

    candidates = []
    for i, d in enumerate(devices):
        if name.lower() not in d["name"].lower():
            continue
        if d["max_input_channels"] < 1:
            continue
        if "[Loopback]" in d["name"]:
            continue
        if wanted_api is not None and d["hostapi"] != wanted_api:
            continue
        candidates.append((i, d))

    if not candidates:
        # Relax host_api constraint — maybe it changed
        candidates = [
            (i, d) for i, d in enumerate(devices)
            if name.lower() in d["name"].lower()
            and d["max_input_channels"] > 0
            and "[Loopback]" not in d["name"]
        ]

    if not candidates:
        raise RuntimeError(f"[capture.py] No input device found matching '{name}'")

    idx, info = candidates[0]
    actual_rate = int(info["default_samplerate"])
    print(f"[capture.py] Resolved '{name}' -> device {idx} ({info['name']}, {sd.query_hostapis(info['hostapi'])['name']}) @ {actual_rate}Hz")
    return idx, actual_rate


def load_instruments_config():
    """Load instruments.json grouped by device name+host_api (stable identifiers)."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(base_dir, "config", "instruments.json")

    try:
        with open(config_path) as f:
            config = json.load(f)

        instruments = config.get("instruments", {})
        enabled = {
            name: inst for name, inst in instruments.items()
            if inst.get("enabled", False)
        }

        if not enabled:
            print("[capture.py] No enabled instruments in instruments.json")
            return {}

        # Group by (device_name, host_api) — stable across reboots
        devices = {}

        for name, inst in enabled.items():

            # Skip internal mixes — they have no audio_device to capture from
            if inst.get("type") == "mix" and inst.get("mix_source") == "internal":
                continue
            
            device_info = inst.get("audio_device", {})
            device_name = device_info.get("name")
            host_api    = device_info.get("host_api", "Windows WASAPI")
            channel     = device_info.get("channel")

            if not device_name or channel is None:
                print(f"[capture.py] Skipping {name}: missing device name or channel")
                continue

            key = (device_name, host_api)
            if key not in devices:
                devices[key] = {
                    "name":               device_name,
                    "host_api":           host_api,
                    "max_input_channels": device_info.get("max_input_channels", 2),
                    "channels":           {}
                }

            devices[key]["channels"][channel] = {
                "instrument_name": name,
                "channel_id":      channel
            }

            print(f"[capture.py] {name}: device '{device_name}' ({host_api}), channel {channel}")

        return devices

    except FileNotFoundError:
        print(f"[capture.py] instruments.json not found at {config_path}")
        return {}
    except json.JSONDecodeError as e:
        print(f"[capture.py] Failed to parse instruments.json: {e}")
        return {}

def send_chunk(sock, channel_id, audio_chunk, capture_time):
    """
    Frame format sent to broadcaster.py:
      [1 byte : channel_id  (uint8) ]
      [4 bytes: data length (uint32)]
      [N bytes: raw float32 PCM    ]
    
    Thread-safe: uses socket_lock to prevent concurrent writes
    """
    raw = audio_chunk.astype(np.float32).tobytes()
    
    header = struct.pack(">BdI", channel_id, capture_time, len(raw))
    
    with socket_lock:
        sock.sendall(header + raw)



def stream_device(device_config, sock):

    # Initialize COM on this thread — required for ASIO drivers
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception as e:
        print(f"[capture.py] COM init warning: {e}")

    channels_map  = device_config["channels"]
    max_channels  = device_config["max_input_channels"]
    device_name   = device_config["name"]
    host_api      = device_config["host_api"]

    # Resolve stable name -> current integer index + actual sample rate
    try:
        device_id, sample_rate = resolve_device_id(device_name, host_api)
    except RuntimeError as e:
        print(e)
        return

    max_channel_index   = max(channels_map.keys())
    channels_to_capture = max_channel_index + 1

    print(f"[capture.py] Opening '{device_name}' ({host_api}) as device {device_id} @ {sample_rate}Hz")
    print(f"[capture.py] Capturing {channels_to_capture}/{max_channels} channels")

    channel_queues = {ch: queue.Queue() for ch in channels_map.keys()}

    def audio_callback(indata, frames, time, status):
        if status:
            print(f"[capture.py] Status: {status}", flush=True)
        capture_time = time_module.perf_counter()
        for ch in channels_map.keys():
            channel_queues[ch].put((indata[:, ch].copy(), capture_time))

    def send_loop(q, channel_id):
        while True:
            chunk, capture_time = q.get()
            try:
                send_chunk(sock, channel_id, chunk, capture_time)
            except OSError:
                break


    for ch, info in channels_map.items():
        threading.Thread(
            target=send_loop,
            args=(channel_queues[ch], info["channel_id"]),
            daemon=True
        ).start()
        print(f"[capture.py] Sender thread for channel {ch} ({info['instrument_name']})")

    try:
        with sd.InputStream(
            device=device_id,
            channels=channels_to_capture,
            samplerate=sample_rate,
            blocksize=2048, # Minimum block size needed by all analysers. (2048 works for now.)
            dtype="float32",
            callback=audio_callback,
        ):
            print(f"[capture.py] Stream open — '{device_name}' @ {sample_rate}Hz")
            threading.Event().wait()
    except Exception as e:
        print(f"[capture.py] Stream error for '{device_name}': {e}", flush=True)



def main():
    devices_config = load_instruments_config()

    if not devices_config:
        print("[capture.py] No devices to capture from.")
        return

    print(f"[capture.py] Connecting to broadcaster at {BROADCASTER_HOST}:{BROADCASTER_PORT}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((BROADCASTER_HOST, BROADCASTER_PORT))
        print("[capture.py] Connected to broadcaster.")

        device_threads = []

        for key, device_config in devices_config.items():
            thread = threading.Thread(
                target=stream_device,
                args=(device_config, sock),   # no device_id arg — resolved inside
                daemon=True,
                name=f"Device-{key[0]}"
            )
            thread.start()
            device_threads.append(thread)

        for thread in device_threads:
            thread.join()



if __name__ == "__main__":
    try:
        main()
    except ConnectionRefusedError:
        print("[capture.py] Connection refused — is broadcaster.py running?")
    except KeyboardInterrupt:
        print("[capture.py] Stopped.")