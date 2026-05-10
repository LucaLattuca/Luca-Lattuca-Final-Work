import time
import os
import numpy as np
from collections import deque
from scipy.signal import resample_poly
from math import gcd
from pythonosc import udp_client

# ── CONFIG ────────────────────────────────────────────────────────────────────
MODEL_SR      = 11025
SMOOTHING     = 3
SEND_INTERVAL = 4.0
OSC_HOST      = "127.0.0.1"
OSC_PORT      = 9000
# ─────────────────────────────────────────────────────────────────────────────

# .pb frozen graph lives at models/bpm_models/deepsquare-k16-3.pb
# Download from: https://essentia.upf.edu/models/tempo/tempocnn/deepsquare-k16-3.pb
_HERE      = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(_HERE, "..", "..", "models", "bpm_models")
MODEL_FILE = os.path.join(_MODEL_DIR, "deepsquare-k16-3.pb")


# Accurate BPM via Essentia TempoCNN (deepsquare-k16-3).
# Runs on WSL. Outputs to /musinfo/bpm/accurate/{instrument}.
class BpmTempoCNNAnalyser:

    def __init__(self, instrument_name: str, sample_rate: int = 48000):
        self.instrument_name = instrument_name
        self.input_sr        = sample_rate
        self.osc             = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.address         = f"/musinfo/bpm/accurate/{instrument_name}"

        self._model       = None
        self._audio_buf   = np.array([], dtype=np.float32)
        self._predictions = deque(maxlen=SMOOTHING)
        self._last_send   = 0.0

        print(f"[bpm_tempo_cnn] '{instrument_name}' ready")

    def stop(self):
        self._model = None
        print(f"[bpm_tempo_cnn] '{self.instrument_name}' stopped")