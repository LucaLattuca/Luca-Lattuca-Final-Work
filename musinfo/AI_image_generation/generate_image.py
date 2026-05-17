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
import torch
from diffusers import AutoPipelineForText2Image

# ── OSC config ─────────────────────────────────────────────────────────────────
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9002


# ── Generation config ──────────────────────────────────────────────────────────
# Change RESOLUTION to switch between speed and quality.
# "512" targets ~2s per frame on RTX 4060
# "768" targets ~4s per frame
RESOLUTION = "512"

RESOLUTION_MAP = {
    "512":  (512, 512),
    "768":  (768, 768),
    "1024": (1024, 768),
}

NUM_INFERENCE_STEPS = 1   # 1–4 for SDXL Turbo; 1 = fastest
GUIDANCE_SCALE      = 0.0  # CFG-free for Turbo

_width, _height = RESOLUTION_MAP.get(RESOLUTION, (512, 512))


# ── Pipeline ───────────────────────────────────────────────────────────────────
def _load_pipeline():
    print("[gen_image] Loading SDXL Turbo pipeline...", flush=True)
    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sdxl-turbo",
        torch_dtype=torch.float16,
        variant="fp16",
    )
    pipe = pipe.to("cuda")
    pipe.enable_attention_slicing()
    print(f"[gen_image] Pipeline ready — {_width}×{_height} @ {NUM_INFERENCE_STEPS} step(s)", flush=True)
    return pipe


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
_pipe = _load_pipeline()

d = dispatcher.Dispatcher()
d.map("/image/prompt/positive", _on_positive_prompt)
d.map("/image/prompt/negative", _on_negative_prompt)

server = osc_server.ThreadingOSCUDPServer((LISTEN_HOST, LISTEN_PORT), d)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()

print(f"[gen_image] OSC server listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)

server_thread.join()