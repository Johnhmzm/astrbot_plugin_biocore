# -*- coding: utf-8 -*-
import math, unittest
from biocore_model import autonomy_model as am

class AutonomyModelTest(unittest.TestCase):
    def test_gap_zero_near_zero(self):
        self.assertLess(am.social_gap(0, 18, 1.0, 1.0), 0.01)

    def test_gap_12h_about_half(self):
        self.assertAlmostEqual(am.social_gap(12, 18, 1.0, 1.0), 0.487, delta=0.05)

    def test_gap_48h_about_09(self):
        value = am.social_gap(48, 18, 1.0, 1.0) * (0.6 + 0.4 * 1.0)
        self.assertGreater(value, 0.85)

    def test_closeness_scales_gap(self):
        self.assertGreater(am.social_gap(24, 18, 1.0, 1.0), am.social_gap(24, 18, 1.0, 0.0))

    def test_lonely_multiplies_prob_intensity(self):
        self.assertAlmostEqual(am.lonely(0.8, 0.5), 0.4)

    def test_quiet_raises_cost(self):
        quiet = am.gate(0.8, 0.6, 0.5, 0.35, quiet=True)
        normal = am.gate(0.8, 0.6, 0.5, 0.35, quiet=False)
        self.assertGreater(quiet['cost'], normal['cost'])

    def test_recent_activity_lowers_cost(self):
        active = am.gate(0.8, 0.6, 0.5, 0.35, recent_user_active=True)
        idle = am.gate(0.8, 0.6, 0.5, 0.35, recent_user_active=False)
        self.assertLess(active['cost'], idle['cost'])

    def test_lonely_discounts_cost(self):
        high = am.gate(0.8, 0.6, 0.5, 0.35, lonely_value=1.0)
        low = am.gate(0.8, 0.6, 0.5, 0.35, lonely_value=0.0)
        self.assertLess(high['cost'], low['cost'])

    def test_habit_power(self):
        self.assertAlmostEqual(am.habit(1.0, 0), 1.0)
        self.assertAlmostEqual(am.habit(1.0, 1), 0.7)
        self.assertAlmostEqual(am.habit(1.0, 2), 0.49)

    def test_compute_fields(self):
        out = am.compute({'social_gap': 0.5, 'lonely': 0.2, 'stress_load': 0.1, 'drive_dev': 0.1, 'echo': 0.0, 'noise': 0.2}, 0.6)
        for key in ('drive', 'parts', 'gate', 'ready'):
            self.assertIn(key, out)
        for key in ('social_gap', 'lonely', 'anxiety_fear', 'sadness', 'joy', 'anger_conflict', 'boredom', 'stress_load', 'drive_dev'):
            self.assertIn(key, out['parts'])
        for key in ('p_ready', 'benefit', 'cost', 'expected'):
            self.assertIn(key, out['gate'])

    def test_weights_normalised(self):
        out = am.compute({'social_gap': 1.0, 'lonely': 1.0, 'stress_load': 1.0, 'drive_dev': 1.0, 'echo': 1.0, 'noise': 1.0}, 0.6)
        self.assertLessEqual(out['drive'], 1.0)

    def test_ready_requires_gate_and_threshold(self):
        out = am.compute({'social_gap': 0.0, 'lonely': 0.0, 'stress_load': 0.0, 'drive_dev': 0.0, 'echo': 0.0, 'noise': 0.0}, 0.6)
        self.assertFalse(out['ready'])

if __name__ == '__main__':
    unittest.main()
