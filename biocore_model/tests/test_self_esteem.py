# -*- coding: utf-8 -*-
import unittest
from biocore_model import self_esteem as se

NOW = 1_700_000_000

class SelfEsteemTest(unittest.TestCase):
    def test_initial_baseline(self):
        state = se.initial(NOW)
        self.assertAlmostEqual(state['value'], se.BASELINE)
    def test_praised_raises(self):
        self.assertAlmostEqual(se.update(se.initial(NOW), 'praised', NOW)['value'], 0.61)
    def test_replied_raises(self):
        self.assertAlmostEqual(se.update(se.initial(NOW), 'replied', NOW)['value'], 0.61)
    def test_ignored_lowers(self):
        self.assertAlmostEqual(se.update(se.initial(NOW), 'ignored', NOW)['value'], 0.5)
    def test_insulted_lowers(self):
        self.assertAlmostEqual(se.update(se.initial(NOW), 'insulted', NOW)['value'], 0.5)
    def test_decay_toward_baseline(self):
        state = {'value': 0.2, 'baseline': se.BASELINE, 'last_decay_ts': NOW - 1}
        self.assertGreater(se.decay(state, NOW)['value'], 0.2)
    def test_decay_same_now_idempotent(self):
        state = {'value': 0.3, 'baseline': se.BASELINE, 'last_decay_ts': NOW}
        self.assertEqual(se.decay(state, NOW)['value'], 0.3)
    def test_update_same_now_does_not_double(self):
        state = se.update(se.initial(NOW), 'praised', NOW)
        again = se.update(se.initial(NOW), 'praised', NOW)
        self.assertAlmostEqual(again['value'], state['value'])
    def test_clamp_upper(self):
        state = {'value': 0.99, 'baseline': se.BASELINE}
        self.assertLessEqual(se.update(state, 'praised', NOW)['value'], 1.0)
    def test_clamp_lower(self):
        state = {'value': 0.01, 'baseline': se.BASELINE}
        self.assertGreaterEqual(se.update(state, 'insulted', NOW)['value'], 0.0)
    def test_unknown_event_no_change(self):
        self.assertAlmostEqual(se.update(se.initial(NOW), 'bogus', NOW)['value'], se.BASELINE)
    def test_confidence_low_esteem(self):
        self.assertLess(se.confidence_delta(0.2), 0)  # lower esteem -> lower confidence
    def test_view_fields(self):
        view = se.view(se.update(se.initial(NOW), 'praised', NOW))
        for key in ('value', 'baseline', 'last_event', 'confidence_delta'):
            self.assertIn(key, view)

if __name__ == '__main__':
    unittest.main()
