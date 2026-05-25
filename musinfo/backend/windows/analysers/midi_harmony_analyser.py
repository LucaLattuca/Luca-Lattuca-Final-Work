# midi_harmony_analyser.py — MIDI Harmony Analyser
# Pure analysis class — no socket, no TCP, no WSL.
# Instantiated by midi_capture.py (Windows), called via push(event).
# Produces the same result shape and OSC output as HarmonyAnalyser
# so TouchDesigner and the frontend require no changes.
#
# commit: feat(midi_harmony_analyser): skeleton — class only, no TCP

import sys
import subprocess
import numpy as np
from pythonosc import udp_client


# ── OSC config ────────────────────────────────────────────────────────────────

def get_windows_host_ip():
    # on Windows we send OSC to localhost
    return "127.0.0.1"

OSC_HOST    = get_windows_host_ip()
OSC_PORT    = 9000
OSC_TD_PORT = 9100

# send OSC output at most every N note events to avoid flooding TouchDesigner
OSC_THROTTLE_EVENTS = 1


# ── note helpers ──────────────────────────────────────────────────────────────

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def note_name(midi_note: int) -> str:
    return NOTE_NAMES[int(midi_note) % 12] + str(int(midi_note) // 12 - 1)

def midi_to_hz(midi_note: int) -> float:
    # frequency of a MIDI note — used for Plomp-Levelt dissonance later
    return 440.0 * (2.0 ** ((int(midi_note) - 69) / 12.0))


# ── MidiHarmonyAnalyser ───────────────────────────────────────────────────────

class MidiHarmonyAnalyser:
    """
    One instance per MIDI instrument.
    Receives MIDI events via push(event), maintains internal harmonic state,
    and sends analysis results over OSC after every note/pedal event.

    Result shape is identical to HarmonyAnalyser._empty_result() — same keys,
    same OSC addresses — so TouchDesigner and the frontend need no changes.
    """

    def __init__(self, instrument_name="unknown", instrument_index=0,
                 forced_key=None):
        # commit: feat(midi_harmony_analyser): skeleton — __init__ state

        self.instrument_name   = instrument_name
        self.instrument_index  = instrument_index
        self.forced_key        = forced_key   # None = detect, ("C", "major") = override

        # held notes: { midi_note_int: velocity_int }
        self._active_notes: dict[int, int] = {}

        # sustain pedal — notes released while pedal is down stay in active set
        self._sustain_on       = False
        self._sustained_notes: set[int] = set()

        self._event_count      = 0

        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.td_client  = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)

        print(f"[midi_harmony] Ready for '{instrument_name}'", flush=True)
        print(f"[midi_harmony] OSC target: {OSC_HOST}:{OSC_PORT}", flush=True)


    # ── event entry point ─────────────────────────────────────────────────────

    def push(self, event: dict):
        # commit: feat(midi_harmony_analyser): skeleton — push dispatcher
        event_type = event.get("type")

        if event_type == "note_on":
            self._on_note_on(event)
        elif event_type == "note_off":
            self._on_note_off(event)
        elif event_type == "control_change":
            self._on_control_change(event)
        # pitch_bend does not affect harmony — ignored for now


    # ── MIDI event handlers ───────────────────────────────────────────────────

    def _on_note_on(self, event: dict):
        note     = int(event["note"])
        velocity = int(event["velocity"])
        self._active_notes[note] = velocity
        self._sustained_notes.discard(note)
        self._analyse_and_send()

    def _on_note_off(self, event: dict):
        note = int(event["note"])
        if self._sustain_on:
            # pedal is down — keep note sounding, track it as sustained
            self._sustained_notes.add(note)
        else:
            self._active_notes.pop(note, None)
        self._analyse_and_send()

    def _on_control_change(self, event: dict):
        # only sustain pedal (CC 64) affects harmonic state
        if event.get("cc_num") == 64:
            if event.get("cc_value", 0) >= 64:
                self._sustain_on = True
            else:
                # pedal released — drop all sustained notes
                self._sustain_on = False
                for note in self._sustained_notes:
                    self._active_notes.pop(note, None)
                self._sustained_notes.clear()
                self._analyse_and_send()


    # ── analysis pipeline ─────────────────────────────────────────────────────

    def _analyse_and_send(self):
        result = self.analyse()
        self._handle_result(result)


    def analyse(self) -> dict:
        # commit: feat(midi_harmony_analyser): skeleton — analyse stub
        # Steps added here one by one:
        #   step 1 : key detection  (Krumhansl-Schmuckler)
        #   step 2 : HPCP           (velocity-weighted pitch class profile)
        #   step 3 : chord          (template matching)
        #   step 4 : dissonance     (Plomp-Levelt on active note frequencies)
        #   step 5 : OSC output
        result = self._empty_result()

        # skeleton print — confirms pipeline is live before analysis is added
        if self._active_notes:
            names = [note_name(n) for n in sorted(self._active_notes.keys())]
            print(
                f"[midi_harmony/{self.instrument_name}] active={names}",
                flush=True,
            )

        return result


    # ── OSC output ────────────────────────────────────────────────────────────

    def _handle_result(self, result: dict):
        # commit: feat(midi_harmony_analyser): skeleton — _handle_result stub
        # OSC sends added once analysis fields are populated
        self._event_count += 1


    # ── result shape ──────────────────────────────────────────────────────────
    # Identical to HarmonyAnalyser._empty_result() — same keys, same defaults.

    @staticmethod
    def _empty_result() -> dict:
        return {
            # chord
            "chord":           None,
            "chord_root":      None,
            "chord_quality":   None,
            "chord_strength":  0.0,
            # how the chord relates to the key
            "roman_degree":    None,
            "relation":        None,
            # key
            "key":             None,
            "scale":           None,
            "key_confidence":  0.0,
            "key_forced":      False,
            # chroma
            "hpcp":            [0.0] * 12,
            "chroma_spread":   0.0,
            "chroma_centroid": 0.0,
            "harmonic_change": 0.0,
            "dissonance":      0.0,
        }