import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['ESSENTIA_LOG_LEVEL'] = 'error'

DEBUG = False
INFO  = True

import json
import sys
import numpy as np
from math import gcd
from scipy.signal import resample_poly
from essentia.standard import TensorflowPredictEffnetDiscogs
from pythonosc import udp_client
import subprocess

from analysers.shared_embedder import embedder as shared_embedder

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

MODEL_RATE     = 16000
CHUNK_DURATION = 4
CHUNK_SAMPLES  = MODEL_RATE * CHUNK_DURATION
HOP_FRACTION   = 0.5 # 0.5 = 2s, 0.25 = 1s

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "models")
MODEL_PB   = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.pb")
MODEL_JSON = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.json")

DETAILED_GENRES = False


def get_windows_host_ip():
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"

OSC_HOST        = get_windows_host_ip()
OSC_PORT        = 9000
OSC_PROMPT_PORT = 9001


def resample(audio, from_rate, to_rate):
    g = gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)


class AudioBuffer:
    def __init__(self, sender_rate):
        self.buffer      = np.array([], dtype=np.float32)
        self.sender_rate = sender_rate

    def push(self, chunk):
        self.buffer = np.concatenate([
            self.buffer,
            resample(chunk, self.sender_rate, MODEL_RATE)
        ])

    def ready(self):
        return len(self.buffer) >= CHUNK_SAMPLES

    def pop_window(self):
        window      = self.buffer[:CHUNK_SAMPLES]
        self.buffer = self.buffer[int(CHUNK_SAMPLES * HOP_FRACTION):]
        return window


STYLE_MAP = {
    "Jazz":         ["Jazz", "Contemporary Jazz", "Bebop", "Cool Jazz", "Hard Bop",
                     "Post-Bop", "Vocal Jazz", "Free Jazz", "Fusion", "Swing"],
    "Blues":        ["Blues", "Delta Blues", "Country Blues", "Piano Blues", "Electric Blues"],
    "Classical":    ["Classical", "Neo-Classical", "Impressionist", "Romantic",
                     "Baroque", "Modern", "Contemporary"],
    "Folk":         ["Folk", "Acoustic", "Singer/Songwriter"],
    "Rock":         ["Rock", "Classic Rock", "Indie Rock", "Alternative Rock", "Hard Rock"],
    "Metal":        ["Heavy Metal", "Thrash", "Death Metal", "Black Metal", "Doom Metal"],
    "Pop":          ["Pop", "Indie Pop", "Synth-pop", "Chamber Pop"],
    "Soul / R&B":   ["Soul", "R&B", "Funk", "Gospel"],
    "Hip-Hop":      ["Hip Hop", "Rap"],
    "Electronic":   ["Electronic", "Techno", "House", "Ambient", "Drum n Bass", "IDM"],
    "Reggae":       ["Reggae", "Dub", "Ska"],
    "Country":      ["Country", "Bluegrass", "Americana"],
    "Latin":        ["Latin", "Bossa Nova", "Salsa", "Samba", "Tango"],
    "Experimental": ["Experimental", "Avantgarde", "Noise", "Abstract"],
}


class GenreAnalyser:
    def __init__(self, instrument_name: str, sample_rate: int, instrument_role: str = "default", instrument_index: int = 0):
        self.instrument_role  = instrument_role
        self.instrument_index = instrument_index
        self.instrument_name = instrument_name
        self.sender_rate     = sample_rate

        with open(MODEL_JSON, "r") as f:
            self.labels = json.load(f)["classes"]

        # Genre's own model instance — PartitionedCall:0 gives 400-label predictions.
        # GPU calls are routed through shared_embedder's _gpu_lock so they never
        # overlap with mood's embedder calls.
        self._model = TensorflowPredictEffnetDiscogs(
            graphFilename=MODEL_PB,
            output="PartitionedCall:0"
        )

        self.buffer = AudioBuffer(self.sender_rate)
        # Offset genre slightly so it doesn't align with mood's first fire at t=3s
        # Genre fires every 4s, first fire at t=4.5s
        self.buffer.buffer = np.zeros(int(MODEL_RATE * 0.5), dtype=np.float32)

        self.osc_client        = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.prompt_osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PROMPT_PORT)

        if INFO:
            print(f"[genre] Ready for '{instrument_name}' @ {sample_rate}Hz")
            print(f"[genre] OSC target: {OSC_HOST}:{OSC_PORT}")
            print(f"[genre] OSC Prompt target: {OSC_HOST}:{OSC_PROMPT_PORT}")
            sys.stdout.flush()

    def push(self, audio):
        self.buffer.push(audio)
        if self.buffer.ready():
            window  = self.buffer.pop_window()
            # Route through shared GPU lock — never overlaps with mood
            predictions = shared_embedder.get_predictions(window, self._model)
            results     = self._classify(predictions)
            self._handle_results(results)

    def _classify(self, predictions):
        mean_preds = np.mean(predictions, axis=0)

        if DETAILED_GENRES:
            top_indices = np.argsort(mean_preds)[::-1][:5]
            return [(self.labels[i], float(mean_preds[i])) for i in top_indices]

        style_scores = {}
        for style, members in STYLE_MAP.items():
            scores = [
                mean_preds[i]
                for i, label in enumerate(self.labels)
                if any(m.lower() in label.lower() for m in members)
            ]
            style_scores[style] = float(max(scores)) if scores else 0.0

        return sorted(style_scores.items(), key=lambda x: x[1], reverse=True)[:5]

    def _handle_results(self, results):
        top_3 = [
            {"genre": genre, "confidence": round(conf * 100, 1)}
            for genre, conf in results[:3]
        ]
        message = json.dumps(top_3)

        self.osc_client.send_message(f"/genre/{self.instrument_name}", message)
        self.prompt_osc_client.send_message("/prompt/genre", message)

        if DEBUG:
            self._display(results)
            print(f"[genre] -> {message}")
            sys.stdout.flush()

    def _display(self, results):
        print(f"\n[genre/{self.instrument_name}] ──────────────────────────────────")
        for genre, confidence in results:
            bar = "█" * int(confidence * 30) + "░" * (30 - int(confidence * 30))
            print(f"  {genre[:28]:<28} {confidence*100:5.1f}%  {bar}")
        print("──────────────────────────────────────────────")
        sys.stdout.flush()