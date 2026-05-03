# broadcaster.py Audio Router 
# Reads instruments.json and analysers.json to route per-channel audio from capture.py
# to either WSL receiver or Windows analysers based on each analyser's target.


import socket
import struct
import json
import threading
import os
import time

LOCAL_HOST      = "127.0.0.1"
LOCAL_PORT      = 5005

WSL_HOST        = "172.29.28.224"
WSL_PORT        = 5006

WINDOWS_HOST = "127.0.0.1"
WINDOWS_PORT = 5007


CONFIG_POLL_INTERVAL = 2.0 


# Loads both config files and returns them merged into one dict.
def load_config():
    base_dir         = os.path.dirname(os.path.dirname(__file__))
    instruments_path = os.path.join(base_dir, "config", "instruments.json")
    analysers_path      = os.path.join(base_dir, "config", "analysers.json")


    try:
        with open(instruments_path) as f:
            instruments = json.load(f)
        with open(analysers_path) as f:
            analysers = json.load(f)
        print(f"[broadcaster] Config loaded.")
        return {
            "instruments": instruments.get("instruments", {}),
            "analysers":      analysers.get("analysers", {})
        }
    except FileNotFoundError as e:
        print(f"[broadcaster] Config file not found: {e} — no instruments active")
        return {"instruments": {}, "analysers": {}}
    except json.JSONDecodeError as e:
        print(f"[broadcaster] Config malformed: {e} — no instruments active")
        return {"instruments": {}, "analysers": {}}


# builds a lookup table mapping channel_id → instrument name and analysers split by target
# so broadcaster can instantly look up routing info for each incoming chunk
def build_channel_map(config):
    channel_map  = {}
    analysers_config = config.get("analysers", {})

    for name, instrument in config.get("instruments", {}).items():
        if not instrument.get("enabled", False):
            continue
        channel_id = instrument.get("channel")
        if channel_id is None:
            continue

        active_analysers = instrument.get("analysers", [])

        channel_map[channel_id] = {
            "name":            name,
            "wsl_analysers":     [m for m in active_analysers if analysers_config.get(m, {}).get("target") == "wsl"],
            "windows_analysers": [m for m in active_analysers if analysers_config.get(m, {}).get("target") == "windows"],
        }
        print(f"[broadcaster] Channel {channel_id} → '{name}' | wsl: {channel_map[channel_id]['wsl_analysers']} | windows: {channel_map[channel_id]['windows_analysers']}")

    return channel_map

# opens TCP connection to WSL receiver, retries until ready
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


# opens TCP connection to Windows receiver, retries until ready
def connect_to_windows():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((WINDOWS_HOST, WINDOWS_PORT))
            print(f"[broadcaster] Connected to Windows receiver at {WINDOWS_HOST}:{WINDOWS_PORT}")
            return s
        except ConnectionRefusedError:
            print(f"[broadcaster] Windows receiver not ready — retrying in 2s")
            time.sleep(2)


# reads exactly n bytes from a socket, looping until complete since TCP may deliver bytes in pieces
def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


# packs instrument name + analysers list + raw PCM into a framed TCP message and sends to a receiver
def send_framed_chunk(sock, instrument_name, analysers, audio_bytes):
    """
    Frame format:
      [4 bytes: header length  (uint32 big-endian)]
      [N bytes: header JSON                       ]
      [4 bytes: audio length   (uint32 big-endian)]
      [K bytes: raw float32 PCM                   ] (Pulse Code Modulation : uncompressed raw audio data)
      
    """
    header = json.dumps({
        "instrument": instrument_name,
        "analysers":     analysers,
    }).encode("utf-8")

    frame = (
        struct.pack(">I", len(header)) +
        header +
        struct.pack(">I", len(audio_bytes)) +
        audio_bytes
    )
    sock.sendall(frame)

# reads chunks from capture.py, looks up instrument routing, forwards to receivers
def handle_capture_connection(conn, config_holder):
    print("[broadcaster] capture.py connected.")
    wsl_sock = connect_to_wsl()
    windows_sock = connect_to_windows()

    # TODO include device name with channel in order to tell differen channels on various audio devices apart 

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

            # route to Windows receiver
            if instrument_info["windows_analysers"]:
                try:
                    send_framed_chunk(windows_sock, instrument_info["name"], instrument_info["windows_analysers"], audio_bytes)
                except OSError:
                    print("[broadcaster] Lost Windows connection — reconnecting")
                    windows_sock = connect_to_windows()

            # route to WSL receiver
            if instrument_info["wsl_analysers"]:
                try:
                    send_framed_chunk(wsl_sock, instrument_info["name"], instrument_info["wsl_analysers"], audio_bytes)
                except OSError:
                    print("[broadcaster] Lost WSL connection — reconnecting")
                    wsl_sock = connect_to_wsl()

    finally:
        print("[broadcaster] capture.py disconnected.")
        wsl_sock.close()
        windows_sock.close()
        conn.close()


# reloads config files every CONFIG_POLL_INTERVAL seconds so changes take effect without restarting
def watch_config(config_holder):
    while True:
        time.sleep(CONFIG_POLL_INTERVAL)
        config_holder["config"] = load_config()
        print("[broadcaster] Config refreshed.")
        


# opens TCP server and accepts incoming capture.py connections
def start_server(config_holder):
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


def main():
    config_holder = {"config": load_config()}
    threading.Thread(target=watch_config, args=(config_holder,), daemon=True).start()
    start_server(config_holder)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[broadcaster] Stopped.")