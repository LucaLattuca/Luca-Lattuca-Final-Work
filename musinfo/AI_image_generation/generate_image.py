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
import time
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



# ── Prompt store ───────────────────────────────────────────────────────────────
_prompt_lock      = threading.Lock()
_pending_positive = None
_pending_negative = None
_new_prompt_event = threading.Event()




# ── OSC handlers ───────────────────────────────────────────────────────────────
def _on_positive_prompt(address, *args):
    global _pending_positive
    value = str(args[0]) if args else ""
    if not value:
        return
    with _prompt_lock:
        _pending_positive = value
    _new_prompt_event.set()
    print(f"[gen_image] positive prompt received ({len(value)} chars)", flush=True)

def _on_negative_prompt(address, *args):
    global _pending_negative
    value = str(args[0]) if args else ""
    if not value:
        return
    with _prompt_lock:
        _pending_negative = value
    print(f"[gen_image] negative prompt received ({len(value)} chars)", flush=True)



# ── Generation loop ────────────────────────────────────────────────────────────
def _generation_loop(pipe):
    while True:
        _new_prompt_event.wait()
        _new_prompt_event.clear()

        with _prompt_lock:
            positive = _pending_positive
            negative = _pending_negative or ""

        if not positive:
            continue

        print(f"[gen_image] Generating... ({_width}×{_height}, {NUM_INFERENCE_STEPS} step)", flush=True)
        t0 = time.time()

        try:
            result = pipe(
                prompt              = positive,
                negative_prompt     = negative,
                width               = _width,
                height              = _height,
                num_inference_steps = NUM_INFERENCE_STEPS,
                guidance_scale      = GUIDANCE_SCALE,
            )
            image   = result.images[0]
            elapsed = time.time() - t0
            print(f"[gen_image] Done in {elapsed:.2f}s", flush=True)

        except Exception as e:
            print(f"[gen_image] Generation error: {e}", flush=True)

# ── Main ───────────────────────────────────────────────────────────────────────
_pipe = _load_pipeline()

gen_thread = threading.Thread(target=_generation_loop, args=(_pipe,), daemon=True)
gen_thread.start()

d = dispatcher.Dispatcher()
d.map("/image/prompt/positive", _on_positive_prompt)
d.map("/image/prompt/negative", _on_negative_prompt)

server = osc_server.ThreadingOSCUDPServer((LISTEN_HOST, LISTEN_PORT), d)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()

print(f"[gen_image] OSC server listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)

server_thread.join()