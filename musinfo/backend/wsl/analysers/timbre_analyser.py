"""
timbre_analyser.py — WSL analyser for spectral timbre features.

Instantiate with the sample rate of the incoming audio stream:
    TimbreAnalyser(sample_rate=48000)
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

        # Frame accumulator (chunks from broadcaster aren't frame-aligned)
        self._buffer = np.zeros(0, dtype=np.float32)

        # Rate-agnostic spectral primitives
        self._window = es.Windowing(type="hann", size=FRAME_SIZE)
        self._spectrum = es.Spectrum(size=FRAME_SIZE)

    def push(self, audio: np.ndarray, instrument_name: str):
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Silence gate — skip frame work entirely when input is dead
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
        pass