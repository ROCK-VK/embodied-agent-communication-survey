#!/usr/bin/env python3
"""Wire format shared by the Jetson UDP probe sender and receiver (Python 3.8+)."""
import struct
import zlib

MAGIC = b"CSID"
VERSION = 1
HEADER = struct.Struct("<4sBBHIIQHH")
TRAILER = struct.Struct("<I")
HEADER_LEN = HEADER.size  # 28 bytes
TEST_DATA_LEN = 16
PACKET_LEN = HEADER_LEN + TEST_DATA_LEN + TRAILER.size  # 48-byte UDP payload


class PacketError(ValueError):
    pass


def _test_data(packet_id):
    return bytes((packet_id + offset) & 0xFF for offset in range(TEST_DATA_LEN))


def encode_packet(run_id, packet_id, sender_mono_ns):
    if not 0 <= run_id <= 0xFFFFFFFF:
        raise ValueError("run_id must fit uint32")
    if not 0 <= packet_id <= 0xFFFFFFFF:
        raise ValueError("packet_id must fit uint32")
    if not 0 <= sender_mono_ns <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("sender_mono_ns must fit uint64")
    header = HEADER.pack(MAGIC, VERSION, HEADER_LEN, 0, run_id, packet_id,
                         sender_mono_ns, TEST_DATA_LEN, 0)
    body = header + _test_data(packet_id)
    return body + TRAILER.pack(zlib.crc32(body) & 0xFFFFFFFF)


def decode_packet(datagram):
    if len(datagram) < 4 or datagram[:4] != MAGIC:
        raise PacketError("magic_mismatch")
    if len(datagram) < HEADER_LEN + TRAILER.size:
        raise PacketError("truncated_header")
    magic, version, header_len, flags, run_id, packet_id, sender_ns, data_len, reserved = HEADER.unpack_from(datagram)
    if magic != MAGIC or version != VERSION or header_len != HEADER_LEN:
        raise PacketError("unsupported_header")
    if flags != 0 or reserved != 0 or data_len != TEST_DATA_LEN:
        raise PacketError("invalid_header_fields")
    if len(datagram) != header_len + data_len + TRAILER.size:
        raise PacketError("length_mismatch")
    body = datagram[:-TRAILER.size]
    expected_crc = TRAILER.unpack_from(datagram, len(body))[0]
    if zlib.crc32(body) & 0xFFFFFFFF != expected_crc:
        raise PacketError("crc_mismatch")
    payload = datagram[header_len:header_len + data_len]
    if payload != _test_data(packet_id):
        raise PacketError("payload_pattern_mismatch")
    return {
        "version": version,
        "run_id": run_id,
        "packet_id": packet_id,
        "sender_mono_ns": sender_ns,
        "payload_len": len(datagram),
    }
