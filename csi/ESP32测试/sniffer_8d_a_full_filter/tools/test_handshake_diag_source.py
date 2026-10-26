"""Static guardrails for the firmware's CSI-centric diagnostic path."""
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'main' / 'capture_core.inc'
STAGED = Path(__file__).resolve().parents[1] / 'main' / 'staged.c'
WIRE = Path(__file__).resolve().parent / 'wire8c.py'
from capture_csi_diag import EXPECTED_MODE, passive_sanity_failures


class HandshakeDiagSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = CORE.read_text(encoding='utf-8')
        cls.staged = STAGED.read_text(encoding='utf-8')
        cls.wire = WIRE.read_text(encoding='utf-8')

    def test_diagnostic_mode_is_separate_and_named(self):
        self.assertIn('MODE_HANDSHAKE_DIAG=3', self.core)
        self.assertIn('"HANDSHAKE_DIAG"', self.core)
        self.assertIn('MODE HANDSHAKE_DIAG', self.staged)
        self.assertIn('MODE_HANDSHAKE_DUAL_DIAG=4', self.core)
        self.assertIn('MODE HANDSHAKE_DUAL_DIAG', self.staged)

    def test_promiscuous_is_counters_only_in_diagnostic_mode(self):
        self.assertIn('if(mode==MODE_HANDSHAKE_DIAG)return;', self.core)
        self.assertIn('CSI-centric HANDSHAKE_DIAG deliberately counts but does not export promisc frames.', self.core)
        self.assertIn('if(mode==MODE_HANDSHAKE_DUAL_DIAG) {', self.core)
        self.assertIn('if(!eapol)return; // Protected/background Data and clear non-EAPOL never enter RAW.', self.core)

    def test_csi_path_accepts_both_exact_infrastructure_directions(self):
        self.assertIn('*up=tods&&!fromds&&same(p+4,ap)&&same(p+10,target);', self.core)
        self.assertIn('*down=!tods&&fromds&&same(p+4,target)&&same(p+10,ap);', self.core)
        self.assertIn('if(mode==MODE_HANDSHAKE_DIAG){csi_diag_cb(p,true);return;}', self.core)
        self.assertIn('if(mode==MODE_HANDSHAKE_DUAL_DIAG){csi_diag_cb(p,false);return;}', self.core)

    def test_export_gate_requires_clear_pair_snap_and_eapol_ethertype(self):
        self.assertIn('if(eapol_only){atomic_fetch_add(&diag_reject_protected,1);return;}', self.core)
        self.assertIn('static const uint8_t snap[]={0xaa,0xaa,3,0,0,0};', self.core)
        self.assertIn('llc[6]==0x88&&llc[7]==0x8e', self.core)
        self.assertIn('memcpy(e->data+base+origp,p->buf,cc);', self.core)
        self.assertIn('put16(e->header+58,p->rx_seq);', self.core)

    def test_dual_promisc_only_enqueues_exact_clear_eapol(self):
        branch = self.core.split('if(mode==MODE_HANDSHAKE_DUAL_DIAG) {', 1)[1].split('\n    }', 1)[0]
        self.assertIn('if(!up&&!down)return;', branch)
        self.assertIn('bool eapol=ethertype&&is_eapol', branch)
        self.assertIn('if(!eapol)return;', branch)
        self.assertIn('DUAL_ADD(prom_raw_enqueued);enqueue(e);return;', branch)
        self.assertNotIn('pair_small', branch)

    def test_dual_csi_path_retains_protected_atomic_records(self):
        protected = self.core.split('if(protected_frame){', 1)[1].split('\n    }else{', 1)[0]
        self.assertIn('if(eapol_only)', protected)
        self.assertIn('DUAL_ADD(csi_protected);', protected)
        self.assertIn('if(!eapol_only&&!csi_valid)return;', self.core)
        self.assertIn('DUAL_ADD(csi_data_enqueued);', self.core)

    def test_dual_timeline_is_bounded_and_has_a_wire_event(self):
        self.assertIn('#define TIMELINE_BUCKET_US 200000', self.core)
        self.assertIn('"TIMELINE"', self.core)
        self.assertIn('atomic_exchange(&metrics->name,0)', self.core)
        self.assertIn('TIMELINE=8', self.wire)

    def test_mode_retains_full_promiscuous_filter(self):
        expected = ('WIFI_PROMIS_FILTER_MASK_MGMT|WIFI_PROMIS_FILTER_MASK_CTRL|'
                    'WIFI_PROMIS_FILTER_MASK_DATA|WIFI_PROMIS_FILTER_MASK_MISC')
        self.assertIn(expected, ''.join(self.staged.split()))

    def test_passive_sanity_uses_firmware_mode_name_and_requires_clean_counters(self):
        self.assertEqual(EXPECTED_MODE['PROBE'], 'PROBE_CAPTURE')
        self.assertEqual(EXPECTED_MODE['HANDSHAKE_DUAL_DIAG'], 'HANDSHAKE_DUAL_DIAG')
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
