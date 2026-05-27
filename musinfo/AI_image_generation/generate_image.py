"""
generate_image.py
Windows side — AI_image_generation/

Launched by Rust/Tauri as a managed process.

Listens on port 9002 for prompts from prompt_generator.py:
  /image/prompt/positive   str   positive prompt
  /image/prompt/negative   str   negative prompt

Sends to TouchDesigner on port 9000:
  /musinfo/image_change    1.0   fired after every new NDI frame
"""

import sys
import threading
import time
from pythonosc import dispatcher, osc_server, udp_client
import torch
from diffusers import AutoPipelineForText2Image


# pipeline state — set by Tauri when start/stop_pipeline fires
_pipeline_running = False
_pipeline_lock    = threading.Lock()

# ── OSC config ─────────────────────────────────────────────────────────────────
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9002

# TouchDesigner OSC target — change TD_HOST to the TD machine's IP if on another PC
TD_HOST     = "127.0.0.1"
TD_PORT     = 9099
_td_client  = udp_client.SimpleUDPClient(TD_HOST, TD_PORT)


# ── Generation config ──────────────────────────────────────────────────────────
# Change RESOLUTION to switch between speed and quality.
# "512" targets ~2s per frame on RTX 4060
# "768" targets ~4s per frame
# "1024" 
RESOLUTION_MAP = {
    "512":  (512, 512),
    "768":  (768, 768),
    "1024": (1024, 768),
    "wide": (1280, 720),   # 720p widescreen
    "1080": (1920, 1080), # need touchdesigner license
}

RESOLUTION = "wide"

NUM_INFERENCE_STEPS = 1   # 1–4 for SDXL Turbo; 1 = fastest
GUIDANCE_SCALE      = 0.0  # CFG-free for Turbo

_width, _height = RESOLUTION_MAP.get(RESOLUTION)


# Pipeline Handler
def _on_pipeline_running(address, *args):
    global _pipeline_running
    value = int(args[0]) if args else 0
    with _pipeline_lock:
        _pipeline_running = bool(value)
    state = "RUNNING" if _pipeline_running else "STOPPED"
    print(f"[gen_image] pipeline {state}", flush=True)


# ── NDI output ─────────────────────────────────────────────────────────────────
NDI_SOURCE_NAME = "MUSINFO_Background"
_ndi_send = None

def _init_ndi():
    global _ndi_send
    import NDIlib as ndi
    if not ndi.initialize():
        print("[gen_image] NDI init failed — is the runtime installed?", flush=True)
        return
    send_settings            = ndi.SendCreate()
    send_settings.ndi_name = NDI_SOURCE_NAME
    _ndi_send                = ndi.send_create(send_settings)
    print(f"[gen_image] NDI sender ready — '{NDI_SOURCE_NAME}'", flush=True)

def _send_ndi_frame(image):
    if _ndi_send is None:
        print("[gen_image] NDI sender not initialised — skipping frame", flush=True)
        return
    import NDIlib as ndi
    import numpy as np

    # Convert PIL → numpy RGBA and assign directly to frame.data
    rgba = np.array(image.convert("RGBA"), dtype=np.uint8)

    frame        = ndi.VideoFrameV2()
    frame.data   = rgba
    frame.FourCC = ndi.FOURCC_VIDEO_TYPE_RGBA

    ndi.send_send_video_v2(_ndi_send, frame)
    print(f"[gen_image] NDI frame sent ({image.width}×{image.height})", flush=True)



# ── Prompt store ───────────────────────────────────────────────────────────────
_prompt_lock      = threading.Lock()
_pending_positive = None
_pending_negative = None
_new_prompt_event = threading.Event()


# controlled by the Performance tab toggle via OSC from Tauri
_image_gen_enabled = False
_image_gen_lock    = threading.Lock()


# ── Pipeline ───────────────────────────────────────────────────────────────────
def _load_pipeline():
    print("[gen_image] Loading SDXL Turbo pipeline...", flush=True)
    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sd-turbo",
        torch_dtype=torch.float16,
        variant="fp16",
    )
    pipe = pipe.to("cuda")
    pipe.enable_attention_slicing()
    print(f"[gen_image] Pipeline ready — {_width}×{_height} @ {NUM_INFERENCE_STEPS} step(s)", flush=True)
    return pipe



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

def _on_image_gen_enabled(address, *args):
    global _image_gen_enabled
    value = int(args[0]) if args else 0
    with _image_gen_lock:
        _image_gen_enabled = bool(value)
    state = "ENABLED" if _image_gen_enabled else "DISABLED"
    print(f"[gen_image] image generation {state}", flush=True)


def _send_fade_trigger():
    _td_client.send_message("/musinfo/image_change", 1.0)
    time.sleep(0.1)
    _td_client.send_message("/musinfo/image_change", 0.0)


# ── Generation loop ────────────────────────────────────────────────────────────
def _generation_loop(pipe):
    while True:
        _new_prompt_event.wait()
        _new_prompt_event.clear()

        with _pipeline_lock:
            pipeline = _pipeline_running
        with _image_gen_lock:
            active = _image_gen_enabled

        if not (pipeline and active):
            continue  # silent — prompt_generator already logs the pause

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

            _send_ndi_frame(image)
            threading.Thread(target=_send_fade_trigger, daemon=True).start()
            print("[gen_image] OSC fade trigger sent to TD", flush=True)

        except Exception as e:
            print(f"[gen_image] Generation error: {e}", flush=True)

# ── Main ───────────────────────────────────────────────────────────────────────

# Start OSC server immediately — before model loads so port 9002 is ready
# for incoming prompts. They'll be held back by _image_gen_enabled = False.
d = dispatcher.Dispatcher()
d.map("/image/prompt/positive",     _on_positive_prompt)
d.map("/image/prompt/negative",     _on_negative_prompt)
d.map("/musinfo/image_gen_enabled", _on_image_gen_enabled)
d.map("/musinfo/pipeline_running", _on_pipeline_running)

# allow Reuse of the adress
class ReusableOSCServer(osc_server.ThreadingOSCUDPServer):
    allow_reuse_address = True

server = ReusableOSCServer((LISTEN_HOST, LISTEN_PORT), d)

server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()
print(f"[gen_image] OSC server listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)

# Now load the heavy model — OSC is already accepting while this runs
_pipe = _load_pipeline()
_init_ndi()

gen_thread = threading.Thread(target=_generation_loop, args=(_pipe,), daemon=True)
gen_thread.start()

server_thread.join()