#!/usr/bin/env python3
"""
OSC Test Script - sends a test message to verify Rust is receiving OSC

Run this WHILE your MUSINFO app is open to test if OSC is working.
You should see the message appear in the OutputPanel.
"""

from pythonosc import udp_client
import time

OSC_HOST = "127.0.0.1"
OSC_PORT = 9000

print("[OSC Test] Creating client...")
client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)

print(f"[OSC Test] Sending test messages to {OSC_HOST}:{OSC_PORT}")

for i in range(5):
    message = f"Test message #{i+1}"
    address = "/test/vocals"
    
    print(f"[OSC Test] Sending: {address} -> {message}")
    client.send_message(address, message)
    
    time.sleep(1)

print("[OSC Test] Done! Check your MUSINFO OutputPanel.")