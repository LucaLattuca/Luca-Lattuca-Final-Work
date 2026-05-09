import os
import sys
import json
import subprocess
from math import gcd

import numpy as np
from scipy.signal import resample_poly
from pythonosc import udp_client


from essentia.standard import PitchCREPE

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

MODEL_RATE       = 16000
CHUNK_DURATION   = 0.1
CHUNK_SAMPLES    = int(MODEL_RATE * CHUNK_DURATION) # 1600 samples @ 0.1s
HOP_FRACTION     = 0.5
CONF_THRESHOLD   = 0.5

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "models", "pitch_models")

CREPE_MODELS = {
    # "tiny":   os.path.join(MODELS_DIR, "crepe-tiny-1.pb"),  -> not added
    # "small":  os.path.join(MODELS_DIR, "crepe-small-1.pb"), -> not added
    "medium": os.path.join(MODELS_DIR, "crepe-medium-1.pb"),
    "large":  os.path.join(MODELS_DIR, "crepe-large-1.pb"),
    # "full":   os.path.join(MODELS_DIR, "crepe-full-1.pb"), -> not added
}

MODEL_SIZE = "medium" # medium | large



def get_windows_host_ip():
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"

OSC_HOST = get_windows_host_ip()
OSC_PORT = 9000


def _resample(audio, from_rate, to_rate):
    g = gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)


class AudioBuffer:
    def __init__(self, sender_rate):
        self.sender_rate = sender_rate
        self.buffer = np.array([], dtype=np.float32)

    def push(self, chunk):
        self.buffer = np.concatenate([self.buffer, _resample(chunk, self.sender_rate, MODEL_RATE)])

    def ready(self):
        return len(self.buffer) >= CHUNK_SAMPLES

    def pop_window(self):
        window = self.buffer[:CHUNK_SAMPLES]
        self.buffer = self.buffer[int(CHUNK_SAMPLES * HOP_FRACTION):]
        return window
    


def load_model():
    path = CREPE_MODELS[MODEL_SIZE]
    if not os.path.exists(path):
        raise FileNotFoundError(f"[CREPE] model not found: {path}")
    model = PitchCREPE(graphFilename=path)
    print(f"[CREPE] loaded: {MODEL_SIZE} ({path})")
    sys.stdout.flush()
    return model


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def _hz_to_note(freq_hz):
    if freq_hz <= 0:
        return None
    midi = int(round(69 + 12 * np.log2(freq_hz / 440.0)))
    return f"{_NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"


def classify(audio, model):
    # essentia unpacks the wrapped model output into 4 parallel frame-level arrays
    time, frequency, confidence, activations = model(audio)

    frames = []
    for t, freq, conf in zip(time, frequency, confidence):
        if conf < CONF_THRESHOLD:
            continue  # unvoiced / silent frame
        note = _hz_to_note(float(freq))
        if note:
            frames.append({
                "time":       round(float(t), 3),
                "freq_hz":    round(float(freq), 2),
                "note":       note,
                "confidence": round(float(conf), 3),
            })
    return frames



class PitchCREPEAnalyser:
    def __init__(self, instrument_name="unknown", sample_rate=48000):
        self.instrument_name = instrument_name
        self.model  = load_model()
        self.buffer = AudioBuffer(sample_rate)
        self.osc    = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        print(f"[Pitch_crepe] ready — {instrument_name} @ {sample_rate}Hz → OSC {OSC_HOST}:{OSC_PORT}")
        sys.stdout.flush()

    def push(self, audio):
        self.buffer.push(audio)
        if self.buffer.ready():
            self._run(self.buffer.pop_window())

    def _run(self, window):
        frames = classify(window, self.model)
        if not frames:
            return

        # highest-confidence frame represents the window
        best = max(frames, key=lambda f: f["confidence"])
        summary = {
            "note":       best["note"],
            "freq_hz":    best["freq_hz"],
            "confidence": best["confidence"],
            "voiced_frames": len(frames),
        }

        self._display(summary)
        self.osc.send_message(f"/pitch_crepe/{self.instrument_name}", json.dumps(summary))
        print(f"[Pitch] → /pitch_crepe/{self.instrument_name}  {summary['note']} {summary['freq_hz']}Hz")
        sys.stdout.flush()

    def _display(self, s):
        print(f"\n[pitch_crepe/{self.instrument_name}]")
        print(f"  {s['note']}  {s['freq_hz']} Hz  conf={s['confidence']:.3f}  voiced={s['voiced_frames']} frames")
        sys.stdout.flush()