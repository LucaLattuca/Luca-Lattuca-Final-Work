# Claude (sonnet 4.6) used to write capture.py
# https://claude.ai/share/52e2944c-e51f-4af7-897c-736ca8b8c08e
"""
capture.py — Audio Capture + TCP Streamer (Windows side)

Captures audio from a specified input device and streams raw PCM chunks
to the WSL receiver over TCP. Runs continuously until killed by Tauri.

Protocol:
    Each chunk sent over TCP is framed as:
    [4 bytes: chunk length as uint32] + [N bytes: raw float32 PCM data]
    This lets the receiver know exactly how many bytes to read per chunk.
"""


import socket
import struct
import queue
import numpy as np
import sounddevice as sd


WSL_HOST = "172.29.28.224"
WSL_PORT     = 5006

# config for audio capture - matches the focusrite scarlett capabilities
SAMPLE_RATE = 48000
CHANNELS = 2        # Both Focusrite inputs (mic + instrument)
CHUNK_SIZE = 2048   # Samples per chunk — balances latency vs CPU


# The search term used to find the target device by name.
# Change this to match whatever device you're using:
#   "Scarlett" or "Focusrite" → Focusrite Scarlett Solo
#   "Headset"                 → a headset mic
#   "Microphone"              → default Windows mic
#   None                      → uses system default input device
DEVICE_NAME_HINT = "Focusrite"

# TODO: Make input device finder configurable from the Tauri UI, and persist it across sessions.
def find_input_device(name_hint: str | None) -> int | None:
    """
    Searches WASAPI input devices for one whose name contains name_hint.
    Returns the device index, or None to let sounddevice use the system default.

    Args:
        name_hint: Partial device name to search for (case-insensitive).
                   Pass None to use the system default input device.
    """
    if name_hint is None:
        print("[capture.py] No device hint — using system default input device.")
        return None

    devices = sd.query_devices()
    host_apis = sd.query_hostapis()

    for i, d in enumerate(devices):
        api_name = host_apis[d["hostapi"]]["name"]
        if api_name != "Windows WASAPI":
            continue
        if d["max_input_channels"] == 0:
            continue
        if name_hint.lower() in d["name"].lower():
            print(f"[capture.py] Found device matching '{name_hint}': '{d['name']}' at index {i}")
            return i

    # List available devices to help with debugging
    print(f"[capture.py] No device found matching '{name_hint}'. Available WASAPI input devices:")
    for i, d in enumerate(devices):
        api_name = host_apis[d["hostapi"]]["name"]
        if api_name == "Windows WASAPI" and d["max_input_channels"] > 0:
            print(f"  [{i}] {d['name']}")

    raise RuntimeError(
        f"[capture.py] No input device found matching '{name_hint}'. "
        f"Check the device list above and update DEVICE_NAME_HINT."
    )



def send_chunk(sock: socket.socket, audio_chunk: np.ndarray):
    """
    Sends one audio chunk over TCP using length-prefix framing.
    Converts float32 numpy array to raw bytes, prefixed with its length.
    """
    raw = audio_chunk.astype(np.float32).tobytes()
    length_prefix = struct.pack(">I", len(raw))
    sock.sendall(length_prefix + raw)


def stream_audio(device_index: int | None):
    """
    Opens a sounddevice InputStream on the given device and streams
    audio chunks to the WSL receiver over TCP.

    Args:
        device_index: WASAPI device index, or None for system default.
    """
    print(f"[capture.py] Connecting to WSL at {WSL_HOST}:{WSL_PORT} ...")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((WSL_HOST, WSL_PORT))
        print(f"[capture.py] Connected. Streaming audio ({CHANNELS}ch, {SAMPLE_RATE}Hz) ...")

        audio_queue = queue.Queue()

        def audio_callback(indata, frames, time, status):
            """
            Called by sounddevice on every chunk.
            Runs on a dedicated audio thread — never block here.
            """
            if status:
                print(f"[capture.py] Stream status: {status}")
            audio_queue.put(indata.copy())

        with sd.InputStream(
            device=device_index,
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SIZE,
            dtype="float32",
            callback=audio_callback,
        ):
            print("[capture.py] Stream open. Sending chunks to WSL...")
            while True:
                chunk = audio_queue.get()
                send_chunk(s, chunk)


if __name__ == "__main__":
    try:
        device_index = find_input_device(DEVICE_NAME_HINT)
        stream_audio(device_index)
    except ConnectionRefusedError:
        print(f"[capture.py] Connection refused — is receiver.py running on port {WSL_PORT}?")
    except RuntimeError as e:
        print(e)
    except KeyboardInterrupt:
        print("[capture.py] Stopped.")