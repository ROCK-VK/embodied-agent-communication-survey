#!/usr/bin/env python3
"""Send up to 20 CSID UDP probes to an ESP32-C5 Open SoftAP receiver."""
import argparse
import json
import socket
import sys
import time
from pathlib import Path

from udp_probe_protocol import PACKET_LEN, encode_packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True,
                        help="ESP SoftAP IPv4 address printed by OPEN_AP_READY")
    parser.add_argument("--run-id", required=True, type=lambda value: int(value, 0),
                        help="uint32 run identifier, decimal or 0x-prefixed")
    parser.add_argument("--port", type=int, default=39001)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--interval-ms", type=float, default=150.0)
    parser.add_argument("--output", required=True, type=Path,
                        help="new local JSONL sender log; existing files are refused")
    args = parser.parse_args()
    if not 1 <= args.count <= 20:
        parser.error("count must be between 1 and 20")
    if not 0 <= args.run_id <= 0xFFFFFFFF:
        parser.error("run-id must fit uint32")
    if not 1 <= args.port <= 65535:
        parser.error("port must be in 1..65535")
    if args.interval_ms < 100 or args.interval_ms > 5000:
        parser.error("interval-ms must be in 100..5000 ms")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    sent = 0
    target = (args.destination, args.port)
    with args.output.open("x", encoding="utf-8", newline="\n") as log, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for packet_id in range(args.count):
            sender_ns = time.monotonic_ns()
            datagram = encode_packet(args.run_id, packet_id, sender_ns)
            if len(datagram) != PACKET_LEN:
                raise RuntimeError("unexpected CSID packet length")
            written = sock.sendto(datagram, target)
            if written != PACKET_LEN:
                raise OSError("short UDP send: {} of {} bytes".format(written, PACKET_LEN))
            row = {"event": "SEND", "run_id": args.run_id,
                   "packet_id": packet_id, "sender_mono_ns": sender_ns,
                   "datagram_len": written, "destination": args.destination,
                   "port": args.port}
            log.write(json.dumps(row, separators=(",", ":")) + "\n")
            log.flush()
            sent += 1
            print(json.dumps(row, separators=(",", ":")), flush=True)
            if packet_id + 1 < args.count:
                time.sleep(args.interval_ms / 1000.0)
        summary = {"event": "SEND_FINAL", "run_id": args.run_id,
                   "sent": sent, "payload_bytes": PACKET_LEN,
                   "interval_ms": args.interval_ms}
        log.write(json.dumps(summary, separators=(",", ":")) + "\n")
        log.flush()
    print(json.dumps(summary, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
