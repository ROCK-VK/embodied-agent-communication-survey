"""Offline decoding and packet-ID analysis for the OPEN_AP_POC capture path."""
import csv
import json
import struct
import argparse
from collections import Counter, defaultdict
from pathlib import Path

from udp_probe_protocol import PacketError, decode_packet
from wire8c import assemble_api_parts, parse_header

UDP_PORT = 39001
SNAP_IPV4 = bytes.fromhex("aaaa030000000800")
CSV_FIELDS = ("run_id", "packet_id", "csi_record_serial", "rx_seq", "rx_ts",
              "src", "dst", "phy", "rssi", "csi_len", "crc_ok", "csi_valid")


def extract_udp(frame, expected_port=UDP_PORT):
    """Return a structurally complete IPv4 UDP payload from a clear MPDU."""
    h = parse_header(frame)
    if h["protected"] or h["more_fragments"] or h["fragment"] or h["amsdu"]:
        raise ValueError("protected, fragmented, or A-MSDU MPDU")
    body = frame[h["header_len"]:]
    if len(body) < 8 or body[:8] != SNAP_IPV4:
        raise ValueError("not LLC/SNAP IPv4")
    ip = body[8:]
    if len(ip) < 20 or ip[0] >> 4 != 4:
        raise ValueError("short or non-IPv4 packet")
    ihl = (ip[0] & 15) * 4
    total = int.from_bytes(ip[2:4], "big")
    if ihl < 20 or total < ihl + 8 or total > len(ip) or ip[9] != 17:
        raise ValueError("invalid IPv4/UDP lengths or protocol")
    if int.from_bytes(ip[6:8], "big") & 0x3FFF:
        raise ValueError("fragmented IPv4 packet")
    udp = ip[ihl:total]
    src_port, dst_port, udp_len = struct.unpack_from(">HHH", udp)
    if udp_len < 8 or udp_len != len(udp):
        raise ValueError("invalid UDP length")
    if dst_port != expected_port:
        raise ValueError("UDP destination port mismatch")
    return {"src_port": src_port, "dst_port": dst_port, "payload": udp[8:],
            "mac_header": h}


def decode_csi_data(record, expected_port=UDP_PORT):
    """Decode CSID only from a complete, CSI-valid frame in its atomic record."""
    if record.get("event") != "CSI_DATA":
        raise ValueError("not CSI_DATA")
    if not record.get("csi_valid"):
        raise ValueError("CSI is not valid")
    if record.get("truncated") or not record.get("payload_complete") or not record.get("csi_complete"):
        raise ValueError("truncated CSI_DATA")
    frame = assemble_api_parts(record)
    udp = extract_udp(frame, expected_port)
    datagram = udp["payload"]
    if not datagram.startswith(b"CSID"):
        raise ValueError("UDP payload has no CSID magic")
    packet = decode_packet(datagram)
    return {**packet, "src_port": udp["src_port"], "dst_port": udp["dst_port"],
            "mac_header": udp["mac_header"], "frame": frame}


def csi_data_has_csid_magic(record, expected_port=UDP_PORT):
    """Check for an actual CSID UDP payload, independent of its CRC validity."""
    if record.get("event") != "CSI_DATA" or record.get("truncated"):
        return False
    if not record.get("payload_complete"):
        return False
    try:
        frame = assemble_api_parts(record)
        udp = extract_udp(frame, expected_port)
    except (ValueError, KeyError, TypeError):
        return False
    return udp["payload"].startswith(b"CSID")


def _read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                value = json.loads(line)
            except ValueError as exc:
                raise ValueError("{}:{}: {}".format(path, number, exc)) from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def analyze_rows(sender_rows, capture_rows, counters=None, expected_port=UDP_PORT):
    """Join only exact (run_id, packet_id) values present in all three sources."""
    counters = counters or {}
    sends = [r for r in sender_rows if r.get("event") == "SEND"]
    sent_by_id = {}
    for r in sends:
        key = (r.get("run_id"), r.get("packet_id"))
        sent_by_id.setdefault(key, r)
    expected_ids = set(sent_by_id)

    udp_rows = []
    for row in capture_rows:
        event = row.get("event")
        payload = row.get("counters", {}) if event in ("CONTROL", "STATS", "FINAL") else {}
        if payload.get("event") == "UDP_RX":
            udp_rows.append(payload)
    udp_valid_ids = {(r.get("run_id"), r.get("packet_id")) for r in udp_rows
                     if r.get("valid") and r.get("crc_ok")}
    udp_unique_ids = {(r.get("run_id"), r.get("packet_id")) for r in udp_rows
                      if r.get("valid") and r.get("crc_ok") and not r.get("duplicate")}

    csi_rows = [r for r in capture_rows if r.get("event") == "CSI_DATA"]
    csi_ids = defaultdict(list)
    csi_invalid = Counter()
    csi_magic_records = 0
    for r in csi_rows:
        if csi_data_has_csid_magic(r, expected_port):
            csi_magic_records += 1
        try:
            decoded = decode_csi_data(r, expected_port)
        except (ValueError, PacketError) as exc:
            reason = str(exc)
            if reason == "UDP payload has no CSID magic":
                continue
            csi_invalid[reason] += 1
            continue
        key = (decoded["run_id"], decoded["packet_id"])
        csi_ids[key].append((r, decoded))

    csi_valid_ids = set(csi_ids)
    end_to_end = expected_ids & udp_valid_ids & csi_valid_ids
    rows = []
    for key, matches in sorted(csi_ids.items()):
        run_id, packet_id = key
        for record, decoded in matches:
            header = decoded["mac_header"]
            rows.append({
                "run_id": run_id,
                "packet_id": packet_id,
                "csi_record_serial": record.get("record_serial"),
                "rx_seq": record.get("rx_seq"),
                "rx_ts": record.get("timestamp"),
                "src": header.get("ta"),
                "dst": header.get("ra"),
                "phy": record.get("format"),
                "rssi": record.get("rssi"),
                "csi_len": record.get("csi_len"),
                "crc_ok": True,
                "csi_valid": bool(record.get("csi_valid")),
            })

    csi_multi = {key: len(rows_for_id) for key, rows_for_id in csi_ids.items() if len(rows_for_id) > 1}
    result = {
        "sender_expected_unique": len(expected_ids),
        "sender_datagrams_sent": len(sends),
        "esp_udp_rx_total": counters.get("udp_rx_total", len(udp_rows)),
        "esp_udp_valid": counters.get("udp_valid", sum(bool(r.get("valid")) for r in udp_rows)),
        "esp_udp_crc_ok": counters.get("udp_crc_ok", sum(bool(r.get("crc_ok")) for r in udp_rows)),
        "esp_udp_crc_fail": counters.get("udp_crc_fail", sum(not bool(r.get("crc_ok")) for r in udp_rows)),
        "esp_udp_duplicate_packet_id": counters.get("udp_duplicate_packet_id",
                                                       sum(bool(r.get("duplicate")) for r in udp_rows)),
        "esp_udp_unique_ids": len(udp_unique_ids),
        "esp_udp_missing_ids": sorted([{"run_id": rid, "packet_id": pid}
                                        for rid, pid in expected_ids - udp_valid_ids],
                                       key=lambda x: (x["run_id"], x["packet_id"])),
        "csi_data_total": len(csi_rows),
        "csi_data_valid": sum(bool(r.get("csi_valid")) for r in csi_rows),
        "csi_data_csid_magic_records": csi_magic_records,
        "csi_data_unique_packet_ids": len(csi_valid_ids),
        "csi_data_packet_id_records": sum(len(v) for v in csi_ids.values()),
        "packet_ids_with_multiple_csi_records": len(csi_multi),
        "multiple_csi_records_per_packet_id": [
            {"run_id": rid, "packet_id": pid, "csi_records": count}
            for (rid, pid), count in sorted(csi_multi.items())],
        "sender_and_esp_received_ids": len(expected_ids & udp_valid_ids),
        "end_to_end_packet_ids": [
            {"run_id": rid, "packet_id": pid, "csi_records": len(csi_ids[(rid, pid)])}
            for rid, pid in sorted(end_to_end)],
        "packet_id_to_csi_csv_rows": rows,
        "csi_reject_counts": dict(sorted(csi_invalid.items())),
        "minimal_poc_pass": bool(end_to_end),
        "interpretation": ("At least one sender-verified packet ID was received by ESP and recovered "
                           "from a CSI-valid atomic CSI_DATA record." if end_to_end else
                           "No complete sender → ESP UDP → same CSI_DATA packet-ID/valid-CSI chain was proven."),
    }
    return result


def analyze_capture(sender_path, capture_dir, expected_port=UDP_PORT):
    capture_dir = Path(capture_dir)
    sender_rows = _read_jsonl(sender_path)
    capture_rows = _read_jsonl(capture_dir / "records.jsonl")
    capture_summary = json.loads((capture_dir / "summary.json").read_text(encoding="utf-8"))
    result = analyze_rows(sender_rows, capture_rows, capture_summary.get("counters", {}), expected_port)
    result["channel"] = capture_summary.get("actual_channel")
    result["station_connected"] = capture_summary.get("station_connected")
    result["station_ip_assigned"] = capture_summary.get("station_ip_assigned")
    return result


def write_outputs(result, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "open_ap_summary.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "packet_id_to_csi_csv_rows"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "packet_id_to_csi.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(result["packet_id_to_csi_csv_rows"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sender-log", required=True, type=Path)
    parser.add_argument("--capture-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--port", type=int, default=UDP_PORT)
    args = parser.parse_args()
    result = analyze_capture(args.sender_log, args.capture_dir, args.port)
    write_outputs(result, args.output_dir)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("packet_id_to_csi_csv_rows",)}, ensure_ascii=False))
    return 0 if result["minimal_poc_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
