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


# ─── Model loading ────────────────────────────────────────────────────────────
def load_models():
    embedder = TensorflowPredictEffnetDiscogs(
        graphFilename=EFFNET_PB,
        output="PartitionedCall:1"
    )
    print("[mood] Discogs-EffNet embedder loaded")
    sys.stdout.flush()

    mood_classifiers = {}
    for mood, pb_path in MOOD_MODELS.items():
        mood_classifiers[mood] = TensorflowPredict2D(graphFilename=pb_path)
        print(f"[mood] Loaded classifier: {mood}")
        sys.stdout.flush()

    danceability_clf = TensorflowPredict2D(graphFilename=DANCEABILITY_PB)
    print("[mood] Loaded classifier: danceability")
    sys.stdout.flush()

    jamendo_clf = TensorflowPredict2D(graphFilename=JAMENDO_PB)
    with open(JAMENDO_JSON, "r") as f:
        jamendo_labels = json.load(f)["classes"]
    print(f"[mood] Loaded MTG-Jamendo ({len(jamendo_labels)} tags)")
    sys.stdout.flush()

    return embedder, mood_classifiers, danceability_clf, jamendo_clf, jamendo_labels


# ─── Inference ────────────────────────────────────────────────────────────────
def classify(audio, embedder, mood_classifiers, danceability_clf, jamendo_clf, jamendo_labels):
    # shared embeddings — computed once, reused by all classifiers
    embeddings = embedder(audio)

    # binary moods — index 1 = probability of positive class
    mood_scores = {}
    for mood, clf in mood_classifiers.items():
        preds = clf(embeddings)                  # [frames, 2]
        mood_scores[mood] = float(np.mean(preds[:, 1]))

    top_mood = max(mood_scores, key=mood_scores.get)

    # danceability — index 1 = danceable
    dance_preds  = danceability_clf(embeddings)  # [frames, 2]
    danceability = float(np.mean(dance_preds[:, 1]))

    # jamendo multi-label — mean over frames, top N above threshold
    jamendo_preds = jamendo_clf(embeddings)      # [frames, 56]
    mean_preds    = np.mean(jamendo_preds, axis=0)
    top_indices   = np.argsort(mean_preds)[::-1]

    jamendo_tags = []
    for i in top_indices:
        conf = float(mean_preds[i])
        if conf < JAMENDO_MIN_CONFIDENCE:
            break
        jamendo_tags.append(jamendo_labels[i])
        if len(jamendo_tags) >= JAMENDO_TOP_N:
            break

    return top_mood, danceability, jamendo_tags


# ─── Analyser class ───────────────────────────────────────────────────────────
class MoodAnalyser:
    def __init__(self, instrument_name="unknown", sample_rate=48000):
        self.instrument_name = instrument_name
        self.sender_rate     = sample_rate

        (self.embedder,
         self.mood_classifiers,
         self.danceability_clf,
         self.jamendo_clf,
         self.jamendo_labels) = load_models()

        self.buffer     = AudioBuffer(self.sender_rate)
        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)

        print(f"[mood] Ready for '{instrument_name}' @ {sample_rate}Hz")
        print(f"[mood] OSC target: {OSC_HOST}:{OSC_PORT}")
        sys.stdout.flush()

    def push(self, audio):
        self.buffer.push(audio)
        if self.buffer.ready():
            window = self.buffer.pop_window()
            top_mood, danceability, jamendo_tags = classify(
                window,
                self.embedder,
                self.mood_classifiers,
                self.danceability_clf,
                self.jamendo_clf,
                self.jamendo_labels,
            )
            self._send(top_mood, danceability, jamendo_tags)

    def _send(self, top_mood, danceability, jamendo_tags):
        inst = self.instrument_name

        self.osc_client.send_message(f"/mood/{inst}/top",          top_mood)
        self.osc_client.send_message(f"/mood/{inst}/danceability", round(danceability * 100, 1))
        self.osc_client.send_message(f"/mood/{inst}/tags",         ", ".join(jamendo_tags))

        print(f"[mood/{inst}] mood: {top_mood}")
        print(f"[mood/{inst}] danceability_score: {round(danceability * 100, 1)}")
        print(f"[mood/{inst}] mood_tags: {', '.join(jamendo_tags) or 'none'}")
        sys.stdout.flush()