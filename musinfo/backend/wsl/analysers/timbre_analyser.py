"""
timbre_analyser.py — WSL analyser for spectral timbre features.

Instantiate with the sample rate of the incoming audio stream:
    TimbreAnalyser(sample_rate=48000)

Outputs over OSC (per instrument):
  /{instrument}/timbre/centroid     brightness            (float, Hz)
  /{instrument}/timbre/flatness     tonal vs noisy        (float, 0–1)
  /{instrument}/timbre/rolloff      spectral weight       (float, Hz)
"""

import subprocess
import numpy as np
import essentia.standard as es
from pythonosc.udp_client import SimpleUDPClient

SILENCE_THRESHOLD = 0.01

FRAME_SIZE = 2048
HOP_SIZE = 1024

EMA_ALPHA = 0.3


def get_windows_host_ip():
    result = subprocess.run(
        ["ip", "route", "show", "default"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"


OSC_HOST = get_windows_host_ip()
OSC_PORT = 9000


class TimbreAnalyser:
    def __init__(self, sample_rate: int, host=OSC_HOST, port=OSC_PORT):
        self.osc = SimpleUDPClient(host, port)
        self.sample_rate = sample_rate

        self._buffer = np.zeros(0, dtype=np.float32)

        # Spectral primitives
        self._window = es.Windowing(type="hann", size=FRAME_SIZE)
        self._spectrum = es.Spectrum(size=FRAME_SIZE)
        self._centroid = es.Centroid(range=sample_rate / 2)
        self._rolloff = es.RollOff(sampleRate=sample_rate)
        self._flatness = es.Flatness()

        # EMA state for continuous values, keyed "instrument/descriptor"
        self._ema = {}

    def push(self, audio: np.ndarray, instrument_name: str):
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        if np.sqrt(np.mean(audio ** 2)) < SILENCE_THRESHOLD:
            return

        self._buffer = np.concatenate([self._buffer, audio])

        while len(self._buffer) >= FRAME_SIZE:
            frame = self._buffer[:FRAME_SIZE]
            self._buffer = self._buffer[HOP_SIZE:]

            windowed = self._window(frame)
            spectrum = self._spectrum(windowed)

            self._process_frame(spectrum, instrument_name)

    def _process_frame(self, spectrum: np.ndarray, instrument_name: str):
        centroid = self._centroid(spectrum)
        rolloff = self._rolloff(spectrum)
        flatness = self._flatness(spectrum)

        self._send_continuous(instrument_name, "centroid", centroid)
        self._send_continuous(instrument_name, "rolloff", rolloff)
        self._send_continuous(instrument_name, "flatness", flatness)

    def _send_continuous(self, instrument_name: str, name: str, value: float):
        key = f"{instrument_name}/{name}"
        smoothed = self._smooth(key, float(value))
        self.osc.send_message(f"/{instrument_name}/timbre/{name}", smoothed)

    def _smooth(self, key, value):
        prev = self._ema.get(key, value)
        smoothed = EMA_ALPHA * value + (1 - EMA_ALPHA) * prev
        self._ema[key] = smoothed
        return smoothed