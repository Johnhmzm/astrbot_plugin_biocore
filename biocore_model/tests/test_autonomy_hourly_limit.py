# -*- coding: utf-8 -*-
import time, unittest
from biocore_model import autonomy_model as am

NOW = 1_700_000_000

class HourlyLimitTest(unittest.TestCase):
    def test_under_cap_allowed(self):
        ok, acc, cap = am.hourly_allowed({'hour_sent_count': 2}, NOW, 3)
        self.assertTrue(ok); self.assertEqual(cap, 3)
    def test_cap_reached_blocked(self):
        ok, _, _ = am.hourly_allowed({'hour_sent_count': 3}, NOW, 3)
        self.assertFalse(ok)
    def test_window_roll_resets(self):
        acc = am.hourly_window({'hour_window_start': NOW - 3700, 'hour_sent_count': 3, 'hour_blocked_count': 2}, NOW)
        self.assertEqual(acc['hour_sent_count'], 0); self.assertEqual(acc['hour_blocked_count'], 0)
    def test_window_not_reset_within_hour(self):
        acc = am.hourly_window({'hour_window_start': NOW - 100, 'hour_sent_count': 2}, NOW)
        self.assertEqual(acc['hour_sent_count'], 2)
    def test_block_feedback_counters(self):
        out = am.block_feedback({'blocked_count': 6}, NOW)
        self.assertEqual(out['total_blocked'], 7); self.assertEqual(out['acc']['hour_blocked_count'], 1)
    def test_block_feedback_emotion_deltas(self):
        out = am.block_feedback({}, NOW)
        self.assertGreater(out['stress'], 0); self.assertEqual(out['valence'], 0.0); self.assertGreater(out['drive_mult'], 1.0)
    def test_clingy_retry_always_allowed(self):
        self.assertTrue(am.withdraw_retry_allowed(NOW - 60, NOW, clingy=True))
    def test_non_clingy_retry_waits_6h(self):
        self.assertFalse(am.withdraw_retry_allowed(NOW - 60, NOW, clingy=False))
        self.assertTrue(am.withdraw_retry_allowed(NOW - 7 * 3600, NOW, clingy=False))
    def test_limit_view_fields(self):
        view = am.limit_view({'hour_sent_count': 2, 'hour_blocked_count': 5, 'blocked_count': 9}, 3, NOW)
        for key in ('hourly_cap', 'hour_sent', 'hour_blocked', 'total_blocked', 'window_reset_in'):
            self.assertIn(key, view)
    def test_limit_view_values(self):
        view = am.limit_view({'hour_sent_count': 2, 'hour_blocked_count': 5, 'blocked_count': 9}, 3, NOW)
        self.assertEqual(view['hour_sent'], 2); self.assertEqual(view['hour_blocked'], 5); self.assertEqual(view['total_blocked'], 9)
    def test_cap_clamped(self):
        ok, _, cap = am.hourly_allowed({}, NOW, 99)
        self.assertEqual(cap, 12)
    def test_status_snapshot_includes_limit(self):
        snap = am.status_snapshot({'limit': {'hour_sent': 1, 'hourly_cap': 3}})
        self.assertIn('limit', snap)

if __name__ == '__main__':
    unittest.main()
