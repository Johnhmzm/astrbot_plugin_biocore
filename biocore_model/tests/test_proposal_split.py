# -*- coding: utf-8 -*-
"""task-243 step 3.1: proposals stay separate (arbiter / batches / core state).

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_proposal_split.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import arbiter as arb
from biocore_runtime import batch_registry as reg
from biocore_runtime import core_state
from biocore_runtime import field as fld
from biocore_runtime import pipeline as pl


NOW = 1700000000.0


class ArbiterProposalTest(unittest.TestCase):
    """Every proposal is kept; the value comes from one named strategy."""

    def proposals(self):
        return [
            {"learner": "memory_feedback", "field": "v", "delta": 0.05},
            {"learner": "mood_recall", "field": "v", "delta": -0.02},
            {"learner": "preference_drift", "field": "v", "delta": 0.03},
        ]

    def test_every_proposal_is_kept(self):
        value = fld.Field({"v": 0.0})
        out = arb.Arbiter().apply(value, self.proposals())
        rows = out["resolved"]["v"]["proposals"]
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["learner"] for row in rows],
                         ["memory_feedback", "mood_recall", "preference_drift"])
        self.assertEqual([row["delta"] for row in rows], [0.05, -0.02, 0.03])
        self.assertEqual(sorted(out["proposals"]), ["v"])
        self.assertEqual(len(out["proposals"]["v"]), 3)

    def test_default_strategy_is_max_weight(self):
        self.assertEqual(arb.DEFAULT_STRATEGY, "max_weight")
        default = arb.Arbiter().apply(fld.Field({"v": 0.0}), self.proposals())
        self.assertEqual(default["resolved"]["v"]["strategy"], "max_weight")
        # memory_feedback is the most trusted learner (1.0) -> its delta wins
        self.assertAlmostEqual(default["resolved"]["v"]["delta"], 0.05,
                               places=6)
        self.assertAlmostEqual(fld.Field(default["field"]).get("v"), 0.05,
                               places=6)

    def test_the_median_stays_available_but_is_not_the_default(self):
        median = arb.Arbiter().apply(fld.Field({"v": 0.0}), self.proposals(),
                                     strategy="weighted_median")
        self.assertEqual(median["resolved"]["v"]["strategy"], "weighted_median")
        # the median settles opposite proposals on one side -> opt-in only
        self.assertAlmostEqual(median["resolved"]["v"]["delta"], 0.03, places=6)
        self.assertNotEqual(arb.Arbiter().strategy, "weighted_median")

    def test_first_strategy_keeps_declaration_order(self):
        out = arb.Arbiter().apply(fld.Field({"v": 0.0}), self.proposals(),
                                  strategy="first")
        self.assertEqual(out["resolved"]["v"]["strategy"], "first")
        self.assertAlmostEqual(out["resolved"]["v"]["delta"], 0.05, places=6)

    def test_conflict_lists_every_delta_and_the_strategy(self):
        out = arb.Arbiter().apply(fld.Field({"v": 0.0}), self.proposals())
        conflict = out["conflicts"][0]
        self.assertEqual(conflict["field"], "v")
        self.assertEqual(conflict["deltas"], [0.05, -0.02, 0.03])
        self.assertEqual(conflict["strategy"], "max_weight")
        self.assertAlmostEqual(conflict["winner"],
                               out["resolved"]["v"]["delta"], places=6)

    def test_snapshot_persists_the_proposals(self):
        engine = arb.Arbiter()
        engine.apply(fld.Field({"v": 0.0}), self.proposals())
        snapshot = engine.snapshot()
        self.assertEqual(snapshot["strategy"], "max_weight")
        self.assertEqual(len(snapshot["proposals"]["v"]), 3)
        self.assertEqual(sorted(snapshot["proposals"]["v"][0]),
                         ["delta", "learner", "weight"])
        json.dumps(snapshot)     # must stay JSON-safe for field.json


class BatchProposalTest(unittest.TestCase):
    """Four batches name one field: the deltas are kept, never summed."""

    def hook(self, name, deltas):
        class Hook:
            def apply_turn(self, state, phase, payload):
                return {"modules": {name + ".mod": True},
                        "activity": {name + ".mod": True},
                        "field_deltas": dict(deltas),
                        "state_deltas": {}, "skipped": []}
        return Hook()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self.store.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def tick(self, hooks):
        return reg.tick(str(self.store), "s1", "turn_end", {}, {},
                        now=NOW, hooks=hooks)

    def test_two_batches_on_one_field_are_not_added(self):
        out = self.tick({"b": self.hook("b", {"v": 0.05}),
                         "e": self.hook("e", {"v": 0.02})})
        self.assertAlmostEqual(out["field_deltas"]["v"], 0.05, places=6)
        rows = out["field_proposals"]["v"]
        self.assertEqual([row["batch"] for row in rows], ["b", "e"])
        self.assertEqual([row["delta"] for row in rows], [0.05, 0.02])
        self.assertEqual(out["resolved"]["v"]["strategy"], "max_weight")
        self.assertEqual(len(out["resolved"]["v"]["proposals"]), 2)

    def test_one_source_keeps_its_own_delta(self):
        out = self.tick({"b": self.hook("b", {"v": 0.06, "trust": 0.01})})
        self.assertAlmostEqual(out["field_deltas"]["v"], 0.06, places=6)
        self.assertAlmostEqual(out["field_deltas"]["trust"], 0.01, places=6)

    def test_the_resolved_delta_is_still_capped(self):
        out = self.tick({"b": self.hook("b", {"v": 0.5}),
                         "e": self.hook("e", {"v": 0.4})})
        self.assertAlmostEqual(out["field_deltas"]["v"], 0.10, places=6)
        self.assertEqual(len(out["resolved"]["v"]["proposals"]), 2)


class CoreStateSourceTest(unittest.TestCase):
    """core_state keeps one line per source and resolves per field."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "core_state.json"
        core_state.apply(self.path, absolute={"v": 0.0}, now=NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_nested_sources_are_recorded_separately(self):
        doc = core_state.apply(self.path,
                               deltas={"memory_feedback": {"v": 0.03},
                                       "state_sync": {"v": 0.01}},
                               now=NOW + 60)
        row = doc["proposals"]["fields"]["v"]
        self.assertEqual([item["source"] for item in row["proposals"]],
                         ["memory_feedback", "state_sync"])
        self.assertEqual([item["delta"] for item in row["proposals"]],
                         [0.03, 0.01])
        self.assertEqual(row["strategy"], "max_weight")
        # the folded value is the strategy's choice, not 0.03 + 0.01
        self.assertAlmostEqual(doc["v"], 0.03, places=4)

    def test_flat_delta_is_one_source_and_old_behaviour(self):
        doc = core_state.apply(self.path, deltas={"v": 0.03}, now=NOW + 60)
        self.assertAlmostEqual(doc["v"], 0.03, places=4)
        row = doc["proposals"]["fields"]["v"]
        self.assertEqual(len(row["proposals"]), 1)
        self.assertEqual(row["proposals"][0]["source"], core_state.FLAT_SOURCE)

    def test_snapshot_exposes_the_proposals(self):
        core_state.apply(self.path,
                         deltas={"memory_feedback": {"v": 0.03},
                                 "mood_recall": {"v": -0.01}}, now=NOW + 60)
        view = core_state.snapshot(self.path)
        self.assertIn("proposals", view)
        self.assertEqual(len(view["proposals"]["fields"]["v"]["proposals"]), 2)


class StateArbiterViewTest(unittest.TestCase):
    """/state.arbiter shows every proposal of the last batch."""

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

    def test_state_arbiter_exposes_proposals(self):
        pl.dispatch("turn_start", {"session_id": "s1", "store": str(self.store),
                                   "user_text": "今天有点累",
                                   "state": {"core": {"v": 0.2, "a": 0.6}}})
        ended = pl.dispatch("turn_end", {
            "session_id": "s1", "store": str(self.store),
            "assistant_text": "那就先歇一会儿吧。",
            "learner_deltas": {"memory_feedback": {"v": 0.06},
                               "mood_recall": {"v": -0.02},
                               "preference_drift": {"trust": 0.05}}})
        self.assertEqual(ended["field"]["strategy"], "max_weight")
        self.assertGreaterEqual(ended["field"]["proposal_count"], 3)
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store)})
        arbiter_view = shown["state"]["arbiter"]
        self.assertIn("proposals", arbiter_view)
        self.assertEqual(arbiter_view["strategy"], "max_weight")
        rows = arbiter_view["proposals"]["v"]
        self.assertEqual({row["learner"] for row in rows},
                         {"memory_feedback", "mood_recall"})
        for row in rows:
            self.assertEqual(sorted(row), ["delta", "learner", "weight"])
