# midi_capture.py — MIDI Capture (Windows side)
# Loads instruments.json, opens a pygame.midi.Input for every enabled MIDI
# instrument, and passes events directly to MidiHarmonyAnalyser in-process.
#
# No socket, no WSL — the analyser runs here on Windows alongside capture.

import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import json
import threading
import time

import pygame.midi

from analysers.midi_harmony_analyser import MidiHarmonyAnalyser


# ── config ────────────────────────────────────────────────────────────────────

INFO = True

POLL_INTERVAL = 0.005   # 5 ms polling — tight enough for live performance


# ── instruments.json ──────────────────────────────────────────────────────────

def load_midi_instruments() -> dict:
    """
    Return every instrument where:
      - enabled               == True
      - type                  == "midi"
      - midi_device.connected == True
    """
    base_dir    = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(base_dir, "config", "instruments.json")

    try:
        with open(config_path) as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"[midi_capture] instruments.json not found at {config_path}", flush=True)
        return {}
    except json.JSONDecodeError as e:
        print(f"[midi_capture] Failed to parse instruments.json: {e}", flush=True)
        return {}

    # load instrument indices the same way windows_receiver does — sorted audio instruments
    audio_instruments = sorted(
        name for name, inst in config.get("instruments", {}).items()
        if inst.get("type") == "audio"
    )
    instrument_indices = {name: idx for idx, name in enumerate(audio_instruments)}

    result = {}
    for name, inst in config.get("instruments", {}).items():
        if not inst.get("enabled", False):
            continue
        if inst.get("type") != "midi":
            continue
        midi_dev = inst.get("midi_device", {})
        if not midi_dev.get("connected", False):
            print(f"[midi_capture] '{name}': not connected — skipping", flush=True)
            continue
        dev_name = midi_dev.get("name")
        if not dev_name:
            print(f"[midi_capture] '{name}': no device name — skipping", flush=True)
            continue
        result[name] = {
            "device_name":      dev_name,
            "analysers":        inst.get("analysers", []),
            "instrument_index": instrument_indices.get(name, 0),
        }
        if INFO:
            print(f"[midi_capture] Found: '{name}' -> '{dev_name}'", flush=True)

    return result


# ── device resolution ─────────────────────────────────────────────────────────

def resolve_midi_device_id(target_name: str) -> int | None:
    """
    Exact match first, then base-name fallback to survive Windows MME
    re-enumeration (e.g. 'Digital Piano-1' -> 'Digital Piano-2').
    """
    def base(n: str) -> str:
        idx = n.rfind("-")
        if idx != -1 and n[idx + 1:].isdigit():
            return n[:idx].strip()
        return n

    count = pygame.midi.get_count()

    for i in range(count):
        info = pygame.midi.get_device_info(i)
        name, is_input = info[1].decode("utf-8"), info[2]
        if is_input and name == target_name:
            return i

    target_base = base(target_name)
    for i in range(count):
        info = pygame.midi.get_device_info(i)
        name, is_input = info[1].decode("utf-8"), info[2]
        if is_input and base(name) == target_base:
            if INFO:
                print(f"[midi_capture] Fuzzy match: '{target_name}' -> '{name}' (device {i})", flush=True)
            return i

    return None


# ── note helpers ──────────────────────────────────────────────────────────────

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def note_name(midi_note: int) -> str:
    return NOTE_NAMES[midi_note % 12] + str(midi_note // 12 - 1)


# ── per-instrument listener thread ────────────────────────────────────────────

def listen_instrument(instrument_name: str, device_name: str, analysers: list,
                      analyser: MidiHarmonyAnalyser):
    """
    Polls the MIDI device and passes each event directly to the analyser.
    Runs in its own daemon thread — one per instrument.
    """
    device_id = resolve_midi_device_id(device_name)
    if device_id is None:
        print(f"[midi_capture] '{instrument_name}': '{device_name}' not found — exiting thread", flush=True)
        return

    if INFO:
        print(f"[midi_capture] '{instrument_name}' listening on '{device_name}' (device {device_id})", flush=True)

    try:
        midi_in = pygame.midi.Input(device_id)
    except Exception as e:
        print(f"[midi_capture] Failed to open '{device_name}': {e}", flush=True)
        return

    active_notes: dict[int, int] = {}   # note -> velocity for currently held notes

    try:
        while True:
            if not midi_in.poll():
                time.sleep(POLL_INTERVAL)
                continue

            for event in midi_in.read(32):
                data      = event[0]   # [status, data1, data2, unused]
                timestamp = event[1]

                status   = data[0] & 0xF0
                note     = data[1]
                velocity = data[2]

                # ── note on ──────────────────────────────────────────────────
                if status == 0x90 and velocity > 0:
                    active_notes[note] = velocity
                    midi_event = {
                        "type":         "note_on",
                        "note":         note,
                        "note_name":    note_name(note),
                        "velocity":     velocity,
                        "active_notes": {str(n): v for n, v in active_notes.items()},
                        "timestamp":    timestamp,
                    }
                    print(
                        f"[midi_capture/{instrument_name}] NOTE ON  "
                        f"{note_name(note):4s} (#{note:3d})  vel={velocity:3d}  "
                        f"active={sorted(note_name(n) for n in active_notes)}",
                        flush=True,
                    )

                # ── note off ─────────────────────────────────────────────────
                elif status == 0x80 or (status == 0x90 and velocity == 0):
                    active_notes.pop(note, None)
                    midi_event = {
                        "type":         "note_off",
                        "note":         note,
                        "note_name":    note_name(note),
                        "velocity":     0,
                        "active_notes": {str(n): v for n, v in active_notes.items()},
                        "timestamp":    timestamp,
                    }
                    print(
                        f"[midi_capture/{instrument_name}] NOTE OFF "
                        f"{note_name(note):4s} (#{note:3d})  "
                        f"active={sorted(note_name(n) for n in active_notes)}",
                        flush=True,
                    )

                # ── control change ───────────────────────────────────────────
                elif status == 0xB0:
                    cc_num, cc_value = note, velocity
                    label = "sustain" if cc_num == 64 else f"CC{cc_num}"
                    state = "on" if cc_value >= 64 else "off"
                    midi_event = {
                        "type":      "control_change",
                        "cc_num":    cc_num,
                        "cc_value":  cc_value,
                        "label":     label,
                        "state":     state,
                        "timestamp": timestamp,
                    }
                    print(
                        f"[midi_capture/{instrument_name}] CTRL     "
                        f"{label} {state} (raw={cc_value})",
                        flush=True,
                    )

                # ── pitch bend ───────────────────────────────────────────────
                elif status == 0xE0:
                    bend_raw    = (data[2] << 7) | data[1]
                    bend_signed = bend_raw - 8192
                    midi_event = {
                        "type":      "pitch_bend",
                        "value":     bend_signed,
                        "timestamp": timestamp,
                    }
                    print(f"[midi_capture/{instrument_name}] BEND     {bend_signed:+d}", flush=True)

                else:
                    continue    # ignore clock, aftertouch, sysex, etc.

                # pass event directly to the in-process analyser
                if "harmony" in analysers:
                    analyser.push(midi_event)

    except Exception as e:
        print(f"[midi_capture/{instrument_name}] Error: {e}", flush=True)
    finally:
        midi_in.close()
        if INFO:
            print(f"[midi_capture/{instrument_name}] Listener closed.", flush=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    pygame.midi.init()

    instruments = load_midi_instruments()

    if not instruments:
        print("[midi_capture] No enabled MIDI instruments — staying alive.", flush=True)
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            pass
        pygame.midi.quit()
        return

    threads = []

    for name, cfg in instruments.items():
        # instantiate one analyser per instrument
        analyser = MidiHarmonyAnalyser(
            instrument_name  = name,
            instrument_index = cfg["instrument_index"],
        )

        t = threading.Thread(
            target=listen_instrument,
            args=(name, cfg["device_name"], cfg["analysers"], analyser),
            name=f"MidiCapture-{name}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    if INFO:
        print(f"[midi_capture] {len(threads)} instrument thread(s) running.", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[midi_capture] Stopped.", flush=True)
    finally:
        pygame.midi.quit()


if __name__ == "__main__":
    main()