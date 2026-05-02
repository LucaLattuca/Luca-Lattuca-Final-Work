# capture.py — Audio Capture + TCP Streamer (Windows side)
# Loads instruments.json, captures enabled channels, streams to broadcaster.py

import socket
import struct
import queue
import threading
import numpy as np
import sounddevice as sd
import json
import os


BROADCASTER_HOST = "127.0.0.1"
BROADCASTER_PORT = 5005

# Thread lock for socket operations (multiple devices sending simultaneously)
socket_lock = threading.Lock()


def load_instruments_config():
    """Load instruments.json and return enabled instruments grouped by device."""
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
        
        # Group instruments by device_id
        devices = {}
        for name, inst in enabled.items():
            device_info = inst.get("audio_device", {})
            device_id = device_info.get("device_id")
            channel = device_info.get("channel")
            sample_rate = device_info.get("sample_rate", 44100)
            
            if device_id is None or channel is None:
                print(f"[capture.py] Skipping {name}: missing device_id or channel")
                continue
            
            if device_id not in devices:
                devices[device_id] = {
                    "sample_rate": sample_rate,
                    "max_input_channels": device_info.get("max_input_channels", 2),
                    "name": device_info.get("name", "Unknown"),
                    "channels": {}
                }
            
            devices[device_id]["channels"][channel] = {
                "instrument_name": name,
                "channel_id": channel
            }
            
            print(f"[capture.py] {name}: device {device_id}, channel {channel}, {sample_rate}Hz")
        
        return devices
        
    except FileNotFoundError:
        print(f"[capture.py] instruments.json not found at {config_path}")
        return {}
    except json.JSONDecodeError as e:
        print(f"[capture.py] Failed to parse instruments.json: {e}")
        return {}


def send_chunk(sock, channel_id, audio_chunk):
    """
    Frame format sent to broadcaster.py:
      [1 byte : channel_id  (uint8) ]
      [4 bytes: data length (uint32)]
      [N bytes: raw float32 PCM    ]
    
    Thread-safe: uses socket_lock to prevent concurrent writes
    """
    raw = audio_chunk.astype(np.float32).tobytes()
    header = struct.pack(">BI", channel_id, len(raw))
    
    with socket_lock:
        sock.sendall(header + raw)


def stream_device(device_id, device_config, sock):
    """
    Opens an audio stream for one device and sends each enabled channel to broadcaster.
    """
    channels_map = device_config["channels"]
    sample_rate = device_config["sample_rate"]
    max_channels = device_config["max_input_channels"]
    device_name = device_config["name"]
    
    # Determine how many channels we need to capture
    max_channel_index = max(channels_map.keys())
    channels_to_capture = max_channel_index + 1
    
    print(f"[capture.py] Opening device {device_id} ({device_name})")
    print(f"[capture.py] Sample rate: {sample_rate}Hz, capturing {channels_to_capture}/{max_channels} channels")
    
    # Create a queue for each enabled channel
    channel_queues = {ch: queue.Queue() for ch in channels_map.keys()}
    
    def audio_callback(indata, frames, time, status):
        if status:
            print(f"[capture.py] Status: {status}")
        
        # Put each enabled channel's data into its queue
        for ch in channels_map.keys():
            channel_queues[ch].put(indata[:, ch].copy())
    
    # Start sender threads for each enabled channel
    def send_loop(q, channel_id):
        while True:
            chunk = q.get()
            try:
                send_chunk(sock, channel_id, chunk)
            except OSError:
                break
    
    for ch, info in channels_map.items():
        threading.Thread(
            target=send_loop,
            args=(channel_queues[ch], info["channel_id"]),
            daemon=True
        ).start()
        print(f"[capture.py] Started sender thread for channel {ch} ({info['instrument_name']})")
    
    # Open the audio stream
    with sd.InputStream(
        device=device_id,
        channels=channels_to_capture,
        samplerate=sample_rate,
        blocksize=2048,
        dtype="float32",
        callback=audio_callback,
    ):
        print(f"[capture.py] Stream open for device {device_id}")
        threading.Event().wait()


def main():
    devices_config = load_instruments_config()
    
    if not devices_config:
        print("[capture.py] No devices to capture from. Check instruments.json.")
        return
    
    print(f"[capture.py] Connecting to broadcaster at {BROADCASTER_HOST}:{BROADCASTER_PORT}")
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((BROADCASTER_HOST, BROADCASTER_PORT))
        print("[capture.py] Connected to broadcaster.")
        
        # Handle multiple devices - each in its own thread
        device_threads = []
        
        for device_id, device_config in devices_config.items():
            thread = threading.Thread(
                target=stream_device,
                args=(device_id, device_config, sock),
                daemon=True,
                name=f"Device-{device_id}"
            )
            thread.start()
            device_threads.append(thread)
            print(f"[capture.py] Started capture thread for device {device_id}")
        
        # Wait for all device threads
        for thread in device_threads:
            thread.join()


if __name__ == "__main__":
    try:
        main()
    except ConnectionRefusedError:
        print("[capture.py] Connection refused — is broadcaster.py running?")
    except KeyboardInterrupt:
        print("[capture.py] Stopped.")