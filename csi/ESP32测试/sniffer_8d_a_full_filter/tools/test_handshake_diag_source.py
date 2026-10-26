"""Static guardrails for the firmware's CSI-centric diagnostic path."""
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'main' / 'capture_core.inc'
STAGED = Path(__file__).resolve().parents[1] / 'main' / 'staged.c'
from capture_csi_diag import EXPECTED_MODE, passive_sanity_failures


class HandshakeDiagSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = CORE.read_text(encoding='utf-8')
        cls.staged = STAGED.read_text(encoding='utf-8')

    def test_diagnostic_mode_is_separate_and_named(self):
        self.assertIn('MODE_HANDSHAKE_DIAG=3', self.core)
        self.assertIn('"HANDSHAKE_DIAG"', self.core)
        self.assertIn('MODE HANDSHAKE_DIAG', self.staged)

    def test_promiscuous_is_counters_only_in_diagnostic_mode(self):
        self.assertIn('if(mode==MODE_HANDSHAKE_DIAG)return;', self.core)
        self.assertIn('CSI-centric diagnostics use CSI_DATA as the frame source', self.core)

    def test_csi_path_accepts_both_exact_infrastructure_directions(self):
        self.assertIn('bool up=tods&&!fromds&&same(hdr+4,ap)&&same(hdr+10,target);', self.core)
        self.assertIn('bool down=!tods&&fromds&&same(hdr+4,target)&&same(hdr+10,ap);', self.core)
        self.assertIn('if(mode==MODE_HANDSHAKE_DIAG){csi_diag_cb(p);return;}', self.core)

    def test_export_gate_requires_clear_pair_snap_and_eapol_ethertype(self):
        self.assertIn('if(fc&0x4000){atomic_fetch_add(&diag_protected', self.core)
        self.assertIn('static const uint8_t snap[]={0xaa,0xaa,3,0,0,0};', self.core)
        self.assertIn('llc[6]!=0x88||llc[7]!=0x8e', self.core)
        self.assertIn('memcpy(e->data+base+origp,p->buf,cc);', self.core)
        self.assertIn('put16(e->header+58,p->rx_seq);', self.core)

    def test_mode_retains_full_promiscuous_filter(self):
        expected = ('WIFI_PROMIS_FILTER_MASK_MGMT|WIFI_PROMIS_FILTER_MASK_CTRL|'
                    'WIFI_PROMIS_FILTER_MASK_DATA|WIFI_PROMIS_FILTER_MASK_MISC')
        self.assertIn(expected, ''.join(self.staged.split()))

    def test_passive_sanity_uses_firmware_mode_name_and_requires_clean_counters(self):
        self.assertEqual(EXPECTED_MODE['PROBE'], 'PROBE_CAPTURE')
        summary = dict(mode='PROBE', channel=2, actual_channel=2,
                       channel_readback_ok=True, mode_ack=True, stop_ack=True,
                       final_received=True, transport_errors={},
                       counters={'csi_target_valid': 1, 'queue_drop': 0,
                                 'raw_drop': 0, 'csi_drop': 0, 'write_errors': 0,
                                 'raw_truncated': 0, 'csi_truncated': 0,
                                 'payload_truncated': 0})
        self.assertEqual(passive_sanity_failures(summary), [])
        summary['counters']['csi_target_valid'] = 0
        summary['counters']['queue_drop'] = 1
        self.assertIn('target valid CSI is zero', passive_sanity_failures(summary))
        self.assertIn('queue_drop is nonzero', passive_sanity_failures(summary))


if __name__ == '__main__':
    unittest.main()
