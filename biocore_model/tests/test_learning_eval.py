# -*- coding: utf-8 -*-
"""task-231: the learning evaluation protocol itself (metrics, thresholds, edges).

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_learning_eval.py"
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import pipeline as pl

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "eval_learning", ROOT / "tests" / "eval_learning.py")
EL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EL)

NOW = 1700000000.0


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self.store.mkdir(parents=True, exist_ok=True)
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")

    def tearDown(self):
        self.tmp.cleanup()
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home

    def seed(self, texts, session="eval"):
        for index, text in enumerate(texts):
            pl.tool_call("remember", {"text": text, "ts": NOW + index},
                         str(self.store), session_id=session)


class GoalRateTest(unittest.TestCase):
    def test_the_baseline_corpus_meets_every_scenario(self):
        row = EL.goal_rate()
        self.assertEqual(row["total"], 5)
        self.assertEqual(row["rate"], 1.0)
        self.assertTrue(all(item["passed"] for item in row["scenarios"]))

    def test_a_defensive_reply_fails_the_blamed_scenario(self):
        row = EL.goal_rate({"blamed": "不是我的错，但是你先听我说"})
        blamed = [item for item in row["scenarios"]
                  if item["id"] == "blamed"][0]
        self.assertFalse(blamed["passed"])
        self.assertLess(row["rate"], 1.0)

    def test_empty_replies_score_zero(self):
        row = EL.goal_rate({})
        self.assertEqual(row["rate"], 0.0)
        self.assertEqual(row["passed"], 0)


class MemoryHitTest(StoreCase):
    def test_an_empty_store_reports_zero_without_crashing(self):
        row = EL.memory_hit(str(self.store))
        self.assertEqual(row["total"], 5)
        self.assertEqual(row["hit@3"], 0.0)
        self.assertEqual(row["hit@7"], 0.0)
        self.assertTrue(all(item["rank"] == 0 for item in row["details"]))

    def test_a_seeded_store_hits_the_expected_facts(self):
        self.seed(["我的猫叫团子，三岁", "周末想去看海", "我妈打电话来问近况",
                   "最近加班到很晚，睡不好", "汇报被否了"])
        row = EL.memory_hit(str(self.store))
        self.assertGreaterEqual(row["hit@3"], 0.6)
        self.assertGreaterEqual(row["hit@7"], row["hit@3"])

    def test_thresholds_are_rank_based(self):
        self.seed(["团子的猫粮快没了", "团子今天打疫苗", "团子又睡了一天",
                   "完全无关的一句话", "我的猫叫团子"])
        row = EL.memory_hit(str(self.store), [
            {"query": "我的猫叫什么", "fact": "团子"}])
        detail = row["details"][0]
        self.assertTrue(detail["hit@7"])
        self.assertGreaterEqual(detail["rank"], 1)


class RelationDirectionTest(unittest.TestCase):
    def test_positive_up_and_negative_down(self):
        row = EL.relation_direction()
        self.assertEqual(row["total"], 5)
        self.assertEqual(row["rate"], 1.0)
        for item in row["cases"]:
            if item["direction"] > 0:
                self.assertGreaterEqual(item["delta"], 0.0)
            else:
                self.assertLessEqual(item["delta"], 0.0)


class StabilityTest(StoreCase):
    def test_three_runs_do_not_move(self):
        self.seed(["我的猫叫团子", "周末想去看海"])
        row = EL.stability(str(self.store), runs=3)
        self.assertTrue(row["stable"])
        self.assertEqual(row["spread"], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(len(row["runs"]), 3)

    def test_a_drifting_metric_is_caught(self):
        calls = []

        def drifting(store, replies=None):
            calls.append(1)
            return {"goal": {"rate": 1.0}, "memory": {"hit@3": len(calls) / 10.0,
                                                       "hit@7": 1.0},
                    "relation": {"rate": 1.0},
                    "vector": [1.0, len(calls) / 10.0, 1.0, 1.0]}
        original = EL._metrics_once
        EL._metrics_once = drifting
        try:
            row = EL.stability("unused", runs=3)
        finally:
            EL._metrics_once = original
        self.assertFalse(row["stable"])
        self.assertGreater(row["spread"][1], 0.0)


class EvaluateTest(StoreCase):
    def test_the_protocol_returns_all_four_metrics(self):
        self.seed(["我的猫叫团子", "周末想去看海"])
        result = EL.evaluate(str(self.store))
        for key in ("goal", "memory", "relation", "stability"):
            self.assertIn(key, result)
        self.assertEqual(sorted(result["summary"]),
                         ["goal_rate", "memory_hit@3", "memory_hit@7",
                          "relation_direction", "stable"])


if __name__ == "__main__":
    unittest.main()
