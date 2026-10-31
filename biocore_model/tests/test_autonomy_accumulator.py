# -*- coding: utf-8 -*-
import math, random, unittest
from biocore_model import autonomy_model as am

class AccumulatorTest(unittest.TestCase):
    def test_v_accumulates_until_theta(self):
        V = 0.0; fired = 0
        for _ in range(30):
            out = am.step(V, 0.1, leak=0.15, sigma=0.0, theta=0.55)
            V = out['V']
            if out['fire']: fired += 1; self.assertEqual(V, 0.0)
        self.assertGreaterEqual(fired, 1)

    def test_leak_half_life_about_4_3_ticks(self):
        V = 1.0
        for _ in range(5):
            V = am.step(V, 0.0, leak=0.15, sigma=0.0, theta=99)['V']
        self.assertAlmostEqual(V, 0.85 ** 5, places=6)
        half = math.log(0.5) / math.log(1 - 0.15)
        self.assertAlmostEqual(half, 4.27, delta=0.05)

    def test_sigma_zero_deterministic(self):
        a = [am.step(0.0, 0.1, sigma=0.0)['V'] for _ in range(3)]
        b = [am.step(0.0, 0.1, sigma=0.0)['V'] for _ in range(3)]
        self.assertEqual(a, b)

    def test_sigma_creates_jitter(self):
        rng = random.Random(42)
        times = []
        for _ in range(20):
            V = 0.0
            for tick in range(1, 200):
                out = am.step(V, 0.1, sigma=0.06, theta=0.55, rng=rng)
                V = out['V']
                if out['fire']: times.append(tick); break
        self.assertGreater(len(set(times)), 1)

    def test_fire_resets_v(self):
        out = am.step(0.6, 0.1, sigma=0.0, theta=0.55)
        self.assertTrue(out['fire']); self.assertEqual(out['V'], 0.0)

    def test_user_reply_satiety(self):
        self.assertAlmostEqual(am.on_user_reply(1.0), 0.3)

    def test_drift_weights_sum(self):
        self.assertAlmostEqual(sum(am.DRIFT_WEIGHTS.values()), 1.0, places=6)

    def test_drift_value_clamped(self):
        self.assertLessEqual(am.drift_value({k: 1.0 for k in am.DRIFT_WEIGHTS}), 1.0)

    def test_memory_due_today(self):
        now = 1_700_000_000
        out = am.memory_due([{'id': 'e1', 'due_ts': now + 3600}], now)
        self.assertAlmostEqual(out['memory_due'], 1.0)

    def test_memory_due_commitment_bonus(self):
        now = 1_700_000_000
        out = am.memory_due([{'id': 'e1', 'due_ts': now + 86400 * 1.2, 'title': '记得答应她'}], now)
        self.assertGreater(out['memory_due'], 0.7)

    def test_memory_due_only_once(self):
        now = 1_700_000_000
        first = am.memory_due([{'id': 'e1', 'due_ts': now + 3600}], now)
        second = am.memory_due([{'id': 'e1', 'due_ts': now + 3600}], now, triggered={'e1': now})
        self.assertEqual(first['memory_due'], 1.0); self.assertEqual(second['memory_due'], 0.0)

    def test_memory_due_far_events_ignored(self):
        now = 1_700_000_000
        self.assertEqual(am.memory_due([{'id': 'x', 'due_ts': now + 86400 * 10}], now)['memory_due'], 0.0)

    def test_snapshot_fields(self):
        snap = am.accumulator_snapshot({'V': 0.3, 'ticks_since_fire': 4}, theta=0.55)
        for key in ('V', 'theta', 'drift', 'leak', 'sigma', 'ticks_since_fire', 'to_threshold'):
            self.assertIn(key, snap)

    def test_to_threshold(self):
        snap = am.accumulator_snapshot({'V': 0.25}, theta=0.55)
        self.assertAlmostEqual(snap['to_threshold'], 0.3)

    def test_theta_configurable(self):
        self.assertFalse(am.step(0.4, 0.05, theta=0.9, sigma=0.0)['fire'])

if __name__ == '__main__':
    unittest.main()
