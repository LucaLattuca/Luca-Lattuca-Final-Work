"""
prompt_generator.py
Windows side — AI_image_generation/

Launched by Rust/Tauri as a managed process.

Listens on port 9001 for incoming OSC from the WSL analysers:
  /prompt/genre        JSON  [{"genre": "Jazz", "confidence": 87.3}, ...]
  /prompt/mood         str   "relaxed"
  /prompt/mood_tags    str   "film, dark"
  /prompt/danceability float 0–100
  /prompt/bpm          float BPM value
  /prompt/tempo_feel   str   "ballad" | "slow" | "medium" | "uptempo" | "fast"
"""

import sys
import json
import threading
from pythonosc import dispatcher, osc_server

# ── OSC config ─────────────────────────────────────────────────────────────────
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 9001


# ── OSC handlers ───────────────────────────────────────────────────────────────
def _on_genre(address, *args):
    raw = args[0] if args else "[]"
    try:
        genres = json.loads(raw)
        print(f"[prompt_gen] genre: {[g['genre'] for g in genres[:3]]}", flush=True)
    except Exception as e:
        print(f"[prompt_gen] genre parse error: {e}", flush=True)

def _on_mood(address, *args):
    value = str(args[0]) if args else ""
    print(f"[prompt_gen] mood: {value}", flush=True)

def _on_mood_tags(address, *args):
    value = str(args[0]) if args else ""
    print(f"[prompt_gen] mood_tags: {value}", flush=True)

def _on_danceability(address, *args):
    try:
        value = float(args[0]) if args else 0.0
        print(f"[prompt_gen] danceability: {value:.1f}", flush=True)
    except Exception as e:
        print(f"[prompt_gen] danceability parse error: {e}", flush=True)

def _on_bpm(address, *args):
    try:
        value = float(args[0]) if args else 0.0
        print(f"[prompt_gen] bpm: {value:.1f}", flush=True)
    except Exception as e:
        print(f"[prompt_gen] bpm parse error: {e}", flush=True)

def _on_tempo_feel(address, *args):
    value = str(args[0]) if args else ""
    print(f"[prompt_gen] tempo_feel: {value}", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────────
d = dispatcher.Dispatcher()
d.map("/prompt/genre",        _on_genre)
d.map("/prompt/mood",         _on_mood)
d.map("/prompt/mood_tags",    _on_mood_tags)
d.map("/prompt/danceability", _on_danceability)
d.map("/prompt/bpm",          _on_bpm)
d.map("/prompt/tempo_feel",   _on_tempo_feel)

server = osc_server.ThreadingOSCUDPServer((LISTEN_HOST, LISTEN_PORT), d)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()

print(f"[prompt_gen] OSC server listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)

# Block main thread — Rust will terminate the process when shutting down
server_thread.join()