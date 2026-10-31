# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am

BASE = {'social_gap': 0.3, 'lonely': 0.1, 'anxiety_fear': 0.1, 'sadness': 0.1, 'joy': 0.1,
        'anger_conflict': 0.1, 'boredom': 0.1, 'stress_load': 0.1, 'drive_dev': 0.1}

def d(parts): return am.drive(parts)

class AutonomyV2Test(unittest.TestCase):
    def test_weight_sum_is_one(self):
        total = sum(am.DEFAULTS[k] for k in am.WEIGHT_KEYS)
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_anxiety_raises_drive(self):
        self.assertGreater(d(dict(BASE, anxiety_fear=0.9)), d(BASE))

    def test_sadness_raises_drive(self):
        self.assertGreater(d(dict(BASE, sadness=0.9)), d(BASE))

    def test_joy_raises_drive(self):
        self.assertGreater(d(dict(BASE, joy=0.9)), d(BASE))

    def test_anger_raises_drive(self):
        self.assertGreater(d(dict(BASE, anger_conflict=0.9)), d(BASE))

    def test_boredom_raises_drive(self):
        self.assertGreater(d(dict(BASE, boredom=0.9)), d(BASE))

    def test_anger_raises_cost(self):
        high = am.gate(0.8, 0.6, 0.5, anger=1.0)
        low = am.gate(0.8, 0.6, 0.5, anger=0.0)
        self.assertGreater(high['cost'], low['cost'])

    def test_joy_lowers_cost(self):
        high = am.gate(0.8, 0.6, 0.5, joy=1.0)
        low = am.gate(0.8, 0.6, 0.5, joy=0.0)
        self.assertLess(high['cost'], low['cost'])

    def test_anxiety_lowers_cost(self):
        self.assertLess(am.gate(0.8, 0.6, 0.5, anxiety=1.0)['cost'], am.gate(0.8, 0.6, 0.5, anxiety=0.0)['cost'])

    def test_missing_emotions_no_crash(self):
        out = am.compute({}, 0.6)
        self.assertEqual(out['drive'], 0.0)
        self.assertIn('anxiety_fear', out['parts'])

    def test_parts_complete(self):
        out = am.compute(BASE, 0.6)
        for key in ('social_gap', 'lonely', 'anxiety_fear', 'sadness', 'joy', 'anger_conflict', 'boredom', 'stress_load', 'drive_dev'):
            self.assertIn(key, out['parts'])

    def test_gate_fields(self):
        out = am.compute(BASE, 0.6)
        for key in ('p_ready', 'benefit', 'cost', 'expected'):
            self.assertIn(key, out['gate'])

    def test_habit_still_applies(self):
        self.assertAlmostEqual(am.habit(1.0, 2), 0.49, places=6)

    def test_missing_weights_fall_back(self):
        self.assertGreaterEqual(am.drive(dict(BASE, joy=1.0), {'w_joy': 0.5}), 0.0)

    def test_ready_false_without_gate(self):
        self.assertFalse(am.compute({}, 0.6)['ready'])

if __name__ == '__main__':
    unittest.main()
