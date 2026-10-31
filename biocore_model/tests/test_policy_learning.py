# -*- coding: utf-8 -*-
import random, unittest
from biocore_model import policy_learning as pl

class PolicyLearningTest(unittest.TestCase):
    def table(self):
        t = {}
        t = pl.update(t, "expect|secure|day", "approach", 1.0)
        for _ in range(2):
            t = pl.update(t, "expect|secure|day", "approach", 1.0)
        for _ in range(4):
            t = pl.update(t, "expect|secure|day", "share", -1.0)
        return t

    def test_update_positive(self):
        t = pl.update({}, "c", "approach", 1.0)
        self.assertGreater(t["c"]["approach"]["q"], 0.0)
        self.assertEqual(t["c"]["approach"]["n"], 1)

    def test_update_negative(self):
        t = pl.update({}, "c", "share", -1.0)
        self.assertLess(t["c"]["share"]["q"], 0.0)

    def test_update_alpha(self):
        low = pl.update({}, "c", "approach", 1.0, alpha=0.1)
        high = pl.update({}, "c", "approach", 1.0, alpha=0.5)
        self.assertGreater(high["c"]["approach"]["q"], low["c"]["approach"]["q"])

    def test_update_immutable(self):
        original = {}
        updated = pl.update(original, "c", "approach", 1.0)
        self.assertEqual(original, {})
        self.assertNotIn("c", original)
        self.assertIn("c", updated)

    def test_reward_responded(self):
        self.assertGreater(pl.reward(True, 1.0, 0.0), pl.reward(False, 1.0, 0.0))

    def test_reward_speed(self):
        self.assertGreater(pl.reward(True, 1.0, 0.0), pl.reward(True, 100.0, 0.0))

    def test_reward_clamped(self):
        self.assertLessEqual(pl.reward(True, 0.0, 5.0), 1.0)
        self.assertGreaterEqual(pl.reward(True, 0.0, -5.0), -0.3)

    def test_choose_greedy(self):
        t = self.table()
        result = pl.choose("expect|secure|day", t, epsilon=0.0, rng=random.Random(1))
        self.assertEqual(result["action"], "approach")
        self.assertFalse(result["explored"])

    def test_choose_epsilon_seed(self):
        t = self.table()
        rng = random.Random(42)
        explored = sum(1 for _ in range(1000) if pl.choose("expect|secure|day", t, epsilon=0.3, rng=rng)["explored"])
        self.assertGreater(explored, 200)
        self.assertLess(explored, 400)

    def test_choose_unseen_q_zero(self):
        result = pl.choose("loss|avoidant|night", {}, epsilon=0.0, rng=random.Random(2))
        self.assertIn(result["action"], pl.ACTIONS)
        self.assertEqual(result["q"], 0.0)

    def test_policy_view_sorted(self):
        rows = pl.policy_view(self.table(), "expect|secure|day")
        self.assertEqual(len(rows), len(pl.ACTIONS))
        self.assertEqual(rows[0]["action"], "approach")
        self.assertGreaterEqual(rows[0]["q"], rows[-1]["q"])

    def test_policy_view_unseen(self):
        rows = pl.policy_view({}, "unknown")
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["q"] == 0 for row in rows))

    def test_context_buckets(self):
        self.assertEqual(pl.hour_bucket(9), "day")
        self.assertEqual(pl.hour_bucket(20), "evening")
        self.assertEqual(pl.hour_bucket(2), "night")
        self.assertIn("|", pl.make_context("protest", "anxious", 20))

    def test_reward_slow_vs_fast(self):
        self.assertAlmostEqual(pl.reward(True, 0.0, 0.0), 0.7, places=6)
        self.assertAlmostEqual(pl.reward(True, 120.0, 0.0), 0.5, places=6)

    def test_choice_after_history(self):
        t = self.table()
        first = pl.choose("expect|secure|day", t, epsilon=0.0, rng=random.Random(3))
        second = pl.choose("expect|secure|day", t, epsilon=0.0, rng=random.Random(4))
        self.assertEqual(first["action"], "approach")
        self.assertEqual(second["action"], "approach")

    def test_update_incremental_values(self):
        t = pl.update({}, "c", "approach", 1.0, alpha=0.2)
        self.assertAlmostEqual(t["c"]["approach"]["q"], 0.2, places=6)
        t = pl.update(t, "c", "approach", 1.0, alpha=0.2)
        self.assertAlmostEqual(t["c"]["approach"]["q"], 0.36, places=6)
        self.assertEqual(t["c"]["approach"]["n"], 2)

    def test_choose_same_seed_reproducible(self):
        t = self.table()
        first = [pl.choose("expect|secure|day", t, epsilon=0.5, rng=random.Random(11))
                 for _ in range(20)]
        second = [pl.choose("expect|secure|day", t, epsilon=0.5, rng=random.Random(11))
                  for _ in range(20)]
        self.assertEqual(first, second)

    def test_reward_extremes(self):
        self.assertAlmostEqual(pl.reward(True, 0.0, 1.0), 1.0, places=6)
        self.assertAlmostEqual(pl.reward(False, 9999.0, -1.0), -0.3, places=6)

    def test_make_context_hour_buckets_differ(self):
        day = pl.make_context("expect", "secure", 9)
        night = pl.make_context("expect", "secure", 2)
        self.assertTrue(day.endswith("|day"))
        self.assertTrue(night.endswith("|night"))
        self.assertNotEqual(day, night)
