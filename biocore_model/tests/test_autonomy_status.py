# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am

ACC = {'V': 0.2, 'theta': 0.55, 'drift': 0.1, 'leak': 0.15, 'sigma': 0.06, 'ticks_since_fire': 3}

class StatusSnapshotTest(unittest.TestCase):
    def test_fields(self):
        snap = am.status_snapshot(ACC, {'social_gap': 0.5})
        for key in ('V', 'theta', 'drift', 'leak', 'sigma', 'ticks_since_fire', 'to_threshold', 'parts', 'gate_allowed', 'block_reason', 'last_tick_ts', 'eta_hours'):
            self.assertIn(key, snap)
    def test_does_not_mutate(self):
        acc = dict(ACC)
        am.status_snapshot(acc, {'social_gap': 0.1})
        self.assertEqual(acc, ACC)
    def test_to_threshold(self):
        self.assertAlmostEqual(am.status_snapshot(ACC)['to_threshold'], 0.35)
    def test_eta_hours(self):
        self.assertAlmostEqual(am.status_snapshot(ACC)['eta_hours'], round(0.35 / 0.1 * 300 / 3600.0, 2))
    def test_zero_drift_eta_none(self):
        self.assertIsNone(am.status_snapshot(dict(ACC, drift=0.0))['eta_hours'])
    def test_parts_include_all_weights(self):
        snap = am.status_snapshot(ACC, {})
        for key in am.DRIFT_WEIGHTS:
            self.assertIn(key, snap['parts'])
    def test_affect_field(self):
        snap = am.status_snapshot({'affect': {'valence': -0.1}})
        self.assertIn('affect', snap); self.assertEqual(snap['affect']['valence'], -0.1)

    def test_missing_acc_no_crash(self):
        snap = am.status_snapshot(None)
        self.assertEqual(snap['V'], 0.0)

if __name__ == '__main__':
    unittest.main()
