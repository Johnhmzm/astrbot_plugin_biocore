# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_affect as aa

class FakeCore:
    v = 0.0; a = 0.5; stress = 0.2; social = 0.5; confidence = 1.0

NOW = 1_700_000_000

class AffectTest(unittest.TestCase):
    def test_silence_deltas(self):
        delta = aa.compute_deltas(24, 1.0, 0.0)
        self.assertAlmostEqual(delta['valence'], -0.015); self.assertAlmostEqual(delta['lonely'], 0.02)
    def test_blame_valence(self):
        delta = aa.compute_deltas(0, 0.0, 0.5)
        self.assertAlmostEqual(delta['valence'], -0.05); self.assertAlmostEqual(delta['confidence'], 0.75)
    def test_dt_cap(self):
        capped = aa.compute_deltas(100, 1.0, 0.0)
        full = aa.compute_deltas(6, 1.0, 0.0)
        self.assertAlmostEqual(capped['valence'], full['valence'])
    def test_apply_applies_once(self):
        core = FakeCore()
        _, acc = aa.apply(core, {}, NOW, 24, 1.0, 0.0)
        v1 = core.v
        _, acc = aa.apply(core, acc, NOW, 24, 1.0, 0.0)
        self.assertAlmostEqual(core.v, v1)
    def test_apply_clamps(self):
        core = FakeCore(); core.v = -0.55
        aa.apply(core, {}, NOW, 100, 4.0, 0.5)
        self.assertGreaterEqual(core.v, -0.6)
    def test_confidence_written(self):
        core = FakeCore()
        aa.apply(core, {}, NOW, 0, 0.0, 0.6)
        self.assertAlmostEqual(core.confidence, 0.7)
    def test_affect_field_on_core(self):
        core = FakeCore()
        aa.apply(core, {}, NOW, 12, 0.5, 0.2)
        self.assertIn('autonomy_affect', core.__dict__)
    def test_affect_in_acc(self):
        _, acc = aa.apply(FakeCore(), {}, NOW, 12, 0.5, 0.0)
        for key in ('valence', 'arousal', 'stress', 'lonely'):
            self.assertIn(key, acc['affect'])
    def test_no_duplicate_stress(self):
        delta = aa.compute_deltas(24, 1.0, 0.0)
        self.assertEqual(delta['stress'], 0.0); self.assertEqual(delta['arousal'], 0.0)
    def test_first_tick_dt_zero(self):
        core = FakeCore()
        delta, _ = aa.apply(core, {}, NOW, 24, 1.0, 0.0)
        self.assertEqual(delta['valence'], 0.0)
    def test_lonely_only_from_silence(self):
        delta = aa.compute_deltas(0, 0.0, 1.0)
        self.assertEqual(delta['lonely'], 0.0)
    def test_second_call_same_now_zero(self):
        core = FakeCore()
        _, acc = aa.apply(core, {}, NOW - 3600, 12, 1.0, 0.0)
        _, acc = aa.apply(core, acc, NOW, 12, 1.0, 0.0)
        v = core.v
        _, acc = aa.apply(core, acc, NOW, 12, 1.0, 0.0)
        self.assertAlmostEqual(core.v, v)

if __name__ == '__main__':
    unittest.main()
