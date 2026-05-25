# windows_receiver.py — Audio Receiver on windows side
# Opens a TCP socket for broadcaster to connect to.
# On first connection, reads instrument/analyser config and initialises
# one analyser instance per instrument per active analyser.
# Then routes incoming audio chunks to the correct analyser instance.

import socket
import struct
import json
import numpy as np
import os
import sys

import threading
from queue import Queue, Full

from analysers.pitch_analyser import PitchAnalyser
from analysers.tempo_analyser import TempoAnalyser


TCP_HOST = "0.0.0.0"
TCP_PORT = 5007


# ─── SAMPLE RATES ─────────────────────────────────────────────────────────────
def load_sample_rates():
    """Read sample rates directly from instruments.json audio_device config."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(base_dir, "config", "instruments.json")

    try:
        with open(config_path) as f:
            config = json.load(f)

        rates = {}
        for name, inst in config.get("instruments", {}).items():
            device_info = inst.get("audio_device", {})
            sample_rate = device_info.get("sample_rate")
            if sample_rate is not None:
                rates[name] = sample_rate

        print(f"[windows_receiver] Loaded sample rates: {rates}")
        sys.stdout.flush()
        return rates

    except FileNotFoundError:
        print(f"[windows_receiver] instruments.json not found, using default 48000Hz")
        sys.stdout.flush()
        return {}

# Load sample rates at startup
SAMPLE_RATES = load_sample_rates()


# Load instrument indexes
def load_instrument_indices():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(base_dir, "config", "instruments.json")
    try:
        with open(config_path) as f:
            config = json.load(f)
        audio_instruments = sorted(
            name for name, inst in config.get("instruments", {}).items()
            if inst.get("type") == "audio"
        )
        return {name: idx for idx, name in enumerate(audio_instruments)}
    except Exception:
        return {}


INSTRUMENT_INDICES = load_instrument_indices()



ANALYSER_QUEUE_SIZES = {
    "pitch": 4,
    "tempo": 2,  # aubio tempo — needs some beat continuity
}


class ThreadedAnalyser:
    """
    Wraps any analyser instance in its own worker thread.
    The main recv loop calls push() which drops into a queue and returns
    immediately — the worker thread calls the real analyser.push() independently.
    If the queue is full, the oldest chunk is dropped to stay current.
    """
    def __init__(self, analyser, queue_size=2):
        self._analyser = analyser
        self._queue    = Queue(maxsize=queue_size)
        self._thread   = threading.Thread(
            target=self._worker,
            name=f"Analyser-{type(analyser).__name__}",
            daemon=True
        )
        self._thread.start()

    def _worker(self):
        while True:
            audio = self._queue.get()
            if audio is None:       # shutdown signal
                break
            try:
                self._analyser.push(audio)
            except Exception as e:
                print(f"[ThreadedAnalyser] {type(self._analyser).__name__} error: {e}",
                      flush=True)

    def push(self, audio):
        try:
            self._queue.put_nowait(audio)
        except Full:
            try:
                self._queue.get_nowait()   # drop oldest
            except Exception:
                pass
            try:
                self._queue.put_nowait(audio)
            except Full:
                pass                       # still full, just drop

    def stop(self):
        self._queue.put(None)



# ─── ANALYSERS ────────────────────────────────────────────────────────────────
AVAILABLE_ANALYSERS = {
    "pitch": PitchAnalyser,
    "tempo": TempoAnalyser,
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


# instantiate if this receiver handles the analyser's destination
def initialise_analyser(instrument, analyser):
    if instrument not in analyser_registry:
        analyser_registry[instrument] = {}
    if analyser not in analyser_registry[instrument]:
        cls = AVAILABLE_ANALYSERS.get(analyser)
        if cls:
            sample_rate = SAMPLE_RATES.get(instrument, 48000)
            print(f"[windows_receiver] Starting {analyser} for {instrument} @ {sample_rate}Hz")
            sys.stdout.flush()
            instance = cls(
                instrument_name=instrument,
                sample_rate=sample_rate,
                instrument_index=INSTRUMENT_INDICES.get(instrument, 0)
            )
            queue_size = ANALYSER_QUEUE_SIZES.get(analyser, 2)
            analyser_registry[instrument][analyser] = ThreadedAnalyser(instance, queue_size=queue_size)

            
            


            
# prints instrument/analyser combination 
def log_routing(name, analysers):
    analysers_str = ", ".join(analysers) if analysers else "none"
    index = INSTRUMENT_INDICES.get(name, "N/A (mix)")
    print(f"[windows_receiver] {name:<16} index={index}  -> {analysers_str}")
    sys.stdout.flush()



# Handles connection to broadcaster.py, initialises analysers, routes incoming audio chunks
def handle_connection(conn, addr): 
    print(f"[windows_receiver] broadcaster connected from {addr}")
    sys.stdout.flush()
    logged_instruments = set()

    try:
        while True:
            instrument_info, audio = read_frame(conn)

            if instrument_info is None:
                break

            name   = instrument_info.get("instrument", "unknown")
            analysers = instrument_info.get("analysers", [])

            # initialise and log each instrument once per connection
            if name not in logged_instruments:
                logged_instruments.add(name)
                log_routing(name, analysers)
                for analyser in analysers:
                    initialise_analyser(name, analyser)

            # route audio to each active analyser for this instrument
            for analyser in analysers:
                analyser_instance = analyser_registry.get(name, {}).get(analyser)
                if analyser_instance:
                    analyser_instance.push(audio)

    except Exception as e:
        print(f"[windows_receiver] Error: {e}")
        sys.stdout.flush()
    finally:
        print(f"[windows_receiver] broadcaster disconnected.")
        sys.stdout.flush()
        # stop all worker threads cleanly
        for inst_analysers in analyser_registry.values():
            for threaded in inst_analysers.values():
                threaded.stop()
        analyser_registry.clear()
        conn.close()



# start TCP server loop
def start_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((TCP_HOST, TCP_PORT))
        server.listen(1)
        print(f"[windows_receiver] Listening on {TCP_HOST}:{TCP_PORT}")
        sys.stdout.flush()

        while True:
            conn, addr = server.accept()
            handle_connection(conn, addr)


if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        print("[windows_receiver] Stopped.")
        sys.stdout.flush()