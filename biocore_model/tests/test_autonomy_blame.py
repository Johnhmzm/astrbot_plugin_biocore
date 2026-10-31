# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am, proactive_context as pc

class BlameTest(unittest.TestCase):
    def test_6h_low(self):
        self.assertLess(am.self_blame_value(6, 0.4, 'secure'), 0.12)
    def test_24h(self):
        self.assertAlmostEqual(am.self_blame_value(24, 0.4, 'secure'), 0.4)
    def test_48h_capped(self):
        self.assertAlmostEqual(am.self_blame_value(48, 0.4, 'secure'), 0.7)
    def test_rs_scales(self):
        self.assertAlmostEqual(am.self_blame_value(24, 0.8, 'secure'), 0.7)
    def test_anxious(self):
        self.assertAlmostEqual(am.self_blame_value(24, 0.4, 'anxious'), 0.52)
    def test_avoidant(self):
        self.assertAlmostEqual(am.self_blame_value(24, 0.4, 'avoidant'), 0.2)
    def test_decay(self):
        self.assertAlmostEqual(am.self_blame_decay(0.4, 2), 0.2)
        self.assertEqual(am.self_blame_decay(0.4, 5), 0.0)
    def test_blame_mult(self):
        self.assertAlmostEqual(am.blame_mult('anxious', 0.5), 1.075)
        self.assertAlmostEqual(am.blame_mult('avoidant', 0.5), 0.85)
        self.assertAlmostEqual(am.blame_mult('secure', 0.5), 1.0)
    def test_blame_effects(self):
        eff = am.blame_effects(0.4)
        self.assertAlmostEqual(eff['valence'], -0.04); self.assertAlmostEqual(eff['confidence'], 0.8)
        self.assertNotIn('stress', eff); self.assertNotIn('arousal', eff)
    def test_motive_fields(self):
        view = am.motive_view(24, 2, attachment_style='anxious', self_blame=0.5)
        for key in ('silence_mult', 'frust_mult', 'blame_mult', 'total_mult', 'confidence'):
            self.assertIn(key, view)
    def test_clamp_range(self):
        self.assertLessEqual(am.compose_mult(2.0, 10, 1.5), 1.8)
        self.assertGreaterEqual(am.compose_mult(0.2, 0, 0.5), 0.2)
    def test_confidence(self):
        self.assertAlmostEqual(am.motive_view(0, 0, self_blame=0.4)['confidence'], 0.8)
    def test_tone_lines(self):
        self.assertEqual(len(pc.tone_lines(0.2)), 0)
        self.assertEqual(len(pc.tone_lines(0.4)), 1)
        self.assertEqual(len(pc.tone_lines(0.6)), 2)

if __name__ == '__main__':
    unittest.main()
