# midi_harmony_analyser.py — MIDI Harmony Analyser
# Pure analysis class — no socket, no TCP, no WSL.
# Instantiated by midi_capture.py (Windows), called via push(event).
# Produces the same result shape and OSC output as HarmonyAnalyser
# so TouchDesigner and the frontend require no changes.

import numpy as np
from pythonosc import udp_client
import sys
import json
import threading
import time
import os


# ── Debugging ───────────────────────────────────────────────────────────────────────
DEBUG = False
INFO = True

# ── OSC ───────────────────────────────────────────────────────────────────────

# running on Windows — OSC goes to localhost
OSC_HOST    = "127.0.0.1"
OSC_PORT    = 9000
OSC_TD_PORT = 9100


# ── note helpers ──────────────────────────────────────────────────────────────

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# commit: feat(midi_harmony_analyser): skeleton

def note_name(midi_note: int) -> str:
    return NOTE_NAMES[int(midi_note) % 12] + str(int(midi_note) // 12 - 1)

# frequency of a MIDI note number — used for Plomp-Levelt dissonance (step 4)
def midi_to_hz(midi_note: int) -> float:
    return 440.0 * (2.0 ** ((int(midi_note) - 69) / 12.0))


# ── semitone map ──────────────────────────────────────────────────────────────

# semitone position of each note name — used for roman numeral calculation
NOTE_SEMITONES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

# scale degree templates — interval in semitones from tonic -> (roman numeral, plain name)
SCALE_DEGREES = {
    "major": {
        0:  ("I",    "tonic"),
        2:  ("II",   "supertonic"),
        4:  ("III",  "mediant"),
        5:  ("IV",   "subdominant"),
        7:  ("V",    "dominant"),
        9:  ("VI",   "submediant"),
        11: ("VII",  "leading tone"),
    },
    "minor": {
        0:  ("i",    "tonic"),
        2:  ("ii",   "supertonic"),
        3:  ("III",  "mediant"),
        5:  ("iv",   "subdominant"),
        7:  ("v",    "dominant"),
        8:  ("VI",   "submediant"),
        10: ("VII",  "subtonic"),
    },
}

# ── key detection config ──────────────────────────────────────────────────────

# how many semitones to shift the KS profile when correlating against each key
# e.g. C major starts at 0, C# major at 1, D major at 2, etc.


# Krumhansl-Schmuckler major and minor profiles
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                     2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                     2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# decay applied to histogram on every note_on — lower = slower to forget old notes
# 0.92 reacts faster, 0.97 is more stable across a long phrase
KS_DECAY = 0.97

# more events required before attempting detection — gives histogram time to build
KS_MIN_EVENTS = 8

# higher threshold — only change the reported key if very confident
# prevents diminished chords from pulling the key
KS_CONFIDENCE_THRESHOLD = 0.92

# how many consecutive detections the new key must hold before displacing the current one
# e.g. 4 means the new key must win 4 events in a row before we accept it
KS_KEY_LOCK = 4

# ── forced key config ─────────────────────────────────────────────────────────

# set FORCED_KEY_ENABLED to True and fill in root + scale to bypass KS detection entirely
# hot-reloaded from the performance tab — changing these takes effect on the next note event
FORCED_KEY_ENABLED = False
FORCED_KEY_ROOT    = "C"
FORCED_KEY_SCALE   = "major"

# Resolve performance.json — walks up from this file to the project root.
def get_performance_config_path():

    here = os.path.abspath(__file__)
    # windows/midi_capture/midi_harmony_analyser.py -> midi_capture -> windows -> project root -> backend/config
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(project_root, "backend", "config", "performance.json")
# Returns (enabled, raw_key) from performance.json, or defaults on any error.
def load_performance_config():
    try:
        with open(get_performance_config_path(), "r") as f:
            data = json.load(f)
        fk = data["Performance"]["forcedKey"]
        enabled = bool(fk.get("enabled", False))
        raw_key = fk.get("key")
        scale   = fk.get("scale") or "major"
        return enabled, raw_key, scale
    except Exception:
        return False, None, "major"

# ── chord templates ───────────────────────────────────────────────────────────

# binary pitch class masks for each chord quality, root = C (index 0)
# rotate by root semitone to get templates for other keys
CHORD_TEMPLATES = {
    "major":      np.array([1,0,0,0,1,0,0,1,0,0,0,0], dtype=np.float32),  # 1 3 5
    "minor":      np.array([1,0,0,1,0,0,0,1,0,0,0,0], dtype=np.float32),  # 1 b3 5
    "dominant7":  np.array([1,0,0,0,1,0,0,1,0,0,1,0], dtype=np.float32),  # 1 3 5 b7
    "major7":     np.array([1,0,0,0,1,0,0,1,0,0,0,1], dtype=np.float32),  # 1 3 5 7
    "minor7":     np.array([1,0,0,1,0,0,0,1,0,0,1,0], dtype=np.float32),  # 1 b3 5 b7
    "diminished7":     np.array([1,0,0,1,0,0,1,0,0,1,0,0], dtype=np.float32),  # 1 b3 b5 bb7
    "half_diminished": np.array([1,0,0,1,0,0,1,0,0,0,1,0], dtype=np.float32),  # 1 b3 b5 b7
    "sus4":       np.array([1,0,0,0,0,1,0,1,0,0,0,0], dtype=np.float32),  # 1 4 5
}

# minimum dot-product score to report a chord — below this we return None
CHORD_MIN_STRENGTH = 0.5

# ── dissonance config ─────────────────────────────────────────────────────────

# Plomp-Levelt curve parameters — these shape the roughness curve between two partials
# b1/b2 control the steepness of the rise and fall of roughness around the critical bandwidth
PL_B1 = 3.5
PL_B2 = 5.75

# number of overtones to consider per note — more = more accurate but slower
# 4 is a good balance for real-time use
PL_OVERTONES = 4

# amplitude falloff per overtone — each harmonic is weaker than the fundamental
PL_OVERTONE_FALLOFF = 0.6

# ── MidiHarmonyAnalyser ───────────────────────────────────────────────────────

class MidiHarmonyAnalyser:
    """
    One instance per MIDI instrument.
    Receives MIDI events via push(event), maintains internal harmonic state,
    and sends analysis results over OSC after every note/pedal event.

    Result shape is identical to HarmonyAnalyser._empty_result() — same keys,
    same OSC addresses — so TouchDesigner and the frontend need no changes.
    """

    def __init__(self, instrument_name="unknown", instrument_index=0):

        self.instrument_name  = instrument_name
        self.instrument_index = instrument_index

        # held notes: { midi_note_int: velocity_int }
        self._active_notes: dict[int, int] = {}

        # sustain pedal — notes released while pedal is down stay in active set
        self._sustain_on      = False
        self._sustained_notes: set[int] = set()

        # pitch class histogram — accumulated note activity for KS key detection
        # index 0 = C, 1 = C#, ..., 11 = B
        # velocity-weighted: louder notes contribute more to the histogram
        self._pc_histogram = np.zeros(12, dtype=np.float32)

        # cached key result — only updated when KS confidence crosses the threshold
        self._last_key     = (None, None, 0.0, False)  # (key, scale, confidence, forced)

        # consecutive detections of the same key candidate — must reach KS_KEY_LOCK before accepted
        self._key_candidate_streak = 0
        self._key_candidate        = (None, None)
        
        # previous HPCP vector — used to measure harmonic change between events
        self._hpcp_prev = None

        self._event_count     = 0

        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.td_client  = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)
        
        self._start_config_poll()

        if INFO : 
            print(f"[midi_harmony] Ready for '{instrument_name}'", flush=True)
            print(f"[midi_harmony] OSC -> {OSC_HOST}:{OSC_PORT}", flush=True)
            sys.stdout.flush() 

    # Background thread: re-reads performance.json every second and updates module-level forced key constants.
    def _start_config_poll(self):
        def poll():
            global FORCED_KEY_ENABLED, FORCED_KEY_ROOT, FORCED_KEY_SCALE
            while True:
                time.sleep(1)
                enabled, raw_key, scale = load_performance_config()
                FORCED_KEY_ENABLED = enabled and bool(raw_key)
                if raw_key:
                    FORCED_KEY_ROOT  = raw_key.split("/")[0]
                    FORCED_KEY_SCALE = scale
                if INFO and FORCED_KEY_ENABLED:
                    print(f"[midi_harmony] forced key -> {FORCED_KEY_ROOT} {FORCED_KEY_SCALE}", flush=True)
        t = threading.Thread(target=poll, daemon=True)
        t.start()
    
    # ── event entry point ─────────────────────────────────────────────────────

    # routes each incoming event to the correct handler
    def push(self, event: dict):
        event_type = event.get("type")

        if event_type == "note_on":
            self._on_note_on(event)
        elif event_type == "note_off":
            self._on_note_off(event)
        elif event_type == "control_change":
            self._on_control_change(event)
        # pitch_bend does not affect harmony — ignored


    # ── MIDI event handlers ───────────────────────────────────────────────────

    def _on_note_on(self, event: dict):
        note     = int(event["note"])
        velocity = int(event["velocity"])
        self._active_notes[note] = velocity
        # if this note was being held by the pedal, clear that flag
        self._sustained_notes.discard(note)

        # update histogram on every note_on — note_off does not affect key detection
        self._update_histogram(note, velocity)

        self._analyse_and_send()

    def _on_note_off(self, event: dict):
        note = int(event["note"])
        if self._sustain_on:
            # pedal is down — keep note sounding, track it as pedal-sustained
            self._sustained_notes.add(note)
        else:
            self._active_notes.pop(note, None)
        self._analyse_and_send()

    def _on_control_change(self, event: dict):
        # only sustain pedal (CC 64) affects harmonic state
        if event.get("cc_num") != 64:
            return
        if event.get("cc_value", 0) >= 64:
            self._sustain_on = True
        else:
            # pedal released — remove all pedal-sustained notes from active set
            self._sustain_on = False
            for note in self._sustained_notes:
                self._active_notes.pop(note, None)
            self._sustained_notes.clear()
            self._analyse_and_send()
    

    # updates the pitch class histogram on note_on and detects the current key
    # called every note_on event — note_off does not change the histogram
    def _update_histogram(self, note: int, velocity: int):
        # decay the histogram slightly on every event so old notes fade out
        self._pc_histogram *= KS_DECAY
        # add this note's velocity contribution to its pitch class bin
        self._pc_histogram[note % 12] += velocity / 127.0


    # correlates the pitch class histogram against all 24 KS key profiles
    # requires KS_KEY_LOCK consecutive agreements before updating the reported key
    # forced key bypasses all of this entirely
    def _detect_key(self) -> tuple:
        # forced key — read module-level constants so hot-reload takes effect immediately
        if FORCED_KEY_ENABLED:
            return FORCED_KEY_ROOT, FORCED_KEY_SCALE, 1.0, True

        # not enough note history yet
        if self._pc_histogram.sum() < KS_MIN_EVENTS:
            return self._last_key

        best_key, best_scale, best_score = None, None, -np.inf

        for tonic in range(12):
            major_profile = np.roll(KS_MAJOR, tonic)
            minor_profile = np.roll(KS_MINOR, tonic)

            major_score = float(np.corrcoef(self._pc_histogram, major_profile)[0, 1])
            minor_score = float(np.corrcoef(self._pc_histogram, minor_profile)[0, 1])

            if major_score > best_score:
                best_score, best_key, best_scale = major_score, NOTE_NAMES[tonic], "major"
            if minor_score > best_score:
                best_score, best_key, best_scale = minor_score, NOTE_NAMES[tonic], "minor"

        # below confidence threshold — don't even consider this candidate
        if best_score < KS_CONFIDENCE_THRESHOLD:
            return self._last_key

        candidate = (best_key, best_scale)

        if candidate == self._key_candidate:
            # same candidate as last time — increment streak
            self._key_candidate_streak += 1
        else:
            # new candidate — reset streak
            self._key_candidate        = candidate
            self._key_candidate_streak = 1

        # only accept the new key once it has held for KS_KEY_LOCK consecutive events
        if self._key_candidate_streak >= KS_KEY_LOCK:
            self._last_key             = (best_key, best_scale, best_score, False)
            self._key_candidate_streak = 0

        return self._last_key
    
    # builds a velocity-weighted pitch class profile from currently active notes
    # then computes centroid, spread, and harmonic change from the resulting vector
    def _compute_hpcp(self) -> tuple:
        hpcp = np.zeros(12, dtype=np.float32)

        for note, velocity in self._active_notes.items():
            # each note contributes its velocity weight to its pitch class bin
            hpcp[note % 12] += velocity / 127.0

        # normalise so the vector sums to 1 — makes profiles comparable regardless of how many notes are held
        total = hpcp.sum()
        if total > 1e-6:
            hpcp /= total

        # ── chroma descriptors ────────────────────────────────────────────────────

        indices = np.arange(12)

        # weighted average pitch class index by energy
        centroid = float(np.sum(indices * hpcp) / total) if total > 1e-6 else 0.0

        # weighted standard deviation around the centroid — how spread the harmony is
        spread = float(np.sqrt(np.sum(((indices - centroid) ** 2) * hpcp) / total)) if total > 1e-6 else 0.0

        # euclidean distance from previous HPCP — large value means harmony just changed
        if self._hpcp_prev is not None:
            harmonic_change = float(np.linalg.norm(hpcp - self._hpcp_prev))
        else:
            harmonic_change = 0.0

        self._hpcp_prev = hpcp.copy()

        return hpcp, centroid, spread, harmonic_change

    # matches the HPCP vector against all chord templates and returns the best fit
    # returns (chord_name, root, quality, strength, roman_numeral, relation)
    def _detect_chord(self, hpcp: np.ndarray, key: str, scale: str) -> tuple:
        # no notes — nothing to match against
        if hpcp.sum() < 1e-6:
            return None, None, None, 0.0, None, None
    
        best_name, best_root, best_quality, best_strength = None, None, None, 0.0
    
        for root_idx in range(12):
            for quality, template in CHORD_TEMPLATES.items():
                # rotate template to align with this root
                rotated = np.roll(template, root_idx)
    
                # normalise template so dot product is between 0 and 1
                norm = np.linalg.norm(rotated)
                if norm < 1e-6:
                    continue
                
                strength = float(np.dot(hpcp, rotated) / norm)
    
                if strength > best_strength:
                    best_strength = strength
                    best_root     = NOTE_NAMES[root_idx]
                    best_quality  = quality
                    # format chord name: "Am", "Cmaj7", "G7" etc.
                    suffix = "" if quality == "major" else (
                        "m"    if quality == "minor"      else
                        "7"    if quality == "dominant7"  else
                        "maj7" if quality == "major7"     else
                        "m7"   if quality == "minor7"     else
                        "dim7"  if quality == "diminished7"     else
                        "m7b5"  if quality == "half_diminished" else
                        "sus4"
                    )
                    best_name = best_root + suffix
    
        # below threshold — not confident enough to report a chord
        if best_strength < CHORD_MIN_STRENGTH:
            return None, None, None, best_strength, None, None
    
        # roman numeral — only computable if we have a key
        roman, relation = None, None
        if best_root and key and scale:
            interval = (NOTE_SEMITONES[best_root] - NOTE_SEMITONES[key]) % 12
            degree   = SCALE_DEGREES.get(scale, {}).get(interval)
            if degree:
                roman, relation = degree
    
        return best_name, best_root, best_quality, best_strength, roman, relation


    # computes Plomp-Levelt dissonance from currently active MIDI notes
    # models perceptual roughness between all pairs of partials (fundamentals + overtones)
    # returns a value between 0.0 (consonant) and 1.0 (maximally dissonant)
    def _compute_dissonance(self) -> float:
        if len(self._active_notes) < 2:
            # single note or silence — no intervals, no roughness
            return 0.0

        # build list of (frequency, amplitude) for all partials of all active notes
        partials = []
        for note, velocity in self._active_notes.items():
            fundamental = midi_to_hz(note)
            amplitude   = velocity / 127.0
            for k in range(1, PL_OVERTONES + 1):
                # kth harmonic: frequency k*f0, amplitude falls off with each overtone
                partials.append((fundamental * k, amplitude * (PL_OVERTONE_FALLOFF ** (k - 1))))

        # compute roughness for every unique pair of partials
        total_roughness = 0.0
        for i in range(len(partials)):
            for j in range(i + 1, len(partials)):
                f1, a1 = partials[i]
                f2, a2 = partials[j]

                # always put lower frequency first
                if f1 > f2:
                    f1, a1, f2, a2 = f2, a2, f1, a1

                # critical bandwidth — the frequency range within which roughness occurs
                # approximated from Plomp-Levelt (1965)
                # cbw = 1.72 * (f1 ** 0.65)

                # Zwicker critical bandwidth — wider and more accurate than the power law approximation
                cbw = 25 + 75 * (1 + 1.4 * ((f1 / 1000) ** 2)) ** 0.69

                # normalised frequency difference within the critical bandwidth
                x = (f2 - f1) / cbw

                # Plomp-Levelt roughness curve — peaks around x=0.25, zero at x=0 and x>=1
                roughness = (a1 * a2) * (
                    np.exp(-PL_B1 * x) - np.exp(-PL_B2 * x)
                )
                total_roughness += max(0.0, roughness)

        # normalise against the maximum possible roughness for this many notes
        # n_pairs scaling over-penalises dense chords
        normalised = total_roughness / 2.0

        # clamp to [0, 1]
        return float(min(1.0, normalised))
    
    # ── analysis pipeline ─────────────────────────────────────────────────────

    def _analyse_and_send(self):
        result = self.analyse()
        self._handle_result(result)


    # main analysis method — each step populates fields in result
    def analyse(self) -> dict:
        result = self._empty_result()

        

        # step 1 — key detection
        key, scale, confidence, forced = self._detect_key()
        result["key"]            = key
        result["scale"]          = scale
        result["key_confidence"] = confidence
        result["key_forced"]     = forced

        # step 2 — HPCP and chroma descriptors
        hpcp, centroid, spread, harmonic_change = self._compute_hpcp()
        result["hpcp"]            = hpcp.tolist()
        result["chroma_centroid"] = centroid
        result["chroma_spread"]   = spread
        result["harmonic_change"] = harmonic_change
        
        # step 3 — chord detection
        chord, root, quality, strength, roman, relation = self._detect_chord(
            hpcp, result["key"], result["scale"]
        )
        result["chord"]          = chord
        result["chord_root"]     = root
        result["chord_quality"]  = quality
        result["chord_strength"] = strength
        result["roman_degree"]   = roman
        result["relation"]       = relation

        # step 4 — dissonance (Plomp-Levelt)
        result["dissonance"] = self._compute_dissonance()

       

        if self._active_notes:
            names = [note_name(n) for n in sorted(self._active_notes.keys())]
            if INFO:
                print(
                    f"[midi_harmony/{self.instrument_name}] "
                    f"active={names}  "
                    f"chord={result['chord']}  "
                    f"key={result['key']} {result['scale']}  "
                    f"roman={result['roman_degree']}  "
                    f"diss={result['dissonance']:.2f}",
                    flush=True,
                )

        return result


    # ── OSC output ────────────────────────────────────────────────────────────

        
    # sends analysis results over OSC to TouchDesigner and the frontend
    # mirrors HarmonyAnalyser._handle_result exactly — same addresses, same payload shape
    def _handle_result(self, result: dict):
        self._event_count += 1

        if DEBUG:
            self._display(result)

        # full result to frontend via Tauri OSC bridge
        self.osc_client.send_message(
            f"/harmony/{self.instrument_name}",
            json.dumps(result)
        )

        # frontend view — subset the OutputPanel reads
        self.osc_client.send_message(
            f"/harmony/{self.instrument_name}/frontend",
            json.dumps(self.frontend_view(result))
        )

        # per-field messages to TouchDesigner
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


    # ── display ───────────────────────────────────────────────────────────────

    # debug print — mirrors HarmonyAnalyser._display() format
    def _display(self, result: dict):
        chord   = result["chord"] or "—"
        key     = f"{result['key']} {result['scale']}" if result["key"] else "—"
        roman   = result["roman_degree"] or "—"
        quality = result["chord_quality"] or "—"
        conf    = f"{result['key_confidence']*100:.0f}%"
        diss    = f"{result['dissonance']:.2f}"
        forced  = " (forced)" if result["key_forced"] else ""

        print(f"\n[midi_harmony/{self.instrument_name}] ─────────────────────")
        print(f"  chord      {chord}  ({quality})  {roman}")
        print(f"  key        {key}{forced}  confidence {conf}")
        print(f"  dissonance {diss}   change {result['harmonic_change']:.2f}")
        print(f"─────────────────────────────────────────────────────────────")


    # ── result shape ──────────────────────────────────────────────────────────

    # identical to HarmonyAnalyser._empty_result() — every code path returns
    # this exact set of keys so nothing downstream sees a missing field
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

    # the frontend only needs these fields — built from the full result
    def frontend_view(self, result: dict) -> dict:
        return {
            "chord":            result["chord"],
            "root":             result["chord_root"],
            "relation_to_root": result["roman_degree"],
            "chord_quality":    result["chord_quality"],
            "dissonance":       result["dissonance"],
            "key":              result["key"],
        }