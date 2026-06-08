"""
osc_recorder.py — Record all OSC messages sent to TouchDesigner and save
them to a .json file for later playback.

Usage:
    python osc_recorder.py [output_file] [options]

    output_file defaults to: recording_<timestamp>.json

Options:
    --port  <port>   Port to listen on (default: 9100)
    --host  <host>   Host to listen on (default: 0.0.0.0)

Press Ctrl+C to stop recording.
"""

import sys
import json
import time
import argparse
from datetime import datetime
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer
import threading

# ── State ─────────────────────────────────────────────────────────────────────
recorded_messages = []
start_time = None
server = None


def handle_message(address, *args):
    """Called for every incoming OSC message."""
    global start_time

    if start_time is None:
        start_time = time.perf_counter()

    elapsed = time.perf_counter() - start_time

    # Convert args — OSC can send ints, floats, strings, bools
    cleaned_args = []
    for a in args:
        if isinstance(a, (int, float, str, bool)):
            cleaned_args.append(a)
        else:
            cleaned_args.append(str(a))

    entry = {
        "t": round(elapsed, 6),
        "address": address,
        "args": cleaned_args,
    }
    recorded_messages.append(entry)

    # Live feedback
    arg_str = ", ".join(str(a) for a in cleaned_args)
    print(f"  [{elapsed:8.3f}s]  {address}  →  {arg_str}")


def save_recording(output_file: str, listen_port: int):
    duration = recorded_messages[-1]["t"] if recorded_messages else 0
    data = {
        "meta": {
            "recorded_at": datetime.now().isoformat(),
            "duration_seconds": round(duration, 3),
            "message_count": len(recorded_messages),
            "source_port": listen_port,
        },
        "messages": recorded_messages,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n✓  Saved {len(recorded_messages)} messages ({duration:.2f}s) → {output_file}")


def main():
    global server

    parser = argparse.ArgumentParser(description="Record OSC messages to a JSON file.")
    parser.add_argument("output", nargs="?", help="Output .json file (default: recording_<timestamp>.json)")
    parser.add_argument("--port", type=int, default=9100, help="Port to listen on (default: 9100)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to listen on (default: 0.0.0.0)")
    args = parser.parse_args()

    output_file = args.output or f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    dispatcher = Dispatcher()
    dispatcher.set_default_handler(handle_message)

    server = BlockingOSCUDPServer((args.host, args.port), dispatcher)

    print(f"┌─ OSC Recorder ───────────────────────────────────┐")
    print(f"│  Listening on {args.host}:{args.port:<26}│")
    print(f"│  Output file : {output_file:<35}│")
    print(f"│  Press Ctrl+C to stop and save                   │")
    print(f"└──────────────────────────────────────────────────┘")
    print()

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n⏹  Stopping...")
        server.shutdown()

    if recorded_messages:
        save_recording(output_file, args.port)
    else:
        print("⚠  No messages recorded.")


if __name__ == "__main__":
    main()