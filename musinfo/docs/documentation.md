# Documentation

## Context

### Harmonic Visuals

MUSINFO is built around a simple idea: music contains information that is usually invisible. Pitch, timbre, rhythm, genre — these qualities shape how we experience sound, yet they exist as abstract patterns in the air. Harmonic Visuals is the artistic framework behind this project. It asks the question: what if those patterns had a physical presence?

By extracting musical information in real time and routing it to a generative visual system (TouchDesigner), MUSINFO creates a direct bridge between what a performer plays and what an audience sees. The visuals are not pre-programmed animations — they are a translation of the music, moment by moment.

---

## MUSINFO

### What it does

MUSINFO is a desktop application that listens to live instrument input, analyses the audio using machine learning models, and sends structured musical data to TouchDesigner via OSC (Open Sound Control). It runs on Windows, with some analysis happening inside a WSL (Windows Subsystem for Linux) environment where the ML models operate.

The analysis pipeline works as follows:

1. Audio is captured from your audio interface
2. The signal is broadcast simultaneously to two receivers — one on Windows, one in WSL
3. Each receiver runs its own set of analysers (pitch, genre, etc.)
4. Results are sent back to the app via OSC
5. The app forwards relevant data to TouchDesigner

MUSINFO is designed for live performance. Configuration is done before the performance, and once the pipeline is running, everything is automatic.

---

## Setup

### Adding an Instrument

An instrument in MUSINFO represents a single audio source — a piano, a guitar, a microphone. Each instrument has its own audio input channel and its own set of analysis models.

To add an instrument:

1. Open the **Instruments** panel
2. Click **Add Instrument**
3. Give it a name (e.g. "Guitar", "Piano")
4. Select its audio device and channel (see Audio Devices below)
5. Optionally assign a MIDI device for additional input
6. Save the instrument

Your instruments are stored in `backend/config/instruments.json`. You can save and load complete configurations using **File → Save Session** and **File → Load Session**.

### Choosing a Device

When selecting an audio device for an instrument, you will see a list of available inputs filtered by type:

- **Real devices** show all available input channels
- **Virtual devices** (VB-Cable, Voicemeeter) are limited to 4 channels in the list

Each entry shows the device name, channel number, host API, sample rate, and latency. Choose the entry that matches your physical input.

If you are routing multiple instruments through a virtual cable (e.g. VB-Cable A from Reaper), select the appropriate channel for each instrument. Guitar on channels 3/4, for example, if that is how you have configured your Reaper routing.

After selecting a device, use the **Test** button to verify the input is receiving signal. The level meter will show real-time RMS amplitude.

---

## Audio Devices

### Terminology

**Host API** — The audio driver system Windows uses to talk to your hardware. MUSINFO supports four:

- **WASAPI** — Windows Audio Session API. The modern default. Low latency, works with most devices. Recommended for your audio interface.
- **WDM-KS** — Kernel Streaming. Lower level than WASAPI. Used by virtual cables (VB-Cable).
- **ASIO** — Professional audio driver standard. Lowest latency, but uses exclusive access to the device — only one application can use it at a time. Use with caution if you need to share the device between applications.
- **MME** — Legacy Windows multimedia API. High latency. Generally avoid unless nothing else works.

**Device Index** — A number Windows assigns to each audio device at runtime. This number can change when you restart your computer or plug/unplug devices. MUSINFO stores devices by name and channel instead, and uses **reconcile** to resolve the current index on startup.

**Channel** — A single audio stream within a device. A stereo device has channels 0 and 1. A 16-channel virtual cable has channels 0 through 15. Channels are zero-indexed.

**Sample Rate** — How many audio samples per second the device captures. Your Focusrite Scarlett Solo defaults to 48000 Hz (48kHz). Some analysers internally resample to a different rate (the genre analyser resamples to 16kHz for the ML model).

**Latency** — The delay between sound entering the device and the application receiving it. Lower is better for live performance. Displayed in milliseconds.

**Virtual Audio Device** — A software-only audio device that acts as a cable between applications. VB-Cable A (the 16-channel WDM-KS variant) is used in the MUSINFO setup to route multiple instruments from Reaper into separate channels for analysis.
