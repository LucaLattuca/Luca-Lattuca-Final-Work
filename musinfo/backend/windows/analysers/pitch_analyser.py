# pitch_analyser.py — Real-time Pitch Detection
# Receives audio chunks from broadcaster, detects pitch using Aubio YIN

import aubio
import numpy as np
from pythonosc import udp_client
import sys

# Configuration
HOP_SIZE          = 512    # Aubio window size
BUF_SIZE          = 2048   
SILENCE_THRESHOLD = 0.01
MIN_PITCH         = 100 
MAX_PITCH         = 1100
CONFIDENCE        = 0.6

DETECTION_MODE    = "yin" # yinfft | yin | mcomb. swap to CREPE for more accurate readings. for now yin is fine       

# OSC Configuration
OSC_HOST = "127.0.0.1"
OSC_PORT = 9000
OSC_TD_PORT = 9100


# Debugging
DEBUG = False
INFO = True

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def hz_to_note(freq):
    """Convert frequency in Hz to note name with octave"""
    midi = round(69 + 12 * np.log2(freq / 440.0))
    return f"{NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"

# TODO add median filter for inaccurate octave readings
class PitchAnalyser:
    def __init__(self, instrument_name: str, sample_rate: int, instrument_role: str = "default", role_index: int = 0, instrument_index: int = 0):
        self.instrument_role  = instrument_role
        self.role_index       = role_index
        self.instrument_index = instrument_index
        self.instrument_name = instrument_name
        self.sample_rate = sample_rate

        # Create Aubio pitch detector with the provided sample rate
        self.detector = aubio.pitch(DETECTION_MODE, BUF_SIZE, HOP_SIZE, sample_rate)
        self.detector.set_unit("Hz")
        self.detector.set_silence(-40)
        
        # Create OSC client
        self.osc_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
        self.td_client = udp_client.SimpleUDPClient("127.0.0.1", OSC_TD_PORT)

        self.last_pitch = 0.0

        if INFO :
            print(f"[pitch] Ready for '{instrument_name}' @ {sample_rate}Hz")
            sys.stdout.flush() 

    def push(self, audio):
        """
        Process incoming audio chunk and detect pitch.
        Handles chunks of any size by processing in HOP_SIZE windows.
        """
        # Check if audio is loud enough overall
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < SILENCE_THRESHOLD:
            self.td_client.send_message(f"/td/pitch/{self.instrument_role}/hz", self.last_pitch)
            return

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
            # if pitch > 0:
            if MIN_PITCH < pitch < MAX_PITCH and confidence > CONFIDENCE:
                note = hz_to_note(pitch)
                message = f"{note} ({pitch:.1f}Hz)"
                
                if DEBUG : 
                    print(f"[pitch/{self.instrument_name}] {message}")
                    sys.stdout.flush() 
                
                # Send via OSC to Tauri frontend
                self.osc_client.send_message(f"/pitch/{self.instrument_name}", message)
                
                # Send pitch to touchdesigner
                self.last_pitch = float(pitch)
                self.td_client.send_message(f"/td/pitch/{self.instrument_role}/hz", self.last_pitch)



                
                break