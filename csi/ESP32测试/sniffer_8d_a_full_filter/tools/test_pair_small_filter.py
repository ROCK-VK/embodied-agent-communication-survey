"""Static contract and boundary regression for HANDSHAKE pair-small filtering."""
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "main" / "capture_core.inc"
MODE_HANDSHAKE = "HANDSHAKE_ONLY"
CANDIDATE_MAX = 256
PROTECTED = 0x4000


def pair_small_allowed(mode, length, frame_control, exact_pair=True):
    return mode == MODE_HANDSHAKE and exact_pair and length <= CANDIDATE_MAX and not (frame_control & PROTECTED)


class PairSmallFilterTests(unittest.TestCase):
    def test_clear_pair_small_boundary(self):
        self.assertTrue(pair_small_allowed(MODE_HANDSHAKE, 256, 0x0008))
        self.assertFalse(pair_small_allowed(MODE_HANDSHAKE, 257, 0x0008))

    def test_protected_and_non_handshake_frames_are_not_candidates(self):
        self.assertFalse(pair_small_allowed(MODE_HANDSHAKE, 128, 0x4008))
        self.assertFalse(pair_small_allowed("PROBE_CAPTURE", 128, 0x0008))

    def test_pair_diagnostic_still_requires_exact_ap_station_pair(self):
        self.assertFalse(pair_small_allowed(MODE_HANDSHAKE, 128, 0x0008, exact_pair=False))

    def test_c_source_matches_policy_and_preserves_eapol_path(self):
        source = SOURCE.read_text(encoding="utf-8")
        match = re.search(r"bool\s+pair_small\s*=\s*\(([^;]+)\);", source)
        self.assertIsNotNone(match)
        expression = re.sub(r"\s+", "", match.group(1))
        self.assertEqual(
            expression,
            "mode==MODE_HANDSHAKE&&(up||down)&&n<=CANDIDATE_MAX&&!(fc&0x4000)",
        )
        self.assertIn("bool target_related=same(p->payload+10,target)||same(p->payload+4,target);", source)
        self.assertIn("if(target_related){atomic_fetch_add(&prom_target_related_data,1);DUAL_ADD(prom_target_related);}", source)
        self.assertIn("if(!target_related)return;", source)
        self.assertIn("bool eapol=is_eapol(p->payload,n,h);", source)
        self.assertIn("if(!eapol && !pair_small) {", source)
        self.assertIn("atomic_fetch_add(&hs_up_clear_small,1);", source)
        self.assertIn("atomic_fetch_add(&hs_filter_protected,1);", source)
        self.assertIn(r'\"prom_target_related_data\":%u,\"pair_seen\":%u,\"pair_frames\":%u', source)
        self.assertIn(r'\"hs_up_seen\":%u,\"hs_down_seen\":%u', source)


if __name__ == "__main__":
    unittest.main()
