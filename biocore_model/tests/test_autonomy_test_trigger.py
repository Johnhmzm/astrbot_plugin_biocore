# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am

class TestTriggerTest(unittest.TestCase):
    def test_sets_v(self):
        out = am.test_trigger({'theta': 0.55}, reset=False)
        self.assertAlmostEqual(out['V_set'], 0.495); self.assertFalse(out['reset'])
    def test_reset_zero(self):
        out = am.test_trigger({'theta': 0.55, 'V': 0.9}, reset=True)
        self.assertEqual(out['V_set'], 0.0); self.assertTrue(out['reset'])
    def test_theta_read(self):
        self.assertEqual(am.test_trigger({'theta': 0.8})['theta'], 0.8)
    def test_default_theta(self):
        self.assertAlmostEqual(am.test_trigger({})['theta'], 0.55)
    def test_missing_acc_no_crash(self):
        self.assertTrue(am.test_trigger(None)['ok'])
    def test_next_tick_can_fire(self):
        out = am.test_trigger({'theta': 0.55})
        tick = am.step(out['V_set'], 0.0, sigma=0.0, theta=out['theta'])
        self.assertGreaterEqual(tick['V_raw'], 0.4)  # leak applies; drift decides firing

if __name__ == '__main__':
    unittest.main()
