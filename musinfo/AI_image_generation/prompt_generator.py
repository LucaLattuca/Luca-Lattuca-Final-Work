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
import time
from pythonosc import dispatcher, osc_server, udp_client



# ── OSC config ─────────────────────────────────────────────────────────────────
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 9001

EMIT_HOST = "127.0.0.1"
EMIT_PORT = 9002

PROMPT_INTERVAL = 4.0  # seconds between prompt emissions


# ── Random prompt mode ─────────────────────────────────────────────────────────
# RANDOM_PROMPT_MODE = True 
RANDOM_PROMPT_MODE = False 


RANDOM_PROMPTS = [
    (
        "vast ocean seascape, deep blue rolling waves, sea foam, horizon mist, "
        "dramatic coastal light, abstract visual art, no text",
    ),
    (
        "endless grass meadow, golden hour sunlight, swaying blades, wind ripples, "
        "soft green palette, peaceful countryside, abstract visual art, no text",
    ),
    (
        "arid desert landscape, warm sand dunes, harsh sunlight, distant heat haze, "
        "ochre and burnt sienna tones, dry stillness, abstract visual art, no text",
    ),
]

_random_prompt_index = 0
_random_prompt_lock  = threading.Lock()

# pipeline state — set by Tauri when start/stop_pipeline fires
_pipeline_running = False
_pipeline_lock    = threading.Lock()

# ── State store ────────────────────────────────────────────────────────────────
# None = not yet received from analyser. Defaults are applied at prompt assembly.
_state_lock = threading.Lock()
_state = {
    "genre":        None,   # list of dicts [{"genre": str, "confidence": float}]
    "mood":         None,   # str
    "mood_tags":    None,   # str (comma-separated)
    "danceability": None,   # float 0–100
    "bpm":          None,   # float
    "tempo_feel":   None,   # str
}

# controlled by the Performance tab toggle via OSC from Tauri
_image_gen_enabled = False
_image_gen_lock    = threading.Lock()


# ── Prompt assembly ────────────────────────────────────────────────────────────
NEGATIVE_PROMPT = (
    "photorealistic, faces, text, letters, words, numbers, logos, watermark, "
    "blurry, low quality"
)

GENRE_LANDSCAPE = {
    "Jazz":         "intimate jazz club atmosphere, smoky room, warm stage light",
    "Blues":        "dusty southern landscape, rustic crossroads, moonlit bayou",
    "Classical":    "grand concert hall, ornate architecture, ethereal cathedral light",
    "Folk":         "rolling countryside, forest clearing, campfire under stars",
    "Rock":         "electric cityscape, urban rooftop, industrial concrete",
    "Metal":        "volcanic landscape, dark fortress, stormy mountain peak",
    "Pop":          "vibrant neon cityscape, colourful abstract geometry",
    "Soul / R&B":   "soulful city nightscape, warm street light, velvet curtains",
    "Hip-Hop":      "urban street mural, graffiti walls, city skyline at dusk",
    "Electronic":   "futuristic grid, glowing data streams, infinite digital space",
    "Reggae":       "tropical beach sunset, lush island coastline, palm silhouettes",
    "Country":      "open prairie sunset, barn wood, golden wheat field",
    "Latin":        "vibrant plaza at night, festive lanterns, cobblestone streets",
    "Experimental": "abstract void, surreal geometry, fractal dreamscape",
    "_default":     "atmospheric abstract landscape, soft gradients",
}

MOOD_COLOR = {
    "aggressive": "harsh red and black contrast, sharp angular forms",
    "happy":      "bright warm palette, cheerful golden tones, light and airy",
    "party":      "vivid saturated colours, dynamic shapes, celebratory energy",
    "relaxed":    "soft muted tones, gentle curves, peaceful atmosphere",
    "sad":        "cool blue and grey palette, melancholic stillness, misty light",
    "_default":   "balanced neutral palette, calm composition",
}

TEMPO_DYNAMICS = {
    "ballad":   "slow dissolving transitions, dreamlike languor",
    "slow":     "unhurried drift, long gentle exposure",
    "medium":   "balanced pace, steady organic flow",
    "uptempo":  "lively vibrant energy, quickening pulse",
    "fast":     "intense rapid movement, electric momentum",
    "_default": "natural flowing pace",
}

KNOWN_TAG_MAP = {
    "film":        "cinematic film aesthetic",
    "dark":        "dark moody atmosphere",
    "emotional":   "deeply emotional atmosphere",
    "positive":    "uplifting positive energy",
    "epic":        "epic grand scale",
    "melancholic": "melancholic introspective tone",
    "dramatic":    "dramatic high contrast",
    "ambiental":   "ambient environmental atmosphere",
    "motivational":"inspiring motivational energy",
    "nature":      "natural organic environment",
}


def _on_pipeline_running(address, *args):
    global _pipeline_running
    value = int(args[0]) if args else 0
    with _pipeline_lock:
        _pipeline_running = bool(value)
    state = "RUNNING" if _pipeline_running else "STOPPED"
    print(f"[prompt_gen] pipeline {state}", flush=True)

def _clean_tags(raw_tags: str) -> str:
    if not raw_tags:
        return ""
    phrases = []
    for tag in [t.strip() for t in raw_tags.split(",") if t.strip()]:
        phrases.append(KNOWN_TAG_MAP.get(tag.lower(), tag))
    return ", ".join(phrases)

def _dance_phrase(danceability: float) -> str:
    if danceability >= 75:
        return "energetic flowing motion, dynamic movement"
    elif danceability >= 50:
        return "gentle rhythmic flow, subtle motion"
    elif danceability >= 25:
        return "slow drifting movement, peaceful stillness"
    else:
        return "serene stillness, contemplative quiet"

def assemble_prompt(state: dict) -> str:
    parts = []

    # Genre — landscape and scene
    if state["genre"]:
        top = state["genre"][:3]
        genre_names = [g["genre"] for g in top]
        primary = genre_names[0]
        parts.append(f"{primary} music atmosphere")
        parts.append(GENRE_LANDSCAPE.get(primary, GENRE_LANDSCAPE["_default"]))
        if len(genre_names) > 1:
            parts.append(f"hints of {' and '.join(genre_names[1:])}")
    else:
        parts.append(GENRE_LANDSCAPE["_default"])

    # Mood — structure and colour
    if state["mood"]:
        parts.append(f"{state['mood']} mood")
        parts.append(MOOD_COLOR.get(state["mood"], MOOD_COLOR["_default"]))
    else:
        parts.append(MOOD_COLOR["_default"])

    # Mood tags — context modifiers
    if state["mood_tags"]:
        cleaned = _clean_tags(state["mood_tags"])
        if cleaned:
            parts.append(cleaned)

    # Danceability — movement
    dance_val = state["danceability"] if state["danceability"] is not None else 50.0
    parts.append(_dance_phrase(dance_val))

    # Tempo feel — dynamics
    feel = state["tempo_feel"] if state["tempo_feel"] else "_default"
    parts.append(TEMPO_DYNAMICS.get(feel, TEMPO_DYNAMICS["_default"]))

    # Closing style tokens
    parts.append("abstract visual art, no text")

    return ", ".join(parts)


def _next_random_prompt() -> str:
    global _random_prompt_index
    with _random_prompt_lock:
        prompt = RANDOM_PROMPTS[_random_prompt_index][0]
        _random_prompt_index = (_random_prompt_index + 1) % len(RANDOM_PROMPTS)
    return prompt



# ── OSC handlers ───────────────────────────────────────────────────────────────
def _on_genre(address, *args):
    raw = args[0] if args else "[]"
    try:
        genres = json.loads(raw)
        with _state_lock:
            _state["genre"] = genres
        print(f"[prompt_gen] genre: {[g['genre'] for g in genres[:3]]}", flush=True)
    except Exception as e:
        print(f"[prompt_gen] genre parse error: {e}", flush=True)

def _on_mood(address, *args):
    value = str(args[0]) if args else ""
    with _state_lock:
        _state["mood"] = value
    print(f"[prompt_gen] mood: {value}", flush=True)

def _on_mood_tags(address, *args):
    value = str(args[0]) if args else ""
    with _state_lock:
        _state["mood_tags"] = value
    print(f"[prompt_gen] mood_tags: {value}", flush=True)

def _on_danceability(address, *args):
    try:
        value = float(args[0]) if args else 0.0
        with _state_lock:
            _state["danceability"] = value
        print(f"[prompt_gen] danceability: {value:.1f}", flush=True)
    except Exception as e:
        print(f"[prompt_gen] danceability parse error: {e}", flush=True)

def _on_bpm(address, *args):
    try:
        value = float(args[0]) if args else 0.0
        with _state_lock:
            _state["bpm"] = value
        print(f"[prompt_gen] bpm: {value:.1f}", flush=True)
    except Exception as e:
        print(f"[prompt_gen] bpm parse error: {e}", flush=True)

def _on_tempo_feel(address, *args):
    value = str(args[0]) if args else ""
    with _state_lock:
        _state["tempo_feel"] = value
    print(f"[prompt_gen] tempo_feel: {value}", flush=True)

def _on_image_gen_enabled(address, *args):
    global _image_gen_enabled
    value = int(args[0]) if args else 0
    with _image_gen_lock:
        _image_gen_enabled = bool(value)
    state = "ENABLED" if _image_gen_enabled else "DISABLED"
    print(f"[prompt_gen] image generation {state}", flush=True)


# ── Emission loop ──────────────────────────────────────────────────────────────
def _prompt_loop(emit_client):
    _pipeline_was_running = False

    while True:
        time.sleep(PROMPT_INTERVAL)

        with _pipeline_lock:
            pipeline = _pipeline_running
        with _image_gen_lock:
            active = _image_gen_enabled

        if not (pipeline and active):
            _pipeline_was_running = pipeline
            continue

        # pipeline just became ready — wait 2s for analysers to warm up
        if not _pipeline_was_running:
            print("[prompt_gen] pipeline just started — waiting 2s for analysers...", flush=True)
            time.sleep(2.0)
            _pipeline_was_running = True

        if RANDOM_PROMPT_MODE:
            positive = _next_random_prompt()
            emit_client.send_message("/image/prompt/positive", positive)
            emit_client.send_message("/image/prompt/negative", NEGATIVE_PROMPT)
            print(f"[prompt_gen] RANDOM PROMPT: {positive}", flush=True)
        else:
            with _state_lock:
                snapshot = dict(_state)

            positive = assemble_prompt(snapshot)
            emit_client.send_message("/image/prompt/positive", positive)
            emit_client.send_message("/image/prompt/negative", NEGATIVE_PROMPT)
            print(f"[prompt_gen] PROMPT: {positive}", flush=True)

# ── Main ───────────────────────────────────────────────────────────────────────
d = dispatcher.Dispatcher()
d.map("/prompt/genre",        _on_genre)
d.map("/prompt/mood",         _on_mood)
d.map("/prompt/mood_tags",    _on_mood_tags)
d.map("/prompt/danceability", _on_danceability)
d.map("/prompt/bpm",          _on_bpm)
d.map("/prompt/tempo_feel",   _on_tempo_feel)
d.map("/musinfo/image_gen_enabled",   _on_image_gen_enabled) 
d.map("/musinfo/pipeline_running", _on_pipeline_running)

server = osc_server.ThreadingOSCUDPServer((LISTEN_HOST, LISTEN_PORT), d)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()

print(f"[prompt_gen] OSC server listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
print(f"[prompt_gen] Emitting prompts every {PROMPT_INTERVAL}s → {EMIT_HOST}:{EMIT_PORT}", flush=True)

emit_client = udp_client.SimpleUDPClient(EMIT_HOST, EMIT_PORT)

# Block main thread on prompt loop — Rust terminates the process on shutdown
_prompt_loop(emit_client)