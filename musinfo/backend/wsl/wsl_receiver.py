# receiver_wsl.py — WSL Audio Receiver
# Opens a TCP socket for broadcaster to connect to.
# On first connection, reads instrument/model config and initialises
# one analyser instance per instrument per active model.
# Then routes incoming audio chunks to the correct analyser instance.

import socket
import struct
import json
import numpy as np

from analysers.genre_analyser import GenreAnalyser


TCP_HOST = "0.0.0.0"
TCP_PORT = 5006


# ─── ANALYSERS ────────────────────────────────────────────────────────────────
AVAILABLE_ANALYSERS = {
    "genre": GenreAnalyser,
}

# holds every instance of each analyser (piano : pitch, guitar : pitch, genre...)
analyser_registry = {}

# reads exactly n bytes from the socket, looping until complete since TCP may split reads
def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf

# unpacks one complete broadcaster frame into instrument metadata and a numpy audio array
def read_frame(conn):
    raw_header_len = recv_exact(conn, 4)
    if raw_header_len is None:
        return None, None
    header_len = struct.unpack(">I", raw_header_len)[0]

    raw_header = recv_exact(conn, header_len)
    if raw_header is None:
        return None, None
    instrument_info = json.loads(raw_header.decode("utf-8"))

    raw_audio_len = recv_exact(conn, 4)
    if raw_audio_len is None:
        return None, None
    audio_len = struct.unpack(">I", raw_audio_len)[0]

    raw_audio = recv_exact(conn, audio_len)
    if raw_audio is None:
        return None, None
    audio = np.frombuffer(raw_audio, dtype=np.float32)

    return instrument_info, audio


# creates one analyser instance per instrument+model combination
def initialise_analyser(instrument, model):
    if instrument not in analyser_registry:
        analyser_registry[instrument] = {}
    if model not in analyser_registry[instrument]:
        cls = AVAILABLE_ANALYSERS.get(model)
        if cls:
            print(f"[receiver] Starting {model} analyser for {instrument}")
            analyser_registry[instrument][model] = cls()

# prints instrument/model combination 
def log_routing(name, models):
    analysers = ", ".join(models) if models else "none"
    print(f"[receiver] {name:<16} → {analysers}")



# Handles connection to broadcaster.py, initialises analysers, routes incoming audio chunks
def handle_connection(conn, addr): 
    print(f"[receiver] broadcaster connected from {addr}")
    logged_instruments = set()

    try:
        while True:
            instrument_info, audio = read_frame(conn)

            if instrument_info is None:
                break

            name   = instrument_info.get("instrument", "unknown")
            models = instrument_info.get("models", [])

            # initialise and log each instrument once per connection
            if name not in logged_instruments:
                logged_instruments.add(name)
                log_routing(name, models)
                for model in models:
                    initialise_analyser(name, model)

            # route audio to each active analyser for this instrument
            for model in models:
                analyser = analyser_registry.get(name, {}).get(model)
                if analyser:
                    analyser.push(audio)

    except Exception as e:
        print(f"[receiver] Error: {e}")
    finally:
        print(f"[receiver] broadcaster disconnected.")
        conn.close()



# start TCP server loop
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