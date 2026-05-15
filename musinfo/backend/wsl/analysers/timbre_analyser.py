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

    def push(self, audio: np.ndarray, instrument_name: str):
        pass