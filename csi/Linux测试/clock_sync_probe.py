"""Read-only clock offset and sensor stream calibration tools.

Subcommands:
  udp-server   Run a minimal UDP 4-timestamp echo server on the peer host.
  udp-client   Measure RTT and wall-clock offset against udp-server.
  jetson-probe Read-only MID360 (1s) and Go2 SportModeState (configurable)
               clock/rate/drift calibration on Jetson.

This script performs read-only measurements and never sends robot control commands.
"""
import argparse
import json
import math
import socket
import statistics
import struct
import threading
import time
import zlib

MAGIC = b"CLK4"
# <4sIQqQ : magic, seq, t1_wall_ns, t2_wall_ns, t3_wall_ns
FMT = "<4sIQQQ"
SIZE = struct.calcsize(FMT)


def linear_fit(xs, ys):
    """Ordinary least squares fit y = slope * x + intercept; x shifted to x[0]."""
    n = len(xs)
    if n < 2:
        return None
    x0 = xs[0]
    dx = [x - x0 for x in xs]
    mx = sum(dx) / n
    my = sum(ys) / n
    sxx = sum((a - mx) ** 2 for a in dx)
    if sxx == 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(dx, ys))
    slope = sxy / sxx
    intercept_at_x0 = my - slope * mx
    residuals = [b - (slope * a + intercept_at_x0) for a, b in zip(dx, ys)]
    return {
        "n": n,
        "x0": x0,
        "slope": slope,
        "drift_ppm": (slope - 1.0) * 1e6,
        "intercept_at_x0": intercept_at_x0,
        "residual_min": min(residuals),
        "residual_max": max(residuals),
        "residual_std": statistics.stdev(residuals) if n > 2 else 0.0,
    }


def run_udp_server(args):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((args.bind, args.port))
        sock.settimeout(args.timeout)
        handled = 0
        print(json.dumps({"ready": True, "bind": args.bind, "port": args.port}), flush=True)
        while handled < args.max_packets:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                break
            t2 = time.time_ns()
            if len(data) != SIZE or data[:4] != MAGIC:
                continue
            _, seq, t1, _, _ = struct.unpack(FMT, data)
            t3 = time.time_ns()
            sock.sendto(struct.pack(FMT, MAGIC, seq, t1, t2, t3), addr)
            handled += 1
        print(json.dumps({"done": True, "handled": handled}), flush=True)


def run_udp_client(args):
    samples = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(args.timeout)
        for seq in range(args.count):
            t1 = time.time_ns()
            pkt = struct.pack(FMT, MAGIC, seq, t1, 0, 0)
            sock.sendto(pkt, (args.host, args.port))
            try:
                resp, _ = sock.recvfrom(1024)
                t4 = time.time_ns()
            except socket.timeout:
                continue
            if len(resp) != SIZE or resp[:4] != MAGIC:
                continue
            _, rseq, rt1, t2, t3 = struct.unpack(FMT, resp)
            if rseq != seq or rt1 != t1:
                continue
            # Standard NTP 4-timestamp estimator:
            # offset = peer_wall - local_wall = ((t2 - t1) + (t3 - t4)) / 2
            # rtt    = (t4 - t1) - (t3 - t2)
            rtt_ns = (t4 - t1) - (t3 - t2)
            offset_ns = ((t2 - t1) + (t3 - t4)) // 2
            samples.append({
                "seq": seq,
                "t1_ns": t1,
                "t2_ns": t2,
                "t3_ns": t3,
                "t4_ns": t4,
                "rtt_ns": rtt_ns,
                "offset_peer_minus_local_ns": offset_ns,
            })
            time.sleep(args.interval)
    if not samples:
        raise RuntimeError("No clock sync responses received")
    # Best-RTT subset (lowest 25% RTT minimizes asymmetric Wi-Fi queuing error)
    sorted_by_rtt = sorted(samples, key=lambda s: s["rtt_ns"])
    best_k = max(3, len(sorted_by_rtt) // 4)
    best = sorted_by_rtt[:best_k]
    summary = {
        "count_sent": args.count,
        "count_received": len(samples),
        "rtt_min_ms": min(s["rtt_ns"] for s in samples) / 1e6,
        "rtt_median_ms": statistics.median(s["rtt_ns"] for s in samples) / 1e6,
        "rtt_max_ms": max(s["rtt_ns"] for s in samples) / 1e6,
        "offset_all_median_ms": statistics.median(s["offset_peer_minus_local_ns"] for s in samples) / 1e6,
        "offset_best_rtt_median_ms": statistics.median(s["offset_peer_minus_local_ns"] for s in best) / 1e6,
        "offset_best_rtt_min_ms": min(s["offset_peer_minus_local_ns"] for s in best) / 1e6,
        "offset_best_rtt_max_ms": max(s["offset_peer_minus_local_ns"] for s in best) / 1e6,
        "uncertainty_half_min_rtt_ms": (min(s["rtt_ns"] for s in samples) / 2.0) / 1e6,
        "sign_convention": "offset = peer_wall - local_wall",
        "samples": samples,
    }
    print(json.dumps(summary, indent=2), flush=True)


def probe_lidar(bind_ip, src_ip, duration_s):
    raw_pkts = []
    records = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        sock.settimeout(2.0)
        sock.bind((bind_ip, 56301))
        t_start = time.monotonic()
        while time.monotonic() - t_start < duration_s:
            data, addr = sock.recvfrom(65535)
            rx_mono = time.monotonic_ns()
            rx_wall = time.time_ns()
            if addr[0] != src_ip or addr[1] != 56300:
                continue
            if len(data) < 36:
                continue
            ver, length, interval, dots, udp_cnt, frame_cnt, dtype, ttype = struct.unpack_from("<BHHHHBBB", data)
            if length != len(data) or dtype != 1 or len(data) != 36 + 14 * dots:
                continue
            ts_ns = struct.unpack_from("<Q", data, 28)[0]
            raw_pkts.append(data)
            records.append({
                "rx_mono_ns": rx_mono,
                "rx_wall_ns": rx_wall,
                "lidar_ts_ns": ts_ns,
                "dots": dots,
                "udp_cnt": udp_cnt,
                "frame_cnt": frame_cnt,
                "time_type": ttype,
                "bytes": len(data),
            })
    if len(records) < 10:
        return {"error": f"too few lidar packets: {len(records)}"}

    # Linear fit: rx_mono_ns = slope * lidar_ts_ns + intercept
    fit_mono = linear_fit([r["lidar_ts_ns"] for r in records], [r["rx_mono_ns"] for r in records])
    fit_wall = linear_fit([r["lidar_ts_ns"] for r in records], [r["rx_wall_ns"] for r in records])
    span_lidar_s = (records[-1]["lidar_ts_ns"] - records[0]["lidar_ts_ns"]) / 1e9
    span_mono_s = (records[-1]["rx_mono_ns"] - records[0]["rx_mono_ns"]) / 1e9
    udp_gaps = []
    for a, b in zip(records, records[1:]):
        diff = (b["udp_cnt"] - a["udp_cnt"]) & 0xFFFF
        if diff != 1:
            udp_gaps.append({"from": a["udp_cnt"], "to": b["udp_cnt"], "gap": diff})

    # Measure compression ratio on 100 ms (one 10 Hz full 360-deg scan)
    t0 = records[0]["lidar_ts_ns"]
    scan100_pkts = [raw_pkts[i] for i, r in enumerate(records) if r["lidar_ts_ns"] - t0 < 100_000_000]
    scan100_raw = b"".join(scan100_pkts)
    scan100_z1 = zlib.compress(scan100_raw, level=1)
    scan100_z6 = zlib.compress(scan100_raw, level=6)

    # Also test compact XYZ+reflectivity extraction (int32 x,y,z + uint8 refl -> 13 bytes/pt vs 14 bytes/pt)
    return {
        "duration_requested_s": duration_s,
        "packet_count": len(records),
        "total_points": sum(r["dots"] for r in records),
        "span_lidar_s": span_lidar_s,
        "span_jetson_mono_s": span_mono_s,
        "packet_rate_hz": (len(records) - 1) / span_lidar_s if span_lidar_s > 0 else 0,
        "point_rate_hz": sum(r["dots"] for r in records[:-1]) / span_lidar_s if span_lidar_s > 0 else 0,
        "time_types_seen": sorted({r["time_type"] for r in records}),
        "udp_seq_gaps": udp_gaps[:10],
        "udp_seq_gap_count": len(udp_gaps),
        "fit_jetson_mono_vs_lidar_ts": {
            "drift_ppm": fit_mono["drift_ppm"],
            "residual_min_ms": fit_mono["residual_min"] / 1e6,
            "residual_max_ms": fit_mono["residual_max"] / 1e6,
            "residual_std_ms": fit_mono["residual_std"] / 1e6,
            "lidar_minus_jetson_mono_at_start_s": (records[0]["lidar_ts_ns"] - records[0]["rx_mono_ns"]) / 1e9,
        } if fit_mono else None,
        "fit_jetson_wall_vs_lidar_ts": {
            "drift_ppm": fit_wall["drift_ppm"],
            "residual_min_ms": fit_wall["residual_min"] / 1e6,
            "residual_max_ms": fit_wall["residual_max"] / 1e6,
            "residual_std_ms": fit_wall["residual_std"] / 1e6,
        } if fit_wall else None,
        "scan_100ms": {
            "packet_count": len(scan100_pkts),
            "point_count": sum(records[i]["dots"] for i in range(len(scan100_pkts))),
            "raw_bytes": len(scan100_raw),
            "zlib_level1_bytes": len(scan100_z1),
            "zlib_level6_bytes": len(scan100_z6),
            "chunks_at_1100B_z1": math.ceil(len(scan100_z1) / 1100),
        },
    }


def probe_go2_pose(iface, duration_s):
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

    lock = threading.Lock()
    samples = []
    errors = [0]

    def cb(msg):
        rx_mono = time.monotonic_ns()
        rx_wall = time.time_ns()
        try:
            rpy = list(msg.imu_state.rpy) if hasattr(msg, "imu_state") and hasattr(msg.imu_state, "rpy") else None
            row = {
                "rx_mono_ns": rx_mono,
                "rx_wall_ns": rx_wall,
                "robot_stamp_ns": int(msg.stamp.sec) * 10**9 + int(msg.stamp.nanosec),
                "pos": [float(v) for v in msg.position],
                "vel": [float(v) for v in msg.velocity],
                "yaw_speed": float(msg.yaw_speed),
                "rpy": [float(v) for v in rpy] if rpy is not None else None,
                "mode": int(msg.mode),
                "gait_type": int(msg.gait_type),
                "body_height": float(msg.body_height),
            }
            with lock:
                samples.append(row)
        except Exception:
            with lock:
                errors[0] += 1

    ChannelFactoryInitialize(0, iface)
    sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
    sub.Init(cb, 10)
    time.sleep(duration_s)
    with lock:
        data = list(samples)
        err_cnt = errors[0]

    if len(data) < 10:
        return {"error": f"too few pose samples: {len(data)}", "errors": err_cnt}

    span_mono_s = (data[-1]["rx_mono_ns"] - data[0]["rx_mono_ns"]) / 1e9
    span_robot_s = (data[-1]["robot_stamp_ns"] - data[0]["robot_stamp_ns"]) / 1e9
    fit_mono = linear_fit([d["robot_stamp_ns"] for d in data], [d["rx_mono_ns"] for d in data])
    wall_minus_robot = [(d["rx_wall_ns"] - d["robot_stamp_ns"]) / 1e9 for d in data]
    rx_gaps_ms = [(b["rx_mono_ns"] - a["rx_mono_ns"]) / 1e6 for a, b in zip(data, data[1:])]
    robot_dt_ms = [(b["robot_stamp_ns"] - a["robot_stamp_ns"]) / 1e6 for a, b in zip(data, data[1:])]

    xs = [d["pos"][0] for d in data]
    ys = [d["pos"][1] for d in data]
    zs = [d["pos"][2] for d in data]
    yaws = [d["rpy"][2] for d in data if d["rpy"] is not None]

    return {
        "duration_requested_s": duration_s,
        "callback_count": len(data),
        "errors": err_cnt,
        "rate_hz": (len(data) - 1) / span_mono_s if span_mono_s > 0 else 0,
        "span_jetson_mono_s": span_mono_s,
        "span_robot_stamp_s": span_robot_s,
        "rx_gap_ms": {
            "min": min(rx_gaps_ms),
            "median": statistics.median(rx_gaps_ms),
            "p99": sorted(rx_gaps_ms)[int(0.99 * (len(rx_gaps_ms) - 1))],
            "max": max(rx_gaps_ms),
        },
        "robot_stamp_step_ms": {
            "min": min(robot_dt_ms),
            "median": statistics.median(robot_dt_ms),
            "max": max(robot_dt_ms),
        },
        "jetson_wall_minus_robot_stamp_s": {
            "min": min(wall_minus_robot),
            "median": statistics.median(wall_minus_robot),
            "max": max(wall_minus_robot),
            "range_ms": (max(wall_minus_robot) - min(wall_minus_robot)) * 1e3,
        },
        "fit_jetson_mono_vs_robot_stamp": {
            "drift_ppm": fit_mono["drift_ppm"],
            "residual_min_ms": fit_mono["residual_min"] / 1e6,
            "residual_max_ms": fit_mono["residual_max"] / 1e6,
            "residual_std_ms": fit_mono["residual_std"] / 1e6,
        } if fit_mono else None,
        "static_pose_summary": {
            "mode_values": sorted({d["mode"] for d in data}),
            "body_height_median": statistics.median(d["body_height"] for d in data),
            "x_start": xs[0],
            "x_end": xs[-1],
            "x_drift_mm": (xs[-1] - xs[0]) * 1000.0,
            "x_drift_mm_per_s": ((xs[-1] - xs[0]) * 1000.0) / span_mono_s if span_mono_s > 0 else 0,
            "y_start": ys[0],
            "y_end": ys[-1],
            "y_drift_mm": (ys[-1] - ys[0]) * 1000.0,
            "y_drift_mm_per_s": ((ys[-1] - ys[0]) * 1000.0) / span_mono_s if span_mono_s > 0 else 0,
            "z_start": zs[0],
            "z_end": zs[-1],
            "z_range_mm": (max(zs) - min(zs)) * 1000.0,
            "yaw_start_rad": yaws[0] if yaws else None,
            "yaw_end_rad": yaws[-1] if yaws else None,
            "yaw_range_deg": math.degrees(max(yaws) - min(yaws)) if yaws else None,
        },
    }


def run_jetson_probe(args):
    res = {"measured_wall_ns": time.time_ns(), "measured_mono_ns": time.monotonic_ns()}
    res["lidar"] = probe_lidar(args.lidar_bind, args.lidar_source, args.lidar_duration)
    res["go2_pose"] = probe_go2_pose(args.dds_iface, args.pose_duration)
    print(json.dumps(res, indent=2), flush=True)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("udp-server")
    s.add_argument("--bind", default="0.0.0.0")
    s.add_argument("--port", type=int, default=39021)
    s.add_argument("--max-packets", type=int, default=40)
    s.add_argument("--timeout", type=float, default=15.0)

    c = sub.add_parser("udp-client")
    c.add_argument("--host", required=True)
    c.add_argument("--port", type=int, default=39021)
    c.add_argument("--count", type=int, default=30)
    c.add_argument("--interval", type=float, default=0.05)
    c.add_argument("--timeout", type=float, default=1.0)

    j = sub.add_parser("jetson-probe")
    j.add_argument("--lidar-bind", required=True)
    j.add_argument("--lidar-source", required=True)
    j.add_argument("--lidar-duration", type=float, default=1.0)
    j.add_argument("--dds-iface", default="eth0")
    j.add_argument("--pose-duration", type=float, default=6.0)

    args = p.parse_args()
    if args.cmd == "udp-server":
        run_udp_server(args)
    elif args.cmd == "udp-client":
        run_udp_client(args)
    elif args.cmd == "jetson-probe":
        run_jetson_probe(args)


if __name__ == "__main__":
    main()
