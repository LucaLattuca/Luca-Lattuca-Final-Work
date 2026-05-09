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
CHUNK_DURATION   = 4
CHUNK_SAMPLES    = MODEL_RATE * CHUNK_DURATION  # 64000 samples
HOP_FRACTION     = 0.5
CONF_THRESHOLD   = 0.5

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "pitch", "crepe")


CREPE_MODELS = {
    # "tiny":   os.path.join(MODELS_DIR, "crepe-tiny-1.pb"),  -> not added
    # "small":  os.path.join(MODELS_DIR, "crepe-small-1.pb"), -> not added
    "medium": os.path.join(MODELS_DIR, "crepe-medium-1.pb"),
    "large":  os.path.join(MODELS_DIR, "crepe-large-1.pb"),
    # "full":   os.path.join(MODELS_DIR, "crepe-full-1.pb"), -> not added
}


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


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