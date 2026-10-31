# -*- coding: utf-8 -*-
import random, unittest
from biocore_model import frustration_curve as fc

NOW = 1_700_000_000

class CurveTest(unittest.TestCase):
    def test_segment_one(self):
        self.assertAlmostEqual(fc.frustration_mult(1), 1.04); self.assertAlmostEqual(fc.frustration_mult(3), 1.12)
    def test_segment_two(self):
        self.assertAlmostEqual(fc.frustration_mult(4), 1.20); self.assertAlmostEqual(fc.frustration_mult(8), 1.24)
    def test_segment_three(self):
        self.assertLess(fc.frustration_mult(12), 1.24); self.assertGreaterEqual(fc.frustration_mult(30), 0.9)
    def test_phase_names(self):
        self.assertEqual(fc.phase(2), 'invigoration'); self.assertEqual(fc.phase(6), 'plateau'); self.assertEqual(fc.phase(10), 'extinction')
    def test_inverted_u(self):
        self.assertGreater(fc.frustration_mult(3), fc.frustration_mult(1))
        self.assertLess(fc.frustration_mult(20), fc.frustration_mult(8))
    def test_interval_range(self):
        for _ in range(50):
            value = fc.next_interval(rng=random.Random(_))
            self.assertGreaterEqual(value, 36.0); self.assertLessEqual(value, 96.0)
    def test_schedule_sets_next(self):
        state = fc.schedule_tick({}, NOW, rng=random.Random(1))
        self.assertGreater(state['next_allowed_ts'], NOW)
    def test_burst_probability(self):
        state = fc.schedule_tick({}, NOW, rng=random.Random(0))
        self.assertAlmostEqual(state['next_allowed_ts'], NOW) if state['burst'] else self.assertGreater(state['next_allowed_ts'], NOW)
    def test_burst_cooldown(self):
        state = {'burst_cooldown_until': NOW + 3600}
        state = fc.schedule_tick(state, NOW, rng=random.Random(0))
        self.assertFalse(state['burst'])
    def test_wait_blocked_counter(self):
        state = {'next_allowed_ts': NOW + 600}
        self.assertEqual(fc.wait_blocked(state, NOW)['wait_blocked'], 1)

class GoalTest(unittest.TestCase):
    def test_goal_frustration(self):
        rows = fc.goals_tick([{'id': 'g1', 'progress': 0.2}], NOW, hours=2)
        self.assertAlmostEqual(rows[0]['frustration_delta'], 0.04)
    def test_goal_anxiety_near_deadline(self):
        rows = fc.goals_tick([{'id': 'g1', 'deadline_ts': NOW + 3600}], NOW)
        self.assertEqual(rows[0]['anxiety_delta'], 0.03)
    def test_goal_completed(self):
        out = fc.goal_completed({'id': 'g1'})
        self.assertEqual(out['joy'], 0.05); self.assertEqual(out['goal']['status'], 'done')
    def test_done_goal_not_ticked(self):
        rows = fc.goals_tick([{'id': 'g1', 'status': 'done'}], NOW)
        self.assertNotIn('frustration_delta', rows[0])

class NeedsTest(unittest.TestCase):
    def test_allowed_raises_autonomy(self):
        self.assertGreater(fc.needs_update(allowed=True)['autonomy_need'], 0.5)
    def test_limited_lowers_autonomy(self):
        self.assertLess(fc.needs_update(allowed=False)['autonomy_need'], 0.5)
    def test_helpful_raises_competence(self):
        self.assertGreater(fc.needs_update(helpful=True)['competence_need'], 0.5)
    def test_wrong_lowers_competence(self):
        self.assertLess(fc.needs_update(wrong=True)['competence_need'], 0.5)
    def test_low_autonomy_suppress_bonus(self):
        self.assertEqual(fc.needs_update(autonomy=0.2)['suppress_bonus'], 0.2)
    def test_low_competence_confidence_delta(self):
        self.assertEqual(fc.needs_update(competence=0.2)['confidence_delta'], -0.05)

if __name__ == '__main__':
    unittest.main()
