# wsl_receiver_heavy.py — WSL Heavy Model Receiver
# Handles GPU-intensive analysers (genre, mood) in a separate process
# so they cannot starve dynamics, timbre, harmony and tempo_cnn of CPU time.

import socket
import struct
import json
import numpy as np
import os
import sys
import threading
from queue import Queue, Full

from analysers.genre_analyser import GenreAnalyser
from analysers.mood_analyser  import MoodAnalyser

TCP_HOST = "0.0.0.0"
TCP_PORT = 5008


# ─── SAMPLE RATES ─────────────────────────────────────────────────────────────
def load_sample_rates():
    base_dir    = os.path.dirname(os.path.dirname(__file__))
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
        print(f"[wsl_receiver_heavy] Loaded sample rates: {rates}")
        sys.stdout.flush()
        return rates
    except FileNotFoundError:
        print(f"[wsl_receiver_heavy] instruments.json not found, using default 48000Hz")
        sys.stdout.flush()
        return {}
    except json.JSONDecodeError as e:
        print(f"[wsl_receiver_heavy] Failed to parse instruments.json: {e}")
        sys.stdout.flush()
        return {}

SAMPLE_RATES = load_sample_rates()


# ─── AVAILABLE ANALYSERS ──────────────────────────────────────────────────────
AVAILABLE_ANALYSERS = {
    "genre": GenreAnalyser,
    "mood":  MoodAnalyser,
}

# ─── THREADED WRAPPER ─────────────────────────────────────────────────────────
ANALYSER_QUEUE_SIZES = {
    "genre": 1,
    "mood":  1,
}

class ThreadedAnalyser:
    def __init__(self, analyser, queue_size=1):
        self._analyser = analyser
        self._queue    = Queue(maxsize=queue_size)
        self._thread   = threading.Thread(
            target=self._worker,
            name=f"Heavy-{type(analyser).__name__}",
            daemon=True
        )
        self._thread.start()

    def _worker(self):
        while True:
            audio = self._queue.get()
            if audio is None:
                break
            try:
                self._analyser.push(audio)
            except Exception as e:
                print(f"[wsl_receiver_heavy] {type(self._analyser).__name__} error: {e}", flush=True)

    def push(self, audio):
        try:
            self._queue.put_nowait(audio)
        except Full:
            try:
                self._queue.get_nowait()
            except Exception:
                pass
            try:
                self._queue.put_nowait(audio)
            except Full:
                pass

    def stop(self):
        self._queue.put(None)


# ─── REGISTRY ─────────────────────────────────────────────────────────────────
analyser_registry = {}

def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf

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

# genre/mood send to prompt_generator (not TD index paths) so role is accepted but not forwarded
def initialise_analyser(instrument, analyser_name, role="default", instrument_index=0):
    if instrument not in analyser_registry:
        analyser_registry[instrument] = {}
    if analyser_name not in analyser_registry[instrument]:
        cls = AVAILABLE_ANALYSERS.get(analyser_name)
        if cls:
            sample_rate = SAMPLE_RATES.get(instrument, 48000)
            print(f"[wsl_receiver_heavy] Starting {analyser_name} for {instrument} (role={role}) @ {sample_rate}Hz")
            sys.stdout.flush()
            instance   = cls(instrument_name=instrument, sample_rate=sample_rate)
            queue_size = ANALYSER_QUEUE_SIZES.get(analyser_name, 1)
            analyser_registry[instrument][analyser_name] = ThreadedAnalyser(
                instance, queue_size=queue_size
            )

def log_routing(name, analysers, role="?", instrument_index="?"):
    print(f"[wsl_receiver_heavy] {name:<16} role={role:<10} -> {', '.join(analysers) if analysers else 'none'}")
    sys.stdout.flush()

def handle_connection(conn, addr):
    print(f"[wsl_receiver_heavy] broadcaster connected from {addr}")
    sys.stdout.flush()

    # Clear stale registry from previous connection — important for persistent tier
    for inst_analysers in analyser_registry.values():
        for threaded in inst_analysers.values():
            threaded.stop()
    analyser_registry.clear()


    logged_instruments = set()

    try:
        while True:
            instrument_info, audio = read_frame(conn)
            if instrument_info is None:
                break

            name             = instrument_info.get("instrument", "unknown")
            analysers        = instrument_info.get("analysers", [])
            role             = instrument_info.get("role", "default")
            instrument_index = instrument_info.get("instrument_index", 0)

            if name not in logged_instruments:
                logged_instruments.add(name)
                log_routing(name, analysers, role, instrument_index)
                for analyser in analysers:
                    initialise_analyser(name, analyser, role, instrument_index)

            for analyser in analysers:
                analyser_instance = analyser_registry.get(name, {}).get(analyser)
                if analyser_instance:
                    analyser_instance.push(audio)

    except Exception as e:
        print(f"[wsl_receiver_heavy] Error: {e}")
        sys.stdout.flush()
    finally:
        print(f"[wsl_receiver_heavy] broadcaster disconnected.")
        sys.stdout.flush()
        for inst_analysers in analyser_registry.values():
            for threaded in inst_analysers.values():
                threaded.stop()
        analyser_registry.clear()
        conn.close()

def start_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((TCP_HOST, TCP_PORT))
        server.listen(1)
        print(f"[wsl_receiver_heavy] Listening on {TCP_HOST}:{TCP_PORT}")
        sys.stdout.flush()
        while True:
            conn, addr = server.accept()
            handle_connection(conn, addr)

if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        print("[wsl_receiver_heavy] Stopped.")
        sys.stdout.flush()