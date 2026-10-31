# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am

BASE = {k: 0.1 for k in am.DRIFT_WEIGHTS}

class AutonomyV4Test(unittest.TestCase):
    def test_weight_sum_one(self):
        self.assertAlmostEqual(sum(am.DRIFT_WEIGHTS.values()), 1.0, places=6)

    def test_distress_low_valence(self):
        self.assertGreater(am.distress_value(0.2, 0.2, -0.8), am.distress_value(0.2, 0.2, 0.8))

    def test_distress_high_anger(self):
        self.assertGreater(am.distress_value(0.1, 0.9, 0.0), am.distress_value(0.1, 0.1, 0.0))

    def test_distress_raises_drift(self):
        self.assertGreater(am.drift_value(dict(BASE, distress=0.9)), am.drift_value(BASE))

    def test_activity_raises_drift(self):
        self.assertGreater(am.drift_value(dict(BASE, activity=1.0)), am.drift_value(BASE))

    def test_activity_weight_small(self):
        delta = am.drift_value(dict(BASE, activity=1.0)) - am.drift_value(dict(BASE, activity=0.0))
        self.assertLess(delta, 0.10)

    def test_user_busy_amplifies_social(self):
        high = am.drift_value(dict(BASE, user_busy=1.0, social_gap=0.5))
        low = am.drift_value(dict(BASE, user_busy=0.0, social_gap=0.5))
        self.assertGreater(high, low)

    def test_social_amplification_ratio(self):
        base = am.drift_value(dict(BASE, social_gap=1.0, user_busy=0.0))
        busy = am.drift_value(dict(BASE, social_gap=1.0, user_busy=1.0))
        self.assertGreater(busy, base)

    def test_user_busy_value_formula(self):
        self.assertAlmostEqual(am.user_busy_value(1.0, 0.0), 0.0)
        self.assertAlmostEqual(am.user_busy_value(0.0, 30.0), 1.0)

    def test_conscientiousness_modulates_memory(self):
        low = am.drift_value(dict(BASE, memory_due=1.0), traits={'conscientiousness': 0.0})
        high = am.drift_value(dict(BASE, memory_due=1.0), traits={'conscientiousness': 1.0})
        self.assertGreater(high, low)

    def test_extraversion_modulates_activity(self):
        low = am.drift_value(dict(BASE, activity=1.0), traits={'extraversion': 0.0})
        high = am.drift_value(dict(BASE, activity=1.0), traits={'extraversion': 1.0})
        self.assertGreater(high, low)

    def test_parts_include_new_fields(self):
        out = am.compute(dict(BASE, distress=0.5, activity=0.5, user_busy=0.5), 0.6)
        for key in ('distress', 'activity', 'user_busy'):
            self.assertIn(key, out['parts'])

    def test_missing_inputs_no_crash(self):
        self.assertGreaterEqual(am.user_busy_value(None, None), 0.0)
        self.assertGreaterEqual(am.drift_value({}), 0.0)

    def test_drift_clamped(self):
        self.assertLessEqual(am.drift_value({k: 1.0 for k in am.DRIFT_WEIGHTS}), 1.0)

if __name__ == '__main__':
    unittest.main()
