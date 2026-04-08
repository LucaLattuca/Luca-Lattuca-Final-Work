# WSL Receiver Script written using Claude (sonnet 4.6)
# https://claude.ai/share/52e2944c-e51f-4af7-897c-736ca8b8c08e


import socket
from pythonosc.udp_client import SimpleUDPClient

TCP_HOST = "0.0.0.0"  # Listen on all WSL network interfaces
TCP_PORT = 5006


# The Windows host IP as seen from WSL2 — this is the default gateway.
# Find it by running: ip route show | grep default | awk '{print $3}'
WINDOWS_HOST = "172.29.16.1"
OSC_PORT = 9000  # Tauri will listen for OSC on this port


def send_osc(address: str, value: str):
    """
    Sends an OSC message back to the Tauri app running on Windows.
    address: OSC address pattern e.g. "/status"
    value:   the string payload
    """
    client = SimpleUDPClient(WINDOWS_HOST, OSC_PORT)
    client.send_message(address, value)
    print(f"[receiver.py] OSC sent → {address}: '{value}' to {WINDOWS_HOST}:{OSC_PORT}")




def handle_message(message: str):
    """
    Dispatch logic for incoming control messages.
    Extend this as the pipeline grows (e.g. "stop", "set_instrument", etc.)
    """
    print(f"[receiver.py] Received message: '{message}'")

    if message == "activate":
        on_activate()
    else:
        print(f"[receiver.py] Unknown message: '{message}'")


def on_activate():
    """
    Response: Called when the 'activate' command is received.
    This is where audio processing will be triggered in later steps.
    For now, just confirms the pipeline is working end-to-end.
    """
    print("[receiver.py] Pipeline activated — rdeady to process.")
    # Send confirmation back to Tauri via OSC
    send_osc("/status", "Pipeline activated successfully bruh.")
    # TODO: start audio capture / analysis here


def start_server():
    """
    Starts a persistent TCP server that handles one connection at a time.
    Runs in a loop so it stays alive between multiple Start button presses.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # Allows restarting the script without waiting for the OS to release the port
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        server.bind((TCP_HOST, TCP_PORT))
        server.listen(1)  # Queue of 1 — one sender (capture.py) at a time

        print(f"[receiver.py] Listening on {TCP_HOST}:{TCP_PORT} ...")

        while True:
            conn, addr = server.accept()
            with conn:
                print(f"[receiver.py] Connection from {addr}")

                # Read up to 1024 bytes — enough for any control message
                data = conn.recv(1024)
                if data:
                    message = data.decode("utf-8").strip()
                    handle_message(message)


if __name__ == "__main__":
    start_server()