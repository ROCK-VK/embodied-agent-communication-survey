#!/usr/bin/env python3
"""Capture sniffer-5 UART JSONL during a packet-ID trial; never flashes firmware."""
import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import serial
from compact_uart import decode_record


VERSION = "sniffer-6c-compact-uart"
MAC_RE = re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")


def read_json_event(line):
    try:
        value = decode_record(line)
    except (ValueError, TypeError, KeyError):
        return None
    return value if isinstance(value, dict) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM10")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--channel", type=int, default=149)
    parser.add_argument("--target-mac", required=True, help="Jetson Wi-Fi MAC, supplied at run time")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument("--output", required=True, type=Path, help="new output directory; existing paths are never overwritten")
    args = parser.parse_args()
    if not MAC_RE.fullmatch(args.target_mac) or not 1 <= args.channel <= 196:
        parser.error("target-mac or channel is invalid")
    if args.duration <= 0 or args.ready_timeout <= 0 or args.baud <= 0:
        parser.error("duration, ready-timeout, and baud must be positive")
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("output directory already exists; choose a new path")
    records_path = args.output / "records.jsonl"
    raw_path = args.output / "uart_raw.log"
    summary_path = args.output / "summary.json"
    counters = Counter()
    armed = False
    stopped = False
    final_stats = None
    ready = None
    started_ns = None
    ended_ns = None

    try:
        ser = serial.Serial(port=None, baudrate=args.baud, timeout=0.2)
        ser.dtr = False
        ser.rts = False
        ser.port = args.port
        with ser, \
                records_path.open("x", encoding="utf-8", newline="\n") as records, \
                raw_path.open("x", encoding="utf-8", newline="\n") as raw:
            ser.rts = True
            time.sleep(0.1)
            ser.rts = False
            deadline = time.monotonic() + args.ready_timeout
            while time.monotonic() < deadline:
                line = ser.readline().decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                raw.write(line + "\n")
                event = read_json_event(line)
                if event and event.get("event") == "READY":
                    ready = event
                    break
            if not ready or ready.get("version") != VERSION:
                raise RuntimeError("expected READY version {}; received {}".format(VERSION, ready))

            ser.write("CFG,{},{}\n".format(args.channel, args.target_mac).encode("ascii"))
            deadline = time.monotonic() + args.ready_timeout
            while time.monotonic() < deadline:
                line = ser.readline().decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                raw.write(line + "\n")
                event = read_json_event(line)
                if event and event.get("event") == "ARMED":
                    records.write(json.dumps(event, separators=(",", ":")) + "\n")
                    records.flush()
                    armed = True
                    started_ns = time.monotonic_ns()
                    assert event["channel"] == args.channel and event["target"].lower() == args.target_mac.lower() and event["mode"] == "NULL"
                    print("ARMED; receiver must already be listening before starting sender", flush=True)
                    break
            if not armed:
                raise RuntimeError("sniffer did not emit ARMED before timeout")

            capture_deadline = time.monotonic() + args.duration
            while time.monotonic() < capture_deadline:
                line = ser.readline().decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                raw.write(line + "\n")
                event = read_json_event(line)
                if not event:
                    counters["json_parse_error"] += 1
                    continue
                event["host_capture_mono_ns"] = time.monotonic_ns()
                name = event.get("event", "UNKNOWN")
                counters[name] += 1
                if name in ("FRAME", "CSI", "STATS"):
                    counters["probe_status_{}".format(event.get("app_probe_status", 0))] += 1
                    if name == "FRAME" and event.get("protected"):
                        counters["protected_frame"] += 1
                    if name == "CSI" and event.get("protected"):
                        counters["protected_csi"] += 1
                if name == "FINAL":
                    final_stats = event
                records.write(json.dumps(event, separators=(",", ":")) + "\n")
                records.flush()

            ser.write(b"STOP\n")
            stop_deadline = time.monotonic() + args.ready_timeout
            while time.monotonic() < stop_deadline:
                line = ser.readline().decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                raw.write(line + "\n")
                event = read_json_event(line)
                if not event:
                    counters["json_parse_error"] += 1
                    continue
                event["host_capture_mono_ns"] = time.monotonic_ns()
                name = event.get("event", "UNKNOWN")
                counters[name] += 1
                if name == "FINAL":
                    final_stats = event
                    stopped = True
                records.write(json.dumps(event, separators=(",", ":")) + "\n")
                records.flush()
                if stopped:
                    break
            ended_ns = time.monotonic_ns()
    except (OSError, serial.SerialException, RuntimeError) as exc:
        print("Capture stopped: {}".format(exc), file=sys.stderr)
        ended_ns = time.monotonic_ns()

    all_rows = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines()]
    data = [r for r in all_rows if r.get("event") in ("FRAME", "CSI")]
    ids = [r["wire_record_id"] for r in data]
    counters["protected_frame"] = sum(r["event"] == "FRAME" and r["protected"] for r in data)
    counters["protected_csi"] = sum(r["event"] == "CSI" and r["protected"] for r in data)
    transport = {"host_records": len(ids), "sequence_contiguous_from_one": ids == list(range(1, len(ids)+1)),
                 "duplicate_ids": len(ids)-len(set(ids))}
    if final_stats:
        transport["output_equals_host"] = all(final_stats.get(k.lower()+"_output") == counters[k] for k in ("FRAME", "CSI"))
        transport["enqueued_equals_output"] = all(final_stats.get(k+"_enqueued") == final_stats.get(k+"_output") for k in ("frame", "csi"))
    summary = {
        "transport_audit": transport,
        "firmware_expected": VERSION,
        "ready_version": ready.get("version") if ready else None,
        "armed": armed,
        "stop_final_received": stopped,
        "requested_duration_s": args.duration,
        "measured_capture_s": ((ended_ns - started_ns) / 1e9) if ended_ns and started_ns else None,
        "event_counts": dict(counters),
        "final_stats": final_stats,
        "records_file": records_path.name,
        "raw_uart_file": raw_path.name,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if armed and stopped else 2


if __name__ == "__main__":
    raise SystemExit(main())
