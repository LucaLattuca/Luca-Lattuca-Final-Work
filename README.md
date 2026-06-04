# Visual Resonance — Final Work

> **Luca Lattuca, Erasmushogeschool Brussel, 2025–2026**

---

## What is Visual Resonance?

<!-- [YOUR TEXT HERE]
     Describe the concept and artistic intent of the final work.
     What does it mean for music to produce visuals in real time?
     What is the viewer's experience? -->

Visual Resonance is a real-time audiovisual installation that translates live musical performance into generative imagery and abstract motion graphics. Audio from multiple instruments is analysed simultaneously — extracting pitch, tempo, timbre, harmony, dynamics, mood and genre — and mapped to visual parameters in TouchDesigner and to AI-generated imagery via Stable Diffusion.

<!-- [YOUR TEXT HERE] — expand, rephrase, make it yours -->

---

## MUSINFO

MUSINFO is the supporting desktop application built for Visual Resonance. It manages the full audio analysis pipeline: configuring instruments and audio devices, launching all backend processes, and routing analysis data over OSC to TouchDesigner and the image generation system.

MUSINFO runs on **Windows only**. macOS is not supported due to the WSL-based analysis pipeline.

---

### Tech Stack

| Layer                       | Technology                                  |
| --------------------------- | ------------------------------------------- |
| Desktop application         | Tauri 2 (Rust)                              |
| User interface              | React 19 + Vite 7                           |
| Windows audio capture       | Python 3.13 · sounddevice                   |
| MIDI capture                | Python 3.13 · pygame.midi                   |
| Windows analysers           | Python 3.13 · Aubio                         |
| WSL analysers               | Python 3.12 · Essentia-TensorFlow · librosa |
| GPU inference               | NVIDIA GPU · CUDA via WSL2                  |
| Image generation            | SD Turbo (local)                            |
| Visual engine               | TouchDesigner                               |
| Inter-process communication | TCP sockets · OSC (python-osc)              |
| Video routing               | NDI                                         |

---

### Features

**Instrument management** — Add, configure, rename and delete instruments. Assign each instrument a role and role index, which determine its OSC address in TouchDesigner.

**Audio device support** — Supports ASIO, WASAPI, and MME host APIs. MUSINFO works with practically any audio interface or virtual device. The one limitation is that instruments on different host APIs cannot be captured in the same session — all active instruments must share the same host API.

**MIDI support** — Connect any MIDI controller via loopMIDI. MIDI harmony is analysed directly from note events, without audio capture.

**Pipeline control** — One-click start and stop for the entire pipeline. All backend processes are launched and managed automatically.

**OSC Config** — Displays all active OSC addresses for the current session, derived from the instrument configuration. Used for setting up TouchDesigner input nodes.

**Session management** — Save and load named sessions from the native OS menu (File → Save Session / Load Session).

**Performance tab** — Real-time piano keyboard display showing active MIDI notes and detected harmony.

---

### Setup

> ⚠️ MUSINFO is developed and tested on Windows 11 with an NVIDIA GPU. It does not run on macOS.

---

#### Prerequisites

- [Node.js](https://nodejs.org/) 18 or later
- [Rust](https://rustup.rs/) (stable toolchain)
- [Python 3.13](https://www.python.org/downloads/) (Windows)
- WSL2 with Ubuntu 22.04 or later — [install guide](https://learn.microsoft.com/en-us/windows/wsl/install)
- NVIDIA GPU with CUDA support (for genre, mood and TempoCNN analysers)
- [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) — for MIDI routing
- [TouchDesigner](https://derivative.ca/) (any recent build)
- [NDI Tools](https://ndi.video/tools/) — for routing generated images into TouchDesigner

---

#### Windows Python packages

```bash
pip install sounddevice python-osc numpy aubio pygame scipy
```

---

#### WSL — Python 3.12 setup

Essentia currently requires Python 3.12. Ubuntu's default Python may be a different version, so install 3.12 explicitly using the deadsnakes PPA.

```bash
# Update and add deadsnakes PPA
sudo apt update && sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update

# Install Python 3.12 with venv and dev headers
sudo apt install -y python3.12 python3.12-venv python3.12-dev

# Verify
python3.12 --version
```

Then create a virtual environment inside the WSL backend folder:

```bash
cd /mnt/c/<path-to-project>/musinfo/backend/wsl
python3.12 -m venv .venv
source .venv/bin/activate
```

Install the required packages inside the virtual environment:

```bash
pip install essentia-tensorflow numpy scipy pythonosc librosa
```

> `essentia-tensorflow` installs Essentia with TensorFlow support, which is required for the genre, mood, CREPE and TempoCNN models. This may take several minutes.

The WSL receiver scripts activate this venv automatically when launched by Tauri.

---

#### Frontend

```bash
cd musinfo
npm install
npm run tauri dev
```

---

## Music Visualisation

<!-- [YOUR TEXT HERE]
     Describe the TouchDesigner patch and what each visual parameter represents.
     Describe the AI image pipeline — prompt construction, generation rate, crossfade. -->

The visual output consists of two layers:

**TouchDesigner** receives real-time OSC data from the analysers and maps musical parameters to visual properties — dynamics to scale, pitch to vertical position, timbre to shape and texture, harmony to colour.

**AI image generation** uses a prompt constructed from genre, mood and harmonic context to generate images via SD Turbo, which are streamed into TouchDesigner via NDI and crossfaded on each new generation.

The TouchDesigner patch is located at `touchdesigner/Harmonic_Visuals.toe`.

---

## Architecture & Maintenance

For a full breakdown of the system architecture — audio pipeline, analyser internals, OSC address schema, and image generation — see [ARCHITECTURE.md](./ARCHITECTURE.md).

For information on maintaining the codebase, adding analysers, and known issues, see [MAINTENANCE.md](./MAINTENANCE.md).

---

## Usage of AI for Development

AI has been used extensively throughout the development process of MUSINFO. For transparency, all chats used during the development process are included in the documentation.

The following section contains a list of all Claude conversations (model Sonnet 4.6, used primarily) for creating and debugging components, creating the audio pipeline, creating audio analysers, debugging, refactoring and more.

Despite the extensive use of Claude AI, a great deal of effort has been made to keep the architecture consistent, as well as maintaining consistent naming conventions across the project. Since AI has a tendency to create hallucinations and apply poor naming conventions, the complexity of the code is on the higher end. Documentation and code comments have been kept consistent across all files with a uniform structure and language.

### Add instrument Modal creation + component bug fixing

- https://claude.ai/share/5c050779-83c6-4c1e-ad70-885d1f4ed813

### refactoring react components architecture

- https://claude.ai/share/b3256154-9a6d-452c-b67a-93c605eae0f2

### pitch analyser using

- https://claude.ai/share/cb1d81fc-e826-4615-b196-d0cad89bcf4a

## research on genre classification using essentia and implementing real time into a genre classifier

- https://claude.ai/share/81bc0885-13c0-4478-b940-ba370920fdd4
- https://claude.ai/share/81bc0885-13c0-4478-b940-ba370920fdd4

### Audio device selection bug fixing + device feedback

- https://claude.ai/share/4e9a0a24-b157-4a37-a8d9-6d4b5abb6006

### Audio Pipeline fix and degugging + OSC throughput

- https://claude.ai/share/acec0893-8ae6-47f0-b5ad-70d1538fdb26
- https://claude.ai/share/6641ac3b-5534-43dd-b4e5-4753671aeaa0
- https://claude.ai/share/6641ac3b-5534-43dd-b4e5-4753671aeaa0

## Essentia Mood Analyser ins WSL

- https://claude.ai/share/d19e2d4a-0844-4664-9941-c98396c9a685

## Rust native OS menu

- https://claude.ai/share/a5a8b937-1181-41b0-b1fd-183bca72ffb6

## Debug audio implementation in broadcaster

- https://claude.ai/share/c5aceabb-907d-4f81-a70a-bef9c113bb65

## audio pipeline latency testing (not merged)

- https://claude.ai/share/751523bc-0515-4642-864a-9c98a185c989

## dynamics analyser : onset, amplitude and onset strength (determines energy for individuals instruments)

- https://claude.ai/share/564582dd-b1bd-4e47-ad32-bc4b22cf2c72

## bpm and tempo analyser + refactoring

- https://claude.ai/share/183bc878-646f-4263-9c4f-073b5b1a9d3e
- https://claude.ai/share/b1bf97bf-82ce-4f63-83d4-8a5d68cfe0ab

## pipeline latency test (not merged)

- https://claude.ai/share/751523bc-0515-4642-864a-9c98a185c989

## Timbre analysis development

- https://claude.ai/share/4ac1d46d-4048-4d5d-a927-e5d261ba3472

## harmonical analysis : audio

- https://claude.ai/share/77546995-40b5-4945-98b2-369e6bd750ff

## Touchdesigner fade effect and image generator tweaking

- https://claude.ai/share/37d83ce7-5d11-4eab-9030-664a81810d43

## Prompt to image generation and OSC throughput

- https://claude.ai/share/d923d23d-8a52-45e4-a000-eedc90586121

## Refactor Internal Mix to use Time based queue + audio debug fix

- https://claude.ai/share/c54338eb-5db0-4aff-9c80-28d9a5629a87

## mix instrument configuration

- https://claude.ai/share/72596e10-6b76-45c4-8286-4f7fe230afcb

## sending data to touchdesigner over OSC and update analysers adresses

- https://claude.ai/share/9ac99f6a-96a9-4556-8d71-e53b945c2165

## Hot reload for performance tab to harmony analyser and piano keyboard component

- https://claude.ai/share/57f251b3-7211-405d-a846-187438d2727b

## Midi_harmony_analyser and debugging forced key and hot reload

- https://claude.ai/share/5af04986-82b5-4222-8e87-25096c406d18

## React switch component

- https://claude.ai/share/8ed83b97-baf1-4956-9915-28b4958c5aec

## Mix instrument on last order

- https://claude.ai/share/ee11e5c3-f953-4e45-a1a1-2045fcc10b36

## Refactor instruments and pipeline optimization and debug image generation SDTURBO errors

- https://claude.ai/share/41b242fb-aaf6-466f-bb52-5d3ea1b65629
- https://claude.ai/share/75042211-a2db-4f8f-a0e1-ed2f74422302

## reducing audio lag upon swapping to setup tab

- https://claude.ai/share/998d52d7-a0d8-4f29-82fd-1d5120c93b3e
