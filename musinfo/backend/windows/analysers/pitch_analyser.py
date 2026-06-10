# pitch_analyser.py — Real-time Pitch Detection
# Receives audio chunks from broadcaster, detects pitch using Aubio YIN

import aubio
import numpy as np
from collections import deque
from pythonosc import udp_client
import sys

# Configuration
HOP_SIZE          = 512
BUF_SIZE          = 2048
SILENCE_THRESHOLD = 0.01
MIN_PITCH         = 100
MAX_PITCH         = 1100
CONFIDENCE        = 0.6

DETECTION_MODE    = "yin"  # yinfft | yin | mcomb

# Smoothing — median over last N valid readings.
# Higher = smoother but slower to respond to real pitch changes.
PITCH_HISTORY = 1

# Reject readings that jump more than this many semitones from the stable pitch
# after octave correction. 1 octave = 12 semitones. 7 = a fifth, catches most
# remaining spikes without rejecting fast legit passages.
MAX_JUMP_SEMITONES = 7

# OSC Configuration
OSC_HOST    = "127.0.0.1"
OSC_PORT    = 9000
OSC_TD_PORT = 9100

# Debugging
DEBUG = False
INFO  = True

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def hz_to_note(freq):
    midi = round(69 + 12 * np.log2(freq / 440.0))
    return f"{NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"


class PitchAnalyser:
    def __init__(self, instrument_name: str, sample_rate: int, instrument_role: str = "default", role_index: int = 0, instrument_index: int = 0):
        self.instrument_role  = instrument_role
        self.role_index       = role_index
        self.instrument_index = instrument_index
        self.instrument_name  = instrument_name
        self.sample_rate      = sample_rate

        self.detector = aubio.pitch(DETECTION_MODE, BUF_SIZE, HOP_SIZE, sample_rate)
        self.detector.set_unit("Hz")
        self.detector.set_silence(-40)

        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.td_client  = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)

        self._pitch_history = deque(maxlen=PITCH_HISTORY)
        self.last_pitch = 0.0

        if INFO:
            print(f"[pitch] Ready for '{instrument_name}' @ {sample_rate}Hz")
            sys.stdout.flush()

    def push(self, audio):
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < SILENCE_THRESHOLD:
            self.td_client.send_message(
                f"/td/pitch/{self.instrument_role}/{self.role_index}/hz",
                self.last_pitch
            )
            return

        for i in range(0, len(audio), HOP_SIZE):
            window = audio[i:i + HOP_SIZE]
            if len(window) < HOP_SIZE:
                continue

            pitch      = self.detector(window)[0]
            confidence = self.detector.get_confidence()

            if not (MIN_PITCH < pitch < MAX_PITCH and confidence > CONFIDENCE):
                continue

            # ── Octave correction ────────────────────────────────────────────
            # YIN commonly returns values an octave too high or too low.
            # If halving or doubling brings the pitch closer to the stable
            # median, prefer that candidate.
            pitch = self._correct_octave(pitch)

            # ── Jump gate ────────────────────────────────────────────────────
            # After octave correction, reject readings that are still too far
            # from the stable pitch — these are genuine detector errors.
            if self._pitch_history:
                stable    = float(np.median(self._pitch_history))
                semitones = abs(12 * np.log2(pitch / stable)) if stable > 0 else 0
                if semitones > MAX_JUMP_SEMITONES:
                    if DEBUG:
                        print(f"[pitch/{self.instrument_name}] jump rejected: {pitch:.1f}Hz ({semitones:.1f} st from {stable:.1f}Hz)")
                    break

            # ── Median smoothing ─────────────────────────────────────────────
            self._pitch_history.append(pitch)
            smoothed = float(np.median(self._pitch_history))
            note     = hz_to_note(smoothed)

            if DEBUG:
                print(f"[pitch/{self.instrument_name}] {note} ({smoothed:.1f}Hz)")
                sys.stdout.flush()

            self.last_pitch = smoothed
            self.osc_client.send_message(f"/pitch/{self.instrument_name}", f"{note} ({smoothed:.1f}Hz)")
            self.td_client.send_message(
                f"/td/pitch/{self.instrument_role}/{self.role_index}/hz",
                smoothed
            )
            break

    def _correct_octave(self, pitch: float) -> float:
        """
        Correct octave errors against the current stable median.
        Checks if halving or doubling the raw pitch lands closer to the
        stable value — if so, prefers that candidate.
        """
        if not self._pitch_history:
            return pitch

        stable = float(np.median(self._pitch_history))
        if stable == 0:
            return pitch

        best      = pitch
        best_dist = abs(np.log2(pitch / stable))

        for multiplier in [0.5, 2.0]:
            candidate = pitch * multiplier
            if MIN_PITCH < candidate < MAX_PITCH:
                dist = abs(np.log2(candidate / stable))
                if dist < best_dist:
                    best      = candidate
                    best_dist = dist

        return best