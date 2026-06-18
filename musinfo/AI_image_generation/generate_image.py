"""
generate_image.py
Windows side — AI_image_generation/

Listens on port 9002 for prompts from prompt_generator.py:
  /image/prompt/positive   str   positive prompt
  /image/prompt/negative   str   negative prompt

Sends to TouchDesigner on port 9099:
  /musinfo/image_change    1.0   fired after every new NDI frame
"""


import signal
import sys
import threading
import time
from pythonosc import dispatcher, osc_server, udp_client
import torch
from diffusers import AutoPipelineForText2Image

# ── OSC config ─────────────────────────────────────────────────────────────────
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9002

# TouchDesigner OSC target — change TD_HOST to the TD machine's IP if on another PC
TD_HOST    = "127.0.0.1"
TD_PORT    = 9099
_td_client = udp_client.SimpleUDPClient(TD_HOST, TD_PORT)

# ── Generation config ──────────────────────────────────────────────────────────
RESOLUTION_MAP = {
    "512":  (512, 512),
    "768":  (768, 768),
    "wide_sm": (768, 512),
    "1024": (1024, 768),
    "wide": (1280, 720),   # 720p widescreen
    "1080": (1920, 1080), # need touchdesigner license
}

# RESOLUTION          = "512"
RESOLUTION          = "wide_sm"
NUM_INFERENCE_STEPS = 1   # 1–4 for SDXL Turbo; 1 = fastest
GUIDANCE_SCALE      = 0.0  # CFG-free for Turbo

_width, _height = RESOLUTION_MAP.get(RESOLUTION)

# ── State ──────────────────────────────────────────────────────────────────────
_pipeline_running = False
_pipeline_lock    = threading.Lock()


_model_ready = False
_image_gen_enabled = False
_image_gen_lock    = threading.Lock()

_prompt_lock      = threading.Lock()
_pending_positive = None
_pending_negative = None
_new_prompt_event = threading.Event()


# Helper functions


def _shutdown(signum, frame):
    global _pipe
    print("[gen_image] Shutting down cleanly...", flush=True)
    try:
        if _pipe is not None:
            del _pipe
            torch.cuda.empty_cache()
            print("[gen_image] CUDA context released.", flush=True)
    except Exception as e:
        print(f"[gen_image] Shutdown error: {e}", flush=True)
    sys.exit(0)

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ── NDI output ─────────────────────────────────────────────────────────────────
NDI_SOURCE_NAME = "MUSINFO_Background"
_ndi_send = None

def _init_ndi():
    global _ndi_send
    import NDIlib as ndi
    if not ndi.initialize():
        print("[gen_image] NDI init failed — is the runtime installed?", flush=True)
        return
    send_settings          = ndi.SendCreate()
    send_settings.ndi_name = NDI_SOURCE_NAME
    _ndi_send              = ndi.send_create(send_settings)
    print(f"[gen_image] NDI sender ready — '{NDI_SOURCE_NAME}'", flush=True)

def _send_ndi_frame(image):
    if _ndi_send is None:
        print("[gen_image] NDI sender not initialised — skipping frame", flush=True)
        return
    import NDIlib as ndi
    import numpy as np

    rgba         = np.ascontiguousarray(np.array(image.convert("RGBA"), dtype=np.uint8))
    frame        = ndi.VideoFrameV2()
    frame.data   = rgba
    frame.FourCC = ndi.FOURCC_VIDEO_TYPE_RGBA

    ndi.send_send_video_v2(_ndi_send, frame)
    print(f"[gen_image] NDI frame sent ({image.width}×{image.height})", flush=True)

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
    global _pending_positive, _model_ready
    value = str(args[0]) if args else ""
    if not value:
        return
    with _prompt_lock:
        _pending_positive = value
    if _model_ready:
        _new_prompt_event.set()

def _on_negative_prompt(address, *args):
    global _pending_negative
    value = str(args[0]) if args else ""
    if not value:
        return
    with _prompt_lock:
        _pending_negative = value

def _on_image_gen_enabled(address, *args):
    global _image_gen_enabled
    value = int(args[0]) if args else 0
    with _image_gen_lock:
        _image_gen_enabled = bool(value)
    state = "ENABLED" if _image_gen_enabled else "DISABLED"
    print(f"[gen_image] image generation {state}", flush=True)

def _on_pipeline_running(address, *args):
    global _pipeline_running
    value = int(args[0]) if args else 0
    with _pipeline_lock:
        _pipeline_running = bool(value)
    state = "RUNNING" if _pipeline_running else "STOPPED"
    print(f"[gen_image] pipeline {state}", flush=True)

def _send_fade_trigger():
    _td_client.send_message("/musinfo/image_change", 1.0)
    time.sleep(0.1)
    _td_client.send_message("/musinfo/image_change", 0.0)

# ── Generation loop ────────────────────────────────────────────────────────────
def _generation_loop(pipe):
    global _pending_positive, _pending_negative
    print("[gen_image] Generation loop started", flush=True)
    while True:
        _new_prompt_event.wait()
        _new_prompt_event.clear()

        with _pipeline_lock:
            pipeline = _pipeline_running
        with _image_gen_lock:
            active = _image_gen_enabled

        if not (pipeline and active):
            continue

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
            image = result.images[0]
            print(f"[gen_image] Done in {time.time() - t0:.2f}s", flush=True)
        except Exception as e:
            print(f"[gen_image] Generation error: {e}", flush=True)
            if "22" in str(e) or "CUDA" in str(e).upper():
                print("[gen_image] CUDA error detected — clearing cache and pausing 5s", flush=True)
                torch.cuda.empty_cache()
                time.sleep(5)
            with _prompt_lock:
                _pending_positive = None
                _pending_negative = None
            continue

        try:
            _send_ndi_frame(image)
            threading.Thread(target=_send_fade_trigger, daemon=True).start()
        except Exception as e:
            print(f"[gen_image] NDI error: {e}", flush=True)

# ── Main ───────────────────────────────────────────────────────────────────────
d = dispatcher.Dispatcher()
d.map("/image/prompt/positive",     _on_positive_prompt)
d.map("/image/prompt/negative",     _on_negative_prompt)
d.map("/musinfo/image_gen_enabled", _on_image_gen_enabled)
d.map("/musinfo/pipeline_running",  _on_pipeline_running)

class ReusableOSCServer(osc_server.ThreadingOSCUDPServer):
    allow_reuse_address = True

server        = ReusableOSCServer((LISTEN_HOST, LISTEN_PORT), d)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()
print(f"[gen_image] OSC server listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)

_pipe = _load_pipeline()
_init_ndi()

_model_ready = True  # now prompts will actually trigger generation
print("[gen_image] Ready for generation", flush=True)


gen_thread = threading.Thread(target=_generation_loop, args=(_pipe,), daemon=True)
gen_thread.start()

server_thread.join()