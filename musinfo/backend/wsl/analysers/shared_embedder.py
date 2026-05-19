# shared_embedder.py — Singleton EffNet embedder shared by genre and mood
# Loads Discogs-EffNet once, exposes get_embeddings() for both analysers.
# Thread-safe — genre and mood workers call this from separate threads.

import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['ESSENTIA_LOG_LEVEL'] = 'error'

import sys
import threading
import numpy as np
from math import gcd
from scipy.signal import resample_poly
from essentia.standard import TensorflowPredictEffnetDiscogs

MODEL_RATE = 16000

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "models")
EFFNET_PB  = os.path.join(MODELS_DIR, "discogs-effnet-bs64-1.pb")


def _resample(audio, from_rate, to_rate):
    if from_rate == to_rate:
        return audio
    g = gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)


class SharedEmbedder:
    """
    Singleton EffNet embedder — loaded once, shared across genre and mood.
    get_embeddings() is thread-safe via _gpu_lock.
    Only one GPU call happens at a time, so genre and mood never collide on CUDA.
    """
    _instance = None
    _init_lock = threading.Lock()
    _gpu_lock  = threading.Lock()

    def __new__(cls):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._loaded = False
        return cls._instance

    def _load(self):
        if self._loaded:
            return
        self._model = TensorflowPredictEffnetDiscogs(
            graphFilename=EFFNET_PB,
            output="PartitionedCall:1"  # embeddings [frames, 1280]
        )
        self._loaded = True
        print("[shared_embedder] Discogs-EffNet loaded (shared instance)")
        sys.stdout.flush()

    def get_predictions(self, audio_16k: np.ndarray, prediction_model) -> np.ndarray:
        """
        Runs any model under the shared GPU lock.
        Pass genre's own model instance — the lock prevents CUDA collision.
        """
        if not self._loaded:
            self._load()  # ensure embedder is ready even if mood hasn't called yet
        with self._gpu_lock:
            return prediction_model(audio_16k)
        
    def get_embeddings(self, audio_16k: np.ndarray) -> np.ndarray:
        """
        Takes audio already at 16kHz (float32), returns embeddings [frames, 1280].
        Caller is responsible for resampling before calling this.
        GPU lock ensures only one inference runs at a time across all threads.
        """
        if not self._loaded:
            self._load()
        with self._gpu_lock:
            return self._model(audio_16k)

    def resample_and_get(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """
        Convenience method — resamples from sample_rate to 16kHz then returns embeddings.
        """
        resampled = _resample(audio.flatten().astype(np.float32), sample_rate, MODEL_RATE)
        return self.get_embeddings(resampled)


# Module-level singleton — both analysers import this directly
embedder = SharedEmbedder()