# WSL Receiver Script written using Claude (sonnet 4.6)
# https://claude.ai/share/52e2944c-e51f-4af7-897c-736ca8b8c08e


import socket
import struct
import numpy as np
from pythonosc.udp_client import SimpleUDPClient


TCP_HOST = "0.0.0.0"  # Listen on all WSL network interfaces
TCP_PORT = 5006


# The Windows host IP as seen from WSL2 — this is the default gateway.
# Find it by running: ip route show | grep default | awk '{print $3}'
WINDOWS_HOST = "172.29.16.1"
OSC_PORT = 9000  # Tauri will listen for OSC on this port


CHANNELS = 2
SAMPLE_RATE = 48000

def send_osc(address: str, value):
    client = SimpleUDPClient(WINDOWS_HOST, OSC_PORT)
    client.send_message(address, value)


def recv_exact(conn: socket.socket, n: int) -> bytes:
    """
    Reads exactly n bytes from the socket.
    TCP can split data across multiple recv() calls, so we loop until we have it all.
    """
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed by sender")
        buf += chunk
    return buf


def handle_audio_chunk(raw: bytes):
    """
    Converts raw bytes back into a float32 numpy array and processes it.
    Shape will be (CHUNK_SIZE, CHANNELS).
    """
    audio = np.frombuffer(raw, dtype=np.float32).reshape(-1, CHANNELS)

    # RMS level per channel — confirms audio is flowing
    rms_ch1 = float(np.sqrt(np.mean(audio[:, 0] ** 2)))
    rms_ch2 = float(np.sqrt(np.mean(audio[:, 1] ** 2)))

    print(f"[receiver.py] Ch1 RMS: {rms_ch1:.4f} | Ch2 RMS: {rms_ch2:.4f}")

    # Send RMS back to OutputPanel via OSC
    send_osc("/audio/rms/ch1", rms_ch1)
    send_osc("/audio/rms/ch2", rms_ch2)

    # TODO: plug Essentia analysis in here




def start_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((TCP_HOST, TCP_PORT))
        server.listen(1)

        print(f"[receiver.py] Listening on {TCP_HOST}:{TCP_PORT} ...")

        while True:
            conn, addr = server.accept()
            print(f"[receiver.py] Connection from {addr} — streaming started")

            with conn:
                try:
                    while True:
                        # Read the 4-byte length prefix first
                        header = recv_exact(conn, 4)
                        chunk_len = struct.unpack(">I", header)[0]

                        # Then read exactly that many bytes of audio
                        raw = recv_exact(conn, chunk_len)
                        handle_audio_chunk(raw)

                except ConnectionError:
                    print("[receiver.py] Stream ended — waiting for next connection.")


if __name__ == "__main__":
    start_server()