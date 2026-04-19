import os 
import json 

import numpy as np # for handling audio data as numpy arrays
from math import gcd # for calculating resampling factors
from scipy.signal import resample_poly # for resampling to required rate used by the model
from essentia.standard import TensorflowPredictEffnetDiscogs # for genre classification
from pythonosc import udp_client # for sending results back to the UI via OSC


os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Suppress TensorFlow logging except for errors

# ─── ABOUT THIS ANALYSER ──────────────────────────────────────────────────────
# The Discogs-EffNet model was trained on full commercial recordings or complete
# mixes with multiple instruments, production, and arrangement. It performs best
# when analysing a full band or produced track (e.g. a guitar + drums + bass mix,
# or a DAW output). It will struggle with solo improvisation, a single dry
# instrument, or sparse audio, as the model won't have enough musical context to
# confidently classify genre in those cases.
#
# Ideal sources: Ableton master output, full mix from a mixer, DAW playback.
# Poor sources:  solo piano improvisation, isolated vocals, single dry instrument.
# ─────────────────────────────────────────────────────────────────────────────

# configuration

# Audio
SENDER_RATE     = 48000   # sample rate broadcaster sends
MODEL_RATE      = 16000   # sample rate the Essentia model expects -> need resampling through resample_poly
CHUNK_DURATION  = 4       # seconds of audio per classification window
CHUNK_SAMPLES   = MODEL_RATE * CHUNK_DURATION  # = 64000 samples at 16kHz
HOP_FRACTION    = 0.5     # how much the window advances after each classify
                          # 0.5 = 50% overlap — classifies every 2 seconds


# Model
MODELS_DIR  = "models"
MODEL_PB    = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.pb")
MODEL_JSON  = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.json")

# Analysis mode
DETAILED_GENRES = True # True = raw discogs labels
                       # False = simplified grouped styles (Jazz, Rock, etc.)


# Load Tensorflow model upon initalisation of GenreAnalyser class
def load_model():
    with open(MODEL_JSON, "r") as f:
        metadata = json.load(f)
    labels = metadata["classes"]

    model = TensorflowPredictEffnetDiscogs(
        graphFilename=MODEL_PB,
        output="PartitionedCall:0"
    )

    print(f"[genre] Model loaded — {len(labels)} labels")
    return model, labels

# Resample audio to model requirements
def resample(audio, from_rate, to_rate):
    g = gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)


# ─── AUDIO BUFFER ─────────────────────────────────────────────────────────────
# The model needs 4 seconds of audio to classify genre — but audio arrives as
# small chunks (~42ms each at 2048 samples). The AudioBuffer accumulates those
# chunks into one continuous numpy array until enough audio has been collected.
#
# Once the buffer holds 4 seconds of audio, it produces a "window" for
# classification. After classifying, it doesn't empty — it slides forward by
# 2 seconds (HOP_FRACTION = 0.5), keeping the second half as the start of the
# next window. This is called a sliding window with 50% overlap:
#
#   window 1:  [████████████████]
#   window 2:          [████████████████]
#   window 3:                  [████████████████]
#
# This means a new classification happens every 2 seconds, even though each
# classification uses 4 seconds of audio. The overlap gives continuity —
# sudden genre changes don't get missed between windows.
# ─────────────────────────────────────────────────────────────────────────────

class AudioBuffer:
    def __init__(self):
        self.buffer = np.array([], dtype=np.float32)
    
    def push(self, chunk):
        resampled = resample(chunk, SENDER_RATE, MODEL_RATE) 
        self.buffer = np.concatenate([self.buffer, resampled])

    def ready(self):
        return len(self.buffer) >= CHUNK_SAMPLES

    def pop_window(self):
        window = self.buffer[:CHUNK_SAMPLES] # take first 4 seconds
        self.buffer = self.buffer[int(CHUNK_SAMPLES * HOP_FRACTION):] # advance window by 2 seconds
        return window
    

# Style map for grouping detailed discogs genres into broader styles for simplified display
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
    # ── 1. run the model ──────────────────────────────────────────────────────
    predictions = model(audio)
    # predictions.shape = (N_frames, 400)
    # N_frames depends on audio length — the model slices internally
    # 400 = number of Discogs genre classes

    # ── 2. average across frames ──────────────────────────────────────────────
    mean_preds = np.mean(predictions, axis=0)
    # now shape = (400,) — one confidence score per label

    if DETAILED_GENRES:
        # ── 3a. detailed: take top 5 raw Discogs labels ───────────────────────
        top_indices = np.argsort(mean_preds)[::-1][:5]
        results = [(labels[i], float(mean_preds[i])) for i in top_indices]

    else:
        # ── 3b. simple: group scores into broad styles ────────────────────────
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
    # returns a list of (genre_name, confidence) tuples, highest first
    # e.g. [("Jazz---Bebop", 0.42), ("Jazz---Hard Bop", 0.31), ...]


class GenreAnalyser:
    def __init__(self):
        self.model, self.labels = load_model()
        self.buffer = AudioBuffer()
        print("[genre] Ready.")

    def push(self, audio):
        self.buffer.push(audio)

        if self.buffer.ready():
            window = self.buffer.pop_window()
            results = classify(window, self.model, self.labels)
            self._handle_results(results)

    def _handle_results(self, results):
        top_genre, top_confidence = results[0]

        # log to terminal
        self._display(results)

        # TODO send via OSC back to musinfo UI + touchdesigner

    def _display(self, results):
        print("\n[genre] ──────────────────────────────────")
        for genre, confidence in results:
            bar = "█" * int(confidence * 30) + "░" * (30 - int(confidence * 30))
            print(f"  {genre[:28]:<28} {confidence*100:5.1f}%  {bar}")
        print("──────────────────────────────────────────")