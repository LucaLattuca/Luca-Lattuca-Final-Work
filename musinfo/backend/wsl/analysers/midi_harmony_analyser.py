# midi_harmony_analyser.py — MIDI Harmony Analyser (WSL side)
# Opens a TCP socket that midi_capture.py connects to directly.
# Phase 1: reads framed MIDI events and prints them to console.
# Phase 2+: harmony analysis (HPCP, key, chord, dissonance, etc.)

import socket
import struct
import json
import sys
import os

TCP_HOST = "0.0.0.0"
TCP_PORT = 5010

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def note_name(midi_note: int) -> str:
    return NOTE_NAMES[int(midi_note) % 12] + str(int(midi_note) // 12 - 1)

# ── socket helpers ────────────────────────────────────────────────────────────

def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def read_frame(conn):
    """
    Frame format (matches what midi_capture.py sends):
      [4 bytes: header length  (uint32 big-endian)]
      [N bytes: header JSON  { instrument, analysers }]
      [4 bytes: payload length (uint32 big-endian)]
      [K bytes: payload JSON  (MIDI event dict)   ]

    Returns (header dict, event dict) or (None, None) on EOF.
    """
    raw = recv_exact(conn, 4)
    if raw is None:
        return None, None
    header_len = struct.unpack(">I", raw)[0]

    raw = recv_exact(conn, header_len)
    if raw is None:
        return None, None
    header = json.loads(raw.decode("utf-8"))

    raw = recv_exact(conn, 4)
    if raw is None:
        return None, None
    payload_len = struct.unpack(">I", raw)[0]

    raw = recv_exact(conn, payload_len)
    if raw is None:
        return None, None
    event = json.loads(raw.decode("utf-8"))

    return header, event


# ── event printer ─────────────────────────────────────────────────────────────

def print_event(instrument: str, event: dict):
    event_type = event.get("type", "unknown")

    # convert active_notes keys (string MIDI numbers) to note names for readability
    active_named = [note_name(n) for n in sorted(event.get("active_notes", {}).keys(), key=int)]

    if event_type == "note_on":
        print(
            f"[midi_harmony/{instrument}] NOTE ON  "
            f"{event.get('note_name', '?'):4s}  "
            f"vel={event.get('velocity', 0):3d}  "
            f"active={active_named}",
            flush=True,
        )

    elif event_type == "note_off":
        print(
            f"[midi_harmony/{instrument}] NOTE OFF "
            f"{event.get('note_name', '?'):4s}  "
            f"active={active_named}",
            flush=True,
        )

    elif event_type == "control_change":
        print(
            f"[midi_harmony/{instrument}] CTRL     "
            f"{event.get('label', '?')} {event.get('state', '?')} "
            f"(raw={event.get('cc_value', 0)})",
            flush=True,
        )

    elif event_type == "pitch_bend":
        print(
            f"[midi_harmony/{instrument}] BEND     "
            f"{event.get('value', 0):+d}",
            flush=True,
        )

    else:
        print(f"[midi_harmony/{instrument}] {event}", flush=True)


# ── connection handler ────────────────────────────────────────────────────────

def handle_connection(conn, addr):
    print(f"[midi_harmony] midi_capture connected from {addr}", flush=True)
    try:
        while True:
            header, event = read_frame(conn)
            if header is None:
                break
            instrument = header.get("instrument", "unknown")
            print_event(instrument, event)
    except Exception as e:
        print(f"[midi_harmony] Error: {e}", flush=True)
    finally:
        print(f"[midi_harmony] midi_capture disconnected.", flush=True)
        conn.close()


# ── server ────────────────────────────────────────────────────────────────────

def start_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((TCP_HOST, TCP_PORT))
        server.listen(1)
        print(f"[midi_harmony] Listening on {TCP_HOST}:{TCP_PORT}", flush=True)

        while True:
            conn, addr = server.accept()
            handle_connection(conn, addr)


if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        print("[midi_harmony] Stopped.", flush=True)