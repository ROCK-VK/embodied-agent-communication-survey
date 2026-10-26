"""Test 8d-a control JSON parsing and field completeness."""
import unittest, json
from wire8c import encode, Decoder

class TestControl8da(unittest.TestCase):
    def test_control_json_observational_fields(self):
        sample_counters = {
            "event": "STATS", "mode": "PROBE_CAPTURE", "mode_epoch": 1,
            "counters_reset": False, "synthetic": False, "rf_capture_enabled": True,
            "target_csi_seen": 10, "candidate_seen": 5, "candidate_enqueued": 5,
            "candidate_output": 5, "large_frame_filtered": 2, "filter_other": 0,
            "handshake_data_count": 0, "queue_drop": 0, "csi_total": 20,
            "target_csi": 5, "raw_drop": 0, "csi_drop": 0, "raw_enqueued": 0,
            "csi_enqueued": 5, "raw_output": 0, "csi_output": 5, "eapol_frames": 0,
            "raw_truncated": 0, "csi_truncated": 0, "payload_truncated": 0,
            "payload_missing": 0, "csi_empty": 0, "hdr_conflict": 0,
            "write_errors": 0, "high_water": 2, "free_heap": 100000,
            "min_free_heap": 95000, "queue_depth": 24, "queue_pending": 0,
            "candidate_max": 256, "channel": 2, "synth_rate": 0,
            "synth_seconds": 0, "synthetic_candidates": 0, "synthetic_large": 0,
            "synthetic_eapol": 0, "wire_bytes": 1024,
            "prom_cb_total": 500, "prom_data": 300, "prom_mgmt": 150, "prom_ctrl": 40, "prom_misc": 10,
            "hs_up_seen": 4, "hs_down_seen": 3, "hs_up_protected": 1, "hs_down_protected": 1,
            "hs_up_clear_small": 2, "hs_down_clear_small": 1, "hs_filter_protected": 2,
            "hs_filter_oversize": 1, "hs_filter_pair_mismatch": 1, "hs_filter_other": 0,
            "csi_cb_total": 20, "csi_null": 0, "csi_source_target": 12, "csi_source_other": 8,
            "csi_hdr_present": 12, "csi_buf_present": 12, "csi_valid_channel_estimate": 10,
            "csi_rxstate_ok": 10, "csi_target_valid": 10,
            "rx_11b": 0, "rx_legacy": 2, "rx_ht": 18, "rx_vht": 0, "rx_other": 0,
            "actual_channel": 2, "actual_mode": 0, "channel_readback_ok": True
        }
        raw_json = json.dumps(sample_counters).encode('utf-8')
        wire = encode(7, raw_json, serial=1)
        d = Decoder()
        records = d.feed(wire)
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r['event'], 'CONTROL')
        c = r['counters']
        self.assertEqual(c['prom_cb_total'], 500)
        self.assertEqual(c['hs_up_clear_small'], 2)
        self.assertEqual(c['hs_filter_pair_mismatch'], 1)
        self.assertEqual(c['csi_cb_total'], 20)
        self.assertEqual(c['rx_ht'], 18)
        self.assertEqual(c['actual_channel'], 2)
        self.assertTrue(c['channel_readback_ok'])

if __name__ == '__main__':
    unittest.main()
