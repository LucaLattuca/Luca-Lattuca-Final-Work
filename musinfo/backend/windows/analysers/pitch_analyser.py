# pitch_analyser.py — Real-time Pitch Detection
# Receives audio chunks from broadcaster, detects pitch using Aubio YIN

import aubio
import numpy as np
from pythonosc import udp_client
import sys

# Configuration
SAMPLE_RATE       = 48000  # From broadcaster
HOP_SIZE          = 512    # Aubio window size
SILENCE_THRESHOLD = 0.01
MIN_PITCH         = 80
MAX_PITCH         = 1100
CONFIDENCE        = 0.7

# OSC Configuration
OSC_HOST = "127.0.0.1"
OSC_PORT = 9000

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def hz_to_note(freq):
    """Convert frequency in Hz to note name with octave"""
    midi = round(69 + 12 * np.log2(freq / 440.0))
    return f"{NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"


class PitchAnalyser:
    def __init__(self, instrument_name="unknown"):
        self.instrument_name = instrument_name
        
        # Create Aubio pitch detector
        self.detector = aubio.pitch("yin", HOP_SIZE, HOP_SIZE, SAMPLE_RATE)
        self.detector.set_unit("Hz")
        self.detector.set_silence(-40)
        
        # Create OSC client
        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        
        print(f"[pitch] Ready for '{instrument_name}'")
        sys.stdout.flush() 

    def push(self, audio):
        """
        Process incoming audio chunk and detect pitch.
        Handles chunks of any size by processing in HOP_SIZE windows.
        """
        # Check if audio is loud enough overall
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < SILENCE_THRESHOLD:
            return  # Too quiet, skip analysis

        # Process audio in HOP_SIZE chunks
        for i in range(0, len(audio), HOP_SIZE):
            window = audio[i:i + HOP_SIZE]
            
            # Skip if window is too small
            if len(window) < HOP_SIZE:
                continue
            
            # Detect pitch for this window
            pitch = self.detector(window)[0]
            confidence = self.detector.get_confidence()

            # Only output if within human singing range and confident
            if MIN_PITCH < pitch < MAX_PITCH and confidence > CONFIDENCE:
                note = hz_to_note(pitch)
                message = f"{note} ({pitch:.1f}Hz)"
                
                print(f"[pitch/{self.instrument_name}] {message}")
                sys.stdout.flush() 
                
                # Send via OSC to Tauri frontend
                self.osc_client.send_message(f"/pitch/{self.instrument_name}", message)
                
                # Only send one detection per chunk to avoid spam
                break