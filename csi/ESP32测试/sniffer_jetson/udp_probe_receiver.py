#!/usr/bin/env python3
"""Receive and validate low-rate UDP probe datagrams without changing firewall settings."""
import argparse
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from udp_probe_protocol import PacketError, decode_packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True, help="receiver IPv4 address; use the selected interface address")
    parser.add_argument("--port", type=int, default=39001)
    parser.add_argument("--count", type=int, default=100, help="expected unique packet IDs")
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--idle-timeout", type=float, default=3.0)
    parser.add_argument("--log", required=True, type=Path, help="new JSONL path; existing files are never overwritten")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.count < 1 or args.start_id < 0 or args.idle_timeout <= 0:
        parser.error("port/count/start-id/idle-timeout must be valid")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = args.log.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        parser.error("log file already exists; choose a new path")
    summary_path = args.log.with_suffix(args.log.suffix + ".summary.json")
    if summary_path.exists():
        log.close()
        parser.error("summary file already exists; choose a new path")

    accepted = set()
    run_id = None
    duplicates = invalid = 0
    last_packet_ns = time.monotonic_ns()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, log:
            sock.bind((args.bind, args.port))
            sock.settimeout(min(args.idle_timeout, 0.5))
            print("listening on {}:{}".format(args.bind, args.port), flush=True)
            while len(accepted) < args.count:
                try:
                    datagram, _peer = sock.recvfrom(4096)
                except socket.timeout:
                    if time.monotonic_ns() - last_packet_ns >= int(args.idle_timeout * 1_000_000_000):
                        break
                    continue
                recv_ns = time.monotonic_ns()
                last_packet_ns = recv_ns
                record = {"event": "RX", "recv_mono_ns": recv_ns,
                          "recv_utc": datetime.now(timezone.utc).isoformat(), "bytes": len(datagram)}
                try:
                    packet = decode_packet(datagram)
                    if run_id is None:
                        run_id = packet["run_id"]
                    if packet["run_id"] != run_id:
                        raise PacketError("run_id_mismatch")
                    key = packet["packet_id"]
                    if key in accepted:
                        duplicates += 1
                        record["status"] = "duplicate"
                    else:
                        accepted.add(key)
                        record["status"] = "valid"
                    record.update(packet)
                except PacketError as exc:
                    invalid += 1
                    record.update({"status": "invalid", "reason": str(exc)})
                log.write(json.dumps(record, separators=(",", ":")) + "\n")
                log.flush()
    except OSError as exc:
        print("UDP receiver failed: {}".format(exc), file=sys.stderr)
        return 2

    expected = set(range(args.start_id, args.start_id + args.count))
    missing = sorted(expected - accepted)
    summary = {"run_id": run_id, "expected_count": args.count, "unique_valid_count": len(accepted),
               "duplicate_count": duplicates, "invalid_count": invalid, "missing_packet_ids": missing,
               "receiver_log": str(args.log)}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if not missing and invalid == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
