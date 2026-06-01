import time
import numpy as np
import aubio
from collections import deque
from pythonosc import udp_client

# Debugging
DEBUG = False
INFO = True

# ── CONFIG ─────────────────────────────────────────────────────────────────────
HOP_SIZE      = 512
SMOOTHING     = 8
SEND_INTERVAL = 1.0

OSC_HOST    = "127.0.0.1"
OSC_PORT    = 9000
OSC_TD_PORT = 9100

MIN_BPM = 40.0
MAX_BPM = 220.0
# ───────────────────────────────────────────────────────────────────────────────

class TempoAnalyser:

    def __init__(self, instrument_name: str, sample_rate: int, instrument_role: str = "default", instrument_index: int = 0):
        self.instrument_role  = instrument_role
        self.instrument_index = instrument_index
        self.instrument_name     = instrument_name
        self.sample_rate         = sample_rate
        self._beat_reset_pending = False
    
        self.osc    = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
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

        if INFO : 
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

        if self._beat_reset_pending:
            self.td_client.send_message(f"/td/tempo/pulse", 0)
            self._beat_reset_pending = False

        if is_beat[0]:
            self.osc.send_message(self.pulse_address, 1)
            self.td_client.send_message(f"/td/tempo/pulse", 1)
            self._beat_reset_pending = True

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

            if DEBUG : 
                print(f"[tempo_analyser] {self.instrument_name}: {self._current_bpm} BPM -> {self.bpm_address}")
            
            self._last_send = now_wall