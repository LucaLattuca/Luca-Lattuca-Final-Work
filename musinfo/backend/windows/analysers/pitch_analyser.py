# Real-time pitch detection from a configured audio input device.
# Uses Aubio's YIN algorithm. Prints detected pitch in Hz to stdout.

# Dependencies: pip install aubio sounddevice numpy


import aubio
import sounddevice as sd
import numpy as np
import queue

# ── Configuration ──────────────────────────────────────────────────────────────

DEVICE_ID     = 41 #set to CABLE-A Output (VB-Audio Point A), Windows WDM-KS (16 in, 0 out) for testing
CHANNELS      = 4
SAMPLE_RATE   = 48000
HOP_SIZE      = 512

SILENCE_THRESHOLD = 0.01
MIN_PITCH         = 80
MAX_PITCH         = 1100
CONFIDENCE        = 0.7

# ── Pitch detector setup ───────────────────────────────────────────────────────

detector = aubio.pitch("yin", HOP_SIZE, HOP_SIZE, SAMPLE_RATE)
detector.set_unit("Hz")
detector.set_silence(-40)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

audio_queue = queue.Queue()

def hz_to_note(freq):
    midi = round(69 + 12 * np.log2(freq / 440.0))
    return f"{NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"

def input_callback(indata, frames, time, status):
    # grab ch1+2 for analysis
    samples = indata[:, 0:2].mean(axis=1).astype(np.float32)

    # send stereo ch1+2 to playback queue
    audio_queue.put(indata[:, 0:2].copy())

    # no analysis if audio lower than silence threshold
    if np.sqrt(np.mean(samples ** 2)) < SILENCE_THRESHOLD:
        return

    pitch      = detector(samples)[0]
    confidence = detector.get_confidence()

    # only print output if within human singing range, and above YIN's confidence score 
    if MIN_PITCH < pitch < MAX_PITCH and confidence > CONFIDENCE:
        print(hz_to_note(pitch))


with sd.InputStream(device=DEVICE_ID, channels=CHANNELS, samplerate=SAMPLE_RATE,
                    blocksize=HOP_SIZE, dtype="float32", callback=input_callback):
    print(f"Listening on device {DEVICE_ID} — Ctrl+C to stop")
    try:
        while True:
            sd.sleep(100)
    except KeyboardInterrupt:
        print("\nStopped.")