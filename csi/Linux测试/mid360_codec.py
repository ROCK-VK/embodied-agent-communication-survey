"""Bit-exact lossless codec for Livox MID360 Type-1 raw UDP point-cloud frames.

Encodes a sequence of 1380-byte Type-1 packets (36B header + 96 x 14B points) via:
- header column-transpose
- int32 XYZ 1st-order delta + zigzag unsigned mapping + byte-plane shuffle
- reflectivity/tag column-transpose
- zlib compression (default level 3)

Decompression reconstructs the exact original byte sequence (identical SHA-256).
"""
import struct
import zlib
import numpy as np

CODEC_MAGIC = b"M36D"
PKT_BYTES = 1380
HDR_BYTES = 36
PTS_PER_PKT = 96
PT_BYTES = 14


def encode_mid360_lossless(blob: bytes, level: int = 3) -> bytes:
    if not blob or len(blob) % PKT_BYTES != 0:
        raise ValueError(f"Expected non-empty multiple of {PKT_BYTES} bytes, got {len(blob)}")
    n = len(blob) // PKT_BYTES
    arr = np.frombuffer(blob, dtype=np.uint8).reshape(n, PKT_BYTES)
    hdr_t = np.ascontiguousarray(arr[:, :HDR_BYTES].T).tobytes()
    pts_raw = np.ascontiguousarray(arr[:, HDR_BYTES:]).reshape(n * PTS_PER_PKT, PT_BYTES)
    xyz = np.frombuffer(np.ascontiguousarray(pts_raw[:, :12]).tobytes(), dtype="<i4").reshape(-1, 3)
    dxyz = np.empty_like(xyz)
    dxyz[0] = xyz[0]
    dxyz[1:] = xyz[1:] - xyz[:-1]
    u = ((dxyz.astype(np.int64) << 1) ^ (dxyz.astype(np.int64) >> 31)) & 0xFFFFFFFF
    u32 = u.astype("<u4")
    bp = u32.view(np.uint8).reshape(-1, 3, 4).transpose(2, 1, 0)
    rt = np.ascontiguousarray(pts_raw[:, 12:14].T)
    packed = struct.pack("<4sI", CODEC_MAGIC, n) + hdr_t + np.ascontiguousarray(bp).tobytes() + rt.tobytes()
    return zlib.compress(packed, level=level)


def decode_mid360_lossless(comp: bytes) -> bytes:
    packed = zlib.decompress(comp)
    if len(packed) < 8:
        raise ValueError("Truncated MID360 delta payload")
    magic, n = struct.unpack_from("<4sI", packed, 0)
    if magic != CODEC_MAGIC or n == 0:
        raise ValueError("Invalid MID360 delta magic or packet count")
    off = 8
    npts = n * PTS_PER_PKT
    expected = off + n * HDR_BYTES + npts * 12 + npts * 2
    if len(packed) != expected:
        raise ValueError(f"Payload length mismatch: {len(packed)} != {expected}")
    hdr_t = np.frombuffer(packed, dtype=np.uint8, count=n * HDR_BYTES, offset=off).reshape(HDR_BYTES, n).T
    off += n * HDR_BYTES
    bp = np.frombuffer(packed, dtype=np.uint8, count=npts * 12, offset=off).reshape(4, 3, npts).transpose(2, 1, 0)
    off += npts * 12
    rt = np.frombuffer(packed, dtype=np.uint8, count=npts * 2, offset=off).reshape(2, npts).T
    u32 = np.ascontiguousarray(bp).view("<u4").reshape(npts, 3)
    u64 = u32.astype(np.uint64)
    dxyz = ((u64 >> 1) ^ (-(u64 & 1))).astype(np.int64).astype("<i4")
    xyz = np.cumsum(dxyz, axis=0, dtype=np.int64).astype("<i4")
    out = np.empty((n, PKT_BYTES), dtype=np.uint8)
    out[:, :HDR_BYTES] = hdr_t
    pts_out = np.empty((npts, PT_BYTES), dtype=np.uint8)
    pts_out[:, :12] = xyz.view(np.uint8).reshape(npts, 12)
    pts_out[:, 12:14] = rt
    out[:, HDR_BYTES:] = pts_out.reshape(n, PTS_PER_PKT * PT_BYTES)
    return out.tobytes()
