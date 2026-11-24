"""Read-only Go2 SportModeState pose recorder for coordinate/unit calibration.

Subscribes to rt/sportmodestate on eth0 (strictly read-only; never sends commands),
records ~100 Hz pose trajectory to JSONL until stop_file appears or max_duration elapses.
"""
import argparse
import json
import math
import pathlib
import threading
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=pathlib.Path)
    p.add_argument("--stop-file", required=True, type=pathlib.Path)
    p.add_argument("--dds-iface", default="eth0")
    p.add_argument("--max-duration", type=float, default=180.0)
    args = p.parse_args()

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

    if args.stop_file.exists():
        args.stop_file.unlink()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    lock = threading.Lock()
    state = {"callbacks": 0, "saved": 0, "errors": 0, "first": None, "last": None}
    ready = threading.Event()
    fp = args.out.open("w", encoding="utf-8")
    closed = [False]

    def cb(msg):
        rx_mono = time.monotonic_ns()
        rx_wall = time.time_ns()
        try:
            rpy = list(msg.imu_state.rpy) if hasattr(msg, "imu_state") and hasattr(msg.imu_state, "rpy") else None
            row = {
                "rx_wall_ns": rx_wall,
                "rx_mono_ns": rx_mono,
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
                state["callbacks"] += 1
                if state["first"] is None:
                    state["first"] = row
                state["last"] = row
                if not closed[0] and state["callbacks"] % 5 == 1:
                    fp.write(json.dumps(row) + "\n")
                    state["saved"] += 1
                    if state["saved"] % 50 == 0:
                        fp.flush()
            ready.set()
        except Exception:
            with lock:
                state["errors"] += 1

    ChannelFactoryInitialize(0, args.dds_iface)
    sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
    sub.Init(cb, 10)
    if not ready.wait(8.0):
        raise RuntimeError("No rt/sportmodestate callbacks received within 8s")

    with lock:
        first = state["first"]
    yaw_deg = math.degrees(first["rpy"][2]) if first.get("rpy") else None
    print(
        "POSE_CAL_READY "
        + json.dumps({
            "pos0": first["pos"],
            "yaw0_rad": first["rpy"][2] if first.get("rpy") else None,
            "yaw0_deg": yaw_deg,
            "mode": first["mode"],
            "body_height": first["body_height"],
        }),
        flush=True,
    )

    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < args.max_duration:
            if args.stop_file.exists():
                break
            time.sleep(0.1)
    finally:
        with lock:
            closed[0] = True
            fp.flush()
            fp.close()
            summary = {
                "callbacks": state["callbacks"],
                "saved": state["saved"],
                "errors": state["errors"],
                "elapsed_s": time.monotonic() - t0,
                "first_pos": state["first"]["pos"] if state["first"] else None,
                "last_pos": state["last"]["pos"] if state["last"] else None,
            }
        print("POSE_CAL_DONE " + json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
