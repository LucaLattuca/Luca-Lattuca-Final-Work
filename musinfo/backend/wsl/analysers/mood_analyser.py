import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'      # suppresses C++ INFO/WARNING logs
os.environ['CUDA_VISIBLE_DEVICES'] = ''         # tells TF no GPU → stops the whole probe loop
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'       # suppresses the oneDNN message
os.environ['ESSENTIA_LOG_LEVEL'] = 'error'  # suppresses INFO from Essentia's C++ logger

import json
import sys
import subprocess

import numpy as np
from math import gcd
from scipy.signal import resample_poly
from essentia.standard import TensorflowPredictEffnetDiscogs, TensorflowPredict2D
from pythonosc import udp_client

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# Debugging
DEBUG = False
INFO = True

# ─── Audio config ─────────────────────────────────────────────────────────────
MODEL_RATE = 16000

# Per-group durations (seconds) — tune these independently
MOOD_DURATION    = 3
DANCE_DURATION   = 3
JAMENDO_DURATION = 3

HOP_FRACTION = 0.5

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR      = os.path.join(os.path.dirname(SCRIPT_DIR), "models")
MOOD_MODELS_DIR = os.path.join(MODELS_DIR, "mood_models")

EFFNET_PB = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.pb")

# (pb_path, positive_class_index) — index of the positive/active class in model output
MOOD_MODELS = {
    "aggressive": (os.path.join(MOOD_MODELS_DIR, "mood_aggressive-discogs-effnet-1.pb"), 0),  # ["aggressive", "not_aggressive"]
    "happy":      (os.path.join(MOOD_MODELS_DIR, "mood_happy-discogs-effnet-1.pb"),      0),  # ["happy", "not_happy"]
    "party":      (os.path.join(MOOD_MODELS_DIR, "mood_party-discogs-effnet-1.pb"),      1),  # ["non_party", "party"]
    "relaxed":    (os.path.join(MOOD_MODELS_DIR, "mood_relaxed-discogs-effnet-1.pb"),    1),  # ["non_relaxed", "relaxed"]
    "sad":        (os.path.join(MOOD_MODELS_DIR, "mood_sad-discogs-effnet-1.pb"),        1),  # ["non_sad", "sad"]
}

DANCEABILITY_POSITIVE_IDX = 0  # ["danceable", "not_danceable"]

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
OSC_PROMPT_PORT = 9001

# ─── Audio helpers ────────────────────────────────────────────────────────────
def resample(audio, from_rate, to_rate):
    g = gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)


class AudioBuffer:
    def __init__(self, sender_rate, duration_seconds):
        self.buffer      = np.array([], dtype=np.float32)
        self.sender_rate = sender_rate
        self.chunk_samples = MODEL_RATE * duration_seconds

    def push(self, chunk):
        resampled = resample(chunk, self.sender_rate, MODEL_RATE)
        self.buffer = np.concatenate([self.buffer, resampled])

    def ready(self):
        return len(self.buffer) >= self.chunk_samples

    def pop_window(self):
        window      = self.buffer[:self.chunk_samples]
        self.buffer = self.buffer[int(self.chunk_samples * HOP_FRACTION):]
        return window


# ─── Model loading ────────────────────────────────────────────────────────────
def load_models():
    embedder = TensorflowPredictEffnetDiscogs(
        graphFilename=EFFNET_PB,
        output="PartitionedCall:1"
    )

    if INFO :
        print("[mood] Discogs-EffNet embedder loaded")
        sys.stdout.flush()

    mood_classifiers = {}
    for mood, (pb_path, pos_idx) in MOOD_MODELS.items():
        mood_classifiers[mood] = (
            TensorflowPredict2D(graphFilename=pb_path, output="model/Softmax"),
            pos_idx
        )
        if INFO :
            print(f"[mood] Loaded classifier: {mood} (positive class index: {pos_idx})")
            sys.stdout.flush()

    danceability_clf = TensorflowPredict2D(
        graphFilename=DANCEABILITY_PB,
        output="model/Softmax"
    )
    if INFO :
        print("[mood] Loaded classifier: danceability")
        sys.stdout.flush()

    jamendo_clf = TensorflowPredict2D(
        graphFilename=JAMENDO_PB,
        output="model/Sigmoid"
    )
    with open(JAMENDO_JSON, "r") as f:
        jamendo_labels = json.load(f)["classes"]
    
    if INFO : 
        print(f"[mood] Loaded MTG-Jamendo ({len(jamendo_labels)} tags)")
        sys.stdout.flush()

    return embedder, mood_classifiers, danceability_clf, jamendo_clf, jamendo_labels


# ─── Inference ────────────────────────────────────────────────────────────────
def classify_moods(audio, embedder, mood_classifiers):
    if DEBUG : 
        print(f"[mood] audio stats: min={audio.min():.3f} max={audio.max():.3f} rms={np.sqrt(np.mean(audio**2)):.4f}", flush=True)

    embeddings = embedder(audio)
    mood_scores = {}
    for mood, (clf, pos_idx) in mood_classifiers.items():
        preds = clf(embeddings)                  # [frames, 2]
        mood_scores[mood] = float(np.mean(preds[:, pos_idx]))
    top_mood = max(mood_scores, key=mood_scores.get)
    return top_mood, mood_scores


def classify_danceability(audio, embedder, danceability_clf):
    embeddings   = embedder(audio)
    preds        = danceability_clf(embeddings)  # [frames, 2]
    danceability = float(np.mean(preds[:, DANCEABILITY_POSITIVE_IDX]))
    return danceability


def classify_jamendo(audio, embedder, jamendo_clf, jamendo_labels):
    embeddings    = embedder(audio)
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

    return jamendo_tags


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

        # separate buffer per classifier group
        self.mood_buffer    = AudioBuffer(self.sender_rate, MOOD_DURATION)
        self.dance_buffer   = AudioBuffer(self.sender_rate, DANCE_DURATION)
        self.jamendo_buffer = AudioBuffer(self.sender_rate, JAMENDO_DURATION)

        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.prompt_osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PROMPT_PORT)

        if INFO :
            print(f"[mood] Ready for '{instrument_name}' @ {sample_rate}Hz")
            print(f"[mood] Windows — mood: {MOOD_DURATION}s  dance: {DANCE_DURATION}s  jamendo: {JAMENDO_DURATION}s")
            print(f"[mood] OSC target: {OSC_HOST}:{OSC_PORT}")
            print(f"[mood] OSC Prompt target: {OSC_HOST}:{OSC_PROMPT_PORT}")
            sys.stdout.flush()

    def push(self, audio):
        self.mood_buffer.push(audio)
        self.dance_buffer.push(audio)
        self.jamendo_buffer.push(audio)

        if self.mood_buffer.ready():
            window = self.mood_buffer.pop_window()
            top_mood, mood_scores = classify_moods(window, self.embedder, self.mood_classifiers)
            self._send_mood(top_mood, mood_scores)

        if self.dance_buffer.ready():
            window       = self.dance_buffer.pop_window()
            danceability = classify_danceability(window, self.embedder, self.danceability_clf)
            self._send_danceability(danceability)

        if self.jamendo_buffer.ready():
            window       = self.jamendo_buffer.pop_window()
            jamendo_tags = classify_jamendo(window, self.embedder, self.jamendo_clf, self.jamendo_labels)
            self._send_jamendo(jamendo_tags)

    def _send_mood(self, top_mood, mood_scores):
        inst = self.instrument_name
        scores_str = "  ".join(f"{k}={v*100:.1f}%" for k, v in sorted(mood_scores.items(), key=lambda x: x[1], reverse=True))
        
        self.osc_client.send_message(f"/mood/{inst}/top", top_mood)
        self.prompt_osc_client.send_message("/prompt/mood", top_mood)

        if DEBUG : 
            print(f"[mood/{inst}] {scores_str}")
            print(f"[mood/{inst}] mood: {top_mood}")
            sys.stdout.flush()

    def _send_danceability(self, danceability):
        inst = self.instrument_name
        
        value = round(danceability * 100, 1)
        self.osc_client.send_message(f"/mood/{inst}/danceability", str(value))
        self.prompt_osc_client.send_message("/prompt/danceability", value)

        if DEBUG : 
            print(f"[mood/{inst}] danceability: {value}%")
            sys.stdout.flush()

    def _send_jamendo(self, jamendo_tags):
        inst = self.instrument_name
        
        tags_str = ", ".join(jamendo_tags)
        self.osc_client.send_message(f"/mood/{inst}/tags", tags_str)
        self.prompt_osc_client.send_message("/prompt/mood_tags", tags_str)

        if DEBUG : 
            print(f"[mood/{inst}] tags: {tags_str or 'none'}")
            sys.stdout.flush()