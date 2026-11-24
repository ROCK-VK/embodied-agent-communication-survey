"""Offline unit tests for CSID v2 streaming protocol, clock fit, and calibration."""
import hashlib
import json
import math
import pathlib
import socket
import struct
import tempfile
import threading
import time
import unittest
import zlib

import clock_sync_probe as clk
import multimodal_stream as stream
import multimodal_udp as legacy
import build_calibrated_dataset as bcd


class TestMultimodalStreamOffline(unittest.TestCase):
    def test_v1_and_v2_backward_compatibility(self):
        payload = b"hello_sensor_chunk" * 10
        digest = hashlib.sha256(payload).digest()
        p1 = legacy.pack(100, 1, 123456, 1, 1, 0, 1, len(payload), digest, payload)
        m1, d1 = stream.unpack_any(p1)
        self.assertEqual(m1["ver"], 1)
        self.assertEqual(m1["block_size"], 400)
        self.assertEqual(d1, payload)

        # v2 with block_size=1100
        big = bytes(range(256)) * 10  # 2560 bytes -> 3 chunks at 1100 B
        bdig = hashlib.sha256(big).digest()
        cnt = math.ceil(len(big) / 1100)
        self.assertEqual(cnt, 3)
        chunks = []
        for i in range(cnt):
            p2 = stream.pack_v2(
                200, i, 9999 + i, 5, 2, i, cnt, len(big), bdig, big[i * 1100 : (i + 1) * 1100], block_size=1100
            )
            # Check CSID header & CRC32 compatibility with direct_csi_decode.py
            self.assertEqual(p2[:4], b"CSID")
            self.assertEqual(len(p2), 32 + struct.unpack_from("<H", p2, 24)[0])
            self.assertEqual(zlib.crc32(p2[:-4]) & 0xFFFFFFFF, struct.unpack_from("<I", p2, len(p2) - 4)[0])
            m2, d2 = stream.unpack_any(p2)
            self.assertEqual(m2["ver"], 2)
            self.assertEqual(m2["block_size"], 1100)
            chunks.append(d2)
        self.assertEqual(b"".join(chunks), big)

    def test_tamper_and_invalid_block_rejected(self):
        data = b"x" * 100
        dig = hashlib.sha256(data).digest()
        p = bytearray(stream.pack_v2(1, 0, 1, 1, 1, 0, 1, len(data), dig, data, block_size=1100))
        p[40] ^= 0xFF
        with self.assertRaises(ValueError):
            stream.unpack_any(bytes(p))
        with self.assertRaises(ValueError):
            stream.pack_v2(1, 0, 1, 1, 1, 0, 1, len(data), dig, data, block_size=2000)

    def test_udp_clock_sync_loopback(self):
        # Find ephemeral free UDP port
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        class SrvArgs:
            bind = "127.0.0.1"
            max_packets = 6
            timeout = 5.0

        SrvArgs.port = port
        t = threading.Thread(target=clk.run_udp_server, args=(SrvArgs,))
        t.start()
        time.sleep(0.15)

        samples = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2.0)
            for seq in range(6):
                t1 = time.time_ns()
                s.sendto(struct.pack(clk.FMT, clk.MAGIC, seq, t1, 0, 0), ("127.0.0.1", port))
                resp, _ = s.recvfrom(1024)
                t4 = time.time_ns()
                _, rseq, rt1, t2, t3 = struct.unpack(clk.FMT, resp)
                self.assertEqual(rseq, seq)
                self.assertEqual(rt1, t1)
                samples.append(((t2 - t1) + (t3 - t4)) / 2e6)
        t.join(timeout=5)
        self.assertEqual(len(samples), 6)
        self.assertLess(abs(sum(samples) / len(samples)), 5.0)

    def test_linear_fit_and_clock_calibration_combine(self):
        xs = [1_000_000_000 + i * 1_000_000 for i in range(100)]
        ys = [int(500_000_000 + (x - xs[0]) * 1.000010) for x in xs]
        fit = stream.linear_fit(xs, ys)
        self.assertAlmostEqual(fit["drift_ppm"], 10.0, delta=0.5)
        self.assertLess(fit["residual_std_ns"], 5.0)

        cal = bcd.compute_clock_calibration(
            {"offset_best_rtt_median_ms": 10.0, "uncertainty_half_min_rtt_ms": 2.0, "rtt_min_ms": 4.0, "rtt_median_ms": 5.0},
            {"offset_best_rtt_median_ms": 10.4, "uncertainty_half_min_rtt_ms": 2.5, "rtt_min_ms": 5.0, "rtt_median_ms": 6.0},
        )
        self.assertTrue(cal["calibrated"])
        self.assertAlmostEqual(cal["offset_linux_minus_jetson_ms"], 10.2, delta=1e-6)
        self.assertAlmostEqual(cal["uncertainty_ms"], 2.7, delta=1e-6)

    def test_loopback_v2_receiver_reassembly(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "rx"
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()

            class RxArgs:
                host = "127.0.0.1"
                run = 777
                idle_timeout = 3.0
                post_idle_timeout = 0.4
                max_duration = 0.0

            RxArgs.out = out
            RxArgs.port = port
            t = threading.Thread(target=stream.run_receiver, args=(RxArgs,))
            t.start()
            time.sleep(0.15)

            raw_lidar = bytes(range(256)) * 40
            comp_lidar = zlib.compress(raw_lidar, level=1)
            dig = hashlib.sha256(comp_lidar).digest()
            cnt = math.ceil(len(comp_lidar) / 1100)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                for i in range(cnt):
                    pkt = stream.pack_v2(
                        777, i, time.monotonic_ns(), 1, 2, i, cnt, len(comp_lidar), dig,
                        comp_lidar[i * 1100 : (i + 1) * 1100], block_size=1100,
                    )
                    s.sendto(pkt, ("127.0.0.1", port))
            t.join(timeout=5)
            summary = json.loads((out / "receiver_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["samples_complete"], 1)
            self.assertEqual(zlib.decompress((out / "sample_1.bin").read_bytes()), raw_lidar)


if __name__ == "__main__":
    unittest.main()
