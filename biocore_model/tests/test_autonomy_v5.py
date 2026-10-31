# -*- coding: utf-8 -*-
import math, unittest
from biocore_model import autonomy_model as am

BASE = {k: 0.1 for k in am.DRIFT_WEIGHTS}

class AutonomyV5Test(unittest.TestCase):
    def test_weight_sum_one(self):
        self.assertAlmostEqual(sum(am.DRIFT_WEIGHTS.values()), 1.0, places=6)
    def test_open_loops_raises_drift(self):
        self.assertGreater(am.drift_value(dict(BASE, open_loops=1.0)), am.drift_value(BASE))
    def test_nostalgia_decay_6h(self):
        self.assertAlmostEqual(am.nostalgia_value(6), math.exp(-1), places=6)
    def test_nostalgia_zero(self):
        self.assertAlmostEqual(am.nostalgia_value(0), 1.0, places=6)
    def test_repair_raises_drift(self):
        self.assertGreater(am.drift_value(dict(BASE, repair_urge=1.0)), am.drift_value(BASE))
    def test_contact_mult_148(self):
        self.assertAlmostEqual(am.contact_mult(0.2), 1.48, places=6)
    def test_contact_amplifies_social(self):
        low = am.drift_value(dict(BASE, social_gap=1.0, attachment_safe=1.0))
        high = am.drift_value(dict(BASE, social_gap=1.0, attachment_safe=0.2))
        self.assertGreater(high, low)
    def test_contact_does_not_amplify_anger(self):
        zero = {k: 0.0 for k in am.DRIFT_WEIGHTS}
        low = am.drift_value(dict(zero, anger_conflict=1.0, contact_mult=1.0))
        high = am.drift_value(dict(zero, anger_conflict=1.0, contact_mult=1.48))
        self.assertAlmostEqual(low, high, places=6)
    def test_parts_complete(self):
        out = am.compute(dict(BASE, open_loops=0.5, nostalgia=0.5, repair_urge=0.5, contact_mult=1.2), 0.6)
        for key in ('open_loops', 'nostalgia', 'repair_urge', 'contact_mult'):
            self.assertIn(key, out['parts'])
    def test_missing_no_crash(self):
        self.assertEqual(am.drift_value({}), 0.0)
        self.assertAlmostEqual(am.nostalgia_value(None), 1.0)
    def test_clamped(self):
        self.assertLessEqual(am.drift_value({k: 1.0 for k in am.DRIFT_WEIGHTS}), 1.0)
    def test_weight_keys(self):
        for key in ('open_loops', 'nostalgia', 'repair_urge'):
            self.assertIn(key, am.DRIFT_WEIGHTS)

if __name__ == '__main__':
    unittest.main()
