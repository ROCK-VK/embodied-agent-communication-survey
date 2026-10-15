#!/usr/bin/env python3
"""Join sender/receiver logs with app-ID-bearing Wi-Fi frames and CSI callbacks."""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise ValueError("{}:{}: {}".format(path, number, exc))
    return rows


def frame_key(row):
    fields = ("timestamp", "ta", "fc", "seq_ctrl")
    if any(row.get(field) is None for field in fields):
        return None
    return tuple(row[field] for field in fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sender", required=True, type=Path)
    parser.add_argument("--receiver", required=True, type=Path)
    parser.add_argument("--capture", required=True, type=Path, help="directory written by capture_packet_id.py")
    parser.add_argument("--output", required=True, type=Path, help="new JSON summary path")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output file already exists; choose a new path")

    sends = [row for row in jsonl(args.sender) if row.get("event") == "SEND"]
    receives = [row for row in jsonl(args.receiver) if row.get("event") == "RX"]
    capture = jsonl(args.capture / "records.jsonl")
    expected = {(row.get("run_id"), row.get("packet_id")) for row in sends}
    received = {(row.get("run_id"), row.get("packet_id")) for row in receives if row.get("status") in ("valid", "duplicate")}
    frames = [row for row in capture if row.get("event") == "FRAME"]
    csi = [row for row in capture if row.get("event") == "CSI"]
    frame_ids = {(row.get("app_run_id"), row.get("app_packet_id")) for row in frames if row.get("app_probe_status") == 4}
    csi_direct_ids = {(row.get("app_run_id"), row.get("app_packet_id")) for row in csi if row.get("app_probe_status") == 4}

    frame_by_key = defaultdict(set)
    for row in frames:
        key = frame_key(row)
        if key is not None and row.get("app_probe_status") == 4:
            frame_by_key[key].add((row.get("app_run_id"), row.get("app_packet_id")))
    joined_by_frame = set()
    joined_pairs = []
    for row in csi:
        key = frame_key(row)
        ids = frame_by_key.get(key, set()) if key is not None else set()
        for packet in ids:
            joined_by_frame.add(packet)
            joined_pairs.append({"run_id": packet[0], "packet_id": packet[1],
                                 "frame_timestamp": key[0], "ta": key[1], "fc": key[2], "seq_ctrl": key[3]})

    protected_frames = sum(bool(row.get("protected")) for row in frames)
    protected_csi = sum(bool(row.get("protected")) for row in csi)
    visible_csi_ids = csi_direct_ids | joined_by_frame
    end_to_end_ids = expected & received & visible_csi_ids
    output = {
        "sender_unique_ids": len(expected),
        "receiver_unique_ids": len(received),
        "receiver_missing_ids": sorted([{"run_id": run, "packet_id": pid} for run, pid in expected - received],
                                        key=lambda item: (item["run_id"], item["packet_id"])),
        "frame_ids_visible": len(frame_ids),
        "csi_ids_visible_directly": len(csi_direct_ids),
        "packet_ids_with_metadata_joined_csi": len(joined_by_frame),
        "sent_and_received_ids": len(expected & received),
        "sent_received_frame_ids": len(expected & received & frame_ids),
        "sent_received_csi_direct_ids": len(expected & received & csi_direct_ids),
        "sent_received_csi_metadata_join_ids": len(expected & received & joined_by_frame),
        "end_to_end_packet_ids": sorted([{"run_id": run, "packet_id": pid} for run, pid in end_to_end_ids],
                                         key=lambda item: (item["run_id"], item["packet_id"])),
        "direct_csi_packet_ids": sorted([{"run_id": run, "packet_id": pid} for run, pid in csi_direct_ids],
                                         key=lambda item: (item["run_id"], item["packet_id"])),
        "frame_to_csi_packet_ids": sorted([{"run_id": run, "packet_id": pid} for run, pid in joined_by_frame],
                                            key=lambda item: (item["run_id"], item["packet_id"])),
        "frame_to_csi_metadata_pairs": joined_pairs,
        "protected_target_data_frames": protected_frames,
        "protected_target_data_csi": protected_csi,
        "interpretation": ("Sent, receiver-validated application packet IDs were linked to CSI." if end_to_end_ids
                           else "No complete sender→receiver→CSI packet-ID chain was observed. Protected-frame payload is skipped by this unassociated sniffer; if the test frames are protected, an explicitly approved test path may be needed." if protected_frames or protected_csi
                           else "No complete sender→receiver→CSI packet-ID chain was observed, and the captured target frames were not marked protected. Payload framing or FRAME/CSI join details remain unverified."),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
