# -*- coding: utf-8 -*-
"""P2-1 learning-loop verification tests (learning_probe.py)."""
import unittest
from pathlib import Path

from biocore_model import learning_probe as lp
from biocore_model import policy_learning as pl

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "biocore_model" / "learning_probe.py").read_text(encoding="utf-8")


class RepeatRewardTest(unittest.TestCase):
    def test_q_rises_and_steps_are_logged(self):
        table, rows = lp.repeat_reward(rewards=(1.0, 1.0, 1.0))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["q"], 0.2)
        self.assertGreater(rows[-1]["q"], rows[0]["q"])
        self.assertIsNone(rows[0]["delta"])
        self.assertIsNotNone(rows[-1]["delta"])
        self.assertIn(lp.DEFAULT_CTX, table)

    def test_repeated_stimulus_decays_response(self):
        _table, rows = lp.repeat_reward(rewards=(1.0, 1.0, 1.0))
        self.assertTrue(lp.declining_deltas(rows))
        self.assertLess(lp.response_ratio(rows), 1.0)
        self.assertGreater(lp.response_ratio(rows), 0.0)
        deltas = [row["delta"] for row in rows if row["delta"] is not None]
        self.assertEqual(len(deltas), 2)
        self.assertLess(deltas[1], deltas[0])

    def test_no_reward_no_learning_contrast(self):
        _table, rows = lp.repeat_reward(rewards=(0.0, 0.0, 0.0))
        self.assertEqual([row["q"] for row in rows], [0.0, 0.0, 0.0])
        self.assertFalse(lp.declining_deltas(rows))
        self.assertEqual(lp.response_ratio(rows), 1.0)

    def test_invalid_inputs_are_safe(self):
        table, rows = lp.repeat_reward(rewards="nope", alpha="x")
        self.assertIsInstance(table, dict)
        self.assertEqual(len(rows), 3)
        _table2, rows2 = lp.repeat_reward(rewards=(1.0,), alpha=0.2)
        self.assertEqual(len(rows2), 1)
        self.assertFalse(lp.declining_deltas(None))
        self.assertEqual(lp.response_ratio(None), 1.0)


class AlphaCurveTest(unittest.TestCase):
    def test_alpha_declines_with_error(self):
        curve = lp.alpha_curve([0.8, 0.4, 0.2, 0.1])
        alphas = [row["alpha"] for row in curve]
        self.assertTrue(all(alpha is not None for alpha in alphas))
        self.assertTrue(all(alphas[i] <= alphas[i - 1]
                            for i in range(1, len(alphas))))


class BehaviourChangeTest(unittest.TestCase):
    def test_preference_changes_after_learning(self):
        before = lp.preferred({})
        self.assertTrue(before.get("explored"))
        table, _rows = lp.repeat_reward(rewards=(1.0, 1.0, 1.0))
        after = lp.preferred(table)
        self.assertFalse(after.get("explored"))
        self.assertEqual(after["action"], lp.DEFAULT_ACTION)
        self.assertGreater(after["q"], 0.0)

    def test_other_action_learned_when_rewarded(self):
        table, _rows = lp.repeat_reward(action="repair", rewards=(1.0, 1.0))
        pick = lp.preferred(table)
        self.assertEqual(pick["action"], "repair")
        self.assertGreater(pick["q"], 0.0)
        self.assertLess(float(table[lp.DEFAULT_CTX]["approach"]["q"]), 1e-9)


class SelfCheckTest(unittest.TestCase):
    def test_report_shape_and_ok(self):
        report = lp.self_check()
        self.assertTrue(report["ok"])
        self.assertTrue(report["declining"])
        self.assertLess(report["ratio"], 1.0)
        self.assertTrue(report["behaviour_changed"])
        self.assertTrue(report["alpha_declines"])
        self.assertEqual(len(report["rows"]), 3)

    def test_module_is_pure(self):
        self.assertNotIn("import main", SOURCE)
        self.assertNotIn("def open(", SOURCE)
        self.assertNotIn("open(", SOURCE)
        self.assertNotIn("time.", SOURCE)


if __name__ == "__main__":
    unittest.main()
