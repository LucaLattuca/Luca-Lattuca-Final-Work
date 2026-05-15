import time
import numpy as np
import aubio
from collections import deque
from pythonosc import udp_client

# ── CONFIG ────────────────────────────────────────────────────────────────────
HOP_SIZE      = 512
SMOOTHING     = 8        # beat intervals kept for median smoothing
SEND_INTERVAL = 1.0      # seconds between BPM OSC sends
OSC_HOST      = "127.0.0.1"
OSC_PORT      = 9000

MIN_BPM       = 40.0
MAX_BPM       = 220.0
# ─────────────────────────────────────────────────────────────────────────────

# Fast tempo tracking via Aubio beat detection.
# Runs on Windows. Outputs:
#   /tempo/{instrument}/pulse  -> trigger (1) on every detected beat
#   /tempo/{instrument}/bpm    -> smoothed BPM, rate-limited
class TempoAnalyser:

    def __init__(self, instrument_name: str, sample_rate: int = 48000):
        self.instrument_name = instrument_name
        self.sample_rate     = sample_rate
        self.osc             = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.pulse_address   = f"/tempo/{instrument_name}/pulse"
        self.bpm_address     = f"/tempo/{instrument_name}/bpm"

        self._tempo = aubio.tempo("default", HOP_SIZE, HOP_SIZE, sample_rate)
        self._tempo.set_threshold(0.3)

        self._audio_buf    = []
        self._intervals    = deque(maxlen=SMOOTHING)
        self._last_beat    = None
        self._sample_count = 0
        self._current_bpm  = None
        self._last_send    = 0.0

        print(f"[tempo_analyser] '{instrument_name}' ready @ {sample_rate}Hz")

    # Accumulate incoming audio and drain in HOP_SIZE slices.
    def push(self, audio: np.ndarray):
        self._audio_buf.extend(audio.flatten().astype(np.float32).tolist())
        while len(self._audio_buf) >= HOP_SIZE:
            hop = np.array(self._audio_buf[:HOP_SIZE], dtype=np.float32)
            self._audio_buf = self._audio_buf[HOP_SIZE:]
            self._process_hop(hop)

    def stop(self):
        print(f"[tempo_analyser] '{self.instrument_name}' stopped")

    # Feed one hop to aubio, fire pulse on every beat, smooth + send BPM.
    def _process_hop(self, hop: np.ndarray):
        is_beat = self._tempo(hop)
        self._sample_count += HOP_SIZE

        if is_beat[0]:
            # Pulse fires on every detected beat — no smoothing, no rate limit
            self.osc.send_message(self.pulse_address, 1)

            now = self._sample_count / self.sample_rate
            if self._last_beat is not None:
                interval = now - self._last_beat
                bpm = 60.0 / interval
                if MIN_BPM <= bpm <= MAX_BPM:
                    self._intervals.append(interval)
            self._last_beat = now

        if len(self._intervals) >= 2:
            self._current_bpm = round(60.0 / float(np.median(self._intervals)), 1)

        now_wall = time.time()
        if self._current_bpm and (now_wall - self._last_send) >= SEND_INTERVAL:
            self.osc.send_message(self.bpm_address, self._current_bpm)
            print(f"[tempo_analyser] {self.instrument_name}: {self._current_bpm} BPM -> {self.bpm_address}")
            self._last_send = now_wall