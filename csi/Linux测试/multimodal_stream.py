"""Low-latency streaming multimodal capture & CSID v2 UDP protocol.

Key upgrades over timed_multimodal_send.py:
- CSID v2 wire format stays compatible with CSID magic/run_id/packet_id/CRC32
  while allowing configurable chunk block_size (default 1100 B, no IP frag).
- Keeps D435i pipeline open across frames (eliminating ~1.0 s pipeline.stop gap
  between camera capture and LiDAR/UDP transmission).
- Captures full configurable MID360 LiDAR scans (e.g., 100 ms = full 360-deg scan),
  saves lossless raw packets locally and transmits lossless zlib-compressed scans
  with SHA-256 verification on both raw and compressed forms.
- Logs continuous 500 Hz Go2 SportModeState trajectory (x, y, z, yaw, vel, stamp)
  plus per-packet pose snapshots and per-frame calibrated clock fit parameters.

This tool is strictly read-only on robot state and never sends motion commands.
"""
import argparse
import hashlib
import json
import math
import pathlib
import socket
import statistics
import struct
import threading
import time
import zlib

HEAD = struct.Struct("<4sBBHIIQHH")
CHUNK = struct.Struct("<IIIHHI32s")
DEFAULT_BLOCK = 1100
MAX_BLOCK = 1360  # keeps UDP payload <= 1444 B (< 1500 B Ethernet MTU)
MAX_SAMPLE_BYTES = 64 * 1024 * 1024

KIND_RGB = 1
KIND_LIDAR_ZLIB = 2
KIND_META = 3
KIND_LIDAR_RAW = 4
KIND_LIDAR_DELTA = 5


def clock():
    return {"wall_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns()}


def linear_fit(xs, ys):
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
        "residual_min_ns": min(residuals),
        "residual_max_ns": max(residuals),
        "residual_std_ns": statistics.stdev(residuals) if n > 2 else 0.0,
    }


def pack_v2(run, pid, mono, sample, kind, idx, count, total, digest, data, block_size=DEFAULT_BLOCK):
    if not 64 <= block_size <= MAX_BLOCK:
        raise ValueError(f"block_size {block_size} out of bounds [64, {MAX_BLOCK}]")
    body = CHUNK.pack(sample, idx, count, kind, block_size, total, digest) + data
    hdr = HEAD.pack(b"CSID", 2, 28, 0, run, pid, mono, len(body), 0) + body
    return hdr + struct.pack("<I", zlib.crc32(hdr) & 0xFFFFFFFF)


def unpack_any(p):
    """Unpack CSID v1 (fixed BLOCK=400) or CSID v2 (block_size in CHUNK field 4)."""
    if len(p) < HEAD.size + CHUNK.size + 4:
        raise ValueError("short")
    magic, ver, hlen, flags, run, pid, mono, length, res = HEAD.unpack_from(p)
    if magic != b"CSID" or ver not in (1, 2) or hlen != 28 or flags or res or len(p) != 32 + length:
        raise ValueError("header")
    if (zlib.crc32(p[:-4]) & 0xFFFFFFFF) != struct.unpack_from("<I", p, len(p) - 4)[0]:
        raise ValueError("crc")
    sample, idx, count, kind, blk_field, total, digest = CHUNK.unpack_from(p, HEAD.size)
    data = p[HEAD.size + CHUNK.size : -4]
    if ver == 1:
        if blk_field != 0:
            raise ValueError("v1 reserved field non-zero")
        block_size = 400
    else:
        block_size = blk_field
        if not 64 <= block_size <= MAX_BLOCK:
            raise ValueError("bad v2 block_size")
    if (
        not total
        or total > MAX_SAMPLE_BYTES
        or not count
        or idx >= count
        or count != (total + block_size - 1) // block_size
        or len(data) != min(block_size, total - idx * block_size)
    ):
        raise ValueError("chunk")
    return {
        "ver": ver,
        "block_size": block_size,
        "run_id": run,
        "packet_id": pid,
        "send_mono_ns": mono,
        "sample_id": sample,
        "chunk_index": idx,
        "chunk_count": count,
        "kind": kind,
        "total": total,
        "sha256": digest.hex(),
    }, data


def pose_at_time(pose, ref_mono_ns, maximum_age_ns):
    if pose is None:
        return {"available": False, "reason": "no_pose_received"}
    age = ref_mono_ns - pose["receipt"]["monotonic_ns"]
    if not 0 <= age <= maximum_age_ns:
        return {"available": False, "reason": "pose_stale_or_future", "age_ns": age}
    return {"available": True, "age_ns": age, "observation": pose}


def frame_info(frame, rs):
    info = {
        "frame_number": int(frame.get_frame_number()),
        "timestamp_ms": float(frame.get_timestamp()),
        "timestamp_domain": str(frame.get_frame_timestamp_domain()),
        "metadata": {},
    }
    for name in (
        "frame_counter",
        "frame_timestamp",
        "sensor_timestamp",
        "backend_timestamp",
        "time_of_arrival",
        "actual_exposure",
    ):
        value = getattr(rs.frame_metadata_value, name, None)
        if value is not None and frame.supports_frame_metadata(value):
            info["metadata"][name] = int(frame.get_frame_metadata(value))
    return info


def capture_lidar_window(sock, src_ip, duration_ms):
    """Capture MID360 UDP packets for duration_ms (e.g. 100 ms = 1 full 360-deg scan)."""
    # Drain stale kernel buffer so scan starts NOW
    sock.setblocking(False)
    drained = 0
    while True:
        try:
            sock.recvfrom(65535)
            drained += 1
        except BlockingIOError:
            break
    sock.setblocking(True)
    sock.settimeout(2.0)

    raw_packets = []
    pkt_meta = []
    t_start = time.monotonic_ns()
    deadline = t_start + int(duration_ms * 1_000_000)
    first_lidar_ts = None

    while True:
        data, addr = sock.recvfrom(65535)
        rx = clock()
        if addr[0] != src_ip or addr[1] != 56300:
            continue
        if len(data) < 36:
            continue
        ver, length, interval, dots, udp_cnt, frame_cnt, dtype, ttype = struct.unpack_from("<BHHHHBBB", data)
        if length != len(data) or dtype != 1 or len(data) != 36 + 14 * dots:
            continue
        lidar_ts_ns = struct.unpack_from("<Q", data, 28)[0]
        if first_lidar_ts is None:
            first_lidar_ts = lidar_ts_ns
        raw_packets.append(data)
        pkt_meta.append({
            "rx_mono_ns": rx["monotonic_ns"],
            "rx_wall_ns": rx["wall_ns"],
            "lidar_ts_ns": lidar_ts_ns,
            "dots": dots,
            "udp_cnt": udp_cnt,
            "time_type": ttype,
            "length": length,
        })
        if (lidar_ts_ns - first_lidar_ts) >= int(duration_ms * 1_000_000) or rx["monotonic_ns"] >= deadline:
            break

    raw_blob = b"".join(raw_packets)
    fit_mono = linear_fit([m["lidar_ts_ns"] for m in pkt_meta], [m["rx_mono_ns"] for m in pkt_meta])
    fit_wall = linear_fit([m["lidar_ts_ns"] for m in pkt_meta], [m["rx_wall_ns"] for m in pkt_meta])
    gaps = 0
    for a, b in zip(pkt_meta, pkt_meta[1:]):
        if ((b["udp_cnt"] - a["udp_cnt"]) & 0xFFFF) != 1:
            gaps += 1

    summary = {
        "drained_stale_packets": drained,
        "duration_requested_ms": duration_ms,
        "packet_count": len(pkt_meta),
        "point_count": sum(m["dots"] for m in pkt_meta),
        "raw_bytes": len(raw_blob),
        "raw_sha256": hashlib.sha256(raw_blob).hexdigest(),
        "time_types": sorted({m["time_type"] for m in pkt_meta}),
        "udp_seq_gaps": gaps,
        "first_packet": pkt_meta[0] if pkt_meta else None,
        "last_packet": pkt_meta[-1] if pkt_meta else None,
        "span_lidar_ms": (pkt_meta[-1]["lidar_ts_ns"] - pkt_meta[0]["lidar_ts_ns"]) / 1e6 if len(pkt_meta) >= 2 else 0.0,
        "fit_jetson_wall_vs_lidar_ts": fit_wall,
        "fit_jetson_mono_vs_lidar_ts": fit_mono,
    }
    return raw_blob, summary


def run_receiver(args):
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        s.settimeout(args.idle_timeout)
        s.bind((args.host, args.port))
        print("RECEIVER_READY", flush=True)

        groups = {}
        seen_ids = {}
        invalid = 0
        dup_id = 0
        dup_chunk = 0
        started_rx = False
        t_rx_start = None

        with (out / "receiver_packets.jsonl").open("x", encoding="utf-8") as f:
            while True:
                try:
                    p, src = s.recvfrom(65535)
                except socket.timeout:
                    break
                try:
                    m, data = unpack_any(p)
                except ValueError:
                    invalid += 1
                    continue
                if m["run_id"] != args.run:
                    continue
                if not started_rx:
                    started_rx = True
                    t_rx_start = time.monotonic()
                    s.settimeout(args.post_idle_timeout)
                key = (m["sample_id"], m["kind"], m["total"], m["chunk_count"], m["sha256"])
                g = groups.setdefault(key, {})
                if m["packet_id"] in seen_ids:
                    if seen_ids[m["packet_id"]] != p:
                        raise ValueError("conflicting packet_id")
                    dup_id += 1
                else:
                    seen_ids[m["packet_id"]] = p
                idx = m["chunk_index"]
                if idx in g:
                    if g[idx] != data:
                        raise ValueError("conflicting chunk data")
                    dup_chunk += 1
                else:
                    g[idx] = data
                m.update({
                    "receiver_wall_ns": time.time_ns(),
                    "receiver_monotonic_ns": time.monotonic_ns(),
                    "source": src[0],
                })
                f.write(json.dumps(m) + "\n")
                f.flush()
                if args.max_duration and started_rx and (time.monotonic() - t_rx_start) >= args.max_duration:
                    break

    summary = []
    for key in sorted(groups.keys()):
        sample, kind, total, count, sha = key
        g = groups[key]
        complete = len(g) == count
        data = b"".join(g[i] for i in range(count)) if complete else b""
        ok = complete and len(data) == total and hashlib.sha256(data).hexdigest() == sha
        if ok:
            (out / f"sample_{sample}.bin").write_bytes(data)
        summary.append({
            "sample_id": sample,
            "kind": kind,
            "total": total,
            "chunks_expected": count,
            "chunks_received": len(g),
            "complete_sha256_valid": ok,
            "sha256": sha,
            "missing_chunks": [i for i in range(count) if i not in g],
        })
    result = {
        "run_id": args.run,
        "unique_packet_ids": len(seen_ids),
        "duplicate_packet_ids": dup_id,
        "duplicate_chunks": dup_chunk,
        "invalid_datagrams": invalid,
        "samples_total": len(summary),
        "samples_complete": sum(1 for x in summary if x["complete_sha256_valid"]),
        "samples": summary,
    }
    (out / "receiver_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


def run_sender(args):
    if not 0 < args.pps <= 400:
        raise ValueError("pps out of bounds (0, 400]")
    if not 1 <= args.repeat <= 3:
        raise ValueError("repeat out of bounds [1, 3]")
    if not 1 <= args.frames <= 400:
        raise ValueError("frames out of bounds [1, 400]")
    if not 64 <= args.block_size <= MAX_BLOCK:
        raise ValueError(f"block_size out of bounds [64, {MAX_BLOCK}]")

    args.out.mkdir(parents=True, exist_ok=False)
    import cv2
    import numpy as np
    import pyrealsense2 as rs
    import mid360_codec as m360
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

    lock = threading.Lock()
    latest = [None]
    counters = {"callbacks": 0, "errors": 0}
    ready = threading.Event()
    pose_file = (args.out / "pose_trace.jsonl").open("x", encoding="utf-8")
    pose_samples_for_fit = []
    pose_closed = [False]

    def callback(msg):
        received = clock()
        try:
            rpy = list(msg.imu_state.rpy) if hasattr(msg, "imu_state") and hasattr(msg.imu_state, "rpy") else None
            pose = {
                "position": [float(v) for v in msg.position],
                "velocity": [float(v) for v in msg.velocity],
                "yaw_speed": float(msg.yaw_speed),
                "rpy": [float(v) for v in rpy] if rpy is not None else None,
                "mode": int(msg.mode),
                "body_height": float(msg.body_height),
                "stamp": {
                    "sec": int(msg.stamp.sec),
                    "nanosec": int(msg.stamp.nanosec),
                    "domain": "go2_internal_unix_clock_unsynced",
                },
                "receipt": received,
                "coordinate_frame": "go2_odometry_frame_unverified_external",
                "units": "meters_unverified_external",
            }
            with lock:
                counters["callbacks"] += 1
                latest[0] = pose
                if not pose_closed[0]:
                    # Save every 5th sample (~100 Hz) to keep pose_trace.jsonl compact & fast
                    if counters["callbacks"] % 5 == 1:
                        pose_file.write(json.dumps(pose) + "\n")
                        pose_samples_for_fit.append((
                            int(msg.stamp.sec) * 10**9 + int(msg.stamp.nanosec),
                            received["monotonic_ns"],
                            received["wall_ns"],
                        ))
            ready.set()
        except Exception:
            with lock:
                counters["errors"] += 1

    ChannelFactoryInitialize(0, args.dds_iface)
    sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
    sub.Init(callback, 10)
    if not ready.wait(8.0):
        raise RuntimeError("no Go2 pose received within 8s")

    lidar_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    lidar_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    lidar_sock.bind((args.lidar_bind, 56301))

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 15)

    pid = 0
    sample_id = 1
    manifest_samples = []
    frames_manifest = []
    started = False

    try:
        pipeline.start(config)
        started = True
        for _ in range(args.warmup_frames):
            pipeline.wait_for_frames(3000)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx_sock, (
            args.out / "sender_packets.jsonl"
        ).open("x", encoding="utf-8") as pkt_log:
            for fidx in range(args.frames):
                if fidx > 0 and args.stop_file and args.stop_file.exists():
                    break
                t_frame_loop_start = time.monotonic()

                # 1. Grab D435i frameset (pipeline stays open -> zero stop delay!)
                frames = pipeline.wait_for_frames(3000)
                cam_rx = clock()
                color = frames.get_color_frame()
                depth = frames.get_depth_frame()
                if not color or not depth:
                    raise RuntimeError(f"missing camera frames at frame {fidx}")
                color_meta = frame_info(color, rs)
                depth_meta = frame_info(depth, rs)
                with lock:
                    pose_cam = pose_at_time(latest[0], cam_rx["monotonic_ns"], args.max_pose_age_ms * 1_000_000)

                # 2. Immediately capture MID360 scan window (no pipeline.stop() in between!)
                raw_lidar, lidar_summary = capture_lidar_window(lidar_sock, args.lidar_source, args.lidar_ms)
                with lock:
                    pose_lidar_end = pose_at_time(latest[0], time.monotonic_ns(), args.max_pose_age_ms * 1_000_000)

                # 3. Encode RGB JPEG + lossless delta+byteplane-compressed LiDAR scan
                ok, encoded = cv2.imencode(
                    ".jpg", np.asanyarray(color.get_data()), [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality]
                )
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                rgb_bytes = encoded.tobytes()
                if args.lidar_codec == "delta":
                    lidar_tx_bytes = m360.encode_mid360_lossless(raw_lidar, level=3)
                    lidar_tx_kind = KIND_LIDAR_DELTA
                    lidar_tx_name = f"frame_{fidx:03d}_lidar.m36d"
                else:
                    lidar_tx_bytes = zlib.compress(raw_lidar, level=1)
                    lidar_tx_kind = KIND_LIDAR_ZLIB
                    lidar_tx_name = f"frame_{fidx:03d}_lidar.zlib"

                rgb_name = f"frame_{fidx:03d}_rgb.jpg"
                lidar_raw_name = f"frame_{fidx:03d}_lidar_raw.bin"
                meta_name = f"frame_{fidx:03d}_meta.json"

                (args.out / rgb_name).write_bytes(rgb_bytes)
                (args.out / lidar_raw_name).write_bytes(raw_lidar)
                (args.out / lidar_tx_name).write_bytes(lidar_tx_bytes)

                frame_meta = {
                    "frame_idx": fidx,
                    "camera": {
                        "frameset_receipt": cam_rx,
                        "color": color_meta,
                        "depth": depth_meta,
                        "jpeg_quality": args.jpeg_quality,
                        "rgb_bytes": len(rgb_bytes),
                        "rgb_sha256": hashlib.sha256(rgb_bytes).hexdigest(),
                    },
                    "lidar": {
                        **lidar_summary,
                        "codec": args.lidar_codec,
                        "compressed_bytes": len(lidar_tx_bytes),
                        "compressed_sha256": hashlib.sha256(lidar_tx_bytes).hexdigest(),
                    },
                    "pose_at_camera_receipt": pose_cam,
                    "pose_at_lidar_end": pose_lidar_end,
                }
                meta_bytes = json.dumps(frame_meta, indent=2).encode("utf-8")
                (args.out / meta_name).write_bytes(meta_bytes)

                # 4. Transmit RGB, compressed full LiDAR scan, and frame metadata with deadline pacing
                frame_items = [
                    (KIND_RGB, rgb_name, rgb_bytes),
                    (lidar_tx_kind, lidar_tx_name, lidar_tx_bytes),
                    (KIND_META, meta_name, meta_bytes),
                ]
                frame_sample_ids = []
                frame_pid_start = pid
                interval_s = (1.0 / args.pps) if args.pps > 0 else 0.0
                next_send_t = time.perf_counter()
                for kind, name, payload in frame_items:
                    sid = sample_id
                    sample_id += 1
                    frame_sample_ids.append(sid)
                    digest = hashlib.sha256(payload).digest()
                    count = math.ceil(len(payload) / args.block_size)
                    manifest_samples.append({
                        "frame_idx": fidx,
                        "sample_id": sid,
                        "kind": kind,
                        "filename": name,
                        "size": len(payload),
                        "sha256": digest.hex(),
                        "chunks": count,
                        "block_size": args.block_size,
                    })
                    for rep in range(args.repeat):
                        for idx in range(count):
                            if interval_s > 0:
                                now_p = time.perf_counter()
                                if next_send_t > now_p:
                                    time.sleep(next_send_t - now_p)
                            with lock:
                                send_mono = time.monotonic_ns()
                                pose_snap = pose_at_time(
                                    latest[0], send_mono, args.max_pose_age_ms * 1_000_000
                                )
                            pkt = pack_v2(
                                args.run,
                                pid,
                                send_mono,
                                sid,
                                kind,
                                idx,
                                count,
                                len(payload),
                                digest,
                                payload[idx * args.block_size : (idx + 1) * args.block_size],
                                block_size=args.block_size,
                            )
                            sent_len = tx_sock.sendto(pkt, (args.host, args.port))
                            send_wall = time.time_ns()
                            row, _ = unpack_any(pkt)
                            row.update({
                                "frame_idx": fidx,
                                "repeat": rep,
                                "wall_ns": send_wall,
                                "datagram_bytes": sent_len,
                                "pose_at_send": pose_snap,
                            })
                            pkt_log.write(json.dumps(row) + "\n")
                            pid += 1
                            next_send_t += interval_s
                pkt_log.flush()
                frames_manifest.append({
                    "frame_idx": fidx,
                    "sample_ids": frame_sample_ids,
                    "packet_id_start": frame_pid_start,
                    "packet_id_end": pid - 1,
                    "packet_count": pid - frame_pid_start,
                    "elapsed_s": time.monotonic() - t_frame_loop_start,
                })
                if args.frame_interval > 0 and fidx + 1 < args.frames:
                    rem = args.frame_interval - (time.monotonic() - t_frame_loop_start)
                    if rem > 0:
                        time.sleep(rem)
    finally:
        if started:
            pipeline.stop()
        lidar_sock.close()
        with lock:
            pose_closed[0] = True
            pose_file.flush()
            pose_file.close()
            fit_samples = list(pose_samples_for_fit)

    robot_fit_mono = linear_fit([x[0] for x in fit_samples], [x[1] for x in fit_samples])
    robot_fit_wall = linear_fit([x[0] for x in fit_samples], [x[2] for x in fit_samples])
    wall_minus_robot = [(x[2] - x[0]) / 1e9 for x in fit_samples] if fit_samples else []

    manifest = {
        "schema_version": 2,
        "run_id": args.run,
        "block_size": args.block_size,
        "pps": args.pps,
        "repeat": args.repeat,
        "frames_count": len(frames_manifest),
        "packet_count": pid,
        "pose_counts": counters,
        "robot_clock_fit": {
            "sample_count": len(fit_samples),
            "jetson_wall_minus_robot_stamp_median_s": statistics.median(wall_minus_robot) if wall_minus_robot else None,
            "jetson_wall_minus_robot_stamp_range_ms": (
                (max(wall_minus_robot) - min(wall_minus_robot)) * 1e3 if wall_minus_robot else None
            ),
            "fit_mono_vs_robot": robot_fit_mono,
            "fit_wall_vs_robot": robot_fit_wall,
        },
        "frames": frames_manifest,
        "samples": manifest_samples,
    }
    (args.out / "sender_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({
        "run_id": args.run,
        "frames_count": len(frames_manifest),
        "packet_count": pid,
        "samples_count": len(manifest_samples),
        "pose_counts": counters,
        "frames": frames_manifest,
    }), flush=True)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("send")
    s.add_argument("--out", required=True, type=pathlib.Path)
    s.add_argument("--host", required=True)
    s.add_argument("--port", type=int, default=39001)
    s.add_argument("--run", required=True, type=int)
    s.add_argument("--frames", type=int, default=1)
    s.add_argument("--frame-interval", type=float, default=0.0)
    s.add_argument("--pps", type=float, default=40.0)
    s.add_argument("--repeat", type=int, default=2)
    s.add_argument("--block-size", type=int, default=DEFAULT_BLOCK)
    s.add_argument("--warmup-frames", type=int, default=60)
    s.add_argument("--jpeg-quality", type=int, default=65)
    s.add_argument("--lidar-ms", type=float, default=100.0)
    s.add_argument("--lidar-codec", choices=["delta", "zlib"], default="delta")
    s.add_argument("--lidar-bind", required=True)
    s.add_argument("--lidar-source", required=True)
    s.add_argument("--dds-iface", default="eth0")
    s.add_argument("--max-pose-age-ms", type=int, default=250)
    s.add_argument("--stop-file", type=pathlib.Path, default=None)

    r = sub.add_parser("receive")
    r.add_argument("--out", required=True, type=pathlib.Path)
    r.add_argument("--host", required=True)
    r.add_argument("--port", type=int, default=39001)
    r.add_argument("--run", required=True, type=int)
    r.add_argument("--idle-timeout", type=float, default=120.0)
    r.add_argument("--post-idle-timeout", type=float, default=10.0)
    r.add_argument("--max-duration", type=float, default=0.0)

    args = p.parse_args()
    if args.mode == "send":
        run_sender(args)
    else:
        run_receiver(args)


if __name__ == "__main__":
    main()
