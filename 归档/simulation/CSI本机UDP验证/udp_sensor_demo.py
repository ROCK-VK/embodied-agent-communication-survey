#!/usr/bin/env python3
"""Verify sample/chunk metadata and reassembly over localhost UDP only."""

from __future__ import annotations

import hashlib
import math
import socket
import struct
import time


MAGIC = b"CSID"
VERSION = 1
CAMERA = 1
LIDAR = 2
SENSOR_NAMES = {CAMERA: "CAMERA", LIDAR: "LIDAR"}
HEADER = struct.Struct("!4sBBQHHdffI")
CHUNK_BYTES = 700
MAX_DATAGRAM_BYTES = 1200


def deterministic_payload(size: int, multiplier: int, offset: int) -> bytes:
    return bytes((index * multiplier + offset) % 256 for index in range(size))


def encode_sample(
    *, sensor_type: int, sample_id: int, timestamp: float, x: float, y: float,
    payload: bytes, chunk_bytes: int = CHUNK_BYTES,
) -> list[bytes]:
    chunks = [payload[start : start + chunk_bytes] for start in range(0, len(payload), chunk_bytes)]
    if not chunks:
        chunks = [b""]
    if len(chunks) > 0xFFFF:
        raise ValueError("too many chunks for the demo header")

    datagrams = []
    for chunk_id, chunk in enumerate(chunks):
        header = HEADER.pack(
            MAGIC, VERSION, sensor_type, sample_id, chunk_id, len(chunks),
            timestamp, x, y, len(chunk),
        )
        datagram = header + chunk
        if len(datagram) > MAX_DATAGRAM_BYTES:
            raise ValueError("datagram exceeds configured demo limit")
        datagrams.append(datagram)
    return datagrams


def decode_datagram(datagram: bytes) -> tuple[dict[str, int | float], bytes]:
    if len(datagram) < HEADER.size:
        raise ValueError("datagram is shorter than its header")
    magic, version, sensor_type, sample_id, chunk_id, chunk_count, timestamp, x, y, payload_len = HEADER.unpack_from(datagram)
    if magic != MAGIC or version != VERSION:
        raise ValueError("unsupported datagram magic or version")
    if sensor_type not in SENSOR_NAMES:
        raise ValueError("unknown sensor type")
    if chunk_count == 0 or chunk_id >= chunk_count:
        raise ValueError("invalid chunk numbering")
    payload = datagram[HEADER.size:]
    if len(payload) != payload_len:
        raise ValueError("payload length does not match header")
    metadata: dict[str, int | float] = {
        "sensor_type": sensor_type,
        "sample_id": sample_id,
        "chunk_count": chunk_count,
        "timestamp": timestamp,
        "x": x,
        "y": y,
    }
    return metadata | {"chunk_id": chunk_id}, payload


def main() -> None:
    camera = deterministic_payload(4096, 37, 11)
    lidar = deterministic_payload(2500, 17, 3)
    now = time.time()
    camera_packets = encode_sample(
        sensor_type=CAMERA, sample_id=173, timestamp=now, x=1.25, y=-0.5, payload=camera,
    )
    lidar_packets = encode_sample(
        sensor_type=LIDAR, sample_id=428, timestamp=now + 0.01, x=1.30, y=-0.45, payload=lidar,
    )

    # Reverse one sample to exercise out-of-order chunk arrival. Withhold one
    # lidar application chunk to exercise incomplete-sample detection.
    transmitted = list(reversed(camera_packets)) + [packet for i, packet in enumerate(lidar_packets) if i != 1]

    received: dict[int, dict[str, object]] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(1.0)
        address = receiver.getsockname()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for packet in transmitted:
                sender.sendto(packet, address)

        for _ in transmitted:
            datagram, _peer = receiver.recvfrom(2048)
            metadata, chunk_payload = decode_datagram(datagram)
            sample_id = int(metadata["sample_id"])
            chunk_id = int(metadata["chunk_id"])
            stable_metadata = {key: value for key, value in metadata.items() if key != "chunk_id"}
            sample = received.setdefault(sample_id, {"metadata": stable_metadata, "chunks": {}})
            if sample["metadata"] != stable_metadata:
                raise AssertionError(f"metadata changed within sample {sample_id}")
            chunks = sample["chunks"]
            assert isinstance(chunks, dict)
            if chunk_id in chunks:
                raise AssertionError(f"duplicate chunk {chunk_id} for sample {sample_id}")
            chunks[chunk_id] = chunk_payload

    camera_record = received[173]
    camera_chunks = camera_record["chunks"]
    assert isinstance(camera_chunks, dict)
    camera_expected_count = int(camera_record["metadata"]["chunk_count"])
    assert len(camera_chunks) == camera_expected_count
    camera_reassembled = b"".join(camera_chunks[index] for index in range(camera_expected_count))
    assert camera_reassembled == camera
    assert math.isclose(float(camera_record["metadata"]["x"]), 1.25, abs_tol=1e-6)
    assert math.isclose(float(camera_record["metadata"]["y"]), -0.5, abs_tol=1e-6)

    lidar_record = received[428]
    lidar_chunks = lidar_record["chunks"]
    assert isinstance(lidar_chunks, dict)
    lidar_expected_count = int(lidar_record["metadata"]["chunk_count"])
    assert len(lidar_chunks) == lidar_expected_count - 1
    assert 1 not in lidar_chunks

    print("UDP localhost demo: PASS")
    print(
        f"CAMERA sample_id=173: {len(camera)} bytes, {camera_expected_count}/{camera_expected_count} chunks received "
        f"out of order; exact reassembly verified; sha256={hashlib.sha256(camera_reassembled).hexdigest()}"
    )
    print(
        f"LIDAR sample_id=428: {len(lidar)} bytes, {len(lidar_chunks)}/{lidar_expected_count} chunks received; "
        "missing chunk correctly left the sample incomplete"
    )
    print(f"UDP datagrams received: {len(transmitted)}; header: {HEADER.size} bytes; application chunk: {CHUNK_BYTES} bytes")
    print("Scope: loopback software test only; no Wi-Fi, Atheros CSI, Go2, or physical sensor was used.")


if __name__ == "__main__":
    main()
