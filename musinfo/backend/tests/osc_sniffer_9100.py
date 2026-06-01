"""
osc_sniffer_9100.py — MUSINFO OSC sniffer
Listens on UDP port 9100 and prints every incoming OSC message.
Usage:
    python osc_sniffer_9100.py
    python osc_sniffer_9100.py --port 9000   # override port
    python osc_sniffer_9100.py --filter /bpm  # only show matching addresses
"""

import argparse
import sys
import time
from datetime import datetime

try:
    from pythonosc import dispatcher, osc_server
    from pythonosc.osc_message import OscMessage
except ImportError:
    print("[error] python-osc not installed. Run: pip install python-osc")
    sys.exit(1)


RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
CYAN    = "\033[36m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
MAGENTA = "\033[35m"
RED     = "\033[31m"


msg_count = 0
start_time = time.time()


def format_value(v):
    if isinstance(v, float):
        return f"{GREEN}{v:.5f}{RESET}"
    if isinstance(v, int):
        return f"{YELLOW}{v}{RESET}"
    if isinstance(v, str):
        return f"{MAGENTA}\"{v}\"{RESET}"
    if isinstance(v, bytes):
        return f"{DIM}<blob {len(v)}B>{RESET}"
    return f"{RESET}{repr(v)}"


def make_handler(address_filter):
    def handler(address, *args):
        global msg_count
        if address_filter and address_filter not in address:
            return

        msg_count += 1
        elapsed = time.time() - start_time
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        type_tags = "".join(
            "f" if isinstance(a, float) else
            "i" if isinstance(a, int) else
            "s" if isinstance(a, str) else
            "b" if isinstance(a, bytes) else "?"
            for a in args
        )
        tag_str = f" {DIM}[{type_tags}]{RESET}" if type_tags else ""

        values_str = "  ".join(format_value(a) for a in args)

        print(
            f"{DIM}{ts}{RESET}  "
            f"{BOLD}{CYAN}{address}{RESET}{tag_str}"
            f"  {values_str}"
            f"  {DIM}#{msg_count}{RESET}"
        )

    return handler


def print_header(port, address_filter):
    print(f"\n{BOLD}MUSINFO OSC Sniffer{RESET}")
    print(f"  Listening on  {CYAN}UDP 0.0.0.0:{port}{RESET}")
    if address_filter:
        print(f"  Filter        {YELLOW}{address_filter}{RESET}")
    print(f"  Started at    {datetime.now().strftime('%H:%M:%S')}")
    print(f"  {DIM}Ctrl+C to stop{RESET}\n")
    print(f"  {'TIMESTAMP':<14}  {'ADDRESS + TYPES':<40}  VALUES")
    print(f"  {'-'*14}  {'-'*40}  {'-'*20}")


def main():
    parser = argparse.ArgumentParser(description="OSC sniffer for MUSINFO")
    parser.add_argument("--port", type=int, default=9100, help="UDP port to listen on (default: 9100)")
    parser.add_argument("--filter", type=str, default=None, help="Only show addresses containing this string")
    args = parser.parse_args()

    print_header(args.port, args.filter)

    d = dispatcher.Dispatcher()
    d.set_default_handler(make_handler(args.filter))

    try:
        server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", args.port), d)
        server.serve_forever()
    except OSError as e:
        print(f"\n{RED}[error]{RESET} Could not bind to port {args.port}: {e}")
        print("  Is another process already using that port?")
        sys.exit(1)
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\n\n{DIM}Stopped after {elapsed:.1f}s — {msg_count} messages received{RESET}\n")


if __name__ == "__main__":
    main()