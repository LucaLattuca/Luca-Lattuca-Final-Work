import time
import os
import numpy as np
from collections import deque
from scipy.signal import resample_poly
from math import gcd
from pythonosc import udp_client
import subprocess

# ── CONFIG ────────────────────────────────────────────────────────────────────
MODEL_SR      = 11025
SMOOTHING     = 3
SEND_INTERVAL = 4.0

# ─────────────────────────────────────────────────────────────────────────────

def _get_windows_host_ip():
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"

OSC_HOST = _get_windows_host_ip()
OSC_PORT      = 9000

# .pb frozen graph lives at models/bpm_models/deepsquare-k16-3.pb
# Download from: https://essentia.upf.edu/models/tempo/tempocnn/deepsquare-k16-3.pb
_HERE      = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(_HERE, "..", "models", "bpm_models")
MODEL_FILE = os.path.join(_MODEL_DIR, "deepsquare-k16-3.pb")


# Accurate BPM via Essentia TempoCNN (deepsquare-k16-3).
# # Runs on WSL. Outputs to /bpm/{instrument}/accurate
class BpmTempoCNNAnalyser:

    def __init__(self, instrument_name: str, sample_rate: int = 48000):
        self.instrument_name = instrument_name
        self.input_sr        = sample_rate
        self.osc             = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.address = f"/bpm/{instrument_name}/accurate"

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
        # patchHopSize=128 -> inference every ~6s; batchSize=1 for streaming
        self._model = es.TempoCNN(graphFilename=MODEL_FILE, patchHopSize=128, batchSize=1)
        print(f"[bpm_tempo_cnn] model loaded: {MODEL_FILE}")

    # Run inference once we have enough audio (~12s at 11025Hz = 132300 samples).
    # TempoCNN returns (globalTempo, localTempos, localProbabilities).
    # We use localTempos and median-smooth ourselves for stable streaming output.
    def _try_inference(self):
        if len(self._audio_buf) < MODEL_SR * 12:
            return

        self._load_model()

        try:
            _, local_bpm, _ = self._model(self._audio_buf)
            valid = [b for b in local_bpm if 30.0 <= b <= 286.0]
            if not valid:
                return
            for b in valid:
                self._predictions.append(b)
        except Exception as e:
            print(f"[bpm_tempo_cnn] inference error: {e}")
            return
        finally:
            # Slide buffer forward by 50% for overlap on next inference
            self._audio_buf = self._audio_buf[len(self._audio_buf) // 2:]

        smoothed = round(float(np.median(self._predictions)), 1)

        now = time.time()
        if (now - self._last_send) >= SEND_INTERVAL:
            self.osc.send_message(self.address, smoothed)
            print(f"[bpm_tempo_cnn] {self.instrument_name}: {smoothed} BPM -> {self.address}")
            self._last_send = now



# Polyphase resample — exact rational ratio, no quality loss.
def _resample(audio: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
    if from_sr == to_sr:
        return audio
    g    = gcd(to_sr, from_sr)
    up   = to_sr   // g
    down = from_sr // g
    return resample_poly(audio, up, down).astype(np.float32)