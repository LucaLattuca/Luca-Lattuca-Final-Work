"""
osc_playback.py — Replay a recorded OSC session to TouchDesigner.

Usage:
    python osc_playback.py <recording.json> [options]

Options:
    --host   <ip>     Target host (default: 127.0.0.1)
    --port   <port>   Target port (default: 9000)
    --speed  <float>  Playback speed multiplier, e.g. 0.5 = half speed (default: 1.0)
    --loop            Loop the recording indefinitely (Ctrl+C to stop)

Examples:
    python osc_playback.py recording_20250609_143012.json
    python osc_playback.py recording.json --speed 0.5 --loop
    python osc_playback.py recording.json --host 192.168.1.50 --port 9000
"""

import sys
import json
import time
import argparse
from pythonosc.udp_client import SimpleUDPClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_recording(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Support both plain list format and the {meta, messages} format
    if isinstance(data, list):
        messages = data
        meta = {"message_count": len(data)}
    else:
        messages = data["messages"]
        meta = data.get("meta", {})

    return meta, messages


def send_message(client: SimpleUDPClient, address: str, args: list):
    """Send an OSC message, handling single vs multiple args cleanly."""
    if not args:
        client.send_message(address, [])
    elif len(args) == 1:
        client.send_message(address, args[0])
    else:
        client.send_message(address, args)


def play_once(client: SimpleUDPClient, messages: list, speed: float, verbose: bool = True):
    """Play back the message list once with accurate timing."""
    if not messages:
        print("⚠  No messages to play.")
        return

    print(f"  Playing {len(messages)} messages...")

    playback_start = time.perf_counter()
    total_duration = messages[-1]["t"] / speed

    for i, msg in enumerate(messages):
        target_time = msg["t"] / speed

        # Sleep until the right moment (busy-wait the last 1ms for accuracy)
        while True:
            now = time.perf_counter() - playback_start
            remaining = target_time - now
            if remaining <= 0:
                break
            elif remaining > 0.002:
                time.sleep(remaining * 0.9)
            # else: spin the last fraction of a ms

        send_message(client, msg["address"], msg["args"])

        if verbose:
            elapsed = time.perf_counter() - playback_start
            arg_str = ", ".join(str(a) for a in msg["args"])
            print(f"  [{elapsed:8.3f}s]  {msg['address']}  →  {arg_str}")

    actual = time.perf_counter() - playback_start
    print(f"  ✓ Done  (expected {total_duration:.2f}s, actual {actual:.2f}s)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Replay an OSC recording to TouchDesigner.")
    parser.add_argument("recording", help="Path to the .json recording file")
    parser.add_argument("--host",  default="127.0.0.1", help="Target OSC host (default: 127.0.0.1)")
    parser.add_argument("--port",  type=int, default=9100, help="Target OSC port (default: 9100)")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier (default: 1.0)")
    parser.add_argument("--loop",  action="store_true", help="Loop indefinitely")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-message output")
    args = parser.parse_args()

    meta, messages = load_recording(args.recording)
    duration = messages[-1]["t"] if messages else 0

    print(f"┌─ OSC Playback ───────────────────────────────────┐")
    print(f"│  File     : {args.recording:<37}│")
    print(f"│  Messages : {meta.get('message_count', len(messages)):<37}│")
    print(f"│  Duration : {duration:.2f}s{'':<33}│")
    print(f"│  Target   : {args.host}:{args.port:<31}│")
    print(f"│  Speed    : {args.speed}x{'':<36}│")
    print(f"│  Loop     : {'yes' if args.loop else 'no':<37}│")
    print(f"│  Press Ctrl+C to stop                            │")
    print(f"└──────────────────────────────────────────────────┘")
    print()

    client = SimpleUDPClient(args.host, args.port)
    verbose = not args.quiet

    loop_count = 0
    try:
        while True:
            loop_count += 1
            if args.loop:
                print(f"── Loop {loop_count} ──────────────────────────────────────────")
            play_once(client, messages, args.speed, verbose=verbose)

            if not args.loop:
                break

            # Brief pause between loops so TD state can settle
            time.sleep(0.5)

    except KeyboardInterrupt:
        print(f"\n⏹  Stopped after {loop_count} loop(s).")


if __name__ == "__main__":
    main()