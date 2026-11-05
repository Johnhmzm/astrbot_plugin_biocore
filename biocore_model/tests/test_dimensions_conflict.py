# -*- coding: utf-8 -*-
"""task-243: the conflict axis -- relationship conflict only, never task conflict.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_dimensions_conflict.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import dimensions as dim
from biocore_runtime import pipeline as pl


NOW = 1700000000.0


def levels(model, *axes):
    return {axis: round(max(model["dims"][axis]["explicit"],
                            model["dims"][axis]["implicit"]), 4)
            for axis in axes}


class ConflictAxisTest(unittest.TestCase):
    """De Dreu & Weingart 2003 / Mayer 1995 / Aron 1992."""

    def test_conflict_is_a_twelfth_axis(self):
        self.assertIn("conflict", dim.DIMS)
        self.assertEqual(len(dim.DIMS), 12)
        self.assertEqual(dim.RANGES["conflict"], (0.0, 1.0))
        seen = []
        for axes in dim.CHANNEL_AXES.values():
            seen.extend(axes)
        self.assertEqual(sorted(seen), sorted(dim.DIMS))
        self.assertIn("conflict", dim.CHANNEL_AXES["relational"])

    def test_a_relationship_event_raises_conflict(self):
        model = dim.raise_conflict(dim.initial(NOW), "appraisal_blame", 0.4,
                                   source="appraisal", now=NOW)
        self.assertAlmostEqual(levels(model, "conflict")["conflict"], 0.4,
                               places=4)
        self.assertEqual(model["dims"]["conflict"]["evidence"][0]["source"],
                         "appraisal")

    def test_a_failed_repair_raises_conflict(self):
        model = dim.raise_conflict(dim.initial(NOW), "repair_failed", 0.25,
                                   now=NOW)
        self.assertAlmostEqual(levels(model, "conflict")["conflict"], 0.25,
                               places=4)

    def test_task_disagreement_never_raises_conflict(self):
        for event in ("task_disagreement", "task_conflict", "work_dispute",
                      "misunderstanding"):
            model = dim.raise_conflict(dim.initial(NOW), event, 0.9, now=NOW)
            self.assertEqual(levels(model, "conflict")["conflict"], 0.0)
            self.assertFalse(dim.is_conflict_event(event))

    def test_trust_and_closeness_do_not_move_with_conflict(self):
        base = dim.initial(NOW)
        model = dim.raise_conflict(base, "explicit_hostility", 0.8, now=NOW)
        self.assertAlmostEqual(levels(model, "conflict")["conflict"], 0.8,
                               places=4)
        self.assertEqual(levels(model, "trust", "closeness"),
                         {"trust": 0.0, "closeness": 0.0})

    def test_a_trust_write_never_touches_conflict(self):
        model = dim.contribute(dim.initial(NOW), "trust", "explicit", 0.3,
                               now=NOW)
        self.assertAlmostEqual(levels(model, "trust")["trust"], 0.3, places=4)
        self.assertEqual(levels(model, "conflict")["conflict"], 0.0)

    def test_switch_off_keeps_the_old_schema(self):
        flags = {"dimensions_conflict": False}
        model = dim.raise_conflict(dim.initial(NOW), "appraisal_blame", 0.5,
                                   now=NOW, flags=flags)
        self.assertEqual(levels(model, "conflict")["conflict"], 0.0)
        view = dim.project(model, conflict=False)
        self.assertNotIn("conflict", view["dims"])
        self.assertNotIn("conflict", view["projection"]["relational"])
        self.assertTrue(dim.project(model)["dims"].get("conflict"))


class ConflictPipelineTest(unittest.TestCase):
    """turn_end only writes conflict for a relationship event."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self.store.mkdir(parents=True, exist_ok=True)
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")
        (self.store / "flags.json").write_text(
            json.dumps({"spatial_recall": False}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home

    def turn(self, conflict_event=None, dims=None):
        payload = {"session_id": "s1", "store": str(self.store),
                   "user_text": "你每次都这样"}
        if dims:
            payload["dimension_deltas"] = dims
        if conflict_event:
            payload["conflict_event"] = conflict_event
        pl.dispatch("turn_start", {"session_id": "s1", "store": str(self.store),
                                   "user_text": "x"})
        pl.dispatch("turn_end", dict(payload, assistant_text="嗯。"))
        return pl.dispatch("state", {"session_id": "s1",
                                     "store": str(self.store)})["state"]

    def test_relationship_event_writes_the_axis(self):
        shown = self.turn(conflict_event="appraisal_blame")
        self.assertIn("conflict", shown["dimensions"]["axes"])
        self.assertAlmostEqual(
            shown["dimensions"]["axes"]["conflict"]["explicit"], 0.10, places=4)
        self.assertAlmostEqual(
            shown["dimensions"]["axes"]["trust"]["explicit"], 0.0, places=4)

    def test_task_event_is_dropped(self):
        shown = self.turn(conflict_event="task_disagreement",
                          dims={"explicit": {"conflict": 0.4}})
        self.assertAlmostEqual(
            shown["dimensions"]["axes"]["conflict"]["explicit"], 0.0, places=4)


class AppraisalConflictWiringTest(unittest.TestCase):
    """perception pushes appraisal blame onto the conflict axis (and nothing else)."""

    NOW = 1700000000.0

    def state(self):
        return {"core": {"v": -0.2, "a": 0.6, "stress": 0.3, "social": 0.5},
                "relationship": {"trust": 0.5, "closeness": 0.5,
                                 "conflict": 0.0},
                "needs": {}}

    def writeback(self, payload):
        from biocore_runtime import perception as pc
        state = self.state()
        out = pc.writeback(None, "s1", payload=payload, state=state,
                           now=self.NOW, enabled_override=True)
        return out, out["_state"].get("dimensions")

    def axis(self, model):
        if not isinstance(model, dict):
            return None
        row = model["dims"]["conflict"]
        return round(max(row["explicit"], row["implicit"]), 4)

    def test_blame_writes_the_axis(self):
        out, model = self.writeback({"dims": {"blame": 0.9}, "confidence": 0.9})
        self.assertEqual(out["dimension_conflict"]["event"], "appraisal_blame")
        self.assertTrue(out["dimension_conflict"]["applied"])
        self.assertAlmostEqual(self.axis(model), 0.15, places=4)
        self.assertEqual(model["dims"]["trust"]["explicit"], 0.0)

    def test_task_disagreement_writes_nothing(self):
        out, model = self.writeback({"dims": {"blame": 0.9}, "confidence": 0.9,
                                     "conflict_event": "task_disagreement"})
        self.assertFalse(out["dimension_conflict"]["applied"])
        self.assertIsNone(model)

    def test_the_turn_cap_is_fifteen_points(self):
        for blame in (0.5, 0.9, 1.0):
            out, model = self.writeback({"dims": {"blame": blame},
                                         "confidence": 1.0})
            self.assertLessEqual(self.axis(model), 0.15 + 1e-9)
            self.assertAlmostEqual(out["dimension_conflict"]["delta"], 0.15,
                                   places=4)

    def test_switch_off_writes_nothing(self):
        out, model = self.writeback({"dims": {"blame": 0.9}, "confidence": 0.9,
                                     "dimensions_conflict": False})
        self.assertFalse(out["dimension_conflict"]["applied"])
        self.assertIsNone(model)

    def test_a_failed_repair_also_writes(self):
        out, model = self.writeback({"dims": {}, "repair_failed": True,
                                     "confidence": 0.9})
        self.assertEqual(out["dimension_conflict"]["event"], "repair_failed")
        self.assertAlmostEqual(self.axis(model), 0.10, places=4)


if __name__ == "__main__":
    unittest.main()
