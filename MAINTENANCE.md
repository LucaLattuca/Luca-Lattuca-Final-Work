# MUSINFO — Maintenance

This document covers how to maintain the codebase, how to add new analysers, and known bugs with workarounds.

---

## NAMING CONVENTIONS

**Python files** — `snake_case` throughout: `pitch_analyser.py`, `windows_receiver.py`, `midi_capture.py`. Every file opens with a comment block:

```python
# filename.py — Short one-line description
# What this file does, what it connects to.
```

Section dividers use capital letters and underscores as a visual separator — this will be standardised during code cleanup.

`INFO` and `DEBUG` constants at the top of each file gate all print output. Every print includes the filename prefix: `[filename] message`.

**Analyser classes** — `push(audio: np.ndarray)` is the only public method. OSC addresses are built from constructor arguments (`instrument_role`, `role_index`), not hardcoded inline.

**React components** — one component per file, CSS Modules throughout, props destructured at function top. Handler functions in `App.jsx` are prefixed `handle` and passed down as `on` props.

**Tauri commands** — `snake_case`, matching the `invoke()` call in React. Every command returns a typed value or an error string.

---

## AI TRANSPARENCY

Claude Sonnet 4.6 was used for implementation assistance throughout. Key principles applied:

- Architecture decisions were made by the developer. The AI was given a defined problem and existing context, not asked to design the system.
- All generated code was reviewed before committing. Inconsistent naming or structural drift was corrected manually.
- Hallucinations were caught by cross-referencing Essentia documentation, Tauri documentation, and runtime behaviour. The AI was not trusted on model output shapes or ASIO threading requirements.

A full list of AI conversations is in `README.md` under _Usage of AI for Development_.

---

## COMMIT CONVENTIONS

```
feat:     new feature
fix:      bug fix
refactor: code restructure without behaviour change
chore:    build, config, tooling (used rarely)
```

Documentation changes are committed on a separate `documentation` branch.

---

## ADDING AN ANALYSER

### Step 1 — Write the analyser

Create the file in the correct folder:

- `musinfo/backend/windows/analysers/` — Windows (Aubio, numpy, pygame)
- `musinfo/backend/wsl/analysers/` — WSL (Essentia, TensorFlow, librosa)

Minimal structure:

```python
# my_analyser.py — Short description
# What it analyses, what it sends.

import numpy as np
import subprocess
from pythonosc import udp_client

def _get_windows_host_ip():  # only needed for WSL analysers
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"

OSC_HOST = _get_windows_host_ip()   # "127.0.0.1" for Windows-side analysers
OSC_PORT    = 9000   # Tauri frontend
OSC_TD_PORT = 9100   # TouchDesigner

MIN_SAMPLES = 4096

class MyAnalyser:
    def __init__(self, instrument_name, sample_rate, instrument_role="default",
                 role_index=0, instrument_index=0):
        self.instrument_name = instrument_name
        self.instrument_role = instrument_role
        self.role_index      = role_index
        self._buffer         = np.array([], dtype=np.float32)
        self._osc            = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self._td             = udp_client.SimpleUDPClient(OSC_HOST, OSC_TD_PORT)

    def push(self, audio: np.ndarray):
        self._buffer = np.concatenate([self._buffer, audio])
        if len(self._buffer) < MIN_SAMPLES:
            return
        result = self._analyse(self._buffer[-MIN_SAMPLES:])
        # Frontend address — instrument-name based, always fixed
        self._osc.send_message(f"/my_analyser/{self.instrument_name}/result", float(result))
        # TD address — role/index based, matches OSC Config tab
        self._td.send_message(f"/td/my_analyser/{self.instrument_role}/{self.role_index}/result", float(result))

    def _analyse(self, audio: np.ndarray) -> float:
        return 0.0
```

### Step 2 — Add a model (if needed)

Place model files in a dedicated subfolder:

```
musinfo/backend/wsl/models/my_analyser_models/
    my_model-1.pb
    my_model-1.json
```

**Do not commit model files to the repository.** They must be saved and distributed manually (e.g. via Hugging Face or shared drive). Essentia model documentation and downloads are available at [essentia.upf.edu/models](https://essentia.upf.edu/models/).

### Step 3 — Register in analysers.json

```json
"my_analyser": {
    "target": "wsl",
    "enabled_by_default": false,
    "description": "Short description"
}
```

`target` can be `"windows"`, `"wsl"`, `"wsl_heavy"`, or `"both"`. When set to `"both"`, broadcaster routes the audio to both the WSL and Windows receivers simultaneously. This is configured in `analysers.json` and read by `broadcaster.py` via the `_target()` helper.

### Step 4 — Register in the receiver

Add the import and the entry to `AVAILABLE_ANALYSERS` in the target receiver file:

```python
from analysers.my_analyser import MyAnalyser

AVAILABLE_ANALYSERS = {
    ...
    "my_analyser": MyAnalyser,
}
```

Set a queue size in `ANALYSER_QUEUE_SIZES`. The queue controls how many audio chunks can wait before the oldest is dropped. Larger queues tolerate slower analysers without dropping frames, but increase latency. Keep GPU-heavy analysers at 1–2 (prefer fresh data over completeness), fast CPU analysers at 4+.

```python
ANALYSER_QUEUE_SIZES = {
    ...
    "my_analyser": 4,
}
```

### Step 5 — Frontend

The analyser toggle appears in the AnalyserConfig component automatically once the `analysers.json` entry is present. No React changes needed. The new TD address pattern should be documented in the OSC Config tab display if it is non-obvious.

---

## KNOWN BUGS

### SDXL Turbo CUDA error — stale GPU state on restart

**Symptom:** `generate_image.py` fails with a CUDA error after the pipeline is stopped and restarted. The error typically involves a stale CUDA context or failed GPU operation.

**Workaround:** Clear the CUDA context from a WSL terminal before restarting:

```python
python -c "import torch; torch.cuda.empty_cache(); torch.cuda.synchronize(); print('CUDA cleared')"
```

**Root cause:** `generate_image.py` is in the persistent tier and does not fully reinitialise its GPU state when the pipeline restarts. A proper fix would add a graceful reinitialise path triggered by `/musinfo/pipeline_running`.

---

### One failing analyser can affect others

**Symptom:** An unhandled exception in one analyser's `push()` method may not crash the receiver process, but if it corrupts shared state or blocks the `ThreadedAnalyser` worker, other analysers in the same receiver may stop producing output without an obvious error message.

**Diagnosis:** Set `DEBUG = True` and/or `INFO = True` at the top of the relevant analyser file and restart the pipeline. The verbose output will show which analyser is throwing errors. Each receiver's `ThreadedAnalyser` catches and prints exceptions in `_worker()`, so the error will appear in the process output.

**Note:** genre and mood share GPU resources via `SharedEmbedder`. If the embedder fails (e.g. due to the CUDA stale state bug), both genre and mood will stop producing results simultaneously.

---

### WSL host IP not resolved correctly in broadcaster.py

**Symptom:** All WSL-based analysis stops if the broadcaster's WSL host IP becomes stale after a WSL reset or network change. WSL assigns a fresh virtual gateway IP on each boot.

**Resolution:** broadcaster.py resolves the WSL host IP dynamically using `ip route show default`, matching the same pattern used in all WSL-side analysers:

```python
def _get_wsl_host_ip():
    result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "default via" in line:
            return line.split()[2]
    return "172.29.16.1"   # fallback
```

If OSC messages from WSL analysers stop arriving, verify the gateway IP manually (`ip route show default` in WSL) and check it matches the fallback value.

---

### AUDIO device index changes between sessions

**Symptom:** After a system restart or USB device reconnection, a different integer index may be assigned to the same physical device.

**Resolution:** `resolve_device_id()` in `capture.py` matches by device name + host API string, not by integer index. `reconcile_devices` runs automatically on pipeline start and session load. If a device shows as disconnected despite being physically present, use the reconcile button in AudioDevicesConfig or restart the app.
