# td_osc_monitor.py — TouchDesigner OSC monitor
# Listens on port 9100 and prints all incoming OSC messages.
# Run this on Windows before starting the pipeline to verify
# that each instrument is sending to the correct TD address.
#
# Expected index mapping for current instruments.json:
#   bass   -> 0
#   drums  -> 1
#   guitar -> 2
#   vocals -> 3
#   mix    -> N/A (tempo pulse only, no index)
#
# Usage: python td_osc_monitor.py

from pythonosc import dispatcher, osc_server
import threading
import time
from collections import defaultdict

PORT = 9100

# ── Colour codes for terminal output ─────────────────────────────────────────
COLORS = {
    "timbre":   "\033[95m",   # pink/purple
    "dynamics": "\033[94m",   # blue
    "harmony":  "\033[95m",   # pink
    "pitch":    "\033[93m",   # yellow
    "tempo":    "\033[33m",   # dark yellow
    "reset":    "\033[0m",
    "dim":      "\033[2m",
    "green":    "\033[92m",
    "header":   "\033[1;37m", # bold white
}

# ── Address → instrument/analyser label ──────────────────────────────────────
# Derived from current instruments.json:
#   bass=0, drums=1, guitar=2, vocals=3
INDEX_MAP = {
    "0": "bass",
    "1": "drums",
    "2": "guitar",
    "3": "vocals",
}

def parse_address(address):
    """
    Parse /td/{analyser}/{index}/{param} or /td/tempo/pulse
    Returns (analyser, instrument_label, param)
    """
    parts = address.strip("/").split("/")
    # parts[0] == "td"
    if len(parts) < 3:
        return None, None, None

    if parts[1] == "tempo":
        return "tempo", "mix", parts[2]

    if len(parts) < 4:
        return None, None, None

    analyser = parts[1]
    index    = parts[2]
    param    = parts[3]
    instrument = INDEX_MAP.get(index, f"idx{index}")
    return analyser, instrument, param


# ── Activity tracker — last value seen per address ───────────────────────────
last_seen   = {}   # address -> (value, timestamp)
msg_counter = defaultdict(int)

def format_value(value):
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, list):
        if len(value) > 4:
            preview = ", ".join(f"{v:.2f}" for v in value[:4])
            return f"[{preview} ... ({len(value)} values)]"
        return "[" + ", ".join(f"{v:.2f}" for v in value) + "]"
    return str(value)

def handle_message(address, *args):
    value = args[0] if len(args) == 1 else list(args)
    now   = time.time()

    analyser, instrument, param = parse_address(address)
    color = COLORS.get(analyser, "") if analyser else ""
    reset = COLORS["reset"]
    dim   = COLORS["dim"]

    last_seen[address] = (value, now)
    msg_counter[address] += 1

    label = f"{instrument}/{param}" if instrument else address
    print(f"  {color}{analyser:<10}{reset}  {label:<28}  {dim}{format_value(value)}{reset}")

# ── Summary printer — runs every 5s ──────────────────────────────────────────
def print_summary():
    while True:
        time.sleep(5)
        if not last_seen:
            continue

        header = COLORS["header"]
        reset  = COLORS["reset"]
        green  = COLORS["green"]
        dim    = COLORS["dim"]

        print(f"\n{header}── Active TD OSC addresses ({'─' * 40}){reset}")

        # Group by analyser
        by_analyser = defaultdict(list)
        for addr, (val, ts) in sorted(last_seen.items()):
            analyser, instrument, param = parse_address(addr)
            age = time.time() - ts
            stale = age > 3.0
            by_analyser[analyser or "unknown"].append(
                (instrument, param, val, stale, msg_counter[addr])
            )

        for analyser, entries in sorted(by_analyser.items()):
            color = COLORS.get(analyser, "")
            print(f"  {color}{analyser}{reset}")
            for instrument, param, val, stale, count in sorted(entries):
                status = f"{dim}(stale {count} msgs){reset}" if stale else f"{green}● {count} msgs{reset}"
                print(f"    {instrument:<10} {param:<20} {dim}{format_value(val):<20}{reset}  {status}")

        print()

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    d = dispatcher.Dispatcher()
    d.map("/td/*", handle_message)

    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", PORT), d)

    summary_thread = threading.Thread(target=print_summary, daemon=True)
    summary_thread.start()

    header = COLORS["header"]
    reset  = COLORS["reset"]
    dim    = COLORS["dim"]

    print(f"\n{header}td_osc_monitor — listening on port {PORT}{reset}")
    print(f"{dim}Expected instruments: bass=0  drums=1  guitar=2  vocals=3  mix=N/A{reset}")
    print(f"{dim}Summary prints every 5s. Ctrl+C to stop.{reset}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[monitor] Stopped.")