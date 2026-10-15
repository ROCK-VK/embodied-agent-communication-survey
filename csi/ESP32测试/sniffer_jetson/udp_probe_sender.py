#!/usr/bin/env python3
"""Send low-rate, uniquely identified UDP probe datagrams from Jetson (Python 3.8+)."""
import argparse
import ipaddress
import json
import secrets
import socket
import sys
import time
from pathlib import Path

from udp_probe_protocol import encode_packet, PACKET_LEN


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=ipaddress.IPv4Address, help="receiver IPv4 address, supplied at run time")
    parser.add_argument("--port", type=int, default=39001)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval", type=float, default=0.2, help="seconds between datagrams; default 5/s")
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--run-id", type=lambda value: int(value, 0), default=None,
                        help="optional uint32; accepts decimal or 0x-prefixed notation")
    parser.add_argument("--log", required=True, type=Path, help="new JSONL path; existing files are never overwritten")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.count < 1 or args.start_id < 0 or args.interval < 0.05:
        parser.error("port/count/start-id must be valid and interval must be at least 0.05s")
    run_id = secrets.randbits(32) if args.run_id is None else args.run_id
    if not 0 <= run_id <= 0xFFFFFFFF or args.start_id + args.count - 1 > 0xFFFFFFFF:
        parser.error("run-id and packet-id range must fit uint32")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = args.log.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        parser.error("log file already exists; choose a new path")

    sent = 0
    start_ns = time.monotonic_ns()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, log:
            for offset in range(args.count):
                packet_id = args.start_id + offset
                deadline = start_ns + int(offset * args.interval * 1_000_000_000)
                remaining = deadline - time.monotonic_ns()
                if remaining > 0:
                    time.sleep(remaining / 1_000_000_000)
                sender_ns = time.monotonic_ns()
                payload = encode_packet(run_id, packet_id, sender_ns)
                written = sock.sendto(payload, (str(args.destination), args.port))
                if written != PACKET_LEN:
                    raise OSError("short UDP send")
                log.write(json.dumps({"event": "SEND", "run_id": run_id, "packet_id": packet_id,
                                      "sender_mono_ns": sender_ns, "bytes": written}, separators=(",", ":")) + "\n")
                log.flush()
                sent += 1
    except OSError as exc:
        print("UDP sender failed: {}".format(exc), file=sys.stderr)
        return 2
    print(json.dumps({"run_id": run_id, "sent": sent, "payload_bytes": PACKET_LEN,
                      "interval_s": args.interval, "destination_port": args.port}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
