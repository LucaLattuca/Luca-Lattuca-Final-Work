# broadcaster.py — Audio Router (Windows side)
# Reads config.json to map Focusrite channels to instruments and their models.
# Receives framed per-channel audio from capture.py and forwards to WSL receiver
# with instrument metadata prepended to each chunk.

import socket
import struct
import json
import threading
import os
import time

LOCAL_HOST      = "127.0.0.1"
LOCAL_PORT      = 5005          # capture.py connects here

WSL_HOST        = "172.29.28.224"   # update to your WSL IP
WSL_PORT        = 5006              # single receiver handles all instruments

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
CONFIG_POLL_INTERVAL = 2.0          # seconds between config reload checks


def load_config():
    """
    Reads config.json. Returns the parsed dict, or a safe empty default.
    Called once at startup and re-checked every CONFIG_POLL_INTERVAL seconds.
    """
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
            print(f"[broadcaster] Config loaded from {CONFIG_PATH}")
            return config
    except FileNotFoundError:
        print(f"[broadcaster] config.json not found at {CONFIG_PATH} — no instruments active")
        return {"instruments": {}}
    except json.JSONDecodeError as e:
        print(f"[broadcaster] config.json is malformed: {e} — no instruments active")
        return {"instruments": {}}


def build_channel_map(config):
    """
    Builds a dict mapping channel_id (int) → instrument info dict.
    Only includes instruments where enabled == true.

    Example output:
      {
        0: {"name": "voice", "models": {"pitch": True, "genre": False}},
        1: {"name": "guitar", "models": {"pitch": False, "genre": True}},
      }
    """
    channel_map = {}
    for name, instrument in config.get("instruments", {}).items():
        if not instrument.get("enabled", False):
            print(f"[broadcaster] Skipping '{name}' (disabled)")
            continue
        channel_id = instrument.get("channel")
        if channel_id is None:
            print(f"[broadcaster] Skipping '{name}' (no channel defined)")
            continue
        channel_map[channel_id] = {
            "name":   name,
            "models": instrument.get("models", {}),
        }
        print(f"[broadcaster] Channel {channel_id} → '{name}' | models: {instrument.get('models', {})}")
    return channel_map


def connect_to_wsl():
    """Opens a TCP connection to the WSL receiver. Retries until it succeeds."""
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((WSL_HOST, WSL_PORT))
            print(f"[broadcaster] Connected to WSL receiver at {WSL_HOST}:{WSL_PORT}")
            return s
        except ConnectionRefusedError:
            print(f"[broadcaster] WSL receiver not ready — retrying in 2s")
            time.sleep(2)


def recv_exact(sock, n):
    """Reads exactly n bytes from a socket. Returns None if connection closes."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def send_framed_chunk(wsl_sock, instrument_info, audio_bytes):
    """
    Sends one chunk to the WSL receiver with this frame format:
      [4 bytes: header length  (uint32 big-endian)]
      [N bytes: header JSON                        ]
      [4 bytes: audio length   (uint32 big-endian)]
      [K bytes: raw float32 PCM                   ]

    The header JSON carries instrument name and active models so the
    receiver knows what it's getting without any extra config files.
    """
    header = json.dumps({
        "instrument": instrument_info["name"],
        "models":     instrument_info["models"],
    }).encode("utf-8")

    frame = (
        struct.pack(">I", len(header)) +
        header +
        struct.pack(">I", len(audio_bytes)) +
        audio_bytes
    )
    wsl_sock.sendall(frame)


def handle_capture_connection(conn, config_holder):
    """
    Handles one capture.py connection.
    Reads per-channel framed audio, looks up the instrument from config,
    and forwards to WSL with instrument metadata.

    config_holder is a mutable dict with key "config" so the polling
    thread can swap in a fresh config without restarting this function.
    """
    print("[broadcaster] capture.py connected.")
    wsl_sock = connect_to_wsl()

    try:
        while True:
            # Frame from capture.py:
            #   [1 byte: channel_id][4 bytes: data length][N bytes: PCM]
            header = recv_exact(conn, 5)
            if header is None:
                break

            channel_id, data_len = struct.unpack(">BI", header)
            audio_bytes = recv_exact(conn, data_len)
            if audio_bytes is None:
                break

            # Rebuild channel map from latest config on every chunk
            # (cheap — it's just dict iteration, not a file read)
            channel_map = build_channel_map(config_holder["config"])
            instrument_info = channel_map.get(channel_id)

            if instrument_info is None:
                # This channel isn't mapped to any enabled instrument — drop it
                continue

            try:
                send_framed_chunk(wsl_sock, instrument_info, audio_bytes)
            except OSError:
                print("[broadcaster] Lost WSL connection — reconnecting")
                wsl_sock = connect_to_wsl()

    finally:
        print("[broadcaster] capture.py disconnected.")
        wsl_sock.close()
        conn.close()


def config_poll_loop(config_holder):
    """
    Runs in a background thread.
    Every CONFIG_POLL_INTERVAL seconds, reloads config.json and updates
    config_holder["config"] in place so handle_capture_connection
    picks up changes without restarting.
    """
    while True:
        time.sleep(CONFIG_POLL_INTERVAL)
        fresh = load_config()
        config_holder["config"] = fresh
        print("[broadcaster] Config refreshed.")


def main():
    config_holder = {"config": load_config()}

    # Start the config polling thread
    threading.Thread(target=config_poll_loop, args=(config_holder,), daemon=True).start()

    print(f"[broadcaster] Listening for capture.py on {LOCAL_HOST}:{LOCAL_PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((LOCAL_HOST, LOCAL_PORT))
        server.listen(1)

        while True:
            conn, addr = server.accept()
            threading.Thread(
                target=handle_capture_connection,
                args=(conn, config_holder),
                daemon=True,
            ).start()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[broadcaster] Stopped.")