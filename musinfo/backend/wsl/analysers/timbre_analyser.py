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

SILENCE_THRESHOLD = 0.01

FRAME_SIZE = 2048
HOP_SIZE = 1024

# EMA smoothing for continuous descriptors
EMA_ALPHA = 0.3

# Attack window: how much audio after an onset to feed LogAttackTime
ATTACK_WINDOW_SEC = 0.15

# Minimum gap between attack events (avoid double-fires)
ATTACK_MIN_GAP_SEC = 0.08


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
OSC_TD_PORT = 9100

class TimbreAnalyser:
    """
    Per-instrument spectral feature extractor.

    Outputs over OSC:
      /timbre/{instrument}/centroid     brightness            (float, Hz)
      /timbre/{instrument}/flux         texture busyness      (float)
      /timbre/{instrument}/flatness     tonal vs noisy        (float, 0–1)
      /timbre/{instrument}/rolloff      spectral weight       (float, Hz)
      /timbre/{instrument}/mfcc_delta   timbral change        (float)
      /timbre/{instrument}/mfcc         raw 13-coeff vector   (float[13])
      /timbre/{instrument}/attack       attack sharpness      (float, sec, event)
    """

    def __init__(self, instrument_name: str, sample_rate: int, instrument_role: str = "default", instrument_index: int = 0):
        self.instrument_role  = instrument_role
        self.instrument_index = instrument_index 
        self.instrument_name = instrument_name
        self.sample_rate = sample_rate

        self._buffer = np.zeros(0, dtype=np.float32)

        # Spectral primitives
        self._window = es.Windowing(type="hann", size=FRAME_SIZE)
        self._spectrum = es.Spectrum(size=FRAME_SIZE)
        self._centroid = es.Centroid(range=sample_rate / 2)
        self._rolloff = es.RollOff(sampleRate=sample_rate, cutoff=0.5)
        self._flatness = es.Flatness()
        self._flux = es.Flux()
        self._mfcc = es.MFCC(inputSize=FRAME_SIZE // 2 + 1,
                             sampleRate=sample_rate,
                             numberCoefficients=13)

        self._last_onset_time = -1.0

        # Onset detection chain (drives the attack-time measurement)
        self._onset_detection = es.OnsetDetection(method="hfc",
                                                  sampleRate=sample_rate)
        self._envelope = es.Envelope(sampleRate=sample_rate)
        self._log_attack = es.LogAttackTime(sampleRate=sample_rate)

        # Rate-dependent buffer sizes
        self._attack_window_samples = int(sample_rate * ATTACK_WINDOW_SEC)
        self._odf_buffer_frames = int(sample_rate / HOP_SIZE)  # ~1s of ODF history

        # EMA state for continuous values
        self._ema = {}

        # Previous-frame MFCC (for delta)
        self._prev_mfcc = None

        # Onset detection state
        self._odf_buffer = []
        self._audio_history = np.zeros(0, dtype=np.float32)
        self._samples_seen = 0
        self._last_attack_sample = -10 ** 9

        self.osc = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.td_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)
        if INFO :
            print(f"[timbre] Ready for '{instrument_name}' @ {sample_rate}Hz")
            print(f"[timbre] OSC target: {OSC_HOST}:{OSC_PORT}")
            sys.stdout.flush()

    def push(self, audio):
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        if np.sqrt(np.mean(audio ** 2)) < SILENCE_THRESHOLD:
            return

        # Raw-audio ring (capped — only need enough for the post-onset slice
        # plus a couple of frames of slack)
        self._audio_history = np.concatenate([self._audio_history, audio])
        max_history = self._attack_window_samples + FRAME_SIZE * 2
        if len(self._audio_history) > max_history:
            self._audio_history = self._audio_history[-max_history:]

        self._buffer = np.concatenate([self._buffer, audio])

        while len(self._buffer) >= FRAME_SIZE:
            frame = self._buffer[:FRAME_SIZE]
            self._buffer = self._buffer[HOP_SIZE:]

            windowed = self._window(frame)
            spectrum = self._spectrum(windowed)

            self._process_frame(spectrum)
            self._samples_seen += HOP_SIZE

    def _process_frame(self, spectrum):
        centroid = self._centroid(spectrum)
        rolloff = self._rolloff(np.sqrt(spectrum + 1e-12))
        flatness = self._flatness(spectrum)
        flux = self._flux(spectrum)
        

        _, mfcc = self._mfcc(spectrum)
        if self._prev_mfcc is not None:
            mfcc_delta = float(np.linalg.norm(mfcc - self._prev_mfcc))
        else:
            mfcc_delta = 0.0
        self._prev_mfcc = mfcc

        # Onset detection function — HFC ignores phase, so feed zeros
        phase = np.zeros_like(spectrum)
        odf = self._onset_detection(spectrum, phase)
        self._detect_onset(odf)

        self._send_continuous("centroid", centroid)
        self._send_continuous("rolloff", rolloff)
        self._send_continuous("flatness", flatness)
        self._send_continuous("flux", flux)
        self._send_continuous("mfcc_delta", mfcc_delta)

        # Raw MFCC vector — unsmoothed, so TD sees the fingerprint as-is
        self.osc.send_message(
            f"/timbre/{self.instrument_name}/mfcc", mfcc.tolist()
        )

        self.td_client.send_message(f"/td/timbre/{self.instrument_role}/mfcc", mfcc.tolist())



    def _detect_onset(self, odf):
        self._odf_buffer.append(float(odf))
        if len(self._odf_buffer) > self._odf_buffer_frames:
            trim_count = len(self._odf_buffer) - self._odf_buffer_frames
            trim_seconds = trim_count * HOP_SIZE / self.sample_rate
            self._odf_buffer = self._odf_buffer[-self._odf_buffer_frames:]
            # Shift last-onset time to match the new buffer origin
            self._last_onset_time -= trim_seconds
            # If it went negative, it's now off the buffer; reset
            if self._last_onset_time < 0:
                self._last_onset_time = -1.0

        if len(self._odf_buffer) % 20 == 0:
            recent = self._odf_buffer[-5:]
    

        # Need enough history for Onsets to peak-pick meaningfully
        if len(self._odf_buffer) < 8:
            return

        odf_matrix = np.array([self._odf_buffer], dtype=np.float32)
        try:
            onsets = es.Onsets()(odf_matrix, [1.0])
        except RuntimeError:
            print(f"[attack debug] Onsets RuntimeError: {e}", flush=True)
            return
        
        if len(onsets) == 0:
            if len(self._odf_buffer) % 50 == 0:
                return

        # Onsets returns times in seconds relative to start of the ODF buffer.
        # We only act on the most recent one, and only if it just appeared.
        latest_onset_sec = float(onsets[-1])

        # Has this onset already been processed? Onsets() returns the same onsets
        # repeatedly as the buffer grows, so we track which we've fired on.
        if latest_onset_sec <= self._last_onset_time + 0.01:  # 10ms tolerance for jitter
            return

        self._last_onset_time = latest_onset_sec

        # Debounce against the previous fired attack
        if (self._samples_seen - self._last_attack_sample) / self.sample_rate < ATTACK_MIN_GAP_SEC:
            return
        self._last_attack_sample = self._samples_seen

        # Compute sec_from_end for _fire_attack
        buffer_duration_sec = len(self._odf_buffer) * HOP_SIZE / self.sample_rate
        sec_from_end = buffer_duration_sec - latest_onset_sec

        self._fire_attack(sec_from_end)

    def _fire_attack(self, sec_from_end):
        if len(self._audio_history) < self._attack_window_samples:
            return

        onset_offset_samples = int(sec_from_end * self.sample_rate)
        start = max(0, len(self._audio_history) - onset_offset_samples - 1)
        end = start + self._attack_window_samples
        if end > len(self._audio_history):
            return
        segment = self._audio_history[start:end].astype(np.float32)

        try:
            envelope = self._envelope(segment)
            log_attack, _, _ = self._log_attack(envelope)
        except RuntimeError as e:
            print(f"[attack debug] LogAttackTime RuntimeError: {e}", flush=True)
            return

        attack_sec = float(10 ** log_attack)
        
        self.osc.send_message(f"/timbre/{self.instrument_name}/attack", attack_sec)

        self.td_client.send_message(f"/td/timbre/{self.instrument_role}/attack", attack_sec)

    def _send_continuous(self, name, value):
        smoothed = self._smooth(name, float(value))
        self.osc.send_message(f"/timbre/{self.instrument_name}/{name}", smoothed)
        self.td_client.send_message(f"/td/timbre/{self.instrument_role}/{name}", smoothed)

    def _smooth(self, key, value):
        prev = self._ema.get(key, value)
        smoothed = EMA_ALPHA * value + (1 - EMA_ALPHA) * prev
        self._ema[key] = smoothed
        return smoothed