# receiver.py — WSL Audio Receiver
# Receives framed chunks from broadcaster.py (Windows side).
# Each chunk carries instrument metadata + raw PCM audio.
# Prints diagnostic info to confirm the full pipeline is working.

import socket
import struct
import json
from musinfo.backend.wsl.analysers.genre_analyser import GenreAnalyser
import numpy as np

TCP_HOST = "0.0.0.0"
TCP_PORT = 5006

SAMPLE_RATE = 48000

# ─── ANALYSERS ────────────────────────────────────────────────────────────────
genre_analyser = None



def recv_exact(conn, n):
    """
    Reads exactly n bytes from the socket.
    TCP can split data across multiple recv() calls, so we loop.
    Returns None if the connection closes mid-read.
    """
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def read_frame(conn):
    """
    Reads one complete frame from broadcaster.py.

    Frame format:
      [4 bytes: header length (uint32)]
      [N bytes: header JSON           ]
      [4 bytes: audio length  (uint32)]
      [K bytes: raw float32 PCM       ]

    Returns (instrument_info dict, audio numpy array)
    or (None, None) if the connection closed.
    """
    # --- read header ---
    raw_header_len = recv_exact(conn, 4)
    if raw_header_len is None:
        return None, None
    header_len = struct.unpack(">I", raw_header_len)[0]

    raw_header = recv_exact(conn, header_len)
    if raw_header is None:
        return None, None
    instrument_info = json.loads(raw_header.decode("utf-8"))

    # --- read audio ---
    raw_audio_len = recv_exact(conn, 4)
    if raw_audio_len is None:
        return None, None
    audio_len = struct.unpack(">I", raw_audio_len)[0]

    raw_audio = recv_exact(conn, audio_len)
    if raw_audio is None:
        return None, None
    audio = np.frombuffer(raw_audio, dtype=np.float32)

    return instrument_info, audio

# diagnostic display of which models are active for this instrument, for debugging
def format_models(models):
    """
    Turns {"pitch": true, "genre": false} into "pitch=ON  genre=OFF"
    """
    return "  ".join(
        f"{name}={'ON ' if active else 'OFF'}"
        for name, active in models.items()
    )

# connects to the WSL receiver, retrying if it's not ready yet
def handle_connection(conn, addr): 
    global genre_analyser
    print(f"[receiver] broadcaster connected from {addr}")

    try:
        while True:
            instrument_info, audio = read_frame(conn)

            if instrument_info is None:
                break

            name   = instrument_info.get("instrument", "unknown")
            models = instrument_info.get("models", {})

            # RMS level — confirms real audio is flowing, not silence or zeros
            rms = float(np.sqrt(np.mean(audio ** 2)))

            print(
                f"[{name:<10}]  "
                f"RMS: {rms:.4f}  |  "
                f"samples: {len(audio)}  |  "
                f"models: {format_models(models)}"
            )

            # ── route to analysers ────────────────────────────────────────────
            if models.get("genre"):
                if genre_analyser is None:
                    print("[receiver] Initialising genre analyser...")
                    genre_analyser = GenreAnalyser()
                genre_analyser.push(audio)

            #TODO: add pitch analyser routing here when implemented

    except Exception as e:
        print(f"[receiver] Error: {e}")
    finally:
        print(f"[receiver] broadcaster disconnected.")
        conn.close()

# TCP server loop
def start_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((TCP_HOST, TCP_PORT))
        server.listen(1)
        print(f"[receiver] Listening on {TCP_HOST}:{TCP_PORT}")

        while True:
            conn, addr = server.accept()
            handle_connection(conn, addr)


if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        print("[receiver] Stopped.")