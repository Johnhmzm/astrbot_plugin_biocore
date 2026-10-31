# -*- coding: utf-8 -*-
import random, unittest
from biocore_model import autonomy_model as am

NOW = 1_700_000_000

class ClingyTest(unittest.TestCase):
    def test_withdraw_clingy(self):
        self.assertAlmostEqual(am.silence_phase(30, True)['drive_mult'], 0.90)
    def test_withdraw_fallback(self):
        self.assertAlmostEqual(am.silence_phase(30, False)['drive_mult'], 0.35)
    def test_other_phases(self):
        self.assertAlmostEqual(am.silence_phase(1, True)['drive_mult'], 1.00)
        self.assertAlmostEqual(am.silence_phase(3, True)['drive_mult'], 1.20)
        self.assertAlmostEqual(am.silence_phase(10, True)['drive_mult'], 0.80)
    def test_retry_allowed(self):
        self.assertTrue(am.withdraw_retry_allowed(NOW - 7 * 3600, NOW))
    def test_retry_blocked(self):
        self.assertFalse(am.withdraw_retry_allowed(NOW - 2 * 3600, NOW))
    def test_burst_probability(self):
        rng = random.Random(0)
        hits = sum(1 for _ in range(2000) if am.clingy_burst(rng))
        self.assertGreater(hits / 2000, 0.10); self.assertLess(hits / 2000, 0.30)
    def test_burst_zero(self):
        self.assertFalse(am.clingy_burst(random.Random(1), p=0.0))
    def test_burst_one(self):
        self.assertTrue(am.clingy_burst(random.Random(1), p=1.0))
    def test_view_multiplier_on_burst(self):
        view = am.silence_view(NOW - 30 * 3600, 0, NOW, clingy=True, rng=random.Random(0))
        if view['burst']:
            self.assertAlmostEqual(view['effective_mult'], round(view['drive_mult'] * 1.5, 4))
    def test_view_fields(self):
        view = am.silence_view(NOW - 3 * 3600, 0, NOW, clingy=True)
        for key in ('hours', 'phase', 'drive_mult', 'burst', 'clingy', 'effective_mult'):
            self.assertIn(key, view)
    def test_status_keeps_clingy(self):
        snap = am.status_snapshot({'silence': {'phase': 'withdraw', 'clingy': True, 'burst': True}})
        self.assertTrue(snap['silence']['clingy'])

if __name__ == '__main__':
    unittest.main()
