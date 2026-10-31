# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am

class V7Test(unittest.TestCase):
    def test_weight_sum_one(self):
        self.assertAlmostEqual(sum(am.DRIFT_WEIGHTS.values()), 1.0, places=3)
    def test_guilt_gratitude_inputs(self):
        self.assertGreater(am.drift_value({'guilt': 1.0}), am.drift_value({}))
        self.assertGreater(am.drift_value({'gratitude': 1.0}), am.drift_value({}))
    def test_guilt_value(self):
        self.assertAlmostEqual(am.guilt_value(1.0, 0.0), 0.7)
    def test_gratitude_value(self):
        self.assertAlmostEqual(am.gratitude_value(1.0, 0.0), 0.6)
    def test_silence_mult_secure(self):
        self.assertAlmostEqual(am.silence_mult(3.0, attachment_style='secure'), 1.2)
    def test_anxious_protest(self):
        self.assertAlmostEqual(am.silence_mult(3.0, attachment_style='anxious'), round(1.2 * 1.4, 4))
    def test_avoidant_withdraw(self):
        self.assertAlmostEqual(am.silence_mult(30.0, clingy=True, attachment_style='avoidant'), round(0.9 * 0.2, 4))
    def test_anxious_withdraw(self):
        self.assertAlmostEqual(am.silence_mult(30.0, clingy=True, attachment_style='anxious'), round(0.9 * 0.9, 4))
    def test_frust_mult(self):
        self.assertAlmostEqual(am.frust_mult(4), 1.16)
        self.assertAlmostEqual(am.frust_mult(10), 1.30)
        self.assertAlmostEqual(am.frust_mult(99), 1.30)
    def test_total_cap(self):
        self.assertEqual(am.compose_mult(1.2, 10), 1.56)
    def test_total_cap_160(self):
        self.assertLessEqual(am.compose_mult(2.0, 10), 1.8)
    def test_total_floor(self):
        self.assertGreaterEqual(am.compose_mult(0.2, 0), 0.20)
    def test_withdraw_high_frustration_bounded(self):
        total = am.compose_mult(0.35, 10)
        self.assertLessEqual(total, 1.8); self.assertGreaterEqual(total, 0.2)
    def test_motive_fields(self):
        view = am.motive_view(3.0, 4)
        for key in ('silence_mult', 'frust_mult', 'total_mult', 'hours'):
            self.assertIn(key, view)
    def test_emotion_effects_division(self):
        effects = am.emotion_effects({'guilt': 1.0, 'gratitude': 1.0})
        self.assertIn('valence', effects); self.assertIn('repair_urge', effects)
    def test_parts_include_guilt_gratitude(self):
        out = am.compute({'guilt': 0.5, 'gratitude': 0.5}, 0.6)
        self.assertIn('guilt', out['parts']); self.assertIn('gratitude', out['parts'])

if __name__ == '__main__':
    unittest.main()
