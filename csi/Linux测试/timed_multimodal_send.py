"""Send measured camera/LiDAR samples with concurrent Go2 pose observations.

Run on Jetson only while the D435i device is available. This experiment does
not control the robot. Each pose is tagged with its Jetson receive clock; the
robot stamp and sensor clocks are retained without asserting synchronization.
"""
import argparse
import hashlib
import json
import math
import pathlib
import socket
import struct
import threading
import time

import multimodal_udp as protocol


def clock():
    return {'wall_ns': time.time_ns(), 'monotonic_ns': time.monotonic_ns()}


def pose_at_send(pose, send_ns, maximum_age_ns):
    if pose is None:
        return {'available': False, 'reason': 'no_pose_received'}
    age = send_ns - pose['receipt']['monotonic_ns']
    if not 0 <= age <= maximum_age_ns:
        return {'available': False, 'reason': 'pose_stale_or_future', 'age_ns': age}
    return {'available': True, 'age_ns': age, 'observation': pose}


def frame_info(frame, rs):
    info = {'frame_number': int(frame.get_frame_number()),
            'timestamp_ms': float(frame.get_timestamp()),
            'timestamp_domain': str(frame.get_frame_timestamp_domain()),
            'metadata': {}}
    for name in ('frame_counter', 'frame_timestamp', 'sensor_timestamp',
                 'backend_timestamp', 'time_of_arrival', 'actual_exposure'):
        value = getattr(rs.frame_metadata_value, name, None)
        if value is not None and frame.supports_frame_metadata(value):
            info['metadata'][name] = int(frame.get_frame_metadata(value))
    return info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=pathlib.Path)
    parser.add_argument('--host', required=True)
    parser.add_argument('--lidar-bind', required=True, help='Jetson IPv4 receiving LiDAR packets')
    parser.add_argument('--lidar-source', required=True, help='expected LiDAR source IPv4')
    parser.add_argument('--port', type=int, default=39001)
    parser.add_argument('--run', required=True, type=int)
    parser.add_argument('--pps', type=float, default=15)
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--max-pose-age-ms', type=int, default=250)
    parser.add_argument('--warmup-frames', type=int, default=60)
    args = parser.parse_args()
    if not 0 < args.pps <= 30 or not 1 <= args.repeat <= 3:
        parser.error('pps/repeat outside experimental bounds')
    if not 1 <= args.warmup_frames <= 150:
        parser.error('warmup-frames must be 1..150')
    args.out.mkdir(parents=True, exist_ok=False)
    import pyrealsense2 as rs
    import numpy as np
    import cv2
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

    lock = threading.Lock()
    latest = [None]
    counters = {'callbacks': 0, 'errors': 0}
    ready = threading.Event()

    def callback(msg):
        received = clock()
        try:
            pose = {'position': list(msg.position), 'velocity': list(msg.velocity),
                    'stamp': {'sec': int(msg.stamp.sec), 'nanosec': int(msg.stamp.nanosec),
                              'domain': 'unknown'}, 'receipt': received,
                    'coordinate_frame': 'unverified', 'units': 'unverified'}
            with lock:
                counters['callbacks'] += 1
                latest[0] = pose
            ready.set()
        except Exception:
            with lock:
                counters['errors'] += 1

    ChannelFactoryInitialize(0, 'eth0')
    sub = ChannelSubscriber('rt/sportmodestate', SportModeState_)
    sub.Init(callback, 10)
    if not ready.wait(8):
        raise RuntimeError('no Go2 pose; no samples sent')

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 15)
    started = False
    try:
        pipeline.start(config)
        started = True
        for _ in range(args.warmup_frames):
            frames = pipeline.wait_for_frames(3000)
        received = clock()
        color = frames.get_color_frame()
        depth = frames.get_depth_frame()
        if not color or not depth:
            raise RuntimeError('missing paired camera frames')
        image_info = frame_info(color, rs)
        depth_info = frame_info(depth, rs)
        ok, encoded = cv2.imencode('.jpg', np.asanyarray(color.get_data()),
                                   [cv2.IMWRITE_JPEG_QUALITY, 65])
        if not ok:
            raise RuntimeError('JPEG encoding failed')
        (args.out / 'rgb.jpg').write_bytes(encoded.tobytes())
        camera = {'frameset_receipt': received, 'warmup_frames': args.warmup_frames,
                  'color': image_info, 'depth': depth_info,
                  'frameset_basis': 'same wait_for_frames return; exposure clocks not assumed synchronized',
                  'color_file': 'rgb.jpg', 'depth_uploaded': False}
    finally:
        if started:
            pipeline.stop()

    packets, packet_info = [], []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as lidar:
        lidar.settimeout(5)
        lidar.bind((args.lidar_bind, 56301))
        while len(packets) < 5:
            data, src = lidar.recvfrom(65535)
            receipt = clock()
            if src[0] != args.lidar_source or src[1] != 56300:
                continue
            if len(data) < 36:
                raise ValueError('short LiDAR packet')
            version, length, interval, dots, udp_count, frame_count, dtype, ttype = struct.unpack_from('<BHHHHBBB', data)
            if length != len(data) or dtype != 1 or len(data) != 36 + 14 * dots:
                raise ValueError('unsupported LiDAR packet')
            packets.append(data)
            packet_info.append({'receipt': receipt, 'length': length, 'version': version,
                                'interval_0_1us': interval, 'dot_num': dots,
                                'udp_count': udp_count, 'frame_count': frame_count,
                                'data_type': dtype, 'time_type': ttype,
                                'timestamp_raw_hex': data[28:36].hex(), 'timestamp_domain': 'unverified'})
    (args.out / 'lidar_packets.bin').write_bytes(b''.join(packets))
    with lock:
        captured_pose = latest[0]
    metadata = {'camera': camera, 'lidar': {'packets': packet_info, 'scope': 'five raw packets, not a complete scan'},
                'pose_at_metadata_creation': captured_pose, 'clock_note': 'Jetson receipt times do not establish sensor or robot clock synchronization'}
    (args.out / 'capture_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf8')

    samples = [(1, 1, 'rgb.jpg'), (2, 2, 'lidar_packets.bin'), (3, 3, 'capture_metadata.json')]
    pid, manifest = 0, []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, (args.out / 'sender_packets.jsonl').open('x', encoding='utf8') as log:
        for sample, kind, name in samples:
            data = (args.out / name).read_bytes()
            digest = hashlib.sha256(data).digest()
            count = math.ceil(len(data) / protocol.BLOCK)
            manifest.append({'sample_id': sample, 'kind': kind, 'filename': name, 'size': len(data),
                             'sha256': digest.hex(), 'chunks': count})
            for repeat in range(args.repeat):
                for index in range(count):
                    with lock:
                        send_ns = time.monotonic_ns()
                        pose = pose_at_send(latest[0], send_ns, args.max_pose_age_ms * 1000000)
                    packet = protocol.pack(args.run, pid, send_ns, sample, kind, index, count,
                                           len(data), digest, data[index * protocol.BLOCK:(index + 1) * protocol.BLOCK])
                    sock.sendto(packet, (args.host, args.port))
                    row, _ = protocol.unpack(packet)
                    row.update({'repeat': repeat, 'wall_ns': time.time_ns(), 'datagram_bytes': len(packet),
                                'pose_at_send': pose})
                    log.write(json.dumps(row) + '\n')
                    log.flush()
                    pid += 1
                    time.sleep(1 / args.pps)
    (args.out / 'sender_manifest.json').write_text(json.dumps({'run_id': args.run, 'samples': manifest,
                                                              'packet_count': pid, 'pose_counts': counters}, indent=2), encoding='utf8')
    print(json.dumps({'run_id': args.run, 'packet_count': pid, 'samples': manifest,
                      'pose_counts': counters, 'camera': camera}), flush=True)


if __name__ == '__main__':
    main()
