"""Offline synthetic coverage for the dual callback diagnostics and host path."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from dual_diag import (csi_data_candidate, exact_pair_direction,
                       promisc_candidate, timeline_buckets,
                       validate_timeline_rows)
from test_csi_data_eapol import make_csi_record, make_eapol_key
from wire8c import ATOMIC, RAW, TIMELINE, Decoder, encode, parse_header
from wpa2_gate8c import classify_record
from analyze_dual_diag import analyze_capture

STA = '02:00:00:00:00:01'
AP = '02:00:00:00:00:02'
OTHER = '02:00:00:00:00:03'
STA_B = bytes.fromhex(STA.replace(':', ''))
AP_B = bytes.fromhex(AP.replace(':', ''))
OTHER_B = bytes.fromhex(OTHER.replace(':', ''))
SNAP = bytes.fromhex('aaaa03000000')


def make_frame(*, direction='jetson_to_ap', eapol=None, protected=False,
               qos=False, amsdu=False, fragment=0, more_fragments=False,
               third_party=False, body=None):
    down = direction == 'ap_to_jetson'
    fc = 0x0208 if down else 0x0108
    if qos:
        fc |= 0x0080
    if protected:
        fc |= 0x4000
    if more_fragments:
        fc |= 0x0400
    ra, ta = (STA_B, AP_B) if down else (AP_B, STA_B)
    if third_party:
        ra, ta = OTHER_B, AP_B
    seq_ctrl = (0x123 << 4) | (fragment & 15)
    hdr = struct.pack('<HH6s6s6sH', fc, 0, ra, ta, AP_B, seq_ctrl)
    if qos:
        hdr += struct.pack('<H', 0x80 if amsdu else 0)
    if body is not None:
        payload = body
    elif eapol is not None:
        payload = SNAP + b'\x88\x8e' + make_eapol_key(eapol)
    else:
        payload = SNAP + b'\x08\x00' + bytes.fromhex('4500001c0000000040110000') + bytes(16)
    return hdr + payload


def decoded_frame_record(raw, serial):
    row = Decoder().feed(encode(RAW, raw, serial=serial,
                                fc=int.from_bytes(raw[:2], 'little'),
                                seq_ctrl=int.from_bytes(raw[22:24], 'little'),
                                ta=raw[10:16], ra=raw[4:10]))[0]
    return row


class DualDiagTests(unittest.TestCase):
    def test_promisc_accepts_target_clear_eapol_m1_to_m4(self):
        for message, direction in ((1, 'ap_to_jetson'), (2, 'jetson_to_ap'),
                                   (3, 'ap_to_jetson'), (4, 'jetson_to_ap')):
            decision = promisc_candidate(make_frame(direction=direction, eapol=message), STA, AP)
            self.assertTrue(decision['accepted'], decision)
            self.assertEqual(decision['direction'], direction)

    def test_protected_tcp_ack_never_enters_raw_candidate_path(self):
        raw = make_frame(protected=True, body=bytes.fromhex('00112233445566778899aabbccddeeff'))
        self.assertEqual(promisc_candidate(raw, STA, AP)['reason'], 'protected')

    def test_third_party_clear_eapol_is_rejected(self):
        raw = make_frame(eapol=1, third_party=True)
        self.assertEqual(promisc_candidate(raw, STA, AP)['reason'], 'not_exact_pair')

    def test_target_clear_non_eapol_is_rejected(self):
        decision = promisc_candidate(make_frame(), STA, AP)
        self.assertFalse(decision['accepted'])
        self.assertEqual(decision['reason'], 'not_eapol')
        self.assertEqual(decision['ether_type'], 0x0800)

    def test_qos_and_non_qos_eapol_are_both_candidates(self):
        for qos in (False, True):
            decision = promisc_candidate(make_frame(eapol=2, qos=qos), STA, AP)
            self.assertTrue(decision['accepted'])
            raw = make_frame(eapol=2, qos=qos)
            self.assertEqual(parse_header(raw)['header_len'], 26 if qos else 24)

    def test_to_ds_and_from_ds_direction_mapping(self):
        up = parse_header(make_frame(direction='jetson_to_ap'))
        down = parse_header(make_frame(direction='ap_to_jetson'))
        self.assertEqual(exact_pair_direction(up, STA, AP), 'jetson_to_ap')
        self.assertEqual(exact_pair_direction(down, STA, AP), 'ap_to_jetson')
        self.assertIsNone(exact_pair_direction(up, STA, OTHER))

    def test_promisc_candidate_excludes_fragments_and_amsdu_eapol_guesses(self):
        for raw in (make_frame(eapol=1, fragment=1),
                    make_frame(eapol=1, more_fragments=True),
                    make_frame(eapol=1, qos=True, amsdu=True)):
            self.assertFalse(promisc_candidate(raw, STA, AP)['accepted'])

    def test_protected_csi_data_is_retained_as_atomic_record(self):
        raw = make_frame(direction='jetson_to_ap', protected=True)
        row = make_csi_record(raw, serial=20, qos=False)
        verdict = csi_data_candidate(row, STA, AP)
        self.assertTrue(verdict['accepted'], verdict)
        self.assertTrue(verdict['protected'])
        self.assertEqual(verdict['direction'], 'jetson_to_ap')
        self.assertEqual(verdict['csi_len'], row['csi_len'])

    def test_csi_data_accepts_both_target_pair_directions(self):
        for direction in ('jetson_to_ap', 'ap_to_jetson'):
            raw = make_frame(direction=direction, protected=True, qos=True)
            row = make_csi_record(raw, qos=True)
            verdict = csi_data_candidate(row, STA, AP)
            self.assertTrue(verdict['accepted'], verdict)
            self.assertEqual(verdict['direction'], direction)

    def test_csi_overlap_reconstruction_and_qos_header_length(self):
        for qos, expected in ((False, 24), (True, 26)):
            raw = make_frame(qos=qos, protected=True)
            row = make_csi_record(raw, qos=qos)
            self.assertEqual(row['hdr_len'], expected)
            verdict = csi_data_candidate(row, STA, AP)
            self.assertTrue(verdict['accepted'], verdict)
            self.assertEqual(verdict['frame_len'], len(raw))

    def test_csi_rejects_truncated_layout_and_empty_payload(self):
        raw = make_frame(protected=True)
        truncated = make_csi_record(raw, payload_copy=4)
        self.assertFalse(csi_data_candidate(truncated, STA, AP)['accepted'])
        empty = make_csi_record(raw)
        empty['payload_len'] = 0
        empty['payload_copied'] = 0
        empty['payload_hex'] = ''
        empty['hdr_len'] = 24
        self.assertEqual(csi_data_candidate(empty, STA, AP)['reason'], 'empty_payload')

    def test_csi_rejects_malformed_frame_control_safely(self):
        row = make_csi_record(make_frame(protected=True))
        hdr = bytearray.fromhex(row['hdr_hex'])
        hdr[0] = (hdr[0] & 0x03)  # Frame type becomes management; the rest is untrusted.
        row['hdr_hex'] = hdr.hex()
        self.assertFalse(csi_data_candidate(row, STA, AP)['accepted'])

    def test_protected_bit_parser_uses_frame_control_bit_14(self):
        clear = parse_header(make_frame(eapol=1))
        encrypted = parse_header(make_frame(protected=True))
        self.assertEqual(clear['protected'], 0)
        self.assertEqual(encrypted['protected'], 1)

    def test_host_frame_parser_classifies_m1_to_m4_and_source(self):
        for serial, (message, direction) in enumerate(((1, 'ap_to_jetson'),
                                                         (2, 'jetson_to_ap'),
                                                         (3, 'ap_to_jetson'),
                                                         (4, 'jetson_to_ap')), 1):
            row = decoded_frame_record(make_frame(direction=direction, eapol=message), serial)
            parsed, _ = classify_record(row, STA, AP)
            self.assertEqual(parsed['message'], message)
            self.assertEqual(parsed['source_event'], 'FRAME')
            self.assertEqual(parsed['direction'], direction)
            self.assertFalse(parsed['same_record_csi'])

    def test_host_csi_data_keeps_protected_business_bytes_opaque(self):
        cipher = bytes.fromhex('ccddeeff00112233445566778899aabb')
        raw = make_frame(protected=True, body=cipher)
        row = make_csi_record(raw)
        verdict = csi_data_candidate(row, STA, AP)
        self.assertTrue(verdict['accepted'], verdict)
        self.assertEqual(bytes.fromhex(row['hdr_hex'])[:2], raw[:2])
        self.assertEqual(bytes.fromhex(row['payload_hex']), raw[24:])
        # Clear EAPOL parser must reject the Protected MPDU rather than inspect ciphertext.
        with self.assertRaisesRegex(ValueError, 'clear unfragmented'):
            classify_record(row, STA, AP)

    def test_host_parser_rejects_malformed_or_truncated_atomic_record(self):
        row = make_csi_record(make_frame(protected=True), payload_copy=4)
        with self.assertRaisesRegex(ValueError, 'truncated CSI frame payload'):
            from wire8c import assemble_api_parts
            assemble_api_parts(row)

    def test_timeline_buckets_roll_at_200ms_boundaries(self):
        rows = timeline_buckets([
            dict(timestamp_us=1, metric='prom_pair'),
            dict(timestamp_us=199_999, metric='prom_pair'),
            dict(timestamp_us=200_000, metric='csi_protected', count=3),
        ])
        self.assertEqual([(r['start_us'], r['end_us']) for r in rows],
                         [(0, 200_000), (200_000, 400_000)])
        self.assertEqual(rows[0]['counters']['prom_pair'], 2)
        self.assertEqual(rows[1]['counters']['csi_protected'], 3)

    def test_firmware_timeline_wire_records_validate(self):
        payload = json.dumps(dict(event='TIMELINE', mode='HANDSHAKE_DUAL_DIAG',
                                  nominal_bucket_us=200_000, bucket_id=0,
                                  start_us=100, end_us=200_100, actual_span_us=200_000,
                                  csi_data_output=4)).encode()
        row = Decoder().feed(encode(TIMELINE, payload, serial=1))[0]
        result = validate_timeline_rows([row])
        self.assertEqual(result[0]['counters']['csi_data_output'], 4)
        self.assertEqual(result[0]['actual_span_us'], 200_000)

    def test_offline_analyzer_keeps_protected_csi_and_timeline_separate_from_eapol(self):
        raw = make_frame(protected=True)
        row = make_csi_record(raw, serial=1, qos=False)
        hl = row['hdr_len']
        payload = bytes.fromhex(row['payload_hex'])
        csi = bytes.fromhex(row['csi_hex'])
        meta = bytes.fromhex(row['rx_ctrl_hex'])
        prefix = struct.pack('<8Hi', hl, len(payload), len(payload), len(csi), len(csi),
                             len(meta), row['wire_sig_len'], row['wire_dump_len'],
                             row['payload_minus_hdr'])
        atomic = encode(ATOMIC, prefix + meta + bytes.fromhex(row['hdr_hex']) + payload + csi,
                        serial=1, timestamp=1, mono_us=1000, fc=row['fc'],
                        seq_ctrl=row['seq_ctrl'], channel=2, phy=2, rssi=-40,
                        rx_state=0, ta=bytes.fromhex(row['ta'].replace(':', '')),
                        ra=bytes.fromhex(row['ra'].replace(':', '')),
                        source=bytes.fromhex(row['source'].replace(':', '')),
                        rx_seq=row['rx_seq'], valid=1, first_invalid=0)
        timeline = encode(TIMELINE, json.dumps(dict(
            event='TIMELINE', mode='HANDSHAKE_DUAL_DIAG', nominal_bucket_us=200_000,
            bucket_id=0, start_us=1000, end_us=201000, actual_span_us=200000,
            csi_pair=1, csi_protected=1, csi_data_output=1)).encode(), serial=2,
            timestamp=2, mono_us=201000)
        with tempfile.TemporaryDirectory() as td:
            capture = Path(td) / 'capture'
            capture.mkdir()
            (capture / 'stream.bin').write_bytes(atomic + timeline)
            (capture / 'stream.bin.times.jsonl').write_text(
                json.dumps(dict(record_serial=1, host_time_ns=1_700_000_000_000_000_001,
                                host_mono_ns=1000)) + '\n' +
                json.dumps(dict(record_serial=2, host_time_ns=1_700_000_000_200_000_001,
                                host_mono_ns=201000)) + '\n', encoding='utf-8')
            (capture / 'summary.json').write_text(json.dumps(dict(
                firmware='synthetic-test', mode='HANDSHAKE_DUAL_DIAG', duration_s=0.2,
                counters=dict(csi_pair=1, csi_protected=1, csi_data_output=1),
                transport_errors={})), encoding='utf-8')
            result = analyze_capture(capture, STA, AP)
            self.assertEqual(result['record_counts']['CSI_DATA'], 1)
            self.assertEqual(result['record_counts']['TIMELINE'], 1)
            self.assertEqual(result['csi_data']['protected'], 1)
            self.assertEqual(result['csi_data']['valid_csi'], 1)
            self.assertEqual(result['handshake']['messages'], {'1': 0, '2': 0, '3': 0, '4': 0})
            self.assertTrue((capture / 'analysis_private' / 'combined_private.pcap').is_file())
            self.assertTrue((capture / 'dual_diag_report.md').is_file())

    def test_observation_aggregation_does_not_change_capture_decisions(self):
        frames = [make_frame(protected=True) for _ in range(20)] + [
            make_frame(eapol=1, direction='ap_to_jetson')]
        decisions_before = [promisc_candidate(f, STA, AP)['accepted'] for f in frames]
        timeline_buckets([dict(timestamp_us=i * 10_000, metric='prom_pair') for i in range(len(frames))])
        decisions_after = [promisc_candidate(f, STA, AP)['accepted'] for f in frames]
        self.assertEqual(decisions_before, decisions_after)

    def test_high_rate_protected_background_does_not_fill_raw_candidates(self):
        background = [make_frame(protected=True) for _ in range(5000)]
        handshakes = [make_frame(eapol=n, direction='ap_to_jetson' if n in (1, 3)
                                 else 'jetson_to_ap') for n in range(1, 5)]
        accepted_background = sum(promisc_candidate(f, STA, AP)['accepted'] for f in background)
        accepted_handshake = [promisc_candidate(f, STA, AP)['accepted'] for f in handshakes]
        self.assertEqual(accepted_background, 0)
        self.assertEqual(accepted_handshake, [True, True, True, True])


if __name__ == '__main__':
    unittest.main()
