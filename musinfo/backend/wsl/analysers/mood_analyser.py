import os
import json
import sys
import subprocess

import numpy as np
from math import gcd
from scipy.signal import resample_poly
from essentia.standard import TensorflowPredictEffnetDiscogs, TensorflowPredict2D
from pythonosc import udp_client

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# ─── Audio config ─────────────────────────────────────────────────────────────
MODEL_RATE     = 16000
CHUNK_DURATION = 4
CHUNK_SAMPLES  = MODEL_RATE * CHUNK_DURATION
HOP_FRACTION   = 0.5

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR      = os.path.join(os.path.dirname(SCRIPT_DIR), "models")
MOOD_MODELS_DIR = os.path.join(MODELS_DIR, "mood_models")

EFFNET_PB = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.pb")

MOOD_MODELS = {
    "aggressive": os.path.join(MOOD_MODELS_DIR, "mood_aggressive-discogs-effnet-1.pb"),
    "happy":      os.path.join(MOOD_MODELS_DIR, "mood_happy-discogs-effnet-1.pb"),
    "party":      os.path.join(MOOD_MODELS_DIR, "mood_party-discogs-effnet-1.pb"),
    "relaxed":    os.path.join(MOOD_MODELS_DIR, "mood_relaxed-discogs-effnet-1.pb"),
    "sad":        os.path.join(MOOD_MODELS_DIR, "mood_sad-discogs-effnet-1.pb"),
}

DANCEABILITY_PB = os.path.join(MOOD_MODELS_DIR, "danceability-discogs-effnet-1.pb")
JAMENDO_PB      = os.path.join(MOOD_MODELS_DIR, "mtg_jamendo_moodtheme-discogs-effnet-1.pb")
JAMENDO_JSON    = os.path.join(MOOD_MODELS_DIR, "mtg_jamendo_moodtheme-discogs-effnet-1.json")

# ─── Jamendo output config ────────────────────────────────────────────────────
JAMENDO_TOP_N          = 2
JAMENDO_MIN_CONFIDENCE = 0.10

# ─── OSC ──────────────────────────────────────────────────────────────────────
def get_windows_host_ip():
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"

OSC_HOST = get_windows_host_ip()
OSC_PORT = 9000

# ─── Audio helpers ────────────────────────────────────────────────────────────
def resample(audio, from_rate, to_rate):
    g = gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)


class AudioBuffer:
    def __init__(self, sender_rate):
        self.buffer      = np.array([], dtype=np.float32)
        self.sender_rate = sender_rate

    def push(self, chunk):
        resampled = resample(chunk, self.sender_rate, MODEL_RATE)
        self.buffer = np.concatenate([self.buffer, resampled])

    def ready(self):
        return len(self.buffer) >= CHUNK_SAMPLES

    def pop_window(self):
        window      = self.buffer[:CHUNK_SAMPLES]
        self.buffer = self.buffer[int(CHUNK_SAMPLES * HOP_FRACTION):]
        return window