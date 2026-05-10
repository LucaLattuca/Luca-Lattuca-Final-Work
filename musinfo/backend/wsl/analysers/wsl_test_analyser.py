# wsl_test_analyser.py — Pipeline latency tester (WSL side)
# Receives audio chunks, computes delta from capture_time, sends via OSC.
# NOTE: capture_time is a Windows perf_counter value.
# WSL runs a different clock — delta here measures TCP transit only,
# not the full Windows-side pipeline time.

import time
import threading
import queue
import numpy as np
from pythonosc import udp_client

OSC_HOST = "172.29.28.224"  # replace with your actual Windows IP if needed
OSC_PORT = 9000
OSC_ADDRESS = "/latency/wsl"

REPORT_INTERVAL = 50


class WslTestAnalyser:

    def __init__(self, instrument_name, sample_rate=48000):
        self.instrument_name = instrument_name
        self.sample_rate = sample_rate
        self.osc = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.queue = queue.Queue()
        self.deltas = []
        self.chunk_count = 0

        threading.Thread(target=self._loop, daemon=True).start()
        print(f"[wsl_test_analyser] Started for {instrument_name}", flush=True)

    def push(self, audio, capture_time=None):
        self.queue.put((audio, capture_time))

    def _loop(self):
        while True:
            audio, capture_time = self.queue.get()

            if capture_time is None:
                continue

            now = time.perf_counter()
            delta_ms = (now - capture_time) * 1000.0
            self.deltas.append(delta_ms)
            self.chunk_count += 1

            msg = f"{self.instrument_name} {delta_ms:.1f}ms"
            self.osc.send_message(OSC_ADDRESS, msg)

            if self.chunk_count % REPORT_INTERVAL == 0:
                self._print_stats()

    def _print_stats(self):
        if not self.deltas:
            return
        arr = sorted(self.deltas)
        n = len(arr)
        mean = sum(arr) / n
        p95  = arr[int(n * 0.95)]
        mn   = arr[0]
        mx   = arr[-1]
        print(
            f"[wsl_test_analyser] {self.instrument_name} | "
            f"n={n} mean={mean:.1f}ms min={mn:.1f}ms max={mx:.1f}ms p95={p95:.1f}ms",
            flush=True
        )