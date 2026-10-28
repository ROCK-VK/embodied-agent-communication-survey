"""Bounded UART-only Open AP CSI/UDP PoC capture.

This script configures the ESP32-C5 SoftAP and capture mode. It never changes
Jetson networking or sends probe traffic; those actions are performed separately
and manually during an authorized lab session.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "uart_benchmark" / "tools"))
from benchmark_host import connect
from open_ap_poc import analyze_capture, write_outputs
from wire8c import Decoder

FIRMWARE = "sniffer-8d-csi-centric"
TRANSPORT_ERRORS = ("bad_header", "crc_error", "discarded_bytes",
                    "serial_discontinuity", "incomplete_bytes",
                    "raw_metadata_conflict")
DEVICE_ERRORS = ("queue_drop", "raw_drop", "csi_drop", "write_errors",
                 "raw_truncated", "csi_truncated", "payload_truncated")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM10")
    parser.add_argument("--baud", type=int, default=3_000_000)
    parser.add_argument("--channel", type=int, choices=(2,), default=2)
    parser.add_argument("--ssid", default="CSI-C5-OPEN-POC")
    parser.add_argument("--max-duration", type=float, default=300.0)
    parser.add_argument("--stop-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sender-log", type=Path,
                        help="optional local copy of the Jetson sender JSONL")
    args = parser.parse_args()
    if not 0 < args.max_duration <= 300:
        parser.error("--max-duration must be in 0..300 seconds")
    if not args.ssid or len(args.ssid.encode("utf-8")) > 32 or "," in args.ssid:
        parser.error("SSID must be 1..32 UTF-8 bytes and cannot contain comma")
    if args.stop_file.exists():
        parser.error("stop-file already exists; choose a new path")
    args.output.mkdir(parents=True, exist_ok=False)

    decoder = Decoder()
    configured = False
    mode_armed = False
    final = None
    open_stats = {}
    ready_event = None
    mode_ack = None
    stop_reason = None
    record_counts = {"CSI_DATA": 0, "FRAME": 0, "CONTROL": 0,
                     "STATS": 0, "FINAL": 0}
    s = serial.Serial(port=None, baudrate=921600, timeout=0.1)
    s.dtr = False
    s.rts = False
    s.port = args.port

    def send(line):
        s.write((line + "\n").encode("ascii"))

    def consume(chunk, raw, records, times):
        nonlocal final, open_stats
        if not chunk:
            return []
        raw.write(chunk)
        output = []
        for row in decoder.feed(chunk):
            host_time_ns = time.time_ns()
            host_mono_ns = time.monotonic_ns()
            row["host_time_ns"] = host_time_ns
            row["host_mono_ns"] = host_mono_ns
            output.append(row)
            records.write(json.dumps(row, separators=(",", ":")) + "\n")
            times.write(json.dumps({"record_serial": row["record_serial"],
                                    "host_time_ns": host_time_ns,
                                    "host_mono_ns": host_mono_ns}) + "\n")
            if row["event"] in record_counts:
                record_counts[row["event"]] += 1
            counters = row.get("counters", {})
            if counters.get("event", "").startswith("OPEN_AP_") or counters.get("event", "").startswith("AP_STA_"):
                open_stats = counters
            if counters.get("event") == "OPEN_AP_FINAL_STATS":
                open_stats = counters
            if row["event"] == "FINAL":
                final = row
        raw.flush();records.flush();times.flush()
        return output

    with s, (args.output / "stream.bin").open("xb") as raw, \
            (args.output / "records.jsonl").open("x", encoding="utf-8") as records, \
            (args.output / "stream.bin.times.jsonl").open("x", encoding="utf-8") as times:
        ready, baud_ready = connect(s, FIRMWARE, args.baud)
        if ready.get("open_ap_poc") is not True:
            raise RuntimeError("firmware READY lacks OPEN_AP_POC capability")
        (args.output / "ready.json").write_text(
            json.dumps({"ready": ready, "baud": baud_ready}, indent=2), encoding="utf-8")
        send("CFG_OPEN_AP,{},{}".format(args.channel, args.ssid))
        setup_deadline = time.monotonic() + 20
        while ready_event is None and time.monotonic() < setup_deadline:
            rows = consume(s.read(max(1, min(65536, s.in_waiting))), raw, records, times)
            for row in rows:
                counters = row.get("counters", {})
                if counters.get("event") == "OPEN_AP_READY":
                    ready_event = counters
                    break
                if counters.get("event") == "OPEN_AP_UDP_ERROR":
                    ready_event = counters
                    break
                if counters.get("event") == "OPEN_AP_INIT_FAILED":
                    ready_event = counters
                    break
            if any(decoder.counts.get(key, 0) for key in TRANSPORT_ERRORS):
                raise RuntimeError("UART transport/parser error during SoftAP setup")
        if ready_event is None:
            raise RuntimeError("timed out waiting for OPEN_AP_READY")
        if ready_event.get("event") != "OPEN_AP_READY":
            if ready_event.get("event") == "OPEN_AP_INIT_FAILED":
                raise RuntimeError("SoftAP initialization failed at {}: {} ({})".format(
                    ready_event.get("api", "unknown API"),
                    ready_event.get("err_name", "unknown error"),
                    ready_event.get("err", "unknown code")))
            raise RuntimeError("ESP UDP server failed to bind: {}".format(ready_event))
        if (ready_event.get("actual_channel") != 2 or
                ready_event.get("bandwidth_mhz") != 20 or
                ready_event.get("channel_readback_ok") is not True or
                ready_event.get("udp_server_ready") is not True):
            raise RuntimeError("SoftAP readback/UDP server readiness gate failed")

        send("MODE OPEN_AP_POC")
        ack_deadline = time.monotonic() + 15
        while mode_ack is None and time.monotonic() < ack_deadline:
            rows = consume(s.read(max(1, min(65536, s.in_waiting))), raw, records, times)
            for row in rows:
                counters = row.get("counters", {})
                if counters.get("event") == "MODE_ACK":
                    mode_ack = counters
                    break
                if counters.get("event") in ("ERROR", "BUSY", "OPEN_AP_MODE_REQUIRED",
                                               "OPEN_AP_INIT_FAILED"):
                    raise RuntimeError("firmware rejected OPEN_AP_POC mode")
        if mode_ack is None or mode_ack.get("mode") != "OPEN_AP_POC" or not mode_ack.get("rf_capture_enabled"):
            raise RuntimeError("OPEN_AP_POC mode was not acknowledged")
        configured = True
        mode_armed = True
        start = time.monotonic()
        print(json.dumps({"status": "OPEN_AP_POC_ARMED",
                          "ssid": ready_event.get("ssid"),
                          "ap_ip": ready_event.get("ap_ip"),
                          "channel": ready_event.get("actual_channel"),
                          "bandwidth_mhz": ready_event.get("bandwidth_mhz"),
                          "udp_port": 39001,
                          "jetson_network_changed": False}, ensure_ascii=False), flush=True)
        while final is None:
            now = time.monotonic()
            if now - start >= args.max_duration:
                stop_reason = "duration_limit"
                break
            if args.stop_file.exists():
                if args.stop_file.read_text(encoding="utf-8").strip() == "STOP":
                    stop_reason = "local_stop_file"
                    break
            chunk = s.read(max(1, min(65536, s.in_waiting)))
            rows = consume(chunk, raw, records, times)
            for row in rows:
                counters = row.get("counters", {})
                if counters.get("event") in ("OPEN_AP_STATS", "OPEN_AP_FINAL_STATS"):
                    open_stats = counters
                    if any(counters.get(key, 0) for key in DEVICE_ERRORS):
                        stop_reason = "device_resource_error"
                        break
            if stop_reason:
                break
            if any(decoder.counts.get(key, 0) for key in TRANSPORT_ERRORS):
                stop_reason = "transport_error"
                break
        if mode_armed and final is None:
            send("MODE STOP")
            stop_deadline = time.monotonic() + 15
            while final is None and time.monotonic() < stop_deadline:
                consume(s.read(max(1, min(65536, s.in_waiting))), raw, records, times)
        if final is None:
            raise RuntimeError("missing firmware FINAL after bounded STOP")

    transport = decoder.finish()
    summary = {
        "firmware": ready.get("version"),
        "mode": "OPEN_AP_POC",
        "ssid": ready_event.get("ssid") if ready_event else None,
        "ap_ip": ready_event.get("ap_ip") if ready_event else None,
        "actual_channel": ready_event.get("actual_channel") if ready_event else None,
        "bandwidth_mhz": ready_event.get("bandwidth_mhz") if ready_event else None,
        "channel_readback_ok": ready_event.get("channel_readback_ok") if ready_event else False,
        "station_connected": open_stats.get("station_connected", False),
        "counters": open_stats,
        "record_counts": record_counts,
        "transport_errors": {key: transport.get(key, 0) for key in TRANSPORT_ERRORS},
        "final_received": bool(final),
        "stop_reason": stop_reason,
        "jetson_network_changed_by_capture_tool": False,
        "scope": "Local ESP SoftAP/UDP/CSI capture only; no Jetson network operation is performed by this tool.",
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.sender_log:
        result = analyze_capture(args.sender_log, args.output)
        write_outputs(result, args.output / "analysis")
        summary["offline_analysis"] = {key: result[key] for key in
                                       ("sender_expected_unique", "esp_udp_rx_total",
                                        "esp_udp_valid", "esp_udp_crc_ok",
                                        "csi_data_total", "csi_data_unique_packet_ids",
                                        "end_to_end_packet_ids", "minimal_poc_pass")}
        (args.output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in
                      ("final_received", "stop_reason", "record_counts",
                       "transport_errors", "offline_analysis") if key in summary},
                     ensure_ascii=False), flush=True)
    return 0 if final and not any(summary["transport_errors"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
