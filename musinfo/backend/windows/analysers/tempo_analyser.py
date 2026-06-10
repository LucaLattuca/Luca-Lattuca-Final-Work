import time
import numpy as np
import aubio
from collections import deque
from pythonosc import udp_client

# Debugging
DEBUG = True
INFO = True

# ── CONFIG ─────────────────────────────────────────────────────────────────────
HOP_SIZE      = 512
SMOOTHING     = 8
SEND_INTERVAL = 1.0

OSC_HOST    = "127.0.0.1"
OSC_PORT    = 9000
OSC_TD_PORT = 9101

MIN_BPM = 40.0
MAX_BPM = 220.0

# How long the pulse stays high before resetting to 0 (wall-clock seconds).
# Keeps the 1 visible for at least this long regardless of how fast
# the audio processing loop is consuming buffered chunks.
PULSE_HOLD_SEC = 0.010   # 10ms
# ───────────────────────────────────────────────────────────────────────────────

class TempoAnalyser:

    def __init__(self, instrument_name: str, sample_rate: int, instrument_role: str = "default", role_index: int = 0, instrument_index: int = 0):
        self.instrument_role  = instrument_role
        self.role_index       = role_index
        self.instrument_index = instrument_index
        self.instrument_name  = instrument_name
        self.sample_rate      = sample_rate
        self._beat_reset_pending = False
        self._beat_time          = None   # wall time of last beat

        self.osc       = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.td_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)

        self.pulse_address = f"/tempo/{instrument_name}/pulse"
        self.bpm_address   = f"/tempo/{instrument_name}/bpm"

        self._tempo = aubio.tempo("default", HOP_SIZE, HOP_SIZE, sample_rate)
        self._tempo.set_threshold(0.5)

        self._audio_buf    = []
        self._intervals    = deque(maxlen=SMOOTHING)
        self._last_beat    = None
        self._sample_count = 0
        self._current_bpm  = None
        self._last_send    = 0.0

        if INFO:
            print(f"[tempo_analyser] '{instrument_name}' ready @ {sample_rate}Hz")

    def push(self, audio: np.ndarray):
        self._audio_buf.extend(audio.flatten().astype(np.float32).tolist())
        while len(self._audio_buf) >= HOP_SIZE:
            hop = np.array(self._audio_buf[:HOP_SIZE], dtype=np.float32)
            self._audio_buf = self._audio_buf[HOP_SIZE:]
            self._process_hop(hop)

    def stop(self):
        print(f"[tempo_analyser] '{self.instrument_name}' stopped")

    def _process_hop(self, hop: np.ndarray):
        is_beat = self._tempo(hop)
        self._sample_count += HOP_SIZE

        if is_beat[0]:
            # Beat detected — send pulse high, record wall time for hold timer
            self.td_client.send_message("/td/tempo/pulse", 1)
            self.osc.send_message(self.pulse_address, 1)
            self._beat_reset_pending = True
            self._beat_time          = time.perf_counter()

            if DEBUG:
                print(f"[tempo_analyser] {self.instrument_name}: beat")

            now = self._sample_count / self.sample_rate
            if self._last_beat is not None:
                interval = now - self._last_beat
                bpm = 60.0 / interval
                if MIN_BPM <= bpm <= MAX_BPM:
                    self._intervals.append(interval)
            self._last_beat = now

        elif self._beat_reset_pending:
            # Only reset after PULSE_HOLD_SEC of wall time has elapsed.
            # Without this, buffered chunk processing can fire the 0 almost
            # immediately after the 1 in real time, making the pulse invisible to TD.
            if (time.perf_counter() - self._beat_time) >= PULSE_HOLD_SEC:
                self.td_client.send_message("/td/tempo/pulse", 0)
                self._beat_reset_pending = False

        self._current_bpm = self._compute_bpm()

        now_wall = time.time()
        if self._current_bpm and (now_wall - self._last_send) >= SEND_INTERVAL:
            # BPM goes to frontend only — TD gets pulse only via td_client
            self.osc.send_message(self.bpm_address, self._current_bpm)

            if DEBUG:
                print(f"[tempo_analyser] {self.instrument_name}: {self._current_bpm} BPM -> {self.bpm_address}")

            self._last_send = now_wall

    def _compute_bpm(self) -> float | None:
        if len(self._intervals) < 2:
            return None

        intervals = list(self._intervals)
        raw_bpm   = 60.0 / float(np.median(intervals))

        # Double-time correction: aubio often locks onto subdivisions (8th notes).
        # Detect this by pairing consecutive intervals — if the paired intervals
        # have less variance than the individual ones, we're at double time.
        if len(intervals) >= 4:
            pairs = [intervals[i] + intervals[i + 1] for i in range(len(intervals) - 1)]
            if np.std(pairs) < np.std(intervals) and (raw_bpm / 2) >= MIN_BPM:
                return round(raw_bpm / 2, 1)

        return round(raw_bpm, 1)