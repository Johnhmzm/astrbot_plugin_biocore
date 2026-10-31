# -*- coding: utf-8 -*-
import unittest
from biocore_model import social_pain as sp

NOW = 1_700_000_000

class SocialPainTest(unittest.TestCase):
    def test_initial_zero(self):
        self.assertEqual(sp.initial(NOW)['value'], 0.0)
    def test_ignored_adds(self):
        self.assertAlmostEqual(sp.update(sp.initial(NOW - 10), 'ignored', NOW)['value'], 0.05)
    def test_rejected_adds(self):
        self.assertAlmostEqual(sp.update(sp.initial(NOW - 10), 'rejected', NOW)['value'], 0.10)
    def test_excluded_adds(self):
        self.assertAlmostEqual(sp.update(sp.initial(NOW - 10), 'excluded', NOW)['value'], 0.15)
    def test_replied_lowers(self):
        state = dict(sp.initial(NOW - 10), value=0.5, last_value=0.5)
        self.assertAlmostEqual(sp.update(state, 'replied', NOW)['value'], 0.4)
    def test_comforted_lowers(self):
        state = dict(sp.initial(NOW - 10), value=0.5, last_value=0.5)
        self.assertAlmostEqual(sp.update(state, 'comforted', NOW)['value'], 0.35)
    def test_decay_per_hour(self):
        state = dict(sp.initial(NOW - 3600 * 2), value=0.3, last_value=0.3)
        self.assertAlmostEqual(sp.decay(state, NOW)['value'], 0.26)
    def test_decay_same_now_idempotent(self):
        state = dict(sp.initial(NOW - 10), value=0.3, last_decay_ts=NOW)
        self.assertEqual(sp.decay(state, NOW)['value'], 0.3)
    def test_update_same_now_no_double(self):
        first = sp.update(sp.initial(NOW - 10), 'rejected', NOW)
        second = sp.update(first, 'rejected', NOW)
        self.assertEqual(second['value'], first['value'])
    def test_clamp_upper(self):
        state = dict(sp.initial(NOW - 10), value=0.95)
        self.assertLessEqual(sp.update(state, 'excluded', NOW)['value'], 1.0)
    def test_clamp_lower(self):
        state = dict(sp.initial(NOW - 10), value=0.02)
        self.assertGreaterEqual(sp.update(state, 'comforted', NOW)['value'], 0.0)
    def test_independent_from_stress(self):
        state = sp.update(sp.initial(NOW - 10), 'rejected', NOW)
        self.assertNotIn('stress', state); self.assertNotIn('allostatic_load', state)
    def test_drive_and_gate(self):
        self.assertAlmostEqual(sp.drive_delta(0.4), 0.2)
        self.assertAlmostEqual(sp.gate_cost(0.4), 0.02)
    def test_view_fields(self):
        view = sp.view(sp.update(sp.initial(NOW - 10), 'ignored', NOW))
        for key in ('value', 'last_event', 'trend'): self.assertIn(key, view)

if __name__ == '__main__':
    unittest.main()
