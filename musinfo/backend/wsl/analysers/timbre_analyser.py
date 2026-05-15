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

# Attack window: how much audio after an onset to feed LogAttackTime
ATTACK_WINDOW_SEC = 0.15

# Minimum gap between attack events per instrument (avoid double-fires)
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
    
        self._mfcc = es.MFCC(inputSize=FRAME_SIZE // 2 + 1,
                             sampleRate=sample_rate,
                             numberCoefficients=13)

         # Onset detection (drives the attack-time chain in the next step)
        self._onset_detection = es.OnsetDetection(method="hfc",
                                                  sampleRate=sample_rate)

        # Rate-dependent buffer sizes
        self._attack_window_samples = int(sample_rate * ATTACK_WINDOW_SEC)
        self._odf_buffer_frames = int(sample_rate / HOP_SIZE)  # ~1s of ODF history


        self._flux_per_instrument = {}

        # EMA state for continuous values, keyed "instrument/descriptor"
        self._ema = {}

        #  Previous-frame MFCC vector per instrument (for delta)
        self._prev_mfcc = {}


        # Per-instrument state for the onset detection chain
        self._odf_buffer = {}            # rolling ODF history
        self._audio_history = {}         # raw audio ring for post-onset slicing
        self._samples_seen = {}          # per-instrument sample clock
        self._last_attack_sample = {}    # debounce across attack events
        

    def push(self, audio: np.ndarray, instrument_name: str):
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        if np.sqrt(np.mean(audio ** 2)) < SILENCE_THRESHOLD:
            return

        # Per-instrument raw-audio ring (capped — only need enough for the
        # post-onset slice + a couple of frames of slack)
        history = self._audio_history.get(instrument_name, np.zeros(0, dtype=np.float32))
        history = np.concatenate([history, audio])
        max_history = self._attack_window_samples + FRAME_SIZE * 2
        if len(history) > max_history:
            history = history[-max_history:]
        self._audio_history[instrument_name] = history

        self._buffer = np.concatenate([self._buffer, audio])

        while len(self._buffer) >= FRAME_SIZE:
            frame = self._buffer[:FRAME_SIZE]
            self._buffer = self._buffer[HOP_SIZE:]

            windowed = self._window(frame)
            spectrum = self._spectrum(windowed)

            self._process_frame(spectrum, instrument_name)

            self._samples_seen[instrument_name] = (
                self._samples_seen.get(instrument_name, 0) + HOP_SIZE
            )

    def _update_odf_and_maybe_fire_attack(self, instrument_name: str, odf: float):
        buf = self._odf_buffer.get(instrument_name, [])
        buf.append(float(odf))
        if len(buf) > self._odf_buffer_frames:
            buf = buf[-self._odf_buffer_frames:]
        self._odf_buffer[instrument_name] = buf

        # Need enough history for Onsets to peak-pick meaningfully
        if len(buf) < 8:
            return

        odf_matrix = np.array([buf], dtype=np.float32)
        try:
            onsets = es.Onsets()(odf_matrix, [1.0])
        except RuntimeError:
            return
        if len(onsets) == 0:
            return

        # Onsets returns times in seconds relative to start of the ODF buffer.
        # We only act on the most recent one, and only if it just appeared.
        latest_onset_sec = float(onsets[-1])
        buffer_duration_sec = len(buf) * HOP_SIZE / self.sample_rate
        sec_from_end = buffer_duration_sec - latest_onset_sec

        if sec_from_end > 2 * HOP_SIZE / self.sample_rate:
            return

        # Debounce: don't fire two events too close together
        current_sample = self._samples_seen.get(instrument_name, 0)
        last = self._last_attack_sample.get(instrument_name, -10 ** 9)
        if (current_sample - last) / self.sample_rate < ATTACK_MIN_GAP_SEC:
            return
        self._last_attack_sample[instrument_name] = current_sample

        # TODO (next commit): compute attack time on post-onset audio
        _ = sec_from_end  # placeholder — used in next commit

    def _process_frame(self, spectrum: np.ndarray, instrument_name: str):
        centroid = self._centroid(spectrum)
        rolloff = self._rolloff(spectrum)
        flatness = self._flatness(spectrum)

        flux_algo = self._flux_per_instrument.setdefault(
            instrument_name, es.Flux()
        )
        flux = flux_algo(spectrum)

        _, mfcc = self._mfcc(spectrum)
        prev = self._prev_mfcc.get(instrument_name)
        mfcc_delta = float(np.linalg.norm(mfcc - prev)) if prev is not None else 0.0
        self._prev_mfcc[instrument_name] = mfcc


        # Onset detection function — HFC ignores phase, so feed zeros
        phase = np.zeros_like(spectrum)
        odf = self._onset_detection(spectrum, phase)
        self._update_odf_and_maybe_fire_attack(instrument_name, odf)


        self._send_continuous(instrument_name, "centroid", centroid)
        self._send_continuous(instrument_name, "rolloff", rolloff)
        self._send_continuous(instrument_name, "flatness", flatness)
        self._send_continuous(instrument_name, "flux", flux)
        self._send_continuous(instrument_name, "mfcc_delta", mfcc_delta)

        # Raw MFCC vector — unsmoothed, so TD sees the fingerprint as-is
        self.osc.send_message(
            f"/{instrument_name}/timbre/mfcc", mfcc.tolist()
        )

    def _send_continuous(self, instrument_name: str, name: str, value: float):
        key = f"{instrument_name}/{name}"
        smoothed = self._smooth(key, float(value))
        self.osc.send_message(f"/{instrument_name}/timbre/{name}", smoothed)

    def _smooth(self, key, value):
        prev = self._ema.get(key, value)
        smoothed = EMA_ALPHA * value + (1 - EMA_ALPHA) * prev
        self._ema[key] = smoothed
        return smoothed