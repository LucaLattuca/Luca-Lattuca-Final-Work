# wsl/analysers/harmony_analyser.py
"""
Harmony analyser — detects chords, key and harmonic descriptors from audio.

Audio comes in, gets converted to a chroma profile (how much energy is in
each of the 12 pitch classes), and from that we read off the chord, the
musical key, and how dissonant the sound is.
"""

import os
import subprocess
import sys

from collections import deque
import numpy as np
import librosa
import essentia.standard as es
from pythonosc import udp_client


import threading
import time

import json 
os.environ['ESSENTIA_LOG_LEVEL'] = 'error'

# Resolve performance.json from WSL — walks up from this file to the project root.
def get_performance_config_path():
    here = os.path.abspath(__file__)
    # backend/wsl/analysers/harmony_analyser.py
    # -> analysers -> wsl -> backend -> project root -> backend/config
    project_root = os.path.dirname(  # project root
        os.path.dirname(             # backend
            os.path.dirname(         # wsl
                os.path.dirname(here)  # analysers
            )
        )
    )
    return os.path.join(project_root, "backend", "config", "performance.json")

# Returns (enabled, key_root, key_scale) from performance.json, or defaults on any error.
def load_performance_config():
    try:
        path = get_performance_config_path()
        with open(path, "r") as f:
            data = json.load(f)
        fk = data["Performance"]["forcedKey"]
        enabled = bool(fk.get("enabled", False))
        raw_key = fk.get("key")
        scale   = fk.get("scale") or "major"
        return enabled, raw_key, scale
    except Exception:
        return False, None, "major"




# Debugging
DEBUG = True
INFO = True

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
OSC_TD_PORT = 9100

# Only send OSC output every N frames. At 48kHz with HOP_SIZE=2048,
# one frame is ~43ms, so 5 frames = ~215ms between updates.
OSC_THROTTLE_FRAMES = 10

# --- analysis configuration --------------------------------------------------

# Audio is analysed in overlapping frames. A larger frame gives finer pitch
# resolution (needed to tell neighbouring notes apart); the hop is how far
# we advance between frames, so a 2048 hop on a 4096 frame means 50% overlap.
FRAME_SIZE = 4096
HOP_SIZE   = 2048

HPCP_SIZE        = 12  # one value per pitch class: C, C#, D, ... B

# Raw per-frame chord guesses jitter a lot. We keep the last few and take
# the most common one so the reported chord is stable.
SMOOTHING_WINDOW = 9

# HPSS (Harmonic-Percussive Source Separation) filters out percussion. 
HPSS_ENABLED = False

# HPSS needs surrounding context to distinguish harmonic from percussive energy.
# This is how many samples of recent audio we feed it — roughly 0.34s at 48kHz.
HPSS_CONTEXT_SIZE = 16384

# only re-run HPSS every 8 frames, reuse last result otherwise
HPSS_EVERY_N_FRAMES = 8  


# When forced key is on, we skip key detection and assume this key instead.
# This narrows chord detection to that key's chords. Off by default.
FORCED_KEY_ENABLED = False
FORCED_KEY_ROOT    = "C"
FORCED_KEY_SCALE   = "major"

# Key detection needs more context than chord detection to be stable.
# We run it less frequently and smooth the result.
KEY_DETECTION_WINDOW = 20  # frames before re-evaluating the key
KEY_SMOOTHING_WINDOW = 10   # keep last N key results and take the most common


# How many HPCP frames we accumulate before running chord detection.
# More frames = more context = stabler chords, but slightly more latency.
CHORD_DETECTION_WINDOW = 20

# Chromatic map 

# Semitone position of each note name, used to compute intervals between roots.
NOTE_SEMITONES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11
}


# Scale degree templates: interval in semitones -> (roman numeral, plain name).
# Major and minor have different sets of diatonic degrees.
# Chords whose root falls outside these intervals are non-diatonic.
SCALE_DEGREES = {
    "major": {
        0:  ("I",   "tonic"),
        2:  ("II",  "supertonic"),
        4:  ("III", "mediant"),
        5:  ("IV",  "subdominant"),
        7:  ("V",   "dominant"),
        9:  ("VI",  "submediant"),
        11: ("VII", "leading tone"),
    },
    "minor": {
        0:  ("i",   "tonic"),
        2:  ("ii",  "supertonic"),
        3:  ("III", "mediant"),
        5:  ("iv",  "subdominant"),
        7:  ("v",   "dominant"),
        8:  ("VI",  "submediant"),
        10: ("VII", "subtonic"),
    },
}


class HarmonyAnalyser:
    """One instance per instrument. Holds that stream's audio and history."""

    # forced_key: None means detect the key normally; ("C", "major") overrides it.
    def __init__(self, instrument_name="unknown", sample_rate=48000,
                 forced_key=None, instrument_index=0):
        
        self._frame_count = 0

        self.instrument_name = instrument_name
        self.sample_rate     = sample_rate
        self.instrument_index = instrument_index
        self.forced_key      = forced_key

        self._key_buffer        = deque(maxlen=KEY_DETECTION_WINDOW)
        self._key_history       = deque(maxlen=KEY_SMOOTHING_WINDOW)
        self._last_key_result   = (None, None, 0.0, False)  # cached between updates

        # Audio chunks from the receiver are whatever size the device sends.
        # We collect them here until there's enough for a full frame.
        self._accumulator = np.array([], dtype=np.float32)


        
        self._hpcp_buffer = deque(maxlen=CHORD_DETECTION_WINDOW)

        # Last frame's chroma, kept so we can measure how much the harmony
        # changed between this frame and the previous one.
        self._hpcp_prev = None


        self._last_harmonic_frame = None
        self._hpss_frame_counter = 0
        # Rolling window of recent audio that HPSS runs across.
        self._hpss_context = np.zeros(HPSS_CONTEXT_SIZE, dtype=np.float32)
        
        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.td_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)
        
        # Chord label history for smoothing — separate from the HPCP history
        # that ChordsDetection reads.
        self._chord_history_labels = deque(maxlen=SMOOTHING_WINDOW)

        self._init_algorithms()
        self._start_config_poll()

        if INFO : 
            print(f"[harmony] Ready for '{instrument_name}' @ {sample_rate}Hz")
            sys.stdout.flush()
            print(f"[harmony] OSC target: {OSC_HOST}:{OSC_PORT}")
            sys.stdout.flush()

    # Background thread: re-reads performance.json every second and updates forced_key.
    def _start_config_poll(self):
        _prev_forced = (None, None, None)
        _was_enabled = False   # track previous enabled state to detect the transition

        def poll():
            nonlocal _prev_forced, _was_enabled
            global FORCED_KEY_ENABLED, FORCED_KEY_ROOT, FORCED_KEY_SCALE
            while True:
                time.sleep(1)
                enabled, raw_key, scale = load_performance_config()
                FORCED_KEY_ENABLED = enabled and bool(raw_key)
                if raw_key:
                    FORCED_KEY_ROOT  = raw_key.split("/")[0]
                    FORCED_KEY_SCALE = scale

                # reset KS state so detection rebuilds cleanly
                if _was_enabled and not FORCED_KEY_ENABLED:
                    self._key_buffer.clear()
                    self._key_history.clear()
                    self._last_key_result = (None, None, 0.0, False)
                    if INFO:
                        print(f"[harmony] forced key disabled — resetting key detector", flush=True)

                _was_enabled = FORCED_KEY_ENABLED

                current = (FORCED_KEY_ENABLED, FORCED_KEY_ROOT, FORCED_KEY_SCALE)
                if INFO and current != _prev_forced:
                    print(f"[midi_harmony] forced key -> enabled={FORCED_KEY_ENABLED} {FORCED_KEY_ROOT} {FORCED_KEY_SCALE}", flush=True)
                _prev_forced = current

        t = threading.Thread(target=poll, daemon=True)
        t.start()

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

        # ChordsDetection expects a sequence of HPCP frames, not one at a time.
        # It matches the sequence against chord templates and returns the best fit.
        self._chords = es.ChordsDetection(
            sampleRate  = self.sample_rate,
            hopSize     = HOP_SIZE,
            windowSize  = 1.5,   # seconds of context it uses internally
        )


        # Key takes a mean HPCP vector and returns key/scale/confidence.
        self._key_extractor = es.Key(
            profileType = 'temperley',
        )

        # Dissonance measures perceptual roughness from the spectral peaks.
        # Based on the Plomp-Levelt model — 0 is consonant, 1 is maximally rough.
        self._dissonance = es.Dissonance()



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
        if not HPSS_ENABLED:
            return frame
        self._hpss_context = np.concatenate([
            self._hpss_context[len(frame):], frame
        ]).astype(np.float32)

        self._hpss_frame_counter += 1
        if self._hpss_frame_counter % HPSS_EVERY_N_FRAMES == 0 or self._last_harmonic_frame is None:
            harmonic = librosa.effects.harmonic(self._hpss_context, margin=3.0)
            self._last_harmonic_frame = harmonic[-len(frame):]

        return self._last_harmonic_frame



    # Splits a chord string like "C#m" into ("C#", "minor").
    # Essentia's quality labels: "" = major, "m" = minor, "7", "maj7", etc.
    def _parse_chord(self, chord_str: str) -> tuple:
        if not chord_str or chord_str == "N":
            return None, None

        QUALITY_MAP = {
            "m":    "minor",
            "M":    "major",
            "7":    "dominant7",
            "m7":   "minor7",
            "M7":   "major7",
            "sus2": "sus2",
            "sus4": "sus4",
            "":     "major",
        }

        # Root is one character (e.g. "C") or two if it has an accidental ("C#", "Bb").
        if len(chord_str) > 1 and chord_str[1] in ("#", "b"):
            root    = chord_str[:2]
            quality = chord_str[2:]
        else:
            root    = chord_str[:1]
            quality = chord_str[1:]

        return root, QUALITY_MAP.get(quality, quality)

    # Returns the most common chord seen across the smoothing window.
    # Prevents the reported chord from flickering on every frame.
    def _smooth_chord_labels(self) -> str:
        if not self._chord_history_labels:
            return None
        labels = list(self._chord_history_labels)
        return max(set(labels), key=labels.count)
    


    # Detects key from a window of recent HPCP frames rather than a single frame.
    # KeyExtractor is only re-run when the buffer is full, then the result is
    # smoothed across the last few detections so the key doesn't flicker.
    def _detect_key(self, hpcp: np.ndarray) -> tuple:
        if self.forced_key is not None:
            root, scale = self.forced_key
            return root, scale, 1.0, True

        self._key_buffer.append(hpcp)

        # Only re-run detection when the buffer is full.
        if len(self._key_buffer) < KEY_DETECTION_WINDOW:
            return self._last_key_result

        # Average the HPCP frames in the buffer into one profile and detect key.
        mean_hpcp           = np.mean(np.array(self._key_buffer), axis=0).astype(np.float32)
        key, scale, conf, _ = self._key_extractor(mean_hpcp)
        self._key_buffer.clear()

        self._key_history.append((key, scale, float(conf)))

        # Weight recent detections but strongly favour consistency —
        # a key needs to appear in the majority of recent windows to displace
        # the current established key.
        keys     = [(k, s) for k, s, _ in self._key_history]
        counts   = {k: keys.count(k) for k in set(keys)}
        best     = max(counts, key=counts.get)

        # Only change the established key if the new candidate appears in
        # at least 60% of recent detections, prevents key hasty switches 
        threshold = len(self._key_history) * 0.6
        if counts[best] >= threshold:
            avg_conf = float(np.mean([c for k, s, c in self._key_history if (k, s) == best]))
            self._last_key_result = (best[0], best[1], avg_conf, False)

        return self._last_key_result


    # Works out where the chord root sits in the key's scale and returns
    # the Roman numeral and a plain-word description.
    # Returns (None, None) for non-diatonic chords rather than guessing.
    def _roman_numeral(self, chord_root: str, key: str, scale: str) -> tuple:
        if not chord_root or not key or not scale:
            return None, None

        if chord_root not in NOTE_SEMITONES or key not in NOTE_SEMITONES:
            return None, None

        # How many semitones above the key root is the chord root?
        interval = (NOTE_SEMITONES[chord_root] - NOTE_SEMITONES[key]) % 12

        degrees  = SCALE_DEGREES.get(scale, {})
        if interval not in degrees:
            # Chord root is outside the scale — non-diatonic, don't guess.
            return None, None

        return degrees[interval]
    


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

        # Dissonance needs the peaks sorted by frequency, not magnitude.
        sorted_indices  = np.argsort(freqs)
        sorted_freqs    = freqs[sorted_indices]
        sorted_mags     = mags[sorted_indices]
        result["dissonance"] = float(self._dissonance(sorted_freqs, sorted_mags))

        result["hpcp"]  = hpcp.tolist()

        centroid, spread, harmonic_change = self._chroma_descriptors(hpcp)
        result["chroma_centroid"] = centroid
        result["chroma_spread"]   = spread
        result["harmonic_change"] = harmonic_change

        self._hpcp_buffer.append(hpcp)

        if len(self._hpcp_buffer) >= 2:
            hpcp_matrix       = np.array(self._hpcp_buffer)
            chords, strengths = self._chords(hpcp_matrix)

            raw_chord         = chords[-1]
            strength          = float(strengths[-1])

            self._chord_history_labels.append(raw_chord)

            chord             = self._smooth_chord_labels()
            root, quality     = self._parse_chord(chord)

            result["chord"]          = chord
            result["chord_root"]     = root
            result["chord_quality"]  = quality
            result["chord_strength"] = strength

        # Key detection runs on hpcp buffer
        key, scale, confidence, forced = self._detect_key(hpcp)

        result["key"]            = key
        result["scale"]          = scale
        result["key_confidence"] = confidence
        result["key_forced"]     = forced

        # Roman numeral is only computable once we have both a chord root and a key.
        if result["chord_root"] and key:
            roman, relation      = self._roman_numeral(result["chord_root"], key, scale)
            result["roman_degree"] = roman
            result["relation"]     = relation

        return result

    # Sends results over OSC
    def _handle_result(self, result: dict):
        self._frame_count += 1
        if self._frame_count % OSC_THROTTLE_FRAMES != 0:
            return
        
        if DEBUG : 
            self._display(result)
            
        self.osc_client.send_message(
            f"/harmony/{self.instrument_name}",
            json.dumps(result)
        )
        self.osc_client.send_message(
            f"/harmony/{self.instrument_name}/frontend",
            json.dumps(self.frontend_view(result))
        )
        
        # send to touchdesigner
        idx = self.instrument_index
        self.td_client.send_message(f"/td/harmony/{idx}/chord",          result["chord"] or "")
        self.td_client.send_message(f"/td/harmony/{idx}/chord_quality",  result["chord_quality"] or "")
        self.td_client.send_message(f"/td/harmony/{idx}/chord_strength", result["chord_strength"])
        self.td_client.send_message(f"/td/harmony/{idx}/roman_degree",   result["roman_degree"] or "")
        self.td_client.send_message(f"/td/harmony/{idx}/key",            result["key"] or "")
        self.td_client.send_message(f"/td/harmony/{idx}/scale",          result["scale"] or "")
        self.td_client.send_message(f"/td/harmony/{idx}/dissonance",     result["dissonance"])
        self.td_client.send_message(f"/td/harmony/{idx}/harmonic_change",result["harmonic_change"])
        self.td_client.send_message(f"/td/harmony/{idx}/hpcp",           result["hpcp"])

    def _display(self, result: dict):
        chord   = result["chord"] or "—"
        key     = f"{result['key']} {result['scale']}" if result["key"] else "—"
        roman   = result["roman_degree"] or "—"
        quality = result["chord_quality"] or "—"
        conf    = f"{result['key_confidence']*100:.0f}%"
        diss    = f"{result['dissonance']:.2f}"
        forced  = " (forced)" if result["key_forced"] else ""

        print(f"\n[harmony/{self.instrument_name}] ──────────────────────────────")
        print(f"  chord      {chord}  ({quality})  {roman}")
        print(f"  key        {key}{forced}  confidence {conf}")
        print(f"  dissonance {diss}   change {result['harmonic_change']:.2f}")
        print("──────────────────────────────────────────────────────────────")
        sys.stdout.flush()

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
            # key
            "key":              result["key"]   or "",
            "scale":            result["scale"] or "",
            # chord
            "chord":            result["chord"]         or "",
            "chord_quality":    result["chord_quality"] or "",
            "root":             result["chord_root"]    or "",
            "relation_to_root": result["roman_degree"]  or "",
            # dissonance
            "dissonance":       result["dissonance"],
        }