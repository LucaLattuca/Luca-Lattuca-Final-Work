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

# Tempo feel buckets (BPM thresholds — inclusive lower bound)
TEMPO_FEEL_BUCKETS = [
    (0,   "ballad"),
    (60,  "slow"),
    (90,  "medium"),
    (120, "uptempo"),
    (160, "fast"),
]
# ─────────────────────────────────────────────────────────────────────────────

def _get_windows_host_ip():
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"

OSC_HOST = _get_windows_host_ip()
OSC_PORT        = 9000
OSC_PROMPT_PORT = 9001


# .pb frozen graph lives at models/bpm_models/deepsquare-k16-3.pb
# Download from: https://essentia.upf.edu/models/tempo/tempocnn/deepsquare-k16-3.pb
_HERE      = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(_HERE, "..", "models", "bpm_models")
MODEL_FILE = os.path.join(_MODEL_DIR, "deepsquare-k16-3.pb")


# Accurate tempo via Essentia TempoCNN (deepsquare-k16-3).
# Runs on WSL. Outputs:
#   /tempo/{instrument}/bpm_accurate -> smoothed BPM from neural network
#   /tempo/{instrument}/feel         -> tempo feel label derived from BPM
class TempoCNNAnalyser:

    def __init__(self, instrument_name: str, sample_rate: int = 48000):
        self.instrument_name = instrument_name
        self.input_sr        = sample_rate

        self.osc             = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.prompt_osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PROMPT_PORT)
        
        self.bpm_address     = f"/tempo/{instrument_name}/bpm_accurate"
        self.feel_address    = f"/tempo/{instrument_name}/feel"

        self._model       = None
        self._audio_buf   = np.array([], dtype=np.float32)
        self._predictions = deque(maxlen=SMOOTHING)
        self._last_send   = 0.0
        self._last_feel   = None

        print(f"[tempo_cnn] '{instrument_name}' ready")

    def stop(self):
        self._model = None
        print(f"[tempo_cnn] '{self.instrument_name}' stopped")
    
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
        print(f"[tempo_cnn] model loaded: {MODEL_FILE}")

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
            print(f"[tempo_cnn] inference error: {e}")
            return
        finally:
            # Slide buffer forward by 50% for overlap on next inference
            self._audio_buf = self._audio_buf[len(self._audio_buf) // 2:]

        smoothed = round(float(np.median(self._predictions)), 1)
        feel = _bpm_to_feel(smoothed)

        now = time.time()
        if (now - self._last_send) >= SEND_INTERVAL:
            self.osc.send_message(self.bpm_address, smoothed)
            print(f"[tempo_cnn] {self.instrument_name}: {smoothed} BPM -> {self.bpm_address}")
            self._last_send = now

        # Feel only sends when the bucket changes — avoids spamming the same label
        if feel != self._last_feel:
            self.osc.send_message(self.feel_address, feel)
            print(f"[tempo_cnn] {self.instrument_name}: {feel} -> {self.feel_address}")
            self._last_feel = feel



# Map a BPM value to a tempo feel label.
def _bpm_to_feel(bpm: float) -> str:
    label = TEMPO_FEEL_BUCKETS[0][1]
    for threshold, name in TEMPO_FEEL_BUCKETS:
        if bpm >= threshold:
            label = name
    return label


# Polyphase resample — exact rational ratio, no quality loss.
def _resample(audio: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
    if from_sr == to_sr:
        return audio
    g    = gcd(to_sr, from_sr)
    up   = to_sr   // g
    down = from_sr // g
    return resample_poly(audio, up, down).astype(np.float32)