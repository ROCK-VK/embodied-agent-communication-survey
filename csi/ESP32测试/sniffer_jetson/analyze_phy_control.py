"""Audit a completed passive PHY control run; no radio or network operations."""
import argparse
import collections
import json
from pathlib import Path

FORMAT_NAMES = {0: "11b", 1: "legacy 11a/11g", 2: "HT", 3: "VHT",
                4: "HE_SU", 5: "HE_MU", 6: "HE_ERSU", 7: "HE_TB", 11: "VHT_MU"}
SOURCE = "https://github.com/espressif/esp-idf/blob/v5.5.5/components/esp_wifi/include/esp_wifi_he_types.h"


def distribution(rows, field):
    return dict(collections.Counter(str(r.get(field)) for r in rows))


def key(row):
    return tuple(row.get(k) for k in ("timestamp", "ta", "fc", "seq_ctrl"))


def audit(capture, target):
    records = [json.loads(l) for l in (capture / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    host = json.loads((capture / "summary.json").read_text(encoding="utf-8"))
    frames = [r for r in records if r.get("event") == "FRAME" and r.get("target")]
    csi = [r for r in records if r.get("event") == "CSI" and r.get("target")]
    valid = [r for r in csi if r.get("source", "").lower() == target.lower()
             and r.get("ta", "").lower() == target.lower()
             and r.get("frame_type") == 2 and r.get("to_ds") == 1 and r.get("from_ds") == 0
             and r.get("estimate_valid") == 1 and r.get("rx_state") == 0
             and r.get("len", 0) > 0 and r.get("copied") == r.get("len")
             and len(r.get("data_hex", "")) == 2 * r["len"]
             and any(bytes.fromhex(r["data_hex"])[4 if r.get("first_word_invalid") else 0:])]
    fmap, cmap = collections.defaultdict(list), collections.defaultdict(list)
    for r in frames:
        fmap[key(r)].append(r)
    for r in valid:
        cmap[key(r)].append(r)
    shared = set(fmap) & set(cmap)
    unique = [k for k in shared if len(fmap[k]) == len(cmap[k]) == 1]
    unique_ht = [k for k in unique if fmap[k][0].get("format") == cmap[k][0].get("format") == 2]
    final = host["final_stats"]
    # RX second is an 8-bit field, not automatically the channel-setting enum.
    # Nonzero raw FRAME values are retained as uninterpreted diagnostics.
    anomalous = [r for r in frames if r.get("second") != 0]
    duration = host["measured_capture_s"]
    return {
        "capture_scope": "passive sanity only; no active UDP sender or receiver started",
        "ready_version": host["ready_version"],
        "armed": [r for r in records if r.get("event") == "ARMED"],
        "stop_final_received": host["stop_final_received"],
        "duration_s": duration,
        "sender": {"status": "not_run_sanity_export_quality_gate_failed"},
        "receiver": {"status": "not_started"},
        "target_data_frame_callback_count": final["prom_target_data"],
        "valid_target_data_csi_callback_count": final["csi_target_data_valid"],
        "target_data_frame_records": len(frames),
        "target_csi_records": len(csi),
        "valid_source_confirmed_uplink_csi_records": len(valid),
        "generic_shared_metadata_keys": len(shared),
        "generic_one_to_one_metadata_keys": len(unique),
        "one_to_one_both_ht_metadata_keys": len(unique_ht),
        "ambiguous_metadata_keys": len(shared) - len(unique),
        "protected_frame_records": sum(bool(r.get("protected")) for r in frames),
        "protected_csi_records": sum(bool(r.get("protected")) for r in csi),
        "frame_formats_raw": distribution(frames, "format"),
        "frame_secondary_channel_raw": distribution(frames, "second"),
        "frame_nonzero_second_uninterpreted_count": len(anomalous),
        "frame_phy_metadata_warning": "Some FRAME format0 records have nonzero raw second values unlike valid HT CSI. RX second is unsigned8 and its full encoding is not decoded here; do not infer 11b/bandwidth for these rows. No repair/deletion applied.",
        "csi_formats": distribution(csi, "format"),
        "csi_lengths": distribution(csi, "len"),
        "csi_valid": distribution(csi, "estimate_valid"),
        "csi_rx_state": distribution(csi, "rx_state"),
        "csi_first_word_invalid": distribution(csi, "first_word_invalid"),
        "csi_channels": distribution(csi, "channel"),
        "csi_secondary_channel_raw": distribution(csi, "second"),
        "frame_types_subtypes": dict(collections.Counter(f"{r['frame_type']}/{r['subtype']}" for r in frames)),
        "csi_rssi": {"min": min((r["rssi"] for r in csi), default=None), "max": max((r["rssi"] for r in csi), default=None)},
        "frame_drop": final["frame_target_drop"], "csi_drop": final["csi_target_drop"],
        "uart_parse_errors": host["event_counts"].get("json_parse_error", 0),
        "frame_callback_minus_queue_drop": final["prom_target_data"] - final["frame_target_drop"],
        "csi_callback_minus_queue_drop": final["csi_target_data_valid"] - final["csi_target_drop"],
        "observed_callback_valid_data_csi_per_s": final["csi_target_data_valid"] / duration,
        "observed_recorded_valid_data_csi_per_s": len(valid) / duration,
        "classification": "HT_Data_and_valid_HT_CSI_observed; full_UDP_control_not_run",
        "format_enum_source": SOURCE, "format_names": FORMAT_NAMES,
        "width_scope": "HT class is directly identified by format=2. second=0/len114 plus Jetson width state are consistent with HT20; no extra SIG bandwidth decoder or IQ layout assumption applied.",
        "sanity_reception_validity_passed": bool(unique_ht) and len(valid) == len(csi),
        "sanity_export_quality_passed": final["frame_target_drop"] == final["csi_target_drop"] == 0,
        "full_trial_status": "stopped_before_active_UDP_due_to_heavy_export_loss",
        "final_device_counters": final,
        "limits": ["Queued-out records have no retained PHY distribution.",
                   "Callback and recorded rates are different; neither is a Wi-Fi capture rate.",
                   "Host summary protected counters omit drain-phase records; this audit counts all saved records.",
                   "No business packet-ID association or decryption attempted."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--target-mac", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.capture, args.target_mac)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ("classification", "target_data_frame_records",
          "valid_source_confirmed_uplink_csi_records", "generic_one_to_one_metadata_keys",
          "one_to_one_both_ht_metadata_keys", "frame_drop", "csi_drop", "full_trial_status")}, ensure_ascii=False))
