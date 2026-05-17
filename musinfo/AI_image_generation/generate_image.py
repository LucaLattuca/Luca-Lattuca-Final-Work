"""
generate_image.py
Windows side — AI_image_generation/

Launched by Rust/Tauri as a managed process.

Listens on port 9002 for prompts from prompt_generator.py:
  /image/prompt/positive   str   positive prompt
  /image/prompt/negative   str   negative prompt
"""

import sys
import threading
from pythonosc import dispatcher, osc_server, udp_client

# ── OSC config ─────────────────────────────────────────────────────────────────
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9002


# ── OSC handlers ───────────────────────────────────────────────────────────────
def _on_positive_prompt(address, *args):
    value = str(args[0]) if args else ""
    if not value:
        return
    print(f"[gen_image] positive prompt received ({len(value)} chars)", flush=True)

def _on_negative_prompt(address, *args):
    value = str(args[0]) if args else ""
    if not value:
        return
    print(f"[gen_image] negative prompt received ({len(value)} chars)", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────────
d = dispatcher.Dispatcher()
d.map("/image/prompt/positive", _on_positive_prompt)
d.map("/image/prompt/negative", _on_negative_prompt)

server = osc_server.ThreadingOSCUDPServer((LISTEN_HOST, LISTEN_PORT), d)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()

print(f"[gen_image] OSC server listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)

server_thread.join()