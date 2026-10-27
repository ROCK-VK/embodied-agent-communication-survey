"""Offline Open AP packet-ID to same-record CSI tests; no network/serial I/O."""
import struct
import unittest

from open_ap_poc import (analyze_rows, decode_csi_data, extract_udp,
                         csi_data_has_csid_magic)
from test_csi_data_eapol import make_csi_record
from udp_probe_protocol import PacketError, encode_packet

STA = bytes.fromhex("020000000001")
AP = bytes.fromhex("020000000002")
SNAP_IPV4 = bytes.fromhex("aaaa030000000800")
PORT = 39001


def make_udp_frame(run_id=0x12345678, packet_id=7, *, qos=False,
                   downlink=False, corrupt_crc=False):
    datagram = bytearray(encode_packet(run_id, packet_id, 987654321))
    if corrupt_crc:
        datagram[-1] ^= 0x80
    udp_len = 8 + len(datagram)
    udp = struct.pack(">HHHH", 50000, PORT, udp_len, 0) + datagram
    ip_len = 20 + len(udp)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, ip_len, 0x1357, 0,
                     64, 17, 0, bytes((192, 168, 4, 2)), bytes((192, 168, 4, 1))) + udp
    body = SNAP_IPV4 + ip
    fc = (0x0208 if downlink else 0x0108) | (0x0080 if qos else 0)
    ra, ta = (STA, AP) if downlink else (AP, STA)
    header = struct.pack("<HH6s6s6sH", fc, 0, ra, ta, AP, 0x120)
    if qos:
        header += b"\x00\x00"
    return header + body


def udp_event(run_id, packet_id, *, valid=True, crc_ok=True, duplicate=False):
    return {"event": "CONTROL", "counters": {
        "event": "UDP_RX", "run_id": run_id, "packet_id": packet_id,
        "valid": valid, "crc_ok": crc_ok, "duplicate": duplicate}}


class OpenApPoCTests(unittest.TestCase):
    def test_csid_datagram_crc_and_packet_id(self):
        frame = make_udp_frame()
        udp = extract_udp(frame)
        from udp_probe_protocol import decode_packet
        packet = decode_packet(udp["payload"])
        self.assertEqual((packet["run_id"], packet["packet_id"]), (0x12345678, 7))
        broken = bytearray(udp["payload"]);broken[-1] ^= 1
        with self.assertRaisesRegex(PacketError, "crc_mismatch"):
            decode_packet(broken)

    def test_plain_udp_frame_with_qos_and_non_qos_header(self):
        for qos, header_len in ((False, 24), (True, 26)):
            raw = make_udp_frame(qos=qos)
            row = make_csi_record(raw, qos=qos)
            decoded = decode_csi_data(row)
            self.assertTrue(row["csi_valid"])
            self.assertEqual(row["hdr_len"], header_len)
            self.assertEqual(decoded["packet_id"], 7)
            self.assertEqual(decoded["mac_header"]["ta"], "02:00:00:00:00:01")

    def test_both_infrastructure_directions_reconstruct(self):
        for downlink in (False, True):
            raw = make_udp_frame(downlink=downlink, qos=True)
            row = make_csi_record(raw, qos=True)
            decoded = decode_csi_data(row)
            self.assertEqual(decoded["packet_id"], 7)
            self.assertEqual(decoded["mac_header"]["to_ds"], 0 if downlink else 1)
            self.assertEqual(decoded["mac_header"]["from_ds"], 1 if downlink else 0)

    def test_same_record_sender_udp_and_valid_csi_is_minimal_pass(self):
        run_id, packet_id = 0x12345678, 7
        row = make_csi_record(make_udp_frame(run_id, packet_id, qos=True),
                              serial=42, rx_seq=0x2211, qos=True)
        self.assertTrue(csi_data_has_csid_magic(row))
        result = analyze_rows(
            [{"event": "SEND", "run_id": run_id, "packet_id": packet_id, "bytes": 48}],
            [udp_event(run_id, packet_id), row],
            {"udp_rx_total": 1, "udp_valid": 1, "udp_crc_ok": 1})
        self.assertTrue(result["minimal_poc_pass"])
        self.assertEqual(result["end_to_end_packet_ids"],
                         [{"run_id": run_id, "packet_id": packet_id, "csi_records": 1}])
        association = result["packet_id_to_csi_csv_rows"][0]
        self.assertEqual(association["csi_record_serial"], 42)
        self.assertTrue(association["csi_valid"])

    def test_duplicate_packet_id_can_map_to_multiple_csi_records(self):
        rid, pid = 3, 5
        rows = [make_csi_record(make_udp_frame(rid, pid), serial=s, rx_seq=s)
                for s in (10, 11)]
        result = analyze_rows([{"event": "SEND", "run_id": rid,
                                "packet_id": pid, "bytes": 48}],
                             [udp_event(rid, pid), *rows])
        self.assertTrue(result["minimal_poc_pass"])
        self.assertEqual(result["packet_ids_with_multiple_csi_records"], 1)
        self.assertEqual(len(result["packet_id_to_csi_csv_rows"]), 2)

    def test_no_time_or_nearby_packet_join(self):
        row = make_csi_record(make_udp_frame(9, 100), serial=100)
        result = analyze_rows([{"event": "SEND", "run_id": 9,
                                "packet_id": 99, "bytes": 48}],
                             [udp_event(9, 99), row])
        self.assertFalse(result["minimal_poc_pass"])

    def test_bad_crc_is_not_counted_as_csid_packet_id(self):
        row = make_csi_record(make_udp_frame(corrupt_crc=True))
        result = analyze_rows([], [row])
        self.assertTrue(csi_data_has_csid_magic(row))
        self.assertEqual(result["csi_data_csid_magic_records"], 1)
        self.assertEqual(result["csi_data_unique_packet_ids"], 0)
        self.assertFalse(result["minimal_poc_pass"])

    def test_protected_and_truncated_records_are_rejected(self):
        protected = make_udp_frame()
        protected = bytearray(protected);protected[1] |= 0x40
        row = make_csi_record(bytes(protected))
        with self.assertRaisesRegex(ValueError, "protected"):
            decode_csi_data(row)
        truncated = make_csi_record(make_udp_frame(), payload_copy=5)
        with self.assertRaisesRegex(ValueError, "truncated"):
            decode_csi_data(truncated)

    def test_invalid_csi_cannot_satisfy_poc(self):
        rid, pid = 1, 2
        row = make_csi_record(make_udp_frame(rid, pid), valid=0)
        result = analyze_rows([{"event": "SEND", "run_id": rid,
                                "packet_id": pid, "bytes": 48}],
                             [udp_event(rid, pid), row])
        self.assertFalse(result["minimal_poc_pass"])
        self.assertEqual(result["csi_data_csid_magic_records"], 1)


if __name__ == "__main__":
    unittest.main()
