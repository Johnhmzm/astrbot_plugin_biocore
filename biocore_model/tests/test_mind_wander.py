# -*- coding: utf-8 -*-
"""HUMAN-4 mind wandering tests: weights, deterministic sampling, rumination bias."""
import unittest

from biocore_model import mind_wander as mw

LOOPS = [{"topic": "calm", "tension": 0.0}, {"topic": "tense", "tension": 1.0}]


class WeightTest(unittest.TestCase):
    def test_weights_positive(self):
        for weight in mw.weights(LOOPS, rumination=0.5):
            self.assertGreater(weight, 0.0)

    def test_rumination_boosts_tension(self):
        calm, tense = mw.weights(LOOPS, rumination=1.0)
        self.assertGreater(tense, calm)

    def test_no_rumination_equal_tension(self):
        loops = [{"topic": "a", "tension": 0.5}, {"topic": "b", "tension": 0.5}]
        a, b = mw.weights(loops, rumination=0.0)
        self.assertEqual(a, b)


class ChooseTest(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(mw.choose(LOOPS, 0.5, seed=4, now=9),
                         mw.choose(LOOPS, 0.5, seed=4, now=9))

    def test_fields(self):
        row = mw.choose(LOOPS, 0.0, seed=1, now=1)
        self.assertIn(row["topic"], ("calm", "tense"))
        self.assertIn("weight", row)
        self.assertIn("total", row)

    def test_empty_returns_none(self):
        self.assertIsNone(mw.choose([], 0.5, seed=1, now=1))

    def test_single_item_always(self):
        row = mw.choose([{"topic": "only", "tension": 0.1}], 0.9, seed=7, now=7)
        self.assertEqual(row["topic"], "only")

    def test_rumination_biases_tense(self):
        picks = [mw.choose(LOOPS, 1.0, seed=index, now=index)["topic"]
                 for index in range(30)]
        self.assertGreaterEqual(picks.count("tense"), 18)


class WanderTest(unittest.TestCase):
    def test_limit_and_distinct(self):
        rows = mw.wander(LOOPS, 0.2, seed=3, now=3, limit=2)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["topic"], rows[1]["topic"])

    def test_does_not_mutate(self):
        snapshot = [dict(row) for row in LOOPS]
        mw.wander(LOOPS, 0.5, seed=2, now=2)
        self.assertEqual(LOOPS, snapshot)

    def test_seeded_helper(self):
        self.assertIn(mw.seeded(5, now=5)["topic"], ("work", "friend", "rest"))


if __name__ == "__main__":
    unittest.main()
