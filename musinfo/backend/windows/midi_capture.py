# midi_capture.py — MIDI Capture + TCP Streamer (Windows side)
# Loads instruments.json, opens a pygame.midi.Input for every instrument
# where type == "midi" and enabled == True, and streams MIDI events
# directly to midi_receiver.py in WSL over TCP.
#
# Bypasses broadcaster entirely — MIDI is discrete events, not PCM stream.
# broadcaster and wsl_receiver remain audio-only and untouched.

import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import json
import socket
import struct
import threading
import time

import pygame.midi

# ── config ────────────────────────────────────────────────────────────────────

INFO = True

WSL_MIDI_HOST = "172.29.28.224"   # same WSL IP as broadcaster uses for wsl_receiver
WSL_MIDI_PORT = 5010               # dedicated port — nothing else touches this

POLL_INTERVAL = 0.005              # 5 ms polling — tight enough for live performance

socket_lock = threading.Lock()     # shared across instrument threads


# ── instruments.json ──────────────────────────────────────────────────────────

def load_midi_instruments() -> dict:
    """
    Return every instrument where:
      - enabled          == True
      - type             == "midi"
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
            "device_name": dev_name,
            "analysers":   inst.get("analysers", []),
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


# ── TCP framing ───────────────────────────────────────────────────────────────

def send_event(sock, instrument_name: str, analysers: list, event: dict):
    """
    Frame format to midi_receiver.py:

      [4 bytes: header length  (uint32 big-endian)]
      [N bytes: header JSON                       ]
      [4 bytes: payload length (uint32 big-endian)]
      [K bytes: payload JSON  (MIDI event dict)   ]

    Header: { instrument, analysers }
    Payload: { type, note, note_name, velocity, active_notes, timestamp, ... }
    """
    header  = json.dumps({"instrument": instrument_name, "analysers": analysers}).encode("utf-8")
    payload = json.dumps(event).encode("utf-8")
    frame   = struct.pack(">I", len(header)) + header + struct.pack(">I", len(payload)) + payload
    with socket_lock:
        sock.sendall(frame)


# ── per-instrument listener thread ────────────────────────────────────────────

def listen_instrument(instrument_name: str, device_name: str, analysers: list, sock):
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
                data      = event[0]        # [status, data1, data2, unused]
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

                # ── control change (sustain pedal, mod wheel, etc.) ──────────
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

                try:
                    send_event(sock, instrument_name, analysers, midi_event)
                except OSError as e:
                    print(f"[midi_capture] Send error: {e}", flush=True)
                    return      # socket dead — let thread exit cleanly

    except Exception as e:
        print(f"[midi_capture/{instrument_name}] Error: {e}", flush=True)
    finally:
        midi_in.close()
        if INFO:
            print(f"[midi_capture/{instrument_name}] Listener closed.", flush=True)


# ── connection ────────────────────────────────────────────────────────────────

def connect_to_midi_receiver() -> socket.socket:
    """Retry loop — midi_receiver.py in WSL may take a moment to be ready."""
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((WSL_MIDI_HOST, WSL_MIDI_PORT))
            if INFO:
                print(f"[midi_capture] Connected to midi_receiver at {WSL_MIDI_HOST}:{WSL_MIDI_PORT}", flush=True)
            return s
        except ConnectionRefusedError:
            print("[midi_capture] midi_receiver not ready — retrying in 2s", flush=True)
            time.sleep(2)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    pygame.midi.init()

    instruments = load_midi_instruments()

    if not instruments:
        print("[midi_capture] No enabled MIDI instruments — staying alive for hot-reload.", flush=True)
        # Stay alive rather than exit — avoids needing a pipeline restart
        # if the user enables a MIDI instrument after launch.
        # TODO: poll instruments.json and open devices dynamically.
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            pass
        pygame.midi.quit()
        return

    sock = connect_to_midi_receiver()

    threads = []
    for name, cfg in instruments.items():
        t = threading.Thread(
            target=listen_instrument,
            args=(name, cfg["device_name"], cfg["analysers"], sock),
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
        sock.close()
        pygame.midi.quit()


if __name__ == "__main__":
    try:
        main()
    except ConnectionRefusedError:
        print("[midi_capture] Connection refused — is midi_receiver.py running?")