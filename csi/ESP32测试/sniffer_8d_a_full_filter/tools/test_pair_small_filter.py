"""Static contract and boundary regression for HANDSHAKE pair-small filtering."""
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "main" / "capture_core.inc"
MODE_HANDSHAKE = "HANDSHAKE_ONLY"
CANDIDATE_MAX = 256
PROTECTED = 0x4000


def pair_small_allowed(mode, length, frame_control):
    return mode == MODE_HANDSHAKE and length <= CANDIDATE_MAX and not (frame_control & PROTECTED)


class PairSmallFilterTests(unittest.TestCase):
    def test_clear_pair_small_boundary(self):
        self.assertTrue(pair_small_allowed(MODE_HANDSHAKE, 256, 0x0008))
        self.assertFalse(pair_small_allowed(MODE_HANDSHAKE, 257, 0x0008))

    def test_protected_and_non_handshake_frames_are_not_candidates(self):
        self.assertFalse(pair_small_allowed(MODE_HANDSHAKE, 128, 0x4008))
        self.assertFalse(pair_small_allowed("PROBE_CAPTURE", 128, 0x0008))

    def test_c_source_matches_policy_and_preserves_eapol_path(self):
        source = SOURCE.read_text(encoding="utf-8")
        match = re.search(r"bool\s+pair_small\s*=\s*\(([^;]+)\);", source)
        self.assertIsNotNone(match)
        expression = re.sub(r"\s+", "", match.group(1))
        self.assertEqual(
            expression,
            "mode==MODE_HANDSHAKE&&n<=CANDIDATE_MAX&&!(fc&0x4000)",
        )
        self.assertIn("if(!eapol && !pair_small)return;", source)


if __name__ == "__main__":
    unittest.main()
