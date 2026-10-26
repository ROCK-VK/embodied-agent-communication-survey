"""Synthetic CSI_DATA fixtures for same-record 802.11/EAPOL parsing only."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from wire8c import ATOMIC, Decoder, TRUNCATED, assemble_api_parts, encode
from wpa2_gate8c import classify_record, convert, inspect_llc_snap

STA = '02:00:00:00:00:01'
AP = '02:00:00:00:00:02'
STA_B = bytes.fromhex(STA.replace(':', ''))
AP_B = bytes.fromhex(AP.replace(':', ''))
SNAP = bytes.fromhex('aaaa03000000')


def make_eapol_key(message):
    key_info = {1: 0x008a, 2: 0x010a, 3: 0x03ca, 4: 0x030a}[message]
    e = bytearray(99)
    e[:4] = bytes((2, 3, 0, 95))
    e[4] = 2
    e[5:7] = key_info.to_bytes(2, 'big')
    e[9:17] = (1 if message <= 2 else 2).to_bytes(8, 'big')
    if message in (1, 2, 3):
        e[17:49] = bytes([0x31 if message != 2 else 0x52]) * 32
    if message != 1:
        e[81:97] = bytes([0x77]) * 16
    return bytes(e)


def make_frame(message=None, *, qos=False, protected=False, ethertype=0x888e):
    down = message in (1, 3) if message is not None else False
    fc = (0x0208 if down else 0x0108) | (0x0080 if qos else 0)
    if protected:
        fc |= 0x4000
    ra, ta = (STA_B, AP_B) if down else (AP_B, STA_B)
    seq_ctrl = 0x120
    hdr = struct.pack('<HH6s6s6sH', fc, 0, ra, ta, AP_B, seq_ctrl)
    if qos:
        hdr += b'\x00\x00'
    body = SNAP + ethertype.to_bytes(2, 'big')
    if message is not None:
        body += make_eapol_key(message)
    else:
        body += bytes.fromhex('4500001c0000000040110000') + bytes(16)
    return hdr + body


def make_csi_record(raw, serial=1, *, rx_seq=0x1234, valid=1, rx_state=0,
                    csi=b'\x01\x02\x03\x04', csi_copy=None,
                    payload_copy=None, delta=24, qos=None):
    hl = 26 if qos else 24
    hdr = raw[:hl]
    payload = raw[delta:]
    pc = len(payload) if payload_copy is None else payload_copy
    cc = len(csi) if csi_copy is None else csi_copy
    copied_payload = payload[:pc]
    copied_csi = csi[:cc]
    meta = bytearray(48)
    meta[0] = rx_state
    # CSI callback prefix: header/API payload/CSI lengths, rx_ctrl length, pointer delta.
    prefix = struct.pack('<8Hi', hl, len(payload), pc, len(csi), cc, len(meta),
                         len(raw), len(raw), delta)
    flags = TRUNCATED if pc != len(payload) or cc != len(csi) else 0
    wire = encode(ATOMIC, prefix + meta + hdr + copied_payload + copied_csi,
                  serial=serial, fc=int.from_bytes(raw[:2], 'little'),
                  seq_ctrl=int.from_bytes(raw[22:24], 'little'), channel=2,
                  phy=2, rssi=-40, rx_state=rx_state, flags=flags,
                  original=20 + len(meta) + hl + len(payload) + len(csi),
                  ta=raw[10:16], ra=raw[4:10], source=raw[10:16],
                  rx_seq=rx_seq, valid=valid)
    rows = Decoder().feed(wire)
    if len(rows) != 1:
        raise AssertionError('fixture did not decode as one CSI_DATA')
    return rows[0]


class CsiDataEapolTests(unittest.TestCase):
    def test_csi_data_reconstructs_clear_data(self):
        raw = make_frame(None, ethertype=0x0800)
        r = make_csi_record(raw, qos=False)
        self.assertEqual(assemble_api_parts(r), raw)
        self.assertEqual(r['event'], 'CSI_DATA')
        self.assertFalse(r['mac_header']['protected'])

    def test_csi_data_llc_snap(self):
        raw = make_frame(None, ethertype=0x0800)
        r = make_csi_record(raw, qos=False)
        info = inspect_llc_snap(assemble_api_parts(r))
        self.assertTrue(info['llc_snap'])
        self.assertEqual(info['ether_type'], 0x0800)

    def test_csi_data_ethertype_888e(self):
        raw = make_frame(1, qos=False)
        r = make_csi_record(raw, qos=False)
        info = inspect_llc_snap(assemble_api_parts(r))
        self.assertEqual(info['ether_type'], 0x888e)
        result, _ = classify_record(r, STA, AP)
        self.assertEqual(result['message'], 1)

    def test_csi_data_classifies_m1_to_m4_and_keeps_same_record_csi(self):
        records = []
        for message in range(1, 5):
            raw = make_frame(message, qos=(message % 2 == 0))
            r = make_csi_record(raw, serial=message, rx_seq=0x200 + message,
                                qos=(message % 2 == 0))
            result, assembled = classify_record(r, STA, AP)
            self.assertEqual(assembled, raw)
            self.assertEqual(result['message'], message)
            self.assertEqual(result['record_serial'], message)
            self.assertEqual(result['rx_seq'], 0x200 + message)
            self.assertEqual(result['source_event'], 'CSI_DATA')
            self.assertTrue(result['same_record_csi'])
            self.assertTrue(result['csi_valid'])
            records.append(r)
        self.assertEqual([r['mac_header']['header_len'] for r in records], [24, 26, 24, 26])

    def test_direction_for_both_ds_paths(self):
        for message, direction, tods, fromds in (
            (1, 'ap_to_jetson', 0, 1), (2, 'jetson_to_ap', 1, 0),
            (3, 'ap_to_jetson', 0, 1), (4, 'jetson_to_ap', 1, 0),
        ):
            r = make_csi_record(make_frame(message), serial=message, qos=False)
            result, _ = classify_record(r, STA, AP)
            self.assertEqual(result['direction'], direction)
            self.assertEqual(result['to_ds'], tods)
            self.assertEqual(result['from_ds'], fromds)

    def test_qos_and_non_qos_pointer_overlap_reconstruction(self):
        for qos, expected_hl in ((False, 24), (True, 26)):
            raw = make_frame(2, qos=qos)
            r = make_csi_record(raw, qos=qos)
            self.assertEqual(r['hdr_len'], expected_hl)
            self.assertEqual(r['payload_minus_hdr'], 24)
            self.assertEqual(r['hdr_hex'][48:], r['payload_hex'][:4] if qos else '')
            self.assertEqual(assemble_api_parts(r), raw)

    def test_overlap_mismatch_is_rejected(self):
        r = make_csi_record(make_frame(2, qos=True), qos=True)
        payload = bytearray.fromhex(r['payload_hex'])
        payload[0] ^= 1
        r['payload_hex'] = payload.hex()
        with self.assertRaisesRegex(ValueError, 'overlapping bytes disagree'):
            assemble_api_parts(r)

    def test_malformed_layout_and_truncated_payload_are_rejected(self):
        raw = make_frame(2, qos=True)
        bad_delta = make_csi_record(raw, qos=True, delta=27)
        with self.assertRaisesRegex(ValueError, 'pointer gap'):
            assemble_api_parts(bad_delta)
        truncated = make_csi_record(raw, qos=True, payload_copy=10)
        with self.assertRaisesRegex(ValueError, 'truncated CSI frame payload'):
            assemble_api_parts(truncated)

    def test_protected_data_cannot_be_misclassified_as_clear_eapol(self):
        r = make_csi_record(make_frame(1, protected=True), qos=False)
        with self.assertRaisesRegex(ValueError, 'clear unfragmented'):
            classify_record(r, STA, AP)

    def test_invalid_csi_is_reported_without_breaking_frame_classification(self):
        r = make_csi_record(make_frame(1), valid=0, csi=b'')
        result, _ = classify_record(r, STA, AP)
        self.assertEqual(result['message'], 1)
        self.assertTrue(result['same_record_csi'])
        self.assertFalse(result['csi_valid'])

    def test_convert_classifies_csi_data_and_retains_csi_index(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            capture = base / 'capture'
            capture.mkdir()
            wire = bytearray()
            times = []
            for i in range(1, 5):
                r = make_csi_record(make_frame(i), serial=i, qos=False)
                # Re-encode from decoded wire isn't needed: make the original atomic record.
                raw = make_frame(i)
                hl = 24
                payload = raw[24:]
                csi = bytes.fromhex(r['csi_hex'])
                meta = bytes.fromhex(r['rx_ctrl_hex'])
                prefix = struct.pack('<8Hi', hl, len(payload), len(payload), len(csi), len(csi),
                                     len(meta), len(raw), len(raw), 24)
                payload_block = prefix + meta + raw[:hl] + payload + csi
                wire += encode(ATOMIC, payload_block, serial=i, fc=int.from_bytes(raw[:2], 'little'),
                               seq_ctrl=int.from_bytes(raw[22:24], 'little'), channel=2, phy=2,
                               rssi=-40, rx_state=0, ta=raw[10:16], ra=raw[4:10],
                               source=raw[10:16], rx_seq=0x300+i, valid=1)
                times.append(dict(record_serial=i, host_time_ns=1700000000000000000+i,
                                  host_mono_ns=i))
            (capture / 'stream.bin').write_bytes(wire)
            (capture / 'stream.bin.times.jsonl').write_text(
                '\n'.join(map(json.dumps, times)) + '\n', encoding='utf-8')
            result = convert(capture, base / 'out', STA, AP)
            self.assertTrue(result['handshake']['complete_four_way'])
            self.assertEqual(result['handshake']['messages'], {'1': 1, '2': 1, '3': 1, '4': 1})
            self.assertTrue(all(x['source_event'] == 'CSI_DATA' and x['same_record_csi']
                                and x['csi_valid'] for x in result['eapol_records']))
            index = json.loads((base / 'out' / 'frame_index_private.json').read_text(encoding='utf-8'))
            self.assertEqual([x['rx_seq'] for x in index], [0x301, 0x302, 0x303, 0x304])


if __name__ == '__main__':
    unittest.main()
