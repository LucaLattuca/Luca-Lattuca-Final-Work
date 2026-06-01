import os
os.environ['ESSENTIA_LOG_LEVEL'] = 'error'

import sys
import subprocess
import numpy as np
import essentia.standard as es
from pythonosc import udp_client

# Debugging
DEBUG = False
INFO = True

# Audio / frame config
SAMPLE_RATE = 44100
FRAME_SIZE = 1024
HOP_SIZE = 512

# Silence gate
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
OSC_TD_PORT = 9100


class DynamicsAnalyser:
    def __init__(self, instrument_name: str, sample_rate: int, instrument_role: str = "default", role_index: int = 0, instrument_index: int = 0):
        self.instrument_role  = instrument_role
        self.role_index       = role_index
        self.instrument_index = instrument_index
        self.instrument_name = instrument_name
        self.sender_rate = sample_rate

        if method not in ONSET_METHODS:
            print(f"[dynamics] unknown method '{method}', falling back to '{DEFAULT_METHOD}'")
            method = DEFAULT_METHOD
        self.method = ONSET_METHODS[method]

        # Essentia algorithms
        self.windower = es.Windowing(type="hann", size=FRAME_SIZE)
        self.spectrum = es.Spectrum(size=FRAME_SIZE)
        self.onset_detection = es.OnsetDetection(
            method=self.method,
            sampleRate=SAMPLE_RATE,
        )
        self.onsets = es.Onsets()

        # State
        self.frame_buffer = np.zeros(0, dtype=np.float32)
        self.smoothed_rms = 0.0
        self.odf_history = []
        self.rms_history = []
        self.frame_counter = 0
        self.last_onset_frame_global = -1
        self.onset_pending_reset = False  # reset onset value on next tick

        # OSC client
        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.addr_rms       = f"/dynamics/{self.instrument_name}/rms"
        self.addr_onset     = f"/dynamics/{self.instrument_name}/onset"
        self.addr_strength  = f"/dynamics/{self.instrument_name}/onset_strength"
        self.addr_rms_onset = f"/dynamics/{self.instrument_name}/rms_at_onset"

        self.td_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)

        if INFO : 
            print(f"[dynamics] Ready for '{instrument_name}' @ {sample_rate}Hz (method={method})")
            sys.stdout.flush()
            print(f"[dynamics] OSC target: {OSC_HOST}:{OSC_PORT}")
            sys.stdout.flush()

    def push(self, audio):
        chunk_rms = float(np.sqrt(np.mean(audio ** 2)))

        # Silence gate — decay smoothed RMS toward 0 so the visual doesn't freeze
        if chunk_rms < SILENCE_THRESHOLD:
            self.smoothed_rms = (1 - RMS_EMA_ALPHA) * self.smoothed_rms
            self._send_rms()
            self._maybe_reset_onset()
            return

        # Accumulate into frame buffer and process as many full frames as available
        self.frame_buffer = np.concatenate([self.frame_buffer, audio])
        while len(self.frame_buffer) >= FRAME_SIZE:
            frame = self.frame_buffer[:FRAME_SIZE]
            self.frame_buffer = self.frame_buffer[HOP_SIZE:]
            self._process_frame(frame)

        # Update smoothed RMS from this chunk
        self.smoothed_rms = (
            RMS_EMA_ALPHA * chunk_rms
            + (1 - RMS_EMA_ALPHA) * self.smoothed_rms
        )
        self._send_rms()
        self._maybe_reset_onset()

    def _process_frame(self, frame):
        windowed = self.windower(frame)
        spec = self.spectrum(windowed)

        # OnsetDetection needs spectrum + phase; pass zero-phase for real-input methods
        phase = np.zeros(len(spec), dtype=np.float32)
        odf_value = float(self.onset_detection(spec, phase))
        frame_rms = float(np.sqrt(np.mean(frame ** 2)))

        # Append to rolling history (~1s window)
        self.odf_history.append(odf_value)
        self.rms_history.append(frame_rms)
        if len(self.odf_history) > ODF_BUFFER_FRAMES:
            self.odf_history.pop(0)
            self.rms_history.pop(0)

        self.frame_counter += 1

        # Need a full buffer before peak-picking is meaningful
        if len(self.odf_history) < ODF_BUFFER_FRAMES:
            return

        # Run Essentia's Onsets on the ODF buffer (adaptive thresholding + peak picking)
        odf_matrix = np.array([self.odf_history], dtype=np.float32)
        weights = np.array([1.0], dtype=np.float32)
        try:
            onset_times = self.onsets(odf_matrix, weights)
        except RuntimeError:
            return

        if len(onset_times) == 0:
            return

        # Convert latest onset time → frame index inside the buffer
        latest_time = float(onset_times[-1])
        latest_local_frame = int(round(latest_time * SAMPLE_RATE / HOP_SIZE))
        latest_local_frame = max(0, min(latest_local_frame, len(self.odf_history) - 1))

        # Map local-buffer frame → absolute frame counter, dedupe against last sent
        buffer_start_global = self.frame_counter - len(self.odf_history)
        onset_global_frame = buffer_start_global + latest_local_frame
        if onset_global_frame <= self.last_onset_frame_global:
            return
        self.last_onset_frame_global = onset_global_frame

        # Strength = ODF value at the onset frame
        onset_strength = self.odf_history[latest_local_frame]

        # rms_at_onset = peak RMS in ±RMS_PEAK_WINDOW_FRAMES around the onset
        lo = max(0, latest_local_frame - RMS_PEAK_WINDOW_FRAMES)
        hi = min(len(self.rms_history), latest_local_frame + RMS_PEAK_WINDOW_FRAMES + 1)
        rms_at_onset = max(self.rms_history[lo:hi]) if hi > lo else 0.0

        self._send_onset(onset_strength, rms_at_onset)

    def _send_rms(self):
        scaled = min(100.0, self.smoothed_rms * 300.0)
        if scaled < 0.01:  # floor — don't send noise
            scaled = 0.0
        self.osc_client.send_message(self.addr_rms, scaled)
        self.td_client.send_message(f"/td/dynamics/{self.instrument_role}/{self.role_index}/rms", scaled)

    def _send_onset(self, onset_strength, rms_at_onset):
        scaled_rms_at_onset = min(100.0, rms_at_onset * 300.0)
        self.osc_client.send_message(self.addr_onset, 1)
        self.osc_client.send_message(self.addr_strength, float(onset_strength))
        self.osc_client.send_message(self.addr_rms_onset, float(scaled_rms_at_onset))

        self.td_client.send_message(f"/td/dynamics/{self.instrument_role}/{self.role_index}/onset",          1)
        self.td_client.send_message(f"/td/dynamics/{self.instrument_role}/{self.role_index}/onset_strength", float(onset_strength))
        self.td_client.send_message(f"/td/dynamics/{self.instrument_role}/{self.role_index}/rms_at_onset",   float(scaled_rms_at_onset))

        # Flag a reset for the next tick so onset value drops back to 0
        self.onset_pending_reset = True

        if DEBUG : 
            print(f"[dynamics/{self.instrument_name}] onset "
                  f"strength={onset_strength:.3f} rms@onset={scaled_rms_at_onset:.1f}")
            sys.stdout.flush()

    def _maybe_reset_onset(self):
        # Called every tick after _send_rms — clears onset value 1 tick after firing
        if not self.onset_pending_reset:
            return
        self.osc_client.send_message(self.addr_onset, 0)
        self.td_client.send_message(f"/td/dynamics/{self.instrument_role}/{self.role_index}/onset", 0)
        self.onset_pending_reset = False