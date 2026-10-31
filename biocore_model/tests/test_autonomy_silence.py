# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am

NOW = 1_700_000_000

class SilenceTest(unittest.TestCase):
    def test_expect_phase(self):
        self.assertEqual(am.silence_phase(1.0)['drive_mult'], 1.00)
    def test_protest_phase(self):
        self.assertEqual(am.silence_phase(3.0)['phase'], 'protest')
    def test_loss_phase(self):
        self.assertEqual(am.silence_phase(10.0)['phase'], 'loss')
    def test_withdraw_phase(self):
        self.assertEqual(am.silence_phase(25.0)['phase'], 'withdraw')
    def test_boundary_2h(self):
        self.assertEqual(am.silence_phase(2.0)['phase'], 'protest')
    def test_boundary_6h(self):
        self.assertEqual(am.silence_phase(6.0)['phase'], 'loss')
    def test_boundary_24h(self):
        self.assertEqual(am.silence_phase(24.0)['phase'], 'withdraw')
    def test_silence_zero_after_reply(self):
        self.assertEqual(am.silence_hours(NOW - 3600, NOW, NOW), 0.0)
    def test_silence_hours(self):
        self.assertAlmostEqual(am.silence_hours(NOW - 7200, NOW - 9000, NOW), 2.0)
    def test_nudges_direction(self):
        n = am.silence_nudges(6, 'protest', 0.8)
        self.assertLess(n['valence'], 0); self.assertEqual(n['arousal'], 0.0)
        self.assertEqual(n['stress'], 0.0); self.assertGreater(n['lonely'], 0)
    def test_nudges_dt_capped(self):
        self.assertLessEqual(am.silence_nudges(100, 'loss', 1.0)['dt_hours'], 6.0)
    def test_silence_view_fields(self):
        view = am.silence_view(NOW - 3 * 3600, 0, NOW)
        self.assertIn('hours', view); self.assertIn('phase', view); self.assertIn('drive_mult', view)

if __name__ == '__main__':
    unittest.main()
