# broadcaster.py — Audio Router (Windows side)
# Reads instruments.json and models.json to route per-channel audio from capture.py
# to either WSL receiver or Windows analysers based on each model's target.

# Receives framed per-channel audio from capture.py and forwards to WSL receiver
# with instrument metadata prepended to each chunk.

import socket
import struct
import json
import threading
import os
import time

LOCAL_HOST      = "127.0.0.1"
LOCAL_PORT      = 5005

WSL_HOST        = "172.29.28.224"   # update to your WSL IP
WSL_PORT        = 5006

BASE_DIR         = os.path.dirname(os.path.dirname(__file__))
INSTRUMENTS_PATH = os.path.join(BASE_DIR, "config", "instruments.json")
MODELS_PATH      = os.path.join(BASE_DIR, "config", "models.json")

CONFIG_POLL_INTERVAL = 2.0


# Loads both config files and returns them merged into one dict.
def load_config():
    try:
        with open(INSTRUMENTS_PATH) as f:
            instruments = json.load(f)
        with open(MODELS_PATH) as f:
            models = json.load(f)
        print(f"[broadcaster] Config loaded.")
        return {
            "instruments": instruments.get("instruments", {}),
            "models":      models.get("models", {})
        }
    except FileNotFoundError as e:
        print(f"[broadcaster] Config file not found: {e} — no instruments active")
        return {"instruments": {}, "models": {}}
    except json.JSONDecodeError as e:
        print(f"[broadcaster] Config malformed: {e} — no instruments active")
        return {"instruments": {}, "models": {}}


# Builds a dict mapping channel_id → instrument info with models split by target.
def build_channel_map(config):
    channel_map  = {}
    models_config = config.get("models", {})

    for name, instrument in config.get("instruments", {}).items():
        if not instrument.get("enabled", False):
            continue
        channel_id = instrument.get("channel")
        if channel_id is None:
            continue

        active_models = instrument.get("models", [])

        channel_map[channel_id] = {
            "name":            name,
            "wsl_models":     [m for m in active_models if models_config.get(m, {}).get("target") == "wsl"],
            "windows_models": [m for m in active_models if models_config.get(m, {}).get("target") == "windows"],
        }
        print(f"[broadcaster] Channel {channel_id} → '{name}' | wsl: {channel_map[channel_id]['wsl_models']} | windows: {channel_map[channel_id]['windows_models']}")

    return channel_map


def connect_to_wsl():
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
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


# Sends a framed chunk to the WSL receiver with instrument name and models list.
def send_framed_chunk(wsl_sock, instrument_name, wsl_models, audio_bytes):
    """
    Frame format:
      [4 bytes: header length  (uint32 big-endian)]
      [N bytes: header JSON                        ]
      [4 bytes: audio length   (uint32 big-endian)]
      [K bytes: raw float32 PCM                   ]
    """
    header = json.dumps({
        "instrument": instrument_name,
        "models":     wsl_models,
    }).encode("utf-8")

    frame = (
        struct.pack(">I", len(header)) +
        header +
        struct.pack(">I", len(audio_bytes)) +
        audio_bytes
    )
    wsl_sock.sendall(frame)


def handle_capture_connection(conn, config_holder):
    print("[broadcaster] capture.py connected.")
    wsl_sock = connect_to_wsl()

    try:
        while True:
            header = recv_exact(conn, 5)
            if header is None:
                break

            channel_id, data_len = struct.unpack(">BI", header)
            audio_bytes = recv_exact(conn, data_len)
            if audio_bytes is None:
                break

            channel_map   = build_channel_map(config_holder["config"])
            instrument_info = channel_map.get(channel_id)

            if instrument_info is None:
                continue

            # Route to Windows analysers directly
            if instrument_info["windows_models"]:
                # TODO: call windows analysers here
                pass

            # Route to WSL receiver
            if instrument_info["wsl_models"]:
                try:
                    send_framed_chunk(wsl_sock, instrument_info["name"], instrument_info["wsl_models"], audio_bytes)
                except OSError:
                    print("[broadcaster] Lost WSL connection — reconnecting")
                    wsl_sock = connect_to_wsl()

    finally:
        print("[broadcaster] capture.py disconnected.")
        wsl_sock.close()
        conn.close()


def config_poll_loop(config_holder):
    while True:
        time.sleep(CONFIG_POLL_INTERVAL)
        config_holder["config"] = load_config()
        print("[broadcaster] Config refreshed.")


def main():
    config_holder = {"config": load_config()}

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