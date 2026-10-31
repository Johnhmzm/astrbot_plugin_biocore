# -*- coding: utf-8 -*-
import unittest
from biocore_model import sleep_circadian as sc

NOW_04 = 1_700_000_000 - ((1_700_000_000 / 3600 + 8) % 24 - 4) * 3600

class SleepTest(unittest.TestCase):
    def test_circadian_trough(self):
        self.assertLess(sc.circadian(4), 0.1)
    def test_circadian_peak(self):
        self.assertGreater(sc.circadian(10), 0.9)
    def test_circadian_range(self):
        for hour in range(24):
            self.assertGreaterEqual(sc.circadian(hour), 0.0); self.assertLessEqual(sc.circadian(hour), 1.0)
    def test_sleep_window_inside(self):
        self.assertTrue(sc.in_sleep_window(1.0))
    def test_sleep_window_wake(self):
        self.assertFalse(sc.in_sleep_window(8.0))
    def test_sleep_window_boundaries(self):
        self.assertTrue(sc.in_sleep_window(0.5)); self.assertFalse(sc.in_sleep_window(7.6))
    def test_sleep_state_fields(self):
        state = sc.sleep_state(1_700_000_000)
        for key in ('sleeping', 'circadian', 'sleep_quality', 'asleep_since', 'wake_ts'):
            self.assertIn(key, state)
    def test_quality_from_duration(self):
        self.assertAlmostEqual(sc.quality_from_durations(3.5), 0.5)
    def test_short_sleep_lowers_energy(self):
        self.assertLess(sc.next_day_energy(0.5), sc.next_day_energy(1.0))
    def test_energy_effects(self):
        low = sc.energy_effects(0.2)
        self.assertLess(low['drive_mult'], 1.0); self.assertLess(low['max_chars_mult'], 1.0); self.assertGreater(low['stress_delta'], 0)
    def test_energy_idempotent_same_now(self):
        energy, ts = sc.settled_energy(1.0, 0.5, 8, 1_700_000_000, last_applied_ts=1_700_000_000)
        self.assertEqual(ts, 1_700_000_000)
        self.assertEqual(energy, 1.0)  # same now => no re-application
    def test_energy_wakes_apply(self):
        energy, ts = sc.settled_energy(1.0, 1.0, 8, 1_700_000_000, last_applied_ts=0)
        self.assertEqual(ts, 1_700_000_000); self.assertAlmostEqual(energy, 1.0)

if __name__ == '__main__':
    unittest.main()
