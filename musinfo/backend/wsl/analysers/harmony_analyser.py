# wsl/analysers/harmony_analyser.py
"""
Harmony analyser — detects chords, key and harmonic descriptors from audio.

Audio comes in, gets converted to a chroma profile (how much energy is in
each of the 12 pitch classes), and from that we read off the chord, the
musical key, and how dissonant the sound is.
"""

import os
os.environ['ESSENTIA_LOG_LEVEL'] = 'error'

import sys
import subprocess
from collections import deque

import numpy as np
import librosa
import essentia.standard as es
from pythonosc import udp_client


# --- OSC config --------------------------------------------------------------

# WSL gets a fresh virtual IP on every boot; the Windows host sits at the
# default gateway, so we read it from the routing table instead of hardcoding.
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


# --- analysis configuration --------------------------------------------------

# Audio is analysed in overlapping frames. A larger frame gives finer pitch
# resolution (needed to tell neighbouring notes apart); the hop is how far
# we advance between frames, so a 2048 hop on a 4096 frame means 50% overlap.
FRAME_SIZE = 4096
HOP_SIZE   = 2048

HPCP_SIZE        = 12  # one value per pitch class: C, C#, D, ... B

# Raw per-frame chord guesses jitter a lot. We keep the last few and take
# the most common one so the reported chord is stable.
SMOOTHING_WINDOW = 5

# HPSS needs surrounding context to distinguish harmonic from percussive energy.
# This is how many samples of recent audio we feed it — roughly 0.34s at 48kHz.
HPSS_CONTEXT_SIZE = 16384

# When forced key is on, we skip key detection and assume this key instead.
# This narrows chord detection to that key's chords. Off by default.
FORCED_KEY_ENABLED = False
FORCED_KEY_ROOT    = "C"
FORCED_KEY_SCALE   = "major"


class HarmonyAnalyser:
    """One instance per instrument. Holds that stream's audio and history."""

    # forced_key: None means detect the key normally; ("C", "major") overrides it.
    def __init__(self, instrument_name="unknown", sample_rate=48000,
                 forced_key=None):
        self.instrument_name = instrument_name
        self.sample_rate     = sample_rate
        self.forced_key      = forced_key

        # Audio chunks from the receiver are whatever size the device sends.
        # We collect them here until there's enough for a full frame.
        self._accumulator = np.array([], dtype=np.float32)

        self._chord_history = deque(maxlen=SMOOTHING_WINDOW)

        # Last frame's chroma, kept so we can measure how much the harmony
        # changed between this frame and the previous one.
        self._hpcp_prev = None

        # Rolling window of recent audio that HPSS runs across.
        self._hpss_context = np.zeros(HPSS_CONTEXT_SIZE, dtype=np.float32)

        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)

        self._init_algorithms()

        print(f"[harmony] Ready for '{instrument_name}' @ {sample_rate}Hz")
        sys.stdout.flush()
        print(f"[harmony] OSC target: {OSC_HOST}:{OSC_PORT}")
        sys.stdout.flush()

    # Essentia algorithms are created once and reused — building them per
    # frame would be wasteful. Each is told the device's sample rate here.
    def _init_algorithms(self):
        # Windowing reduces spectral leakage — without it, a pure sine wave
        # smears energy across neighbouring frequencies in the FFT.
        self._window    = es.Windowing(type='hann', size=FRAME_SIZE)
        self._spectrum  = es.Spectrum(size=FRAME_SIZE)

        # SpectralPeaks picks the loudest, most prominent frequencies out of
        # the spectrum. Only these are passed to HPCP — feeding the raw
        # spectrum would let noise and harmonics pollute the pitch classes.
        self._peaks     = es.SpectralPeaks(
            sampleRate       = self.sample_rate,
            magnitudeThreshold = 0.001,  # ignore peaks quieter than this
            minFrequency     = 40.0,     # below this is mostly bass/noise
            maxFrequency     = 5000.0,   # above this are high overtones we don't need
            orderBy          = 'magnitude',
        )

        # HPCP maps each peak frequency to its pitch class, summing energy
        # across all octaves. size=12 gives one value per semitone (C–B).
        self._hpcp      = es.HPCP(
            size        = HPCP_SIZE,
            sampleRate  = self.sample_rate,
            minFrequency = 40.0,
            maxFrequency = 5000.0,
            harmonics   = 8,   # how many overtones of each peak to consider
            weightType  = 'cosine',
        )

    # Called by the receiver with each incoming audio chunk. We buffer the
    # audio and pull out FRAME_SIZE-long frames as they become available.
    def push(self, audio):
        self._accumulator = np.concatenate([self._accumulator, audio])

        while len(self._accumulator) >= FRAME_SIZE:
            frame = self._accumulator[:FRAME_SIZE]
            self._accumulator = self._accumulator[HOP_SIZE:]
            result = self.analyse(frame)
            self._handle_result(result)

    # Strips drum/percussive energy from a frame before harmonic analysis.
    # HPSS works by separating horizontal lines (steady pitches = harmonic)
    # from vertical lines (short bursts = percussive) in the spectrogram.
    # margin=3.0 means energy has to look clearly harmonic to be kept.
    def _filter_percussive(self, frame: np.ndarray) -> np.ndarray:
        self._hpss_context = np.concatenate([
            self._hpss_context[len(frame):], frame
        ]).astype(np.float32)

        harmonic = librosa.effects.harmonic(self._hpss_context, margin=3.0)

        # Return only the harmonic version of the current frame,
        # which is the tail end of the context window.
        return harmonic[-len(frame):]


    # Computes three descriptors from the HPCP vector.
    # These describe the shape and movement of the harmony without naming a chord.
    def _chroma_descriptors(self, hpcp: np.ndarray) -> tuple:
        indices = np.arange(HPCP_SIZE)
        total   = hpcp.sum()

        if total < 1e-6:
            # Frame is silent or near-silent — return neutral values.
            return 0.0, 0.0, 0.0

        # Weighted average of pitch class indices by their energy.
        centroid = float(np.sum(indices * hpcp) / total)

        # Weighted standard deviation around the centroid — how spread out the energy is.
        spread   = float(np.sqrt(np.sum(((indices - centroid) ** 2) * hpcp) / total))

        # Euclidean distance between this frame's HPCP and the previous one.
        # A large value means the harmony just changed significantly.
        if self._hpcp_prev is not None:
            harmonic_change = float(np.linalg.norm(hpcp - self._hpcp_prev))
        else:
            harmonic_change = 0.0

        self._hpcp_prev = hpcp.copy()

        return centroid, spread, harmonic_change
    

    # Runs the full chord/key/dissonance analysis on a single frame.
    def analyse(self, frame: np.ndarray) -> dict:
        frame  = self._filter_percussive(frame)
        result = self._empty_result()

        windowed        = self._window(frame)
        spectrum        = self._spectrum(windowed)
        freqs, mags     = self._peaks(spectrum)
        hpcp            = self._hpcp(freqs, mags)

        result["hpcp"]  = hpcp.tolist()

        centroid, spread, harmonic_change = self._chroma_descriptors(hpcp)
        result["chroma_centroid"] = centroid
        result["chroma_spread"]   = spread
        result["harmonic_change"] = harmonic_change

        return result
    

    # Sends results over OSC and prints them. Filled in once analysis works.
    def _handle_result(self, result: dict):
        pass

    # The shape of every result this analyser produces. Every code path
    # returns this exact set of keys, so nothing downstream sees a missing field.
    @staticmethod
    def _empty_result() -> dict:
        return {
            # chord
            "chord":          None,   # full chord name, e.g. "C#m"
            "chord_root":     None,   # the chord's root note, e.g. "C#"
            "chord_quality":  None,   # major, minor, etc.
            "chord_strength": 0.0,    # how confident the chord detection is
            # how the chord relates to the key
            "roman_degree":   None,   # scale degree as a numeral, e.g. "V"
            "relation":       None,   # plain-word version, e.g. "dominant"
            # key
            "key":             None,  # tonic note of the key, e.g. "A"
            "scale":           None,  # major or minor
            "key_confidence":  0.0,
            "key_forced":      False, # True if the forced-key override was used
            # chroma / spectral descriptors
            "hpcp":            [0.0] * HPCP_SIZE,  # energy per pitch class
            "chroma_spread":   0.0,   # how spread out the energy is across pitches
            "chroma_centroid": 0.0,   # the "centre of mass" of the chroma
            "harmonic_change": 0.0,   # how much the harmony shifted since last frame
            "dissonance":      0.0,   # roughness of the sound, 0 = consonant
        }

    # The frontend only needs these six fields. It's built from the full
    # result above so the two can never disagree.
    def frontend_view(self, result: dict) -> dict:
        return {
            "chord":            result["chord"],
            "root":             result["chord_root"],
            "relation_to_root": result["roman_degree"],
            "chord_quality":    result["chord_quality"],
            "dissonance":       result["dissonance"],
            "key":              result["key"],
        }