"""Offline WPA2 decryption & exact MPDU-to-CSI verification without CLI key exposure.

The Wi-Fi passphrase is read interactively via getpass (or stdin when piped) and
written only to a short-lived temporary Wireshark profile directory that is removed
immediately after TShark exits; the key never appears in process command arguments
and is never printed or saved to project files.
"""
import argparse
import collections
import getpass
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

import multimodal_stream as proto

DEFAULT_TSHARK = os.environ.get("TSHARK_PATH", "tshark")


def read_secret():
    if sys.stdin.isatty():
        return getpass.getpass("Wi-Fi key: ")
    return sys.stdin.readline().rstrip("\r\n")


def run_tshark_decrypt(tshark_path, pcap_path, ssid, secret, udp_port):
    """Run TShark using a temporary APPDATA/Wireshark profile (no key on CLI)."""
    tmp_root = pathlib.Path(tempfile.mkdtemp(prefix="ws_prof_"))
    try:
        ws_dir = tmp_root / "Wireshark"
        ws_dir.mkdir(parents=True, exist_ok=True)
        # Escape quotes/backslashes for Wireshark UAT 80211_keys format
        esc_pwd = secret.replace("\\", "\\\\").replace('"', '\\"')
        esc_ssid = ssid.replace("\\", "\\\\").replace('"', '\\"')
        (ws_dir / "80211_keys").write_text(
            f'"wpa-pwd","{esc_pwd}:{esc_ssid}"\n',
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["APPDATA"] = str(tmp_root)
        env["WIRESHARK_CONFIG_DIR"] = str(ws_dir)
        cmd = [
            str(tshark_path),
            "-r",
            str(pcap_path),
            "-o",
            "wlan.enable_decryption:TRUE",
            "-Y",
            f"udp.dstport=={udp_port}",
            "-T",
            "fields",
            "-E",
            "separator=|",
            "-e",
            "frame.number",
            "-e",
            "wlan.seq",
            "-e",
            "wlan.frag",
            "-e",
            "wlan.fc.retry",
            "-e",
            "udp.payload",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"tshark exited with code {proc.returncode}")
        return proc.stdout
    finally:
        # Overwrite and remove key file before deleting temp directory
        key_file = tmp_root / "Wireshark" / "80211_keys"
        if key_file.exists():
            key_file.write_bytes(b"\x00" * max(64, key_file.stat().st_size))
        shutil.rmtree(tmp_root, ignore_errors=True)


def extract_pcap_mpdus(pcap_path, frame_numbers):
    """Read raw 802.11 MPDUs (radiotap stripped, trailing 4-byte FCS stripped if present)."""
    wanted = set(frame_numbers)
    result = {}
    with pcap_path.open("rb") as f:
        hdr = f.read(24)
        if hdr[:4] != bytes.fromhex("d4c3b2a1"):
            raise ValueError("expected little-endian microsecond pcap")
        idx = 0
        while True:
            ph = f.read(16)
            if not ph:
                break
            if len(ph) != 16:
                raise ValueError("truncated pcap packet header")
            _, _, incl_len, _ = struct.unpack("<IIII", ph)
            data = f.read(incl_len)
            if len(data) != incl_len:
                raise ValueError("truncated pcap packet body")
            idx += 1
            if idx not in wanted:
                continue
            rt_len = int.from_bytes(data[2:4], "little")
            flags_present = int.from_bytes(data[4:8], "little")
            # Radiotap bit 1 = Flags (offset 8 if bit 0 TSFT absent, else 16)
            has_fcs = False
            if rt_len > 8 and (flags_present & 0x2):
                # Simple check: if TSFT(bit 0) present, Flags is at byte 16; else at byte 8
                off = 8
                # Skip extended present bitmasks (bit 31)
                p = 4
                while int.from_bytes(data[p : p + 4], "little") & 0x80000000:
                    p += 4
                off = p + 4
                if flags_present & 0x1:
                    off = ((off + 7) // 8) * 8 + 8
                if off < rt_len:
                    has_fcs = bool(data[off] & 0x10)
            mpdu = data[rt_len : len(data) - (4 if has_fcs else 0)]
            result[idx] = mpdu
    return result


def parse_tshark_lines(stdout, run_id, source_dir, manifest, record_map=None):
    samples = {s["sample_id"]: s for s in manifest["samples"]}
    sample_blobs = {}
    for sid, s in samples.items():
        blob = (source_dir / s["filename"]).read_bytes()
        if len(blob) != s["size"] or hashlib.sha256(blob).hexdigest() != s["sha256"]:
            raise ValueError(f"source sample {sid} SHA-256 mismatch")
        sample_blobs[sid] = blob

    rows = []
    for line in stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 5:
            continue
        frame_s, seq_s, frag_s, retry_s, hex_payload = parts
        if not hex_payload:
            continue
        try:
            payload = bytes.fromhex(hex_payload.replace(":", ""))
            meta, chunk_data = proto.unpack_any(payload)
        except ValueError:
            continue
        if meta["run_id"] != run_id:
            continue
        sid = meta["sample_id"]
        if sid not in samples:
            continue
        s = samples[sid]
        if (
            meta["sha256"] != s["sha256"]
            or meta["total"] != s["size"]
            or meta["chunk_count"] != s["chunks"]
        ):
            continue
        blk = meta["block_size"]
        expected_chunk = sample_blobs[sid][meta["chunk_index"] * blk : (meta["chunk_index"] + 1) * blk]
        if chunk_data != expected_chunk:
            continue
        row = {
            **meta,
            "pcap_frame": int(frame_s),
            "wlan_seq": seq_s,
            "wlan_frag": frag_s,
            "retry": retry_s in ("1", "True", "true"),
        }
        if record_map is not None:
            if frame_s not in record_map:
                continue
            row.update(record_map[frame_s])
        rows.append(row)
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=pathlib.Path, required=True, help="Sender output directory")
    p.add_argument("--work", type=pathlib.Path, required=True, help="Offline work dir with csi_mpdu_private.pcap & record_map_private.json")
    p.add_argument("--monitor-pcap", type=pathlib.Path, required=True, help="Monitor pcap with handshake+frames (or combined)")
    p.add_argument("--handshake", type=pathlib.Path, required=True, help="Handshake pcap for monitor pcap decryption if needed")
    p.add_argument("--ssid", required=True)
    p.add_argument("--run", type=int, required=True)
    p.add_argument("--port", type=int, default=39001)
    p.add_argument("--tshark", type=pathlib.Path, default=pathlib.Path(DEFAULT_TSHARK))
    args = p.parse_args()

    secret = read_secret()
    if not secret:
        raise RuntimeError("Empty Wi-Fi key")

    manifest = json.loads((args.source / "sender_manifest.json").read_text(encoding="utf-8"))
    record_map = json.loads((args.work / "record_map_private.json").read_text(encoding="utf-8"))

    # 1. Decrypt CSI-embedded MPDUs
    csi_pcap = args.work / "csi_mpdu_private.pcap"
    csi_out = run_tshark_decrypt(args.tshark, csi_pcap, args.ssid, secret, args.port)
    csi_rows = parse_tshark_lines(csi_out, args.run, args.source, manifest, record_map=record_map)
    csi_rows = [r for r in csi_rows if r.get("csi_structural")]

    # 2. Build combined handshake + monitor pcap if monitor pcap lacks EAPOL, then decrypt monitor pcap
    # Reuse monitor_with_hs_private.pcap in work dir
    comb_pcap = args.work / "monitor_with_hs_private.pcap"
    if not comb_pcap.exists():
        # Merge handshake + monitor pcap (same little-endian header)
        with args.handshake.open("rb") as fh, args.monitor_pcap.open("rb") as fm, comb_pcap.open("wb") as fo:
            h1 = fh.read(24)
            h2 = fm.read(24)
            if h1[:4] != bytes.fromhex("d4c3b2a1") or h2[:4] != bytes.fromhex("d4c3b2a1"):
                raise ValueError("Unsupported pcap endianness")
            fo.write(h1)
            shutil.copyfileobj(fh, fo)
            shutil.copyfileobj(fm, fo)

    pcap_out = run_tshark_decrypt(args.tshark, comb_pcap, args.ssid, secret, args.port)
    pcap_rows = parse_tshark_lines(pcap_out, args.run, args.source, manifest, record_map=None)

    # 3. Exact byte-for-byte MPDU crosscheck between CSI-extracted MPDU and monitor PCAP MPDU
    csi_mpdus = extract_pcap_mpdus(csi_pcap, [r["pcap_frame"] for r in csi_rows])
    pcap_mpdus = extract_pcap_mpdus(comb_pcap, [r["pcap_frame"] for r in pcap_rows])

    pcap_by_pid = collections.defaultdict(list)
    for r in pcap_rows:
        pcap_by_pid[r["packet_id"]].append((r["pcap_frame"], pcap_mpdus[r["pcap_frame"]]))

    crosscheck = []
    verified_rows = []
    for r in csi_rows:
        c_bytes = csi_mpdus[r["pcap_frame"]]
        matches = [pf for pf, pb in pcap_by_pid.get(r["packet_id"], []) if pb == c_bytes]
        crosscheck.append({
            "packet_id": r["packet_id"],
            "record": r["record"],
            "csi_frame": r["pcap_frame"],
            "matching_pcap_frames": matches,
        })
        if len(matches) >= 1:
            verified_rows.append(r)

    unique_csi_ids = {r["packet_id"] for r in verified_rows}
    unique_pcap_ids = {r["packet_id"] for r in pcap_rows}
    pcap_only_ids = sorted(unique_pcap_ids - unique_csi_ids)

    verified_doc = {
        "run_id": args.run,
        "matched_records": len(verified_rows),
        "unique_packet_ids": len(unique_csi_ids),
        "pcap_unique_packet_ids": len(unique_pcap_ids),
        "pcap_only_packet_ids": pcap_only_ids,
        "rows": verified_rows,
    }
    (args.work / "multimodal_verified_private.json").write_text(json.dumps(verified_doc, indent=2), encoding="utf-8")
    (args.work / "crosscheck_private.json").write_text(json.dumps(crosscheck, indent=2), encoding="utf-8")
    (args.work / "pcap_results_private.json").write_text(json.dumps(pcap_rows, indent=2), encoding="utf-8")

    print(json.dumps({
        "run_id": args.run,
        "csi_verified_records": len(verified_rows),
        "csi_unique_packet_ids": len(unique_csi_ids),
        "pcap_unique_packet_ids": len(unique_pcap_ids),
        "pcap_only_count": len(pcap_only_ids),
    }, indent=2))


if __name__ == "__main__":
    main()
