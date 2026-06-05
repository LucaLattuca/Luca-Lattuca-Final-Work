# MUSINFO — System Architecture

This document describes the full architecture of MUSINFO: from user interface to audio capture, broadcasting, analysis, OSC routing, and image generation.

---

## Table of Contents

1. [Overview](#overview)
2. [User Interface — React + Tauri](#user-interface--react--tauri)
3. [Rust Backend — lib.rs + menu.rs](#rust-backend--librs--menurs)
4. [Audio Pipeline](#audio-pipeline)
5. [Analysers](#analysers)
6. [OSC Routing](#osc-routing)
7. [Prompt and Image Generation](#prompt-and-image-generation)
8. [TouchDesigner](#touchdesigner)
9. [Configuration Files](#configuration-files)

---

## Overview

MUSINFO runs across three environments: **Windows** (capture, broadcast, Windows analysers, MIDI), **WSL2** (Essentia/ML analysers), and **TouchDesigner** (visuals). Processes communicate over TCP (audio) and OSC (analysis results).

Processes are split into two tiers based on their startup cost:

| Tier           | Processes                                                          | Lifetime                   |
| -------------- | ------------------------------------------------------------------ | -------------------------- |
| **Persistent** | wsl_receiver, wsl_receiver_heavy, prompt_generator, generate_image | App start → app close      |
| **Pipeline**   | windows_receiver, broadcaster, capture, midi_capture               | Start button → Stop button |

Persistent processes hold TensorFlow/Essentia models in memory and survive stop/start cycles. Pipeline processes are killed and respawned freely — they hold no persistent state.

```
WINDOWS                          WSL2
───────────────────────────────  ─────────────────────────────
capture.py ──TCP:5005──► broadcaster.py ──TCP:5006──► wsl_receiver.py
                                         ──TCP:5007──► windows_receiver.py
                                         ──TCP:5008──► wsl_receiver_heavy.py
midi_capture.py (direct, no TCP)

All analysers ──OSC:9000──► Tauri OSC listener (frontend display)
All analysers ──OSC:9100──► TouchDesigner (real-time visual parameters)
genre / mood  ──OSC:9001──► prompt_generator.py ──OSC:9002──► generate_image.py ──NDI──► TouchDesigner
Tauri         ──OSC:9099──► TouchDesigner (pipeline reset pulse)
```

---

## User Interface — React + Tauri

**Location:** `musinfo/src/`

React 19 + Vite 7 frontend inside a Tauri 2 desktop window. The UI communicates with the Rust backend via `invoke()` and receives events via `listen()`.

### Component structure

```
src/
├── App.jsx                      — root state, pipeline control, session management
├── components/
│   ├── layout/                  — Layout, Header, Sidebar, OutputPanel, TabContent
│   ├── tabs/
│   │   ├── Setup/               — instrument and device configuration
│   │   ├── Performance/         — live MIDI display and piano keyboard
│   │   └── OSCConfig/           — active OSC address display for TouchDesigner setup
│   ├── modal/
│   │   └── AddInstrumentModal   — add instrument form
│   └── shared/
│       ├── InstrumentConfig/    — audio device, channel, sample rate selectors
│       ├── AnalyserConfig/      — per-instrument analyser toggles
│       ├── AudioDevicesConfig/  — device list and reconcile status
│       ├── SignalPath/          — visual signal chain
│       ├── TestAudio/           — live RMS meter per device channel
│       └── TestMIDI/            — MIDI event monitor
└── utils/
    └── roleUtils.js             — resequences role_index values within a role bucket
                                   whenever instruments are added, renamed or removed
```

### State and mutations

`App.jsx` owns all top-level state. Every instrument mutation goes through a Tauri `invoke()` to persist to disk first, then updates React state with the returned result. `instruments.json` is always the source of truth.

### Role and index system

Each instrument has a `role` string and a `role_index` (0-based position within that role). These form the OSC address used in TouchDesigner: `/td/{analyser}/{role}/{role_index}/{param}`. `roleUtils.js` keeps indices contiguous across add, delete, rename and role-change operations.

### Tauri commands

| Command                                           | Purpose                                       |
| ------------------------------------------------- | --------------------------------------------- |
| `start_pipeline` / `stop_pipeline`                | Spawn or kill pipeline-tier processes         |
| `get_audio_devices` / `get_midi_devices`          | Return device lists (audio cached at startup) |
| `reconcile_devices`                               | Match saved device names to current hardware  |
| `save_instrument` / `delete_instrument`           | Write/remove entries in instruments.json      |
| `save_session` / `load_session` / `list_sessions` | Session file management                       |
| `test_device_audio` / `stop_device_test`          | Live RMS meter for a device channel           |
| `test_midi_input` / `stop_midi_test`              | MIDI event monitor                            |
| `save_performance_config`                         | Write forced-key settings to performance.json |
| `toggle_image_generation`                         | Enable/disable image generation via OSC       |

---

## Rust Backend — lib.rs + menu.rs

**Location:** `musinfo/src-tauri/src/`  
**Key dependencies:** `tauri`, `tauri-plugin-dialog`, `serde_json` (preserve_order), `rosc`

### Process lifecycle

`lib.rs` manages two tiers. On app startup (`setup()`), persistent processes are spawned immediately — WSL receivers via `wsl.exe -d Ubuntu`, image gen scripts as Windows Python processes. The WSL venv is activated per-launch with `source .venv/bin/activate && python3 ...`.

`start_pipeline` spawns the pipeline tier in dependency order: `windows_receiver → broadcaster → capture → midi_capture`. After all four are up, Tauri sends `/musinfo/pipeline_running 1` to ports 9001/9002, then a `/musinfo/reset` pulse to port 9099.

`stop_pipeline` tears down in reverse: kills capture first (stops audio flow), then midi_capture, writes a stop sentinel file (`backend/broadcaster.stop`) and waits 1.5s for broadcaster to flush its recording, then kills broadcaster and windows_receiver. WSL receivers stay alive.

### Other responsibilities

- **Audio device cache** — pre-warmed at startup in a background thread to avoid a 500ms Python spawn on first device query
- **OSC listener** — binds to port 9000, receives analyser data and emits it as `osc-message` events to React (used for frontend display)
- **Instrument CRUD** — `save_instrument` re-sinks `mix` to the last JSON position after every write, keeping it at the bottom of the list regardless of insertion order
- **Session management** — opens a native file dialog via `tauri-plugin-dialog`; after saving, rebuilds the native menu to populate the Load Session list

### menu.rs

Builds the native OS menu: **File** (Save Session `Ctrl+S`, Load Session submenu), **Help** and **About** (open local HTML docs). After every save, `rebuild_menu` refreshes the Load Session list.

---

## Audio Pipeline

### Environments and communication

Audio flows from the audio interface into Python on Windows, then over TCP to the analysis layer. Three receivers run in parallel — two in WSL and one on Windows — each handling different analysers based on their runtime requirements.

```
Audio interface
     │ (ASIO / WASAPI / MME)
     ▼
capture.py  ──[TCP :5005]──►  broadcaster.py
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
          windows_receiver    wsl_receiver    wsl_receiver_heavy
              [:5007]             [:5006]          [:5008]
          pitch, tempo       dynamics, timbre,   genre, mood
                             harmony, tempo_cnn,
                             pitch_crepe
```

MUSINFO supports ASIO, WASAPI, and MME host APIs. The only constraint is that all active instruments in a session must use the same host API — mixing APIs in a single capture session is not supported.

---

### capture.py

**Location:** `musinfo/backend/windows/capture.py` — Windows, pipeline tier

Reads `instruments.json` and opens one `sounddevice.InputStream` per unique audio device. Multiple channels on the same device share one stream. The audio callback fires at a block size of 2048 frames, extracts the configured channels, and pushes them into per-channel queues. Sender threads drain these queues and write framed data to broadcaster.

Device indices are resolved by name + host API string at startup, so hardware re-enumeration between sessions does not break routing.

**Frame format (capture → broadcaster):**

```
[1 byte ] channel_id (uint8)
[4 bytes] data length (uint32, big-endian)
[N bytes] raw float32 PCM
```

---

### broadcaster.py

**Location:** `musinfo/backend/windows/broadcaster.py` — Windows, pipeline tier

The routing hub. Listens on TCP :5005 for capture.py, and connects outward to all three receivers. Reads `instruments.json` + `analysers.json` to build a channel → instrument → {wsl_analysers, wsl_heavy_analysers, windows_analysers} routing table. The WSL host IP is resolved dynamically from `ip route show default`.

Config is hot-reloaded every 2 seconds (MD5 hash comparison), so instrument changes take effect without restarting the pipeline.

**Frame format (broadcaster → receivers):**

```
[4 bytes] JSON header length (uint32, big-endian)
[N bytes] JSON: { instrument, analysers, role, role_index, instrument_index }
[4 bytes] audio length (uint32, big-endian)
[N bytes] raw float32 PCM
```

**Internal mix:** When a `mix` instrument is configured, broadcaster collects chunks from all source channels into time-based queues. Once all sources have contributed a chunk (or exceeded a 150ms silence timeout), it averages the channels using numpy, resampling mismatched sample rates with `scipy.signal.resample_poly` before mixing. The mix is then routed as its own instrument.

On stop, broadcaster detects the `backend/broadcaster.stop` sentinel file written by Tauri, saves a WAV recording of all captured audio to `backend/audio_debug/`, and exits cleanly.

---

### windows_receiver.py

**Location:** `musinfo/backend/windows/windows_receiver.py` — Windows, pipeline tier  
**Port:** TCP :5007  
**Analysers:** `pitch`, `tempo`

Listens for broadcaster. On connection, initialises one analyser instance per instrument per configured analyser. Each analyser runs in a `ThreadedAnalyser` — a queue-backed worker thread that decouples the recv loop from analysis. If the queue fills, the oldest chunk is dropped to stay current. On disconnect, all worker threads are stopped and the registry cleared.

---

### wsl_receiver.py

**Location:** `musinfo/backend/wsl/wsl_receiver.py` — WSL, persistent tier  
**Port:** TCP :5006  
**Analysers:** `pitch_crepe`, `dynamics`, `timbre`, `harmony`, `tempo` (TempoCNN)

Same architecture as windows_receiver. Persistent — survives stop/start to keep Essentia models loaded. The analyser registry is cleared on each new broadcaster connection, but all Python imports and loaded models stay in memory.

Queue sizes reflect analysis cost: `harmony` = 32 (accumulates audio for chord detection), `dynamics` + `timbre` = 4, `pitch_crepe` = 2, `tempo` = 1.

---

### wsl_receiver_heavy.py

**Location:** `musinfo/backend/wsl/wsl_receiver_heavy.py` — WSL, persistent tier  
**Port:** TCP :5008  
**Analysers:** `genre`, `mood`

Dedicated process for GPU-heavy analysers. Keeping genre and mood in a separate process prevents their inference time from stalling the other analysers. Both share the GPU via `SharedEmbedder`'s lock. Queue size 1 for both — only the latest audio frame is useful for contextual classification.

---

### midi_capture.py

**Location:** `musinfo/backend/windows/midi_capture.py` — Windows, pipeline tier

Polls MIDI devices via `pygame.midi.Input` at 5ms intervals. Events (note on/off, sustain pedal, control change, pitch bend) are passed directly to a `MidiHarmonyAnalyser` instance in-process — no TCP, no WSL. Device resolution uses exact name match first, then base-name fuzzy match to survive Windows MME re-enumeration.

---

## Analysers

All analysers implement `push(audio: np.ndarray)` and maintain an internal buffer, accumulating audio until enough context is available for analysis. Results are sent over OSC after each analysis pass.

Each analyser sends to two OSC destinations:

- **Port 9000** — frontend monitoring (instrument-name-based addresses, always fixed)
- **Port 9100** (or 9001 for contextual analysers) — TouchDesigner / prompt generator (role-based addresses)

---

### Windows Analysers (`musinfo/backend/windows/analysers/`)

#### pitch_analyser.py

**Algorithm:** Aubio YIN / YinFFT  
**Processes audio in:** HOP_SIZE = 512 windows  
**Frontend (9000):** `/pitch/{name}` — note name + Hz string  
**TouchDesigner (9100):** `/td/pitch/{role}/{role_index}/hz`

Fast YIN pitch detection. Filtered to a configurable Hz range with a minimum confidence threshold. Sends on first confident detection per chunk.

#### tempo_analyser.py

**Algorithm:** Aubio beat tracker  
**Frontend (9000):** `/tempo/{name}/pulse`, `/tempo/{name}/bpm`  
**TouchDesigner (9100):** `/td/tempo/pulse` — beat pulse (1 then 0)

Beat pulse fires on every detected beat and resets on the next frame. BPM is sent once per second as the median of recent inter-beat intervals, smoothed over 8 beats.

#### midi_harmony_analyser.py

**Algorithm:** Krumhansl-Schmuckler key detection + template chord matching + Plomp-Levelt dissonance (all numpy, no Essentia)  
**Instantiated by:** `midi_capture.py` directly — does not go through windows_receiver  
**Frontend (9000):** `/harmony/{name}` (full JSON), `/harmony/{name}/frontend` (simplified subset)  
**TouchDesigner (9100):** `/td/harmony/{role}/{role_index}/key`, `scale`, `chord`, `chord_quality`, `chord_strength`, `roman_degree`, `dissonance`, `harmonic_change`, `hpcp`

Works from exact MIDI note knowledge — no spectral estimation. Builds a velocity-weighted pitch class histogram (with KS_DECAY per event) and correlates it against Krumhansl-Schmuckler major/minor profiles for 12 roots. Key changes require KS_KEY_LOCK consecutive agreements to prevent jitter. Chord detection matches a velocity-weighted HPCP vector against rotated chord templates. Dissonance is computed via the Plomp-Levelt model using fundamentals and overtones of all active notes.

Supports forced-key mode (hot-reloaded from `performance.json` every second), which bypasses KS detection and locks to the specified key and scale.

---

### WSL Analysers (`musinfo/backend/wsl/analysers/`)

#### dynamics_analyser.py

**Algorithm:** Essentia OnsetDetection + Onsets (adaptive peak-picking)  
**Frontend (9000):** `/dynamics/{name}/rms`, `onset`, `onset_strength`, `rms_at_onset`  
**TouchDesigner (9100):** `/td/dynamics/{role}/{role_index}/rms`, `onset`, `onset_strength`, `rms_at_onset`

RMS is smoothed with an EMA (α = 0.3) and scaled to a 0–100 range. Onset detection runs Essentia's `OnsetDetection` (complex domain ODF) over a 1-second rolling history, then passes the ODF to `Onsets` for adaptive thresholding and peak-picking. Onset strength is the ODF value at the detected peak; `rms_at_onset` is the peak RMS within ±4 frames. An onset flag fires for one tick, then resets to 0 on the next call.

#### timbre_analyser.py

**Algorithm:** Spectral analysis (Essentia) + HFC onset detection  
**Frontend (9000):** `/timbre/{name}/centroid`, `rolloff`, `flatness`, `flux`, `mfcc_delta`, `mfcc`, `attack`  
**TouchDesigner (9100):** `/td/timbre/{role}/{role_index}/{param}` — same set

All continuous descriptors are EMA-smoothed (α = 0.3). Rolloff uses magnitude-weighted sqrt for robustness. Attack time is measured by detecting an HFC onset, then slicing the raw audio ring buffer and running Essentia's `LogAttackTime` on the 150ms post-onset window. A debounce prevents double-fires within 80ms.

#### harmony_analyser.py

**Algorithm:** SpectralPeaks → HPCP → ChordsDetection → Key → Dissonance (Essentia), optional HPSS via librosa  
**Frontend (9000):** `/harmony/{name}` (full JSON result), `/harmony/{name}/frontend` (simplified subset)  
**TouchDesigner (9100):** `/td/harmony/{role}/{role_index}/chord`, `chord_quality`, `chord_strength`, `roman_degree`, `key`, `scale`, `dissonance`, `harmonic_change`, `hpcp`

Processes audio in 4096-sample frames with 50% overlap. SpectralPeaks filters to 40–5000 Hz before HPCP computation. Chord labels are smoothed over a 9-frame history (most-common-label). Key is detected on a 20-frame buffer and must hold for 60% of a 10-frame history window before being accepted — prevents rapid key flicker. Optional HPSS (disabled by default, `HPSS_ENABLED = False`) separates harmonic from percussive content before analysis using librosa. Supports forced-key mode (same as midi_harmony_analyser), hot-reloaded from performance.json. OSC is throttled to every 10 frames (~430ms at 48kHz).

#### pitch_crepe_analyser.py

**Algorithm:** CREPE (Essentia — crepe-medium or crepe-large model)  
**Model rate:** 16000 Hz (audio resampled before inference)  
**Frontend (9000):** `/pitch_crepe/{name}` — note name string  
**TouchDesigner (9100):** `/td/pitch/{role}/{role_index}/hz`

Processes 200ms windows at 16kHz. Per-frame results are filtered by confidence threshold (0.5) and frequency range (65–1047 Hz). The best-confidence frame is sent if it exceeds the minimum send confidence (0.6). Falls behind detection is handled by dropping old buffer content.

#### tempo_cnn_analyser.py

**Algorithm:** TempoCNN (Essentia — deepsquare-k16-3 model)  
**Model rate:** 11025 Hz (audio resampled before inference)  
**Frontend (9000):** `/tempo/{name}/bpm_accurate`, `/tempo/{name}/feel`  
**Prompt generator (9001):** `/prompt/tempo_feel`

Accumulates ~12s of 11025Hz audio before first inference. TempoCNN returns global and local BPM estimates; MUSINFO uses local estimates, filters to 30–286 BPM, and smooths over 3 predictions. Feel label (`ballad`, `slow`, `medium`, `uptempo`, `fast`) is only sent when the bucket changes. BPM sent once every 4 seconds.

#### genre_analyser.py

**Algorithm:** Discogs-EffNet embeddings → 400-class genre classifier (Essentia)  
**Model:** discogs-effnet-bs64-1  
**Frontend (9000):** `/genre/{name}` — JSON array of top-3 genre/confidence pairs  
**Prompt generator (9001):** `/prompt/genre`

Analyses 4-second windows at 16kHz with 50% hop. Predictions are mapped from 400 Discogs genres onto 14 broader style buckets (Jazz, Blues, Classical, Electronic, etc.) by string matching. GPU calls are routed through `SharedEmbedder`'s lock. Genre fires slightly offset from mood to prevent simultaneous GPU contention at startup.

#### mood_analyser.py

**Algorithm:** Discogs-EffNet embeddings → 5 binary mood classifiers + danceability + Jamendo multi-label (Essentia)  
**Models:** mood_aggressive, mood_happy, mood_sad, mood_party, mood_relaxed, danceability, mtg_jamendo_moodtheme  
**Frontend (9000):** `/mood/{name}/top`, `/mood/{name}/danceability`, `/mood/{name}/tags`  
**Prompt generator (9001):** `/prompt/mood`, `/prompt/danceability`, `/prompt/mood_tags`

Three independent audio buffers (mood, danceability, Jamendo) fire at 3-second intervals, staggered by 1-second offsets to avoid simultaneous GPU calls. Each uses `SharedEmbedder.get_embeddings()` for the shared Discogs-EffNet embedding, then passes the result to its own classifier head. `positive_class_index` is set per model — the positive class is not always at index 1 in Essentia's softmax output.

#### shared_embedder.py

**Location:** `musinfo/backend/wsl/analysers/shared_embedder.py`

Singleton that loads Discogs-EffNet once (`PartitionedCall:1` output, 1280-dim embeddings) and exposes `get_embeddings()` and `get_predictions()` under a single `_gpu_lock`. Genre and mood call into this from separate threads; the lock ensures only one GPU inference runs at a time. Loaded lazily on first use.

---

## OSC Routing

MUSINFO uses two separate OSC ports for analysis output — one for the frontend and one for TouchDesigner.

**Port 9000 — Tauri frontend (instrument-name based)**  
All analysers send their results here. Addresses are fixed and instrument-name based — they do not change based on role or session configuration. Tauri's OSC listener receives these and forwards them to React as `osc-message` events for display in the UI.

```
/pitch/{name}                    → note name + Hz string
/tempo/{name}/pulse              → beat pulse (1)
/tempo/{name}/bpm                → BPM (float)
/dynamics/{name}/rms             → 0–100 float
/dynamics/{name}/onset           → 0 or 1
/timbre/{name}/centroid          → Hz float
/timbre/{name}/rolloff           → Hz float
/timbre/{name}/flatness          → 0–1 float
/timbre/{name}/flux              → float
/timbre/{name}/mfcc_delta        → float
/harmony/{name}                  → full JSON result
/harmony/{name}/frontend         → simplified JSON subset
/genre/{name}                    → JSON array
/mood/{name}/top                 → string label
/mood/{name}/danceability        → 0–100 float
/mood/{name}/tags                → comma-separated string
```

**Port 9100 — TouchDesigner (role/role_index based)**  
All real-time visual parameters. Addresses include the instrument's `role` and `role_index`, as configured in the MUSINFO Setup tab. These are displayed in the OSC Config tab for use when setting up TouchDesigner OSC In nodes.

```
/td/pitch/{role}/{role_index}/hz
/td/tempo/pulse
/td/dynamics/{role}/{role_index}/rms
/td/dynamics/{role}/{role_index}/onset
/td/dynamics/{role}/{role_index}/onset_strength
/td/dynamics/{role}/{role_index}/rms_at_onset
/td/timbre/{role}/{role_index}/centroid
/td/timbre/{role}/{role_index}/rolloff
/td/timbre/{role}/{role_index}/flatness
/td/timbre/{role}/{role_index}/flux
/td/timbre/{role}/{role_index}/mfcc_delta
/td/timbre/{role}/{role_index}/mfcc
/td/timbre/{role}/{role_index}/attack
/td/harmony/{role}/{role_index}/chord
/td/harmony/{role}/{role_index}/chord_quality
/td/harmony/{role}/{role_index}/chord_strength
/td/harmony/{role}/{role_index}/roman_degree
/td/harmony/{role}/{role_index}/key
/td/harmony/{role}/{role_index}/scale
/td/harmony/{role}/{role_index}/dissonance
/td/harmony/{role}/{role_index}/harmonic_change
/td/harmony/{role}/{role_index}/hpcp
```

**Port 9001 — prompt_generator.py**

```
/prompt/genre                    → JSON string
/prompt/mood                     → string label
/prompt/danceability             → float
/prompt/mood_tags                → comma-separated string
/prompt/tempo_feel               → string label
/musinfo/pipeline_running        → 0 or 1 (from Tauri)
/musinfo/image_gen_enabled       → 0 or 1 (from Tauri)
```

**Port 9099 — TouchDesigner reset**  
`/musinfo/reset` — pulse (1 then 0) sent by Tauri on pipeline start and stop.

---

## Prompt and Image Generation

**Location:** `AI_image_generation/` (at the repository root, outside `musinfo/`)

### prompt_generator.py

Listens on OSC :9001. Accumulates genre, mood, tempo feel and harmony context and constructs a natural-language prompt describing the musical atmosphere. The prompt is sent to `generate_image.py` on :9002. Generation is suppressed when `pipeline_running` or `image_gen_enabled` is 0.

### generate_image.py

Listens on OSC :9002. Receives prompts and runs inference using SD Turbo locally. Generated images are sent to TouchDesigner via NDI. This process is in the persistent tier — the model is loaded at app startup so the first generation after pipeline start is fast.

---

## TouchDesigner

**File:** `touchdesigner/Harmonic_Visuals.toe`

Receives all real-time parameters on OSC :9100 and maps them to visual properties. Key architectural elements:

- One **OSC In CHOP** per active address — addresses match the role/role_index configuration from MUSINFO
- Beat pulse (:9100 `/td/tempo/pulse`) routed through Trail/Lag CHOP chain to a Transform TOP for scale pulses
- AI images arrive via **NDI In TOP**, crossfaded using Info CHOP + Logic CHOP + Trigger CHOP + Cross TOP + Cache TOP
- CHOP Execute DAT monitors active instrument count and adjusts layout
- Dedicated OSC receiver on :9099 handles `/musinfo/reset` pulses from Tauri

---

## Configuration Files

**Location:** `musinfo/backend/config/`

**instruments.json** — primary config and single source of truth. Stores all instrument definitions. All routing decisions in broadcaster.py, all receivers, and the React UI derive from this file.

**analysers.json** — defines all available analysers, their `target` receiver (`windows`, `wsl`, `wsl_heavy`, or `both`), and default enabled state. broadcaster.py reads this to split each instrument's analyser list into per-receiver sublists.

**performance.json** — forced-key configuration (`forcedKey.enabled`, `key`, `scale`), hot-reloaded every second by both harmony_analyser.py and midi_harmony_analyser.py.

---

_Architecture documented using Claude Sonnet 4.6._
