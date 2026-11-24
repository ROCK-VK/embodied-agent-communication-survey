"""Analyze and visualize calibrated dynamic (t, x, y, visual, LiDAR, CSI) trajectory.

Generates:
- Anonymized summary JSON & trajectory-CSI figure (relative coordinates dX, dY in meters
  anchored at frame 0; no raw private room origin, no MAC/IP/SSID).
- Optional private full-coordinate diagnostic summary.
"""
import argparse
import csv
import json
import math
import pathlib
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def analyze(cal_dir, out_dir, label):
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = json.loads((cal_dir / "calibrated_dataset_summary.json").read_text(encoding="utf-8"))
    pkts = list(csv.DictReader((cal_dir / "packet_calibrated_csi_private.csv").open(encoding="utf-8")))
    frames = list(csv.DictReader((cal_dir / "frame_multimodal_csi_private.csv").open(encoding="utf-8")))
    npz = np.load(cal_dir / "csi_complex_private.npz")
    csi = npz["csi"]  # (M, 2, 242) complex128
    arr_pos = npz["pose_xyzyaw"]  # (M, 4)
    arr_t_al = npz["csi_aligned_jetson_wall_ns"]  # (M,)
    arr_fidx = npz["frame_idx"]  # (M,)
    arr_kind = npz["sample_kind"]  # (M,)

    # Anchor relative coordinates at frame 0 capture position
    x0 = float(frames[0]["capture_pos_x"])
    y0 = float(frames[0]["capture_pos_y"])
    t0_ns = int(frames[0]["tx_start_wall_ns"])

    rel_x = arr_pos[:, 0] - x0
    rel_y = arr_pos[:, 1] - y0
    rel_t = (arr_t_al - t0_ns) / 1e9

    # Packet-level trajectory metrics across all sent packets
    all_x = [float(r["pos_x"]) - x0 for r in pkts if r["pos_x"]]
    all_y = [float(r["pos_y"]) - y0 for r in pkts if r["pos_y"]]
    all_t = [(int(r["send_wall_ns"]) - t0_ns) / 1e9 for r in pkts if r["pos_x"]]
    all_spd = [math.hypot(float(r["vel_x"]), float(r["vel_y"])) for r in pkts if r["vel_x"]]

    path_len_m = sum(math.hypot(b1 - a1, b2 - a2) for a1, b1, a2, b2 in zip(all_x, all_x[1:], all_y, all_y[1:]))
    net_disp_m = math.hypot(all_x[-1] - all_x[0], all_y[-1] - all_y[0]) if len(all_x) >= 2 else 0.0

    # Per-frame CSI amplitude & variability stats (using valid non-NaN tones per record)
    mag = np.abs(csi)  # (M, 2, 242)
    med_mag = np.nanmedian(mag, axis=2)  # (M, 2)
    num_tones = npz["csi_num_tones"] if "csi_num_tones" in npz else np.full(len(csi), csi.shape[2], dtype=np.int32)
    vht_mask = num_tones == csi.shape[2]

    frame_stats = []
    for f in frames:
        fidx = int(f["frame_idx"])
        mask = arr_fidx == fidx
        n_csi = int(np.sum(mask))
        fx = float(f["capture_pos_x"]) - x0
        fy = float(f["capture_pos_y"]) - y0
        ft = (int(f["tx_start_wall_ns"]) - t0_ns) / 1e9
        if n_csi >= 2:
            sub = mag[mask & vht_mask]  # (k, 2, 242) VHT-80MHz 242-tone records
            if len(sub) >= 2:
                mean_t = np.mean(sub, axis=0)
                std_t = np.std(sub, axis=0)
                cv_rx0 = float(np.median(std_t[0] / np.maximum(mean_t[0], 1e-9)))
                cv_rx1 = float(np.median(std_t[1] / np.maximum(mean_t[1], 1e-9)))
            else:
                cv_rx0 = cv_rx1 = float("nan")
            med_rx0 = float(np.nanmedian(med_mag[mask, 0]))
            med_rx1 = float(np.nanmedian(med_mag[mask, 1]))
        else:
            cv_rx0 = cv_rx1 = med_rx0 = med_rx1 = float("nan")
        frame_stats.append({
            "frame_idx": fidx,
            "rel_t_s": round(ft, 3),
            "rel_x_m": round(fx, 4),
            "rel_y_m": round(fy, 4),
            "tx_disp_mm": float(f["tx_pos_disp_mm"]),
            "cam_to_lidar_ms": float(f["cam_to_lidar_start_ms"]),
            "lidar_points": int(f["lidar_points"]),
            "rgb_chunks_csi": f"{f['rgb_chunks_with_csi']}/{f['rgb_chunks_total']}",
            "lidar_chunks_csi": f"{f['lidar_chunks_with_csi']}/{f['lidar_chunks_total']}",
            "csi_records": n_csi,
            "coverage_pct": float(f["frame_csi_coverage_pct"]),
            "csi_med_mag_rx1": round(med_rx0, 2) if math.isfinite(med_rx0) else None,
            "csi_med_mag_rx2": round(med_rx1, 2) if math.isfinite(med_rx1) else None,
            "csi_temporal_cv_rx1": round(cv_rx0, 4) if math.isfinite(cv_rx0) else None,
            "csi_temporal_cv_rx2": round(cv_rx1, 4) if math.isfinite(cv_rx1) else None,
        })

    # Plot 3-panel anonymized overview figure
    fig, axes = plt.subplots(3, 1, figsize=(11, 10.5), constrained_layout=True)

    # Panel 1: 2D Relative Trajectory colored by time with frame markers
    sc = axes[0].scatter(rel_x, rel_y, c=rel_t, cmap="viridis", s=12, alpha=0.8, label="CSI-matched packets")
    axes[0].plot(all_x, all_y, color="gray", lw=0.8, alpha=0.5, zorder=0)
    for fs in frame_stats:
        axes[0].scatter([fs["rel_x_m"]], [fs["rel_y_m"]], color="red", s=38, zorder=5, edgecolor="white", linewidth=0.6)
        axes[0].annotate(f"F{fs['frame_idx']}", (fs["rel_x_m"], fs["rel_y_m"]), xytext=(4, 4), textcoords="offset points", fontsize=8)
    cb = fig.colorbar(sc, ax=axes[0])
    cb.set_label("Calibrated time since F0 TX start (s)")
    axes[0].set_aspect("equal", adjustable="datalim")
    axes[0].set(xlabel="Relative odometry X (m)", ylabel="Relative odometry Y (m)", title=f"{label}: Robot 2D Trajectory with CSI-Matched Multimodal Packets (path={path_len_m:.2f} m, net={net_disp_m:.2f} m)")
    axes[0].grid(alpha=0.25)

    # Panel 2: CSI median amplitude (RX1 & RX2) and robot speed over calibrated time
    axes[1].plot(rel_t, med_mag[:, 0], ".", markersize=3, alpha=0.8, label="CSI RX1 median |H|")
    axes[1].plot(rel_t, med_mag[:, 1], ".", markersize=3, alpha=0.8, label="CSI RX2 median |H|")
    axes[1].set(xlabel="Calibrated time (s)", ylabel="CSI median magnitude (raw units)", title="Calibrated CSI Magnitude Evolution & Robot Speed")
    axes[1].grid(alpha=0.25)
    ax_spd = axes[1].twinx()
    ax_spd.plot(all_t, all_spd, color="tab:red", lw=1.1, alpha=0.65, label="Robot speed |v| (m/s)")
    ax_spd.set_ylabel("Robot speed |v| (m/s)", color="tab:red")
    lines1, labels1 = axes[1].get_legend_handles_labels()
    lines2, labels2 = ax_spd.get_legend_handles_labels()
    axes[1].legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=8)

    # Panel 3: Subcarrier amplitude heatmap across VHT-80MHz (242-tone) matched packets (RX1)
    vht_mag = mag[vht_mask, 0, :]
    vht_t = rel_t[vht_mask]
    im = axes[2].imshow(
        vht_mag.T,
        aspect="auto",
        origin="lower",
        extent=[float(vht_t[0]), float(vht_t[-1]), 0, vht_mag.shape[1] - 1],
        cmap="magma",
        interpolation="nearest",
    )
    fig.colorbar(im, ax=axes[2], label="RX1 |H| (raw units)")
    axes[2].set(xlabel="Calibrated time (s)", ylabel="Raw tone ordinal (0..241)", title="RX1 Subcarrier Magnitude Across Dynamic Multimodal Upload")

    fig_path = out_dir / f"{label}_trajectory_csi.png"
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)

    anon_summary = {
        "label": label,
        "frames_count": summary["frames_count"],
        "packets_sent": summary["packets_sent"],
        "packets_received_unique": summary["packets_received_unique"],
        "send_rate_pps": round(summary["send_rate_pps"], 3),
        "receive_rate_pps": round(summary["receive_rate_pps"], 3),
        "csi_matched_unique_packets": summary["csi_matched_unique_packets"],
        "csi_matched_records": summary["csi_matched_records"],
        "csi_coverage_pct": round(summary["csi_coverage_pct"], 2),
        "csi_effective_packet_rate_pps": round(summary["csi_effective_packet_rate_pps"], 3),
        "csi_effective_record_rate_rps": round(summary["csi_effective_record_rate_rps"], 3),
        "csi_complex_shape": summary["csi_complex_shape"],
        "csi_all_finite": summary["csi_all_finite"],
        "pose_age_median_ms": round(summary["pose_age_median_ms"], 3),
        "pose_age_max_ms": round(summary["pose_age_max_ms"], 3),
        "trajectory_path_length_m": round(path_len_m, 3),
        "trajectory_net_disp_m": round(net_disp_m, 3),
        "max_robot_speed_mps": round(max(all_spd), 3) if all_spd else 0.0,
        "clock_calibration": summary["clock_calibration"],
        "calibrated_csi_minus_send_ms": summary["calibrated_csi_minus_send_ms"],
        "frames": frame_stats,
    }
    (out_dir / f"{label}_anonymous_summary.json").write_text(
        json.dumps(anon_summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(anon_summary, indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cal-dir", type=pathlib.Path, required=True)
    p.add_argument("--out-dir", type=pathlib.Path, required=True)
    p.add_argument("--label", required=True)
    args = p.parse_args()
    analyze(args.cal_dir, args.out_dir, args.label)


if __name__ == "__main__":
    main()
