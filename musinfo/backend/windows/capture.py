# capture.py — Audio Capture + TCP Streamer (Windows side)
# Captures both Focusrite channels separately and streams to broadcaster.py
# which handles routing to WSL based on config.json

import socket
import struct
import queue
import threading
import numpy as np
import sounddevice as sd


BROADCASTER_HOST = "127.0.0.1"
BROADCASTER_PORT = 5005

SAMPLE_RATE      = 48000
CHANNELS         = 2        # Both Focusrite inputs simultaneously
CHUNK_SIZE       = 2048
DEVICE_NAME_HINT = "Focusrite"

# Must match the "channel" values in config.json
CHANNEL_MIC   = 0           # ch1 XLR  — voice
CHANNEL_PIANO = 1           # ch2 line — guitar/piano


def find_input_device(name_hint):
    if name_hint is None:
        print("[capture.py] No device hint — using system default.")
        return None

    devices   = sd.query_devices()
    host_apis = sd.query_hostapis()

    for i, d in enumerate(devices):
        if host_apis[d["hostapi"]]["name"] != "Windows WASAPI":
            continue
        if d["max_input_channels"] == 0:
            continue
        if name_hint.lower() in d["name"].lower():
            print(f"[capture.py] Found '{d['name']}' at index {i}")
            return i

    print(f"[capture.py] No device matching '{name_hint}'. Available WASAPI inputs:")
    for i, d in enumerate(devices):
        if host_apis[d["hostapi"]]["name"] == "Windows WASAPI" and d["max_input_channels"] > 0:
            print(f"  [{i}] {d['name']}")

    raise RuntimeError(f"[capture.py] No input device found matching '{name_hint}'")


def send_chunk(sock, channel_id, audio_chunk):
    """
    Frame format sent to broadcaster.py:
      [1 byte : channel_id  (uint8) ]
      [4 bytes: data length (uint32)]
      [N bytes: raw float32 PCM    ]
    """
    raw    = audio_chunk.astype(np.float32).tobytes()
    header = struct.pack(">BI", channel_id, len(raw))
    sock.sendall(header + raw)


def stream_audio(device_index):
    print(f"[capture.py] Connecting to broadcaster at {BROADCASTER_HOST}:{BROADCASTER_PORT}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((BROADCASTER_HOST, BROADCASTER_PORT))
        print("[capture.py] Connected. Streaming ch1 (mic) and ch2 (piano)...")

        ch1_queue = queue.Queue()
        ch2_queue = queue.Queue()

        def audio_callback(indata, frames, time, status):
            if status:
                print(f"[capture.py] Status: {status}")
            ch1_queue.put(indata[:, 0].copy())  # XLR mic   → CHANNEL_MIC
            ch2_queue.put(indata[:, 1].copy())  # line piano → CHANNEL_PIANO

        def send_loop(q, channel_id):
            while True:
                chunk = q.get()
                try:
                    send_chunk(s, channel_id, chunk)
                except OSError:
                    break

        threading.Thread(target=send_loop, args=(ch1_queue, CHANNEL_MIC),   daemon=True).start()
        threading.Thread(target=send_loop, args=(ch2_queue, CHANNEL_PIANO), daemon=True).start()

        with sd.InputStream(
            device=device_index,
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SIZE,
            dtype="float32",
            callback=audio_callback,
        ):
            print("[capture.py] Stream open.")
            threading.Event().wait()


if __name__ == "__main__":
    try:
        device_index = find_input_device(DEVICE_NAME_HINT)
        stream_audio(device_index)
    except ConnectionRefusedError:
        print("[capture.py] Connection refused — is broadcaster.py running?")
    except RuntimeError as e:
        print(e)
    except KeyboardInterrupt:
        print("[capture.py] Stopped.")