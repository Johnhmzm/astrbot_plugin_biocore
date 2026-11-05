# -*- coding: utf-8 -*-
"""task-230: indicative priority from field surprise (predictive processing).

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_surprise_priority.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import pipeline as pl
from biocore_runtime import priority as pr


NOW = 1700000000.0
REL = {"trust": 0.6, "closeness": 0.7}


def entry(key, affect, importance=0.6, hits=1, ts=NOW):
    return {"id": key, "text": key, "affect": dict(affect),
            "importance": importance, "hits": hits, "ts": ts}


class SurpriseTest(unittest.TestCase):
    def test_field_surprise_is_absolute_deviation_over_scale(self):
        values = pr.field_values({"v": -0.8, "a": 0.9, "stress": 0.5,
                                  "social": 0.55}, REL)
        row = pr.field_surprise(values)
        self.assertAlmostEqual(row["axes"]["v"], 0.4, places=4)     # 0.8 / 2.0
        self.assertAlmostEqual(row["axes"]["a"], 0.4, places=4)     # 0.4 / 1.0
        self.assertAlmostEqual(row["axes"]["trust"], 0.1, places=4)  # 0.1 / 1.0
        self.assertEqual(row["top"][0]["axis"], "v")

    def test_a_high_deviation_entry_ranks_first(self):
        values = pr.field_values({"v": 0.0, "a": 0.5}, REL)
        rows = pr.rank([entry("calm", {"v": 0.0, "a": 0.5}),
                        entry("shock", {"v": 0.9, "a": 0.9})], values, REL)
        self.assertEqual(rows[0]["id"], "shock")
        self.assertGreater(rows[0]["score"], rows[1]["score"])

    def test_repeated_content_is_damped(self):
        values = pr.field_values({"v": 0.0, "a": 0.5}, REL)
        rows = pr.rank([entry("fresh", {"v": 0.9, "a": 0.9}, hits=1),
                        entry("repeat", {"v": 0.9, "a": 0.9}, hits=5)],
                       values, REL)
        self.assertEqual(rows[0]["id"], "fresh")
        repeat = [row for row in rows if row["id"] == "repeat"][0]
        self.assertAlmostEqual(repeat["predictable"], 0.3, places=4)
        self.assertLess(repeat["score"], rows[0]["score"])

    def test_relation_changes_the_score(self):
        values = pr.field_values({"v": 0.0, "a": 0.5}, REL)
        row = entry("x", {"v": 0.9, "a": 0.9})
        close = pr.score_entry(row, values, {"trust": 0.9, "closeness": 0.9})
        far = pr.score_entry(row, values, {"trust": 0.0, "closeness": 0.0})
        self.assertGreater(close["relation"], far["relation"])
        self.assertGreater(close["score"], far["score"])

    def test_switch_off_returns_the_old_order(self):
        values = pr.field_values({"v": 0.9, "a": 0.9}, REL)
        rows = pr.rank([entry("old", {"v": 0.9, "a": 0.9}, ts=NOW - 100),
                        entry("new", {"v": 0.0, "a": 0.5}, ts=NOW)],
                       values, REL, enabled_override=False)
        self.assertEqual(rows[0]["id"], "new")
        self.assertTrue(rows[0]["legacy"])
        self.assertEqual(rows[0]["score"], 0.0)

    def test_empty_state_is_safe(self):
        self.assertEqual(pr.rank([], {}, {}), [])
        self.assertEqual(pr.field_surprise({})["value"], 0.0)
        self.assertEqual(pr.score_entry({}, {}, {})["score"], 0.0)

    def test_recall_weight_only_lifts_surprising_content(self):
        values = pr.field_values({"v": 0.9, "a": 0.9}, REL)
        self.assertEqual(pr.recall_weight({"affect": {"v": 0.9, "a": 0.9}},
                                          values), 1.0)      # below floor
        self.assertGreater(pr.recall_weight({"affect": {"v": -0.9, "a": 0.1}},
                                            values), 1.0)


class PriorityStateTest(unittest.TestCase):
    """/state.consolidation_priority: top rows with every factor kept."""

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

    def seed(self, rows, core=None):
        pl.dispatch("turn_start", {
            "session_id": "s1", "store": str(self.store), "user_text": "x",
            "state": {"core": core or {"v": 0.9, "a": 0.9}}})
        doc = pl.load_memory(str(self.store), "s1")
        doc["entries"] = rows
        pl.save_memory(str(self.store), "s1", doc)

    def state(self):
        return pl.dispatch("state", {"session_id": "s1",
                                     "store": str(self.store)})["state"]

    def test_state_block_has_the_top_rows_and_factors(self):
        self.seed([entry("far", {"v": -0.9, "a": 0.1}),
                   entry("near", {"v": 0.9, "a": 0.9})])
        block = self.state()["consolidation_priority"]
        self.assertTrue(block["enabled"])
        self.assertEqual(sorted(block["top"][0]),
                         ["id", "importance", "predictable", "relation",
                          "score", "surprise", "text", "ts"])
        self.assertEqual(block["top"][0]["id"], "far")
        self.assertIn("axes", block["field_surprise"])

    def test_empty_store_has_an_empty_top(self):
        self.seed([])
        block = self.state()["consolidation_priority"]
        self.assertEqual(block["top"], [])
        self.assertTrue(block["enabled"])

    def test_switch_off_falls_back_to_the_old_order(self):
        self.seed([entry("older", {"v": -0.9, "a": 0.1}, ts=NOW - 50),
                   entry("newer", {"v": 0.9, "a": 0.9}, ts=NOW)])
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store),
                                      "surprise_priority": False})["state"]
        block = shown["consolidation_priority"]
        self.assertFalse(block["enabled"])
        self.assertEqual(block["top"][0]["id"], "newer")
        self.assertEqual(block["top"][0]["score"], 0.0)


if __name__ == "__main__":
    unittest.main()
