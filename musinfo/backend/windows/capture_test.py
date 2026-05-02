# capture_test.py — Test Audio Capture (standalone, no broadcaster needed)
# Shows what would be sent to broadcaster with visual RMS meters

import struct
import queue
import threading
import numpy as np
import sounddevice as sd
import json
import os
import time
import sys


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
            print("[TEST] No enabled instruments in instruments.json")
            return {}
        
        # Group instruments by device_id
        devices = {}
        for name, inst in enabled.items():
            device_info = inst.get("audio_device", {})
            device_id = device_info.get("device_id")
            channel = device_info.get("channel")
            sample_rate = device_info.get("sample_rate", 44100)
            
            if device_id is None or channel is None:
                print(f"[TEST] Skipping {name}: missing device_id or channel")
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
            
            print(f"[TEST] {name}: device {device_id}, channel {channel}, {sample_rate}Hz")
        
        return devices
        
    except FileNotFoundError:
        print(f"[TEST] instruments.json not found at {config_path}")
        return {}
    except json.JSONDecodeError as e:
        print(f"[TEST] Failed to parse instruments.json: {e}")
        return {}


def format_chunk_info(channel_id, instrument_name, audio_chunk):
    """Format chunk info for display"""
    rms = np.sqrt(np.mean(audio_chunk ** 2))
    peak = np.max(np.abs(audio_chunk))
    chunk_size = len(audio_chunk)
    bytes_size = audio_chunk.astype(np.float32).nbytes
    
    return {
        "channel_id": channel_id,
        "instrument": instrument_name,
        "rms": rms,
        "peak": peak,
        "samples": chunk_size,
        "bytes": bytes_size
    }


def create_meter_bar(value, width=40):
    """Create a visual bar graph"""
    filled = int(value * width)
    bar = "█" * filled + "░" * (width - filled)
    return bar


# Global stats tracking
stats = {}
stats_lock = threading.Lock()


def test_stream_device(device_id, device_config):
    """
    Opens an audio stream for one device and displays chunk info in terminal
    """
    channels_map = device_config["channels"]
    sample_rate = device_config["sample_rate"]
    max_channels = device_config["max_input_channels"]
    device_name = device_config["name"]
    
    # Determine how many channels we need to capture
    max_channel_index = max(channels_map.keys())
    channels_to_capture = max_channel_index + 1
    
    print(f"\n{'='*80}")
    print(f"[TEST] Device {device_id}: {device_name}")
    print(f"[TEST] Sample rate: {sample_rate}Hz")
    print(f"[TEST] Capturing {channels_to_capture}/{max_channels} channels")
    print(f"{'='*80}\n")
    
    # Initialize stats for each channel
    with stats_lock:
        for ch, info in channels_map.items():
            stats[info['channel_id']] = {
                'instrument': info['instrument_name'],
                'chunks': 0,
                'bytes': 0,
                'rms': 0.0,
                'peak': 0.0
            }
    
    # Create a queue for each enabled channel
    channel_queues = {ch: queue.Queue() for ch in channels_map.keys()}
    
    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[TEST] Status: {status}")
        
        # Put each enabled channel's data into its queue
        for ch in channels_map.keys():
            channel_queues[ch].put(indata[:, ch].copy())
    
    # Start display threads for each enabled channel
    def display_loop(q, channel_id, instrument_name):
        while True:
            chunk = q.get()
            
            # Calculate stats
            info = format_chunk_info(channel_id, instrument_name, chunk)
            
            # Update global stats
            with stats_lock:
                stats[channel_id]['chunks'] += 1
                stats[channel_id]['bytes'] += info['bytes']
                stats[channel_id]['rms'] = info['rms']
                stats[channel_id]['peak'] = info['peak']
    
    for ch, info in channels_map.items():
        threading.Thread(
            target=display_loop,
            args=(channel_queues[ch], info["channel_id"], info["instrument_name"]),
            daemon=True
        ).start()
    
    # Open the audio stream
    with sd.InputStream(
        device=device_id,
        channels=channels_to_capture,
        samplerate=sample_rate,
        blocksize=2048,
        dtype="float32",
        callback=audio_callback,
    ):
        print(f"[TEST] Stream open for device {device_id}")
        print(f"[TEST] Press Ctrl+C to stop\n")
        threading.Event().wait()


def display_stats_loop():
    """Display live stats in terminal"""
    while True:
        time.sleep(0.1)
        
        # Clear screen (works on both Windows and Unix)
        os.system('cls' if os.name == 'nt' else 'clear')
        
        print("╔" + "═" * 78 + "╗")
        print("║" + " CAPTURE.PY TEST MODE - LIVE AUDIO MONITORING ".center(78) + "║")
        print("╚" + "═" * 78 + "╝\n")
        
        with stats_lock:
            if not stats:
                print("  No active channels...\n")
                continue
            
            for channel_id in sorted(stats.keys()):
                s = stats[channel_id]
                
                print(f"┌─ Channel {channel_id}: {s['instrument']:<20} " + "─" * 40)
                print(f"│")
                
                # RMS meter
                rms_normalized = min(s['rms'] * 10, 1.0)  # Scale for visibility
                rms_bar = create_meter_bar(rms_normalized, width=50)
                print(f"│  RMS:  {rms_bar} {s['rms']:.4f}")
                
                # Peak meter
                peak_normalized = min(s['peak'] * 10, 1.0)
                peak_bar = create_meter_bar(peak_normalized, width=50)
                print(f"│  Peak: {peak_bar} {s['peak']:.4f}")
                
                # Stats
                kb_sent = s['bytes'] / 1024
                print(f"│")
                print(f"│  Chunks sent: {s['chunks']}")
                print(f"│  Data sent:   {kb_sent:.2f} KB")
                print(f"│")
            
            print("└" + "─" * 76 + "\n")
        
        print("  Press Ctrl+C to stop")


def main():
    devices_config = load_instruments_config()
    
    if not devices_config:
        print("[TEST] No devices to capture from. Check instruments.json.")
        return
    
    print("\n" + "="*80)
    print(" TEST MODE - Monitoring audio capture without broadcaster")
    print("="*80 + "\n")
    
    # Start stats display thread
    threading.Thread(target=display_stats_loop, daemon=True).start()
    
    # Handle multiple devices - each in its own thread
    device_threads = []
    
    for device_id, device_config in devices_config.items():
        thread = threading.Thread(
            target=test_stream_device,
            args=(device_id, device_config),
            daemon=True,
            name=f"Device-{device_id}"
        )
        thread.start()
        device_threads.append(thread)
    
    # Wait for all device threads
    for thread in device_threads:
        thread.join()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[TEST] Stopped.")
        sys.exit(0)