# midi_harmony_analyser.py — MIDI Harmony Analyser
# Pure analysis class — no socket, no TCP, no WSL.
# Instantiated by midi_capture.py (Windows), called via push(event).
# Produces the same result shape and OSC output as HarmonyAnalyser
# so TouchDesigner and the frontend require no changes.

import numpy as np
from pythonosc import udp_client


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
# these represent how strongly each pitch class is associated with a key
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                     2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                     2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# how much each new note event contributes to the histogram
# higher = reacts faster to key changes, lower = more stable
KS_DECAY = 0.92   # multiply histogram by this on every event to slowly forget old notes

# minimum number of note events before we attempt key detection
KS_MIN_EVENTS = 4

# only update the reported key if the new candidate scores above this threshold
# prevents key flickering on sparse input
KS_CONFIDENCE_THRESHOLD = 0.80


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

        self.instrument_name  = instrument_name
        self.instrument_index = instrument_index

        # None = detect automatically, ("C", "major") = skip detection and use this
        self.forced_key       = forced_key

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


        # previous HPCP vector — used to measure harmonic change between events
        self._hpcp_prev = None

        self._event_count     = 0

        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.td_client  = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)

        print(f"[midi_harmony] Ready for '{instrument_name}'", flush=True)
        print(f"[midi_harmony] OSC -> {OSC_HOST}:{OSC_PORT}", flush=True)


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
    # returns (key, scale, confidence, forced) — same shape as _last_key
    def _detect_key(self) -> tuple:
        # forced key — skip detection entirely
        if self.forced_key is not None:
            root, scale = self.forced_key
            return root, scale, 1.0, True

        # not enough note history yet
        if self._pc_histogram.sum() < KS_MIN_EVENTS:
            return self._last_key

        best_key, best_scale, best_score = None, None, -np.inf

        for tonic in range(12):
            # rotate the KS profile to align with this tonic
            major_profile = np.roll(KS_MAJOR, tonic)
            minor_profile = np.roll(KS_MINOR, tonic)

            # Pearson correlation between histogram and each profile
            major_score = float(np.corrcoef(self._pc_histogram, major_profile)[0, 1])
            minor_score = float(np.corrcoef(self._pc_histogram, minor_profile)[0, 1])

            if major_score > best_score:
                best_score, best_key, best_scale = major_score, NOTE_NAMES[tonic], "major"
            if minor_score > best_score:
                best_score, best_key, best_scale = minor_score, NOTE_NAMES[tonic], "minor"

        # only update if confidence is high enough to avoid flickering
        if best_score >= KS_CONFIDENCE_THRESHOLD:
            self._last_key = (best_key, best_scale, best_score, False)

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
        
        # step 3 : chord          (template matching)
        # step 4 : dissonance     (Plomp-Levelt on active note frequencies)
        # step 5 : OSC output


        if self._active_notes:
            names = [note_name(n) for n in sorted(self._active_notes.keys())]
            print(
                f"[midi_harmony/{self.instrument_name}] "
                f"active={names}  key={result['key']} {result['scale']}  "
                f"hpcp={[round(v, 2) for v in result['hpcp']]}",
                flush=True,
            )
            
        return result


    # ── OSC output ────────────────────────────────────────────────────────────

    # stub — OSC sends added in step 5 once all result fields are populated
    def _handle_result(self, result: dict):
        self._event_count += 1


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