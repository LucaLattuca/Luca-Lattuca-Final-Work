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
    
    # Resample to 11025Hz and accumulate — Essentia TempoCNN needs 11025Hz input.
    def push(self, audio: np.ndarray):
        mono      = audio.flatten().astype(np.float32)
        resampled = _resample(mono, self.input_sr, MODEL_SR)
        self._audio_buf = np.concatenate([self._audio_buf, resampled])
        self._try_inference()
    
    # Lazy-load the Essentia TempoCNN algorithm on first call.
    # Raises FileNotFoundError early with a clear message if the .pb is missing.
    def _load_model(self):
        if self._model is not None:
            return
        if not os.path.isfile(MODEL_FILE):
            raise FileNotFoundError(
                f"Model not found: {MODEL_FILE}\n"
                f"Download from: https://essentia.upf.edu/models/tempo/tempocnn/deepsquare-k16-3.pb"
            )
        import essentia.standard as es
        # patchHopSize=128 → inference every ~6s; batchSize=1 for streaming
        self._model = es.TempoCNN(graphFilename=MODEL_FILE, patchHopSize=128, batchSize=1)
        print(f"[bpm_tempo_cnn] model loaded: {MODEL_FILE}")



# Polyphase resample — exact rational ratio, no quality loss.
def _resample(audio: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
    if from_sr == to_sr:
        return audio
    g    = gcd(to_sr, from_sr)
    up   = to_sr   // g
    down = from_sr // g
    return resample_poly(audio, up, down).astype(np.float32)