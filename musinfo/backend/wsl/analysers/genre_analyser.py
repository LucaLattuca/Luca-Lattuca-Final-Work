import os

# Debugging
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'      # suppresses C++ INFO/WARNING logs
os.environ['CUDA_VISIBLE_DEVICES'] = ''         # tells TF no GPU → stops the whole probe loop
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'       # suppresses the oneDNN message
os.environ['ESSENTIA_LOG_LEVEL'] = 'error'  # suppresses INFO from Essentia's C++ logger

DEBUG = False
INFO = True

import json 

import numpy as np
from math import gcd
from scipy.signal import resample_poly
from essentia.standard import TensorflowPredictEffnetDiscogs
from pythonosc import udp_client
import sys
import subprocess

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# Configuration
MODEL_RATE      = 16000
CHUNK_DURATION  = 4
CHUNK_SAMPLES   = MODEL_RATE * CHUNK_DURATION
HOP_FRACTION    = 0.5

# Model - FIXED: Go up one level from analysers/ to find models/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "models")  # Go up one level
MODEL_PB = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.pb")
MODEL_JSON = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.json")

DETAILED_GENRES = False


def get_windows_host_ip():
    result = subprocess.run(
        ["ip", "route", "show", "default"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"

# OSC config
OSC_HOST = get_windows_host_ip()
OSC_PORT = 9000
OSC_PROMPT_PORT = 9001

def load_model():
    with open(MODEL_JSON, "r") as f:
        metadata = json.load(f)
    labels = metadata["classes"]

    model = TensorflowPredictEffnetDiscogs(
        graphFilename=MODEL_PB,
        output="PartitionedCall:0"
    )

    if INFO :
        print(f"[genre] Model loaded — {len(labels)} labels")
        sys.stdout.flush() 
    return model, labels

def resample(audio, from_rate, to_rate):
    g = gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)


class AudioBuffer:
    def __init__(self, sender_rate):
        self.buffer = np.array([], dtype=np.float32)
        self.sender_rate = sender_rate  # Store the sample rate
    
    def push(self, chunk):
        resampled = resample(chunk, self.sender_rate, MODEL_RATE) 
        self.buffer = np.concatenate([self.buffer, resampled])

    def ready(self):
        return len(self.buffer) >= CHUNK_SAMPLES

    def pop_window(self):
        window = self.buffer[:CHUNK_SAMPLES]
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


def classify(audio, model, labels):
    predictions = model(audio)
    mean_preds = np.mean(predictions, axis=0)

    if DETAILED_GENRES:
        top_indices = np.argsort(mean_preds)[::-1][:5]
        results = [(labels[i], float(mean_preds[i])) for i in top_indices]
    else:
        style_scores = {}
        for style, members in STYLE_MAP.items():
            scores = [
                mean_preds[i]
                for i, label in enumerate(labels)
                if any(m.lower() in label.lower() for m in members)
            ]
            style_scores[style] = float(max(scores)) if scores else 0.0
        results = sorted(style_scores.items(), key=lambda x: x[1], reverse=True)[:5]

    return results


class GenreAnalyser:
    def __init__(self, instrument_name="unknown", sample_rate=48000):
        self.instrument_name = instrument_name
        self.sender_rate = sample_rate  # Use the provided sample rate
        self.model, self.labels = load_model()
        self.buffer = AudioBuffer(self.sender_rate)

        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.prompt_osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PROMPT_PORT)

        
        if INFO : 
            print(f"[genre] Ready for '{instrument_name}' @ {sample_rate}Hz")
            sys.stdout.flush() 
        if INFO : 
            print(f"[genre] OSC target: {OSC_HOST}:{OSC_PORT}")
            print(f"[genre] OSC Prompt target: {OSC_HOST}:{OSC_PROMPT_PORT}")
            sys.stdout.flush()
        
    def push(self, audio):
        self.buffer.push(audio)

        if self.buffer.ready():
            window = self.buffer.pop_window()
            results = classify(window, self.model, self.labels)
            self._handle_results(results)

    def _handle_results(self, results):

        if DEBUG:
            self._display(results)
        
        # Send top 3 genres as JSON
        top_3 = [
            {"genre": genre, "confidence": round(conf * 100, 1)}
            for genre, conf in results[:3]
        ]
        message = json.dumps(top_3)

        # send to frontend
        self.osc_client.send_message(f"/genre/{self.instrument_name}", message)
        
        if DEBUG : 
            print(f"[genre] OSC SENT: /genre/{self.instrument_name} → {message}")
            sys.stdout.flush()
        
        # send to prompt generator
        self.prompt_osc_client.send_message("/prompt/genre", message)

        if DEBUG : 
            print(f"[genre] OSC PROMPT SENT: /prompt/genre → {message}")
            sys.stdout.flush()

    
    def _display(self, results):
        print(f"\n[genre/{self.instrument_name}] ──────────────────────────────────")
        sys.stdout.flush() 
        for genre, confidence in results:
            bar = "█" * int(confidence * 30) + "░" * (30 - int(confidence * 30))
            print(f"  {genre[:28]:<28} {confidence*100:5.1f}%  {bar}")
        print("──────────────────────────────────────────────")
        sys.stdout.flush()