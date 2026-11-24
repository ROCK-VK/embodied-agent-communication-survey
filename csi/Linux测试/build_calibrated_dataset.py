"""Build unified clock-calibrated (t, x, y, visual, LiDAR, complex CSI) dataset.

Reads:
- Sender directory (sender_manifest.json, sender_packets.jsonl, frame_*_meta.json, samples)
- Receiver directory (receiver_packets.jsonl, receiver_summary.json)
- Verified CSI matches (multimodal_verified_private.json, crosscheck_private.json)
- Raw .csi file (for RxSBasic systemTime and AX210 CSI v4 complex matrix)
- Optional before/after Jetson<->Linux UDP clock calibration JSON files

Outputs (private):
- packet_calibrated_csi_private.csv
- frame_multimodal_csi_private.csv
- csi_complex_private.npz  (csi: (M,2,242) complex128 + aligned metadata arrays)
- calibrated_dataset_summary.json
"""
import argparse
import collections
import csv
import hashlib
import json
import math
import pathlib
import statistics
import struct
import zlib

import numpy as np

CSI_FMT = "<HBbHQQIHBBBHBhI"


def read_selected_csi_flexible(csi_path, indexes):
    """Read AX210 CSI v4 records of any tone count (e.g., VHT 242 or NonHT 52).

    Preserves exact official RXS-Parsing-Core I/Q order (int16 imag then real).
    Returns dict[record_idx] = (z_rx_tones, system_ns, meta_dict).
    """
    data = csi_path.read_bytes()
    pos = 0
    idx = 0
    results = {}
    sz = struct.calcsize(CSI_FMT)
    while pos < len(data):
        n, magic, version, nseg = struct.unpack_from("<IIHB", data, pos)
        end = pos + 4 + n
        if magic != 0x20150315 or end > len(data):
            raise ValueError(f"bad RxFrame at {idx}")
        if idx in indexes:
            q = pos + (11 if version == 1 else 13)
            segs = {}
            for _ in range(nseg):
                slen = struct.unpack_from("<I", data, q)[0]
                lim = q + 4 + slen
                nl = data[q + 4]
                name = data[q + 5 : q + 5 + nl].rstrip(b"\0").decode("ascii")
                ver = struct.unpack_from("<H", data, q + 5 + nl)[0]
                segs[name] = (ver, data[q + 7 + nl : lim])
                q = lim
            v, c = segs["CSI"]
            fields = struct.unpack_from(CSI_FMT, c)
            dev, fw, fmt, bw, freq, rate, sub, tones, tx, rx, ess, ncsi, ant, offset, rawlen = fields
            if v != 4 or tx != 1 or rx != 2 or rawlen != tones * tx * rx * 4:
                raise ValueError(f"unsupported CSI v={v} tones={tones} tx={tx} rx={rx} rawlen={rawlen}")
            raw = c[sz:]
            iq = np.frombuffer(raw, dtype="<i2").reshape(rx, tx, tones, 2)
            z = iq[..., 1].astype(np.float64) + 1j * iq[..., 0].astype(np.float64)
            rv, rb = segs["RxSBasic"]
            t_sys = struct.unpack_from("<Q", rb, 10)[0] if rv >= 4 else None
            results[idx] = (
                z[:, 0, :],
                t_sys,
                {"format": int(fmt), "cbw_mhz": int(bw), "num_tones": int(tones), "rx": int(rx), "tx": int(tx)},
            )
        pos = end
        idx += 1
    return results


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def compute_clock_calibration(sync_before, sync_after):
    """Combine before/after Linux-minus-Jetson wall offsets and compute uncertainty."""
    offsets = []
    uncertainties = []
    details = {}
    for label, doc in (("before", sync_before), ("after", sync_after)):
        if doc is None:
            continue
        off_ms = doc["offset_best_rtt_median_ms"]
        unc_ms = doc["uncertainty_half_min_rtt_ms"]
        offsets.append(off_ms)
        uncertainties.append(unc_ms)
        details[label] = {
            "offset_linux_minus_jetson_ms": off_ms,
            "uncertainty_half_min_rtt_ms": unc_ms,
            "rtt_min_ms": doc["rtt_min_ms"],
            "rtt_median_ms": doc["rtt_median_ms"],
        }
    if not offsets:
        return {
            "calibrated": False,
            "offset_linux_minus_jetson_ms": None,
            "uncertainty_ms": None,
            "details": details,
        }
    mean_off = sum(offsets) / len(offsets)
    drift_half = abs(offsets[-1] - offsets[0]) / 2.0 if len(offsets) >= 2 else 0.0
    total_unc = max(uncertainties) + drift_half
    return {
        "calibrated": True,
        "offset_linux_minus_jetson_ms": mean_off,
        "offset_linux_minus_jetson_ns": int(round(mean_off * 1e6)),
        "uncertainty_ms": total_unc,
        "drift_between_before_after_ms": (offsets[-1] - offsets[0]) if len(offsets) >= 2 else 0.0,
        "sign_convention": "t_csi_aligned_jetson_wall_ns = csi_receiver_system_ns - offset_linux_minus_jetson_ns",
        "details": details,
    }


def build_dataset(source_dir, rx_dir, work_dir, csi_file, out_dir, sync_before=None, sync_after=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_json(source_dir / "sender_manifest.json")
    sender_rows = read_jsonl(source_dir / "sender_packets.jsonl")
    rx_rows = read_jsonl(rx_dir / "receiver_packets.jsonl")
    verified = read_json(work_dir / "multimodal_verified_private.json")
    crosscheck = read_json(work_dir / "crosscheck_private.json")
    run_id = manifest["run_id"]

    clock_cal = compute_clock_calibration(sync_before, sync_after)
    offset_ns = clock_cal["offset_linux_minus_jetson_ns"] if clock_cal["calibrated"] else None

    # Validate sender & receiver integrity
    samples_by_id = {s["sample_id"]: s for s in manifest["samples"]}
    for sid, s in samples_by_id.items():
        raw = (source_dir / s["filename"]).read_bytes()
        if len(raw) != s["size"] or hashlib.sha256(raw).hexdigest() != s["sha256"]:
            raise ValueError(f"source sample {sid} SHA-256 mismatch")
        rx_bin = rx_dir / f"sample_{sid}.bin"
        if rx_bin.exists():
            rx_raw = rx_bin.read_bytes()
            if hashlib.sha256(rx_raw).hexdigest() != s["sha256"]:
                raise ValueError(f"received sample {sid} SHA-256 mismatch")
            # For compressed LiDAR, verify lossless decompression matches raw file SHA-256
            if s["kind"] in (2, 5):
                raw_name = s["filename"].replace("_lidar.zlib", "_lidar_raw.bin").replace("_lidar.m36d", "_lidar_raw.bin")
                raw_path = source_dir / raw_name
                if raw_path.exists():
                    if s["kind"] == 5:
                        import mid360_codec as m360
                        decomp = m360.decode_mid360_lossless(rx_raw)
                    else:
                        decomp = zlib.decompress(rx_raw)
                    if hashlib.sha256(decomp).hexdigest() != hashlib.sha256(raw_path.read_bytes()).hexdigest():
                        raise ValueError(f"decompressed LiDAR sample {sid} mismatch")

    send_by_pid = {r["packet_id"]: r for r in sender_rows}
    rx_by_pid = collections.defaultdict(list)
    for r in rx_rows:
        rx_by_pid[r["packet_id"]].append(r)

    cross_lookup = {(c["packet_id"], c["record"], c["csi_frame"]): c for c in crosscheck}
    matches_by_pid = collections.defaultdict(list)
    record_ids = set()
    for r in verified["rows"]:
        c = cross_lookup.get((r["packet_id"], r["record"], r["pcap_frame"]))
        if not c or len(c["matching_pcap_frames"]) < 1:
            raise ValueError(f"missing PCAP crosscheck for packet_id={r['packet_id']} record={r['record']}")
        matches_by_pid[r["packet_id"]].append(r)
        record_ids.add(r["record"])

    # Extract complex CSI matrices for all verified records (in sorted record order)
    selected_csi = read_selected_csi_flexible(csi_file, record_ids)
    ordered_records = sorted(record_ids)
    rec_to_arr_idx = {rec: i for i, rec in enumerate(ordered_records)}

    max_tones = max((selected_csi[rec][2]["num_tones"] for rec in ordered_records), default=242)
    csi_stack = np.full((len(ordered_records), 2, max_tones), np.nan + 1j * np.nan, dtype=np.complex128)
    csi_num_tones = np.zeros(len(ordered_records), dtype=np.int32)
    csi_format = np.zeros(len(ordered_records), dtype=np.int32)
    csi_cbw_mhz = np.zeros(len(ordered_records), dtype=np.int32)
    tone_counts_hist = collections.Counter()
    all_valid_finite = True
    for i, rec in enumerate(ordered_records):
        mat, _, cmeta = selected_csi[rec]
        nt = cmeta["num_tones"]
        csi_stack[i, :, :nt] = mat
        csi_num_tones[i] = nt
        csi_format[i] = cmeta["format"]
        csi_cbw_mhz[i] = cmeta["cbw_mhz"]
        tone_counts_hist[f"fmt{cmeta['format']}_bw{cmeta['cbw_mhz']}_tones{nt}"] += 1
        if not np.isfinite(mat).all():
            all_valid_finite = False

    csi_sys_ns = np.array([selected_csi[rec][1] for rec in ordered_records], dtype=np.int64)
    csi_aligned_ns = (csi_sys_ns - offset_ns) if offset_ns is not None else np.full(len(ordered_records), -1, dtype=np.int64)

    # Map each record back to its packet metadata for NPZ alignment
    rec_to_pkt = {}
    for pid, mlist in matches_by_pid.items():
        for m in mlist:
            rec_to_pkt[m["record"]] = send_by_pid[pid]

    npz_packet_ids = np.array([rec_to_pkt[rec]["packet_id"] for rec in ordered_records], dtype=np.int64)
    npz_frame_idx = np.array([rec_to_pkt[rec].get("frame_idx", 0) for rec in ordered_records], dtype=np.int32)
    npz_sample_kind = np.array([rec_to_pkt[rec]["kind"] for rec in ordered_records], dtype=np.int32)

    def pose_fields(row):
        ps = row.get("pose_at_send") or {}
        if not ps.get("available"):
            return (math.nan, math.nan, math.nan, math.nan, math.nan, math.nan, None, None, None)
        obs = ps["observation"]
        pos = obs["position"]
        vel = obs.get("velocity") or [math.nan, math.nan, math.nan]
        rpy = obs.get("rpy")
        yaw = rpy[2] if rpy and len(rpy) >= 3 else math.nan
        st = obs["stamp"]
        return (
            pos[0],
            pos[1],
            pos[2],
            yaw,
            vel[0],
            vel[1],
            ps["age_ns"],
            st["sec"] * 10**9 + st["nanosec"],
            obs["receipt"]["monotonic_ns"],
        )

    npz_pos = np.full((len(ordered_records), 4), np.nan, dtype=np.float64)
    for i, rec in enumerate(ordered_records):
        px, py, pz, yaw, *_ = pose_fields(rec_to_pkt[rec])
        npz_pos[i] = [px, py, pz, yaw]

    np.savez_compressed(
        out_dir / "csi_complex_private.npz",
        csi=csi_stack,
        csi_num_tones=csi_num_tones,
        csi_format=csi_format,
        csi_cbw_mhz=csi_cbw_mhz,
        record=np.array(ordered_records, dtype=np.int64),
        packet_id=npz_packet_ids,
        frame_idx=npz_frame_idx,
        sample_kind=npz_sample_kind,
        csi_receiver_system_ns=csi_sys_ns,
        csi_aligned_jetson_wall_ns=csi_aligned_ns,
        pose_xyzyaw=npz_pos,
    )

    # 1. Packet-level calibrated CSV
    pkt_csv_path = out_dir / "packet_calibrated_csi_private.csv"
    pkt_fields = [
        "run_id",
        "frame_idx",
        "sample_id",
        "sample_kind",
        "chunk_index",
        "chunk_count",
        "repeat",
        "packet_id",
        "send_wall_ns",
        "send_mono_ns",
        "pos_x",
        "pos_y",
        "pos_z",
        "yaw_rad",
        "vel_x",
        "vel_y",
        "pose_age_ms",
        "robot_stamp_ns",
        "csi_matched",
        "csi_record",
        "csi_array_index",
        "csi_retry",
        "csi_receiver_system_ns",
        "csi_aligned_jetson_wall_ns",
        "csi_minus_send_calibrated_ms",
        "clock_uncertainty_ms",
    ]
    kind_names = {1: "rgb", 2: "lidar_zlib", 3: "meta", 4: "lidar_raw", 5: "lidar_delta"}
    cal_air_diffs_ms = []
    pose_ages_ms = []

    with pkt_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=pkt_fields)
        w.writeheader()
        for row in sorted(sender_rows, key=lambda r: r["packet_id"]):
            pid = row["packet_id"]
            px, py, pz, yaw, vx, vy, age_ns, rstamp_ns, _ = pose_fields(row)
            if age_ns is not None:
                pose_ages_ms.append(age_ns / 1e6)
            mlist = sorted(matches_by_pid.get(pid, []), key=lambda x: x["record"])
            base = {
                "run_id": run_id,
                "frame_idx": row.get("frame_idx", 0),
                "sample_id": row["sample_id"],
                "sample_kind": kind_names.get(row["kind"], str(row["kind"])),
                "chunk_index": row["chunk_index"],
                "chunk_count": row["chunk_count"],
                "repeat": row.get("repeat", 0),
                "packet_id": pid,
                "send_wall_ns": row["wall_ns"],
                "send_mono_ns": row["send_mono_ns"],
                "pos_x": "" if math.isnan(px) else f"{px:.6f}",
                "pos_y": "" if math.isnan(py) else f"{py:.6f}",
                "pos_z": "" if math.isnan(pz) else f"{pz:.6f}",
                "yaw_rad": "" if math.isnan(yaw) else f"{yaw:.6f}",
                "vel_x": "" if math.isnan(vx) else f"{vx:.6f}",
                "vel_y": "" if math.isnan(vy) else f"{vy:.6f}",
                "pose_age_ms": "" if age_ns is None else f"{age_ns / 1e6:.3f}",
                "robot_stamp_ns": "" if rstamp_ns is None else str(rstamp_ns),
                "clock_uncertainty_ms": (
                    f"{clock_cal['uncertainty_ms']:.3f}" if clock_cal["calibrated"] else ""
                ),
            }
            if not mlist:
                w.writerow({
                    **base,
                    "csi_matched": 0,
                    "csi_record": "",
                    "csi_array_index": "",
                    "csi_retry": "",
                    "csi_receiver_system_ns": "",
                    "csi_aligned_jetson_wall_ns": "",
                    "csi_minus_send_calibrated_ms": "",
                })
            else:
                for m in mlist:
                    rec = m["record"]
                    arr_idx = rec_to_arr_idx[rec]
                    sys_ns = int(selected_csi[rec][1])
                    al_ns = (sys_ns - offset_ns) if offset_ns is not None else None
                    diff_ms = (al_ns - row["wall_ns"]) / 1e6 if al_ns is not None else None
                    if diff_ms is not None:
                        cal_air_diffs_ms.append(diff_ms)
                    w.writerow({
                        **base,
                        "csi_matched": 1,
                        "csi_record": rec,
                        "csi_array_index": arr_idx,
                        "csi_retry": int(bool(m.get("retry"))),
                        "csi_receiver_system_ns": sys_ns,
                        "csi_aligned_jetson_wall_ns": "" if al_ns is None else al_ns,
                        "csi_minus_send_calibrated_ms": "" if diff_ms is None else f"{diff_ms:.3f}",
                    })

    # 2. Frame-level multimodal summary CSV
    frame_csv_path = out_dir / "frame_multimodal_csi_private.csv"
    frame_fields = [
        "run_id",
        "frame_idx",
        "cam_color_frame_num",
        "cam_global_time_ms",
        "cam_receipt_wall_ns",
        "cam_to_lidar_start_ms",
        "lidar_points",
        "lidar_span_ms",
        "lidar_start_wall_ns",
        "lidar_end_wall_ns",
        "tx_start_wall_ns",
        "tx_end_wall_ns",
        "tx_duration_ms",
        "capture_pos_x",
        "capture_pos_y",
        "capture_pos_z",
        "capture_yaw_rad",
        "tx_pos_disp_mm",
        "rgb_chunks_with_csi",
        "rgb_chunks_total",
        "lidar_chunks_with_csi",
        "lidar_chunks_total",
        "frame_packets_sent",
        "frame_packets_csi_matched",
        "frame_csi_coverage_pct",
        "csi_array_indices_json",
    ]
    frame_summaries = []
    with frame_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=frame_fields)
        w.writeheader()
        for fm in manifest.get("frames", []):
            fidx = fm["frame_idx"]
            meta_file = source_dir / f"frame_{fidx:03d}_meta.json"
            fmeta = read_json(meta_file) if meta_file.exists() else {}
            fpkts = [r for r in sender_rows if r.get("frame_idx", 0) == fidx]
            fpkts.sort(key=lambda r: r["packet_id"])
            matched_pids = [r["packet_id"] for r in fpkts if r["packet_id"] in matches_by_pid]
            arr_indices = sorted({
                rec_to_arr_idx[m["record"]]
                for pid in matched_pids
                for m in matches_by_pid[pid]
            })
            rgb_total = max((r["chunk_count"] for r in fpkts if r["kind"] == 1), default=0)
            rgb_cov = len({r["chunk_index"] for r in fpkts if r["kind"] == 1 and r["packet_id"] in matches_by_pid})
            lid_total = max((r["chunk_count"] for r in fpkts if r["kind"] in (2, 5)), default=0)
            lid_cov = len({r["chunk_index"] for r in fpkts if r["kind"] in (2, 5) and r["packet_id"] in matches_by_pid})

            cam = fmeta.get("camera", {})
            lid = fmeta.get("lidar", {})
            cam_rx_m = cam.get("frameset_receipt", {}).get("monotonic_ns")
            lid_first = lid.get("first_packet") or {}
            lid_last = lid.get("last_packet") or {}
            cam_to_lid_ms = (
                (lid_first["rx_mono_ns"] - cam_rx_m) / 1e6
                if cam_rx_m is not None and "rx_mono_ns" in lid_first
                else None
            )

            pc = (fmeta.get("pose_at_camera_receipt") or {}).get("observation") or {}
            cpos = pc.get("position") or [math.nan, math.nan, math.nan]
            crpy = pc.get("rpy")
            cyaw = crpy[2] if crpy and len(crpy) >= 3 else math.nan

            # Displacement during frame transmission
            p0 = pose_fields(fpkts[0]) if fpkts else (math.nan,) * 9
            p1 = pose_fields(fpkts[-1]) if fpkts else (math.nan,) * 9
            disp_mm = (
                math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * 1000.0
                if not (math.isnan(p0[0]) or math.isnan(p1[0]))
                else math.nan
            )

            tx_start = fpkts[0]["wall_ns"] if fpkts else 0
            tx_end = fpkts[-1]["wall_ns"] if fpkts else 0
            cov_pct = (100.0 * len(matched_pids) / len(fpkts)) if fpkts else 0.0
            row_out = {
                "run_id": run_id,
                "frame_idx": fidx,
                "cam_color_frame_num": cam.get("color", {}).get("frame_number", ""),
                "cam_global_time_ms": cam.get("color", {}).get("timestamp_ms", ""),
                "cam_receipt_wall_ns": cam.get("frameset_receipt", {}).get("wall_ns", ""),
                "cam_to_lidar_start_ms": "" if cam_to_lid_ms is None else f"{cam_to_lid_ms:.3f}",
                "lidar_points": lid.get("point_count", ""),
                "lidar_span_ms": f"{lid.get('span_lidar_ms', 0.0):.3f}",
                "lidar_start_wall_ns": lid_first.get("rx_wall_ns", ""),
                "lidar_end_wall_ns": lid_last.get("rx_wall_ns", ""),
                "tx_start_wall_ns": tx_start,
                "tx_end_wall_ns": tx_end,
                "tx_duration_ms": f"{(tx_end - tx_start) / 1e6:.3f}",
                "capture_pos_x": "" if math.isnan(cpos[0]) else f"{cpos[0]:.6f}",
                "capture_pos_y": "" if math.isnan(cpos[1]) else f"{cpos[1]:.6f}",
                "capture_pos_z": "" if math.isnan(cpos[2]) else f"{cpos[2]:.6f}",
                "capture_yaw_rad": "" if math.isnan(cyaw) else f"{cyaw:.6f}",
                "tx_pos_disp_mm": "" if math.isnan(disp_mm) else f"{disp_mm:.3f}",
                "rgb_chunks_with_csi": rgb_cov,
                "rgb_chunks_total": rgb_total,
                "lidar_chunks_with_csi": lid_cov,
                "lidar_chunks_total": lid_total,
                "frame_packets_sent": len(fpkts),
                "frame_packets_csi_matched": len(matched_pids),
                "frame_csi_coverage_pct": f"{cov_pct:.2f}",
                "csi_array_indices_json": json.dumps(arr_indices),
            }
            w.writerow(row_out)
            frame_summaries.append(row_out)

    # 3. Overall calibrated summary JSON
    tx_span_s = (sender_rows[-1]["send_mono_ns"] - sender_rows[0]["send_mono_ns"]) / 1e9 if len(sender_rows) >= 2 else 0.0
    rx_span_s = (rx_rows[-1]["receiver_monotonic_ns"] - rx_rows[0]["receiver_monotonic_ns"]) / 1e9 if len(rx_rows) >= 2 else 0.0
    summary = {
        "run_id": run_id,
        "frames_count": len(manifest.get("frames", [])),
        "packets_sent": len(sender_rows),
        "packets_received_unique": len(rx_by_pid),
        "send_rate_pps": (len(sender_rows) - 1) / tx_span_s if tx_span_s > 0 else 0.0,
        "receive_rate_pps": (len(rx_by_pid) - 1) / rx_span_s if rx_span_s > 0 else 0.0,
        "csi_matched_unique_packets": len(matches_by_pid),
        "csi_matched_records": len(ordered_records),
        "csi_coverage_pct": (100.0 * len(matches_by_pid) / len(sender_rows)) if sender_rows else 0.0,
        "csi_effective_packet_rate_pps": len(matches_by_pid) / tx_span_s if tx_span_s > 0 else 0.0,
        "csi_effective_record_rate_rps": len(ordered_records) / tx_span_s if tx_span_s > 0 else 0.0,
        "csi_complex_shape": list(csi_stack.shape),
        "csi_all_finite": bool(all_valid_finite),
        "csi_format_distribution": dict(tone_counts_hist),
        "pose_age_median_ms": statistics.median(pose_ages_ms) if pose_ages_ms else None,
        "pose_age_max_ms": max(pose_ages_ms) if pose_ages_ms else None,
        "clock_calibration": clock_cal,
        "calibrated_csi_minus_send_ms": {
            "count": len(cal_air_diffs_ms),
            "min": min(cal_air_diffs_ms),
            "median": statistics.median(cal_air_diffs_ms),
            "max": max(cal_air_diffs_ms),
            "std": statistics.stdev(cal_air_diffs_ms) if len(cal_air_diffs_ms) > 1 else 0.0,
        } if cal_air_diffs_ms else None,
        "robot_clock_fit": manifest.get("robot_clock_fit"),
        "frames": frame_summaries,
    }
    (out_dir / "calibrated_dataset_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=pathlib.Path, required=True)
    p.add_argument("--rx", type=pathlib.Path, required=True)
    p.add_argument("--work", type=pathlib.Path, required=True)
    p.add_argument("--csi", type=pathlib.Path, required=True)
    p.add_argument("--out", type=pathlib.Path, required=True)
    p.add_argument("--sync-before", type=pathlib.Path, default=None)
    p.add_argument("--sync-after", type=pathlib.Path, default=None)
    args = p.parse_args()

    sb = read_json(args.sync_before) if args.sync_before and args.sync_before.exists() else None
    sa = read_json(args.sync_after) if args.sync_after and args.sync_after.exists() else None
    summary = build_dataset(args.source, args.rx, args.work, args.csi, args.out, sync_before=sb, sync_after=sa)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
