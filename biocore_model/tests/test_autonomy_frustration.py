# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am

NOW = 1_700_000_000

class FrustrationTest(unittest.TestCase):
    def test_frustration_increments(self):
        out = am.block_feedback({'frustration': 0}, NOW)
        self.assertEqual(out['acc']['frustration'], 1); self.assertAlmostEqual(out['drive_mult'], 1.04)
    def test_drive_mult_after_four(self):
        out = am.block_feedback({'frustration': 3}, NOW)
        self.assertAlmostEqual(out['drive_mult'], 1.16)
    def test_drive_mult_cap_130(self):
        out = am.block_feedback({'frustration': 10}, NOW)
        self.assertAlmostEqual(out['drive_mult'], 1.30)
    def test_cap_after_12_blocks(self):
        acc = {}
        for _ in range(12):
            out = am.block_feedback(acc, NOW)
            acc = out['acc']
        self.assertAlmostEqual(out['drive_mult'], 1.30)
    def test_emotion_directions(self):
        out = am.block_feedback({}, NOW)
        self.assertGreater(out['stress'], 0); self.assertGreater(out['arousal'], 0); self.assertEqual(out['valence'], 0.0)  # v7: limits only touch stress/arousal
    def test_no_v_decay_field(self):
        self.assertNotIn('drive_scale', am.block_feedback({}, NOW))
    def test_clear_on_success(self):
        acc = am.clear_frustration({'frustration': 5, 'drive_mult': 1.15})
        self.assertEqual(acc['frustration'], 0); self.assertAlmostEqual(acc['drive_mult'], 1.0)
    def test_window_reset_clears_frustration(self):
        acc = am.hourly_window({'hour_window_start': NOW - 3700, 'frustration': 4, 'drive_mult': 1.12}, NOW)
        self.assertEqual(acc['frustration'], 0)
    def test_limit_view_fields(self):
        view = am.limit_view({'frustration': 4, 'drive_mult': 1.12}, 3, NOW)
        self.assertEqual(view['frustration'], 4); self.assertAlmostEqual(view['drive_mult'], 1.12)
    def test_counters_still_count(self):
        out = am.block_feedback({'blocked_count': 6}, NOW)
        self.assertEqual(out['total_blocked'], 7); self.assertEqual(out['acc']['hour_blocked_count'], 1)

if __name__ == '__main__':
    unittest.main()
