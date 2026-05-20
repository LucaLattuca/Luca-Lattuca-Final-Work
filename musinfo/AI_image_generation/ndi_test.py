"""
ndi_test.py
Cycles through 3 images over NDI every 5 seconds.
Same NDI source name as generate_image.py so TD sees it identically.
"""

import time
from PIL import Image
import NDIlib as ndi
import numpy as np

# ── Config ─────────────────────────────────────────────────────────────────────
NDI_SOURCE_NAME = "MUSINFO_Background"
INTERVAL = 4  # seconds between image swaps

IMAGE_PATHS = [
    r"C:\Users\luca_\Pictures\test1.png",
    r"C:\Users\luca_\Pictures\test2.png",
    r"C:\Users\luca_\Pictures\test3.png",
]

# ── NDI setup ──────────────────────────────────────────────────────────────────
if not ndi.initialize():
    print("NDI init failed — is the runtime installed?")
    exit()

send_settings = ndi.SendCreate()
send_settings.ndi_name = NDI_SOURCE_NAME
ndi_send = ndi.send_create(send_settings)
print(f"NDI sender ready — '{NDI_SOURCE_NAME}'")

# ── Send loop ──────────────────────────────────────────────────────────────────
def send_image(path):
    image = Image.open(path).convert("RGBA")
    rgba = np.array(image, dtype=np.uint8)

    frame = ndi.VideoFrameV2()
    frame.data = rgba
    frame.FourCC = ndi.FOURCC_VIDEO_TYPE_RGBA

    ndi.send_send_video_v2(ndi_send, frame)
    print(f"Sent: {path} ({image.width}x{image.height})")

index = 0
while True:
    send_image(IMAGE_PATHS[index])
    index = (index + 1) % len(IMAGE_PATHS)
    time.sleep(INTERVAL)