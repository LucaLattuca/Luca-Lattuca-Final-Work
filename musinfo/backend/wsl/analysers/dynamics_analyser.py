import os
os.environ['ESSENTIA_LOG_LEVEL'] = 'error'

import sys
import subprocess
import numpy as np
import essentia.standard as es
from pythonosc import udp_client


# Audio / frame config
SAMPLE_RATE = 44100
FRAME_SIZE = 1024
HOP_SIZE = 512

# Silence gate — hardcoded for now, wire to instruments.json later
SILENCE_THRESHOLD = 0.01

# RMS smoothing (higher α = snappier, lower α = smoother)
RMS_EMA_ALPHA = 0.3

# ODF history buffer — ~1s of frames for adaptive peak-picking
ODF_BUFFER_FRAMES = int(SAMPLE_RATE / HOP_SIZE)

# ±frames around an onset to grab peak RMS for "rms_at_onset"
RMS_PEAK_WINDOW_FRAMES = 4

# Selectable Essentia onset methods
ONSET_METHODS = {
    "hfc":           "hfc",
    "complex":       "complex",
    "complex_phase": "complex_phase",
    "flux":          "flux",
    "melflux":       "melflux",
    "rms":           "rms",
}
DEFAULT_METHOD = "complex"


def get_windows_host_ip():
    result = subprocess.run(
        ["ip", "route", "show", "default"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"


# OSC config
OSC_HOST = get_windows_host_ip()
OSC_PORT = 9000


class DynamicsAnalyser:
    def __init__(self, instrument_name="unknown", sample_rate=SAMPLE_RATE,
                 method=DEFAULT_METHOD):
        self.instrument_name = instrument_name
        self.sender_rate = sample_rate

        if method not in ONSET_METHODS:
            print(f"[dynamics] unknown method '{method}', falling back to '{DEFAULT_METHOD}'")
            method = DEFAULT_METHOD
        self.method = ONSET_METHODS[method]

        # OSC client
        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.addr_rms       = f"/dynamics/{self.instrument_name}/rms"
        self.addr_onset     = f"/dynamics/{self.instrument_name}/onset"
        self.addr_strength  = f"/dynamics/{self.instrument_name}/onset_strength"
        self.addr_rms_onset = f"/dynamics/{self.instrument_name}/rms_at_onset"

        print(f"[dynamics] Ready for '{instrument_name}' @ {sample_rate}Hz (method={method})")
        sys.stdout.flush()
        print(f"[dynamics] OSC target: {OSC_HOST}:{OSC_PORT}")
        sys.stdout.flush()

    def push(self, audio):
        # implemented in step 2
        pass