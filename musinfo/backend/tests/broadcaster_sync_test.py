# broadcaster_sync_test.py — Test if multi-channel audio stays synchronized
# Monitors TCP stream from capture.py and checks for timing drift between channels

import socket
import struct
import json
import time
import signal
import sys
from collections import defaultdict

# Global flag for shutdown
shutdown_flag = False

def signal_handler(sig, frame):
    """Handle Ctrl+C"""
    global shutdown_flag
    print("\n\n[sync_test] Shutting down...", flush=True)
    shutdown_flag = True
    display_sync_status()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 5005

# Track timing of each channel
channel_stats = defaultdict(lambda: {
    'chunks': 0,
    'last_time': None,
    'intervals': [],
    'total_bytes': 0
})


def recv_exact(sock, n):
    """Read exactly n bytes from socket"""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def display_sync_status():
    """Display sync analysis"""
    print("\n" + "="*80, flush=True)
    print("SYNC ANALYSIS", flush=True)
    print("="*80, flush=True)
    
    if not channel_stats:
        print("No data yet...", flush=True)
        return
    
    # Display per-channel stats
    for channel_id in sorted(channel_stats.keys()):
        stats = channel_stats[channel_id]
        
        avg_interval = sum(stats['intervals']) / len(stats['intervals']) if stats['intervals'] else 0
        
        print(f"\nChannel {channel_id}:", flush=True)
        print(f"  Chunks received: {stats['chunks']}", flush=True)
        print(f"  Data received:   {stats['total_bytes'] / 1024:.2f} KB", flush=True)
        print(f"  Avg interval:    {avg_interval*1000:.2f}ms", flush=True)
    
    # Check for drift
    if len(channel_stats) > 1:
        chunk_counts = [s['chunks'] for s in channel_stats.values()]
        min_chunks = min(chunk_counts)
        max_chunks = max(chunk_counts)
        drift = max_chunks - min_chunks
        
        print(f"\n{'='*80}", flush=True)
        if drift == 0:
            print("✓ PERFECT SYNC - All channels have same chunk count", flush=True)
        elif drift <= 2:
            print(f"⚠ MINOR DRIFT - {drift} chunk difference (acceptable)", flush=True)
        else:
            print(f"✗ SYNC ISSUE - {drift} chunk difference (PROBLEMATIC)", flush=True)
        print(f"{'='*80}\n", flush=True)
    
    # Save to file
    with open('sync_results.txt', 'w') as f:
        f.write("SYNC TEST RESULTS\n")
        f.write("="*80 + "\n\n")
        for channel_id in sorted(channel_stats.keys()):
            stats = channel_stats[channel_id]
            f.write(f"Channel {channel_id}:\n")
            f.write(f"  Chunks: {stats['chunks']}\n")
            f.write(f"  Data: {stats['total_bytes'] / 1024:.2f} KB\n\n")
        if len(channel_stats) > 1:
            f.write(f"\nDrift: {drift} chunks\n")
            if drift == 0:
                f.write("Result: PERFECT SYNC\n")
            elif drift <= 2:
                f.write("Result: MINOR DRIFT (acceptable)\n")
            else:
                f.write("Result: SYNC ISSUE (problematic)\n")


def handle_connection(conn):
    """Monitor incoming chunks from capture.py"""
    print("[sync_test] capture.py connected. Monitoring sync...\n", flush=True)
    print("[sync_test] Press Ctrl+C to stop and see results\n", flush=True)
    
    last_display = time.time()
    
    try:
        while not shutdown_flag:
            # Read header with timeout
            conn.settimeout(0.5)
            try:
                header = recv_exact(conn, 5)
            except socket.timeout:
                continue
            
            if header is None:
                break
            
            channel_id, data_len = struct.unpack(">BI", header)
            
            # Read audio data
            audio_bytes = recv_exact(conn, data_len)
            if audio_bytes is None:
                break
            
            # Record timing
            now = time.time()
            stats = channel_stats[channel_id]
            
            if stats['last_time'] is not None:
                interval = now - stats['last_time']
                stats['intervals'].append(interval)
                
                # Keep only last 100 intervals
                if len(stats['intervals']) > 100:
                    stats['intervals'].pop(0)
            
            stats['last_time'] = now
            stats['chunks'] += 1
            stats['total_bytes'] += data_len
            
            # Display status every second
            if now - last_display >= 1.0:
                display_sync_status()
                last_display = now
    
    except Exception as e:
        print(f"[sync_test] Error: {e}", flush=True)
    finally:
        print("[sync_test] capture.py disconnected.", flush=True)
        display_sync_status()
        conn.close()


def start_server():
    """Start TCP server to receive from capture.py"""
    print(f"[sync_test] Listening for capture.py on {LOCAL_HOST}:{LOCAL_PORT}", flush=True)
    print("[sync_test] NOTE: This replaces broadcaster.py - don't run both!", flush=True)
    print("[sync_test] Press Ctrl+C to stop\n", flush=True)
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((LOCAL_HOST, LOCAL_PORT))
        server.listen(1)
        server.settimeout(1.0)  # Check for shutdown every second
        
        while not shutdown_flag:
            try:
                conn, addr = server.accept()
                handle_connection(conn)
            except socket.timeout:
                continue


if __name__ == "__main__":
    start_server()