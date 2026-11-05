# -*- coding: utf-8 -*-
"""Integration of batches b / c / d / e: registry, monitor, pipeline hooks.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_batch_registry.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import batch_registry as reg
from biocore_runtime import pipeline as pl


NOW = 1700000000.0


class FakeBatch(object):
    """Minimal hook with the b/d/e shape."""

    def __init__(self, modules=("alpha", "beta"), field=None, state=None,
                 skipped=None, error=None):
        self.modules = tuple(modules)
        self.field = dict(field or {})
        self.state = dict(state or {})
        self.skipped = list(skipped or [])
        self.error = error

    def apply_turn(self, state, phase, payload):
        if self.error:
            raise self.error
        return {"enabled": True, "modules": {name: True for name in self.modules},
                "activity": {name: True for name in self.modules},
                "field_deltas": self.field, "state_deltas": self.state,
                "skipped": self.skipped}


class FakeC(object):
    """The older c shape: flat bundle + dotted deltas."""

    fields = ["relationship_stage", "metacog"]

    def apply_turn(self, state, phase, payload):
        return {"ok": True, "phase": phase, "dry_run": True,
                "fields": list(self.fields),
                "deltas": {"relationship_trust": 0.3, "trust": 0.02,
                           "social_repair.gratitude": 0.1}}


def state():
    return {"core": {"v": -0.2, "a": 0.6, "stress": 0.55, "social": 0.45}}


class NormalizeTest(unittest.TestCase):
    def test_bde_shape(self):
        row = reg.normalize("b", FakeBatch(field={"v": 0.05},
                                           state={"memory_tiers": {}})
                            .apply_turn({}, "turn_start", {}))
        self.assertTrue(row["enabled"])
        self.assertEqual(row["modules"], {"alpha": True, "beta": True})
        self.assertAlmostEqual(row["field_deltas"]["v"], 0.05, places=6)
        self.assertIn("memory_tiers", row["state_deltas"])
        self.assertEqual(row["errored"], 0)

    def test_c_shape_maps_dotted_deltas(self):
        row = reg.normalize("c", FakeC().apply_turn({}, "turn_end", {}))
        self.assertEqual(sorted(row["modules"]), ["metacog", "relationship_stage"])
        self.assertAlmostEqual(row["field_deltas"]["trust"], 0.02, places=6)
        self.assertNotIn("relationship_trust", row["field_deltas"])
        self.assertIn("bundle", row["state_deltas"])

    def test_bad_output_is_not_fatal(self):
        row = reg.normalize("b", None)
        self.assertFalse(row["enabled"])
        self.assertEqual(row["modules"], {})

    def test_errors_are_counted_only_for_real_failures(self):
        benign = reg.normalize("b", {"enabled": True, "modules": {},
                                     "skipped": [{"module": "x",
                                                  "reason": "no_entries"}]})
        broken = reg.normalize("b", {"enabled": True, "modules": {},
                                     "skipped": [{"module": "x",
                                                  "reason": "ValueError"}]})
        self.assertEqual(benign["errored"], 0)
        self.assertEqual(broken["errored"], 1)


class TickTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def test_four_batches_run(self):
        hooks = {"b": FakeBatch(), "c": FakeC(), "d": FakeBatch(),
                 "e": FakeBatch()}
        out = reg.tick(self.store, "s1", "turn_start", {}, state(),
                       now=NOW, hooks=hooks)
        self.assertEqual(sorted(out["batches"]), ["b", "c", "d", "e"])
        self.assertEqual(out["counts"]["batches"], 4)

    def test_disabled_batch_is_skipped(self):
        hooks = {"b": FakeBatch(), "d": FakeBatch()}
        out = reg.tick(self.store, "s1", "turn_start", {}, state(), now=NOW,
                       switches={"batch_b": False}, hooks=hooks)
        self.assertNotIn("b", out["batches"])
        self.assertIn({"batch": "b", "reason": "disabled"}, out["skipped"])

    def test_missing_batch_is_reported(self):
        out = reg.tick(self.store, "s1", "turn_start", {}, state(), now=NOW,
                       hooks={"b": FakeBatch()})
        reasons = {row["batch"]: row["reason"] for row in out["skipped"]}
        self.assertEqual(reasons.get("d"), "unavailable")

    def test_field_deltas_are_merged_and_capped(self):
        hooks = {"b": FakeBatch(field={"trust": 0.4}),
                 "d": FakeBatch(field={"trust": 0.3, "v": -0.5})}
        out = reg.tick(self.store, "s1", "turn_end", {}, state(), now=NOW,
                       hooks=hooks)
        self.assertAlmostEqual(out["field_deltas"]["trust"], reg.CAPS["trust"],
                               places=6)
        self.assertAlmostEqual(out["field_deltas"]["v"], -reg.CAPS["v"],
                               places=6)

    def test_safe_keys_only_in_state(self):
        hooks = {"b": FakeBatch(state={"memory_tiers": {"resident": []},
                                       "v": 0.9, "core": {"v": 9}})}
        out = reg.tick(self.store, "s1", "turn_end", {}, state(), now=NOW,
                       hooks=hooks)
        self.assertIn("memory_tiers", out["state_deltas"])
        self.assertNotIn("v", out["state_deltas"])
        self.assertNotIn("core", out["state_deltas"])
        self.assertIn("b", out["state_deltas"]["batches"])
        self.assertIn("v", out["state_deltas"]["batches"]["b"])

    def test_broken_batch_does_not_raise(self):
        hooks = {"b": FakeBatch(error=RuntimeError("boom"))}
        out = reg.tick(self.store, "s1", "turn_end", {}, state(), now=NOW,
                       hooks=hooks)
        self.assertFalse(out["batches"]["b"]["enabled"])
        self.assertEqual(out["batches"]["b"]["reason"], "RuntimeError")


class MonitorTest(TickTest):
    def test_monitor_records_calls_changed_effect_errors(self):
        # task-241: the first snapshot has nothing to compare -> zero change;
        # a later tick whose own view moved counts as changed with a dict effect.
        class Drifting(FakeBatch):
            value = [0.2]

            def apply_turn(self, state, phase, payload):
                return {"enabled": True, "modules": {"predictor": True},
                        "activity": {"predictor": True}, "field_deltas": {},
                        "state_deltas": {}, "skipped": [
                            {"module": "x", "reason": "ValueError"}],
                        "reads": {"forecast": {"confidence": self.value[0]}}}

        hook = Drifting()
        reg.tick(self.store, "s1", "turn_end", {}, state(), now=NOW,
                 hooks={"b": hook})
        hook.value[0] = 0.5
        reg.tick(self.store, "s1", "turn_end", {}, state(), now=NOW + 10,
                 hooks={"b": hook})
        doc = reg.read_monitor(self.store)
        row = doc["modules"]["b.predictor"]
        self.assertEqual(row["calls"], 2)
        self.assertEqual(row["zero_change"], 1)
        self.assertEqual(row["changed"], 1)
        self.assertEqual(row["last_effect"], {"forecast.confidence": 0.3})
        self.assertEqual(row["errored"], 2)
        self.assertTrue(reg.path(self.store).exists())

    def test_idle_module_is_not_a_call(self):
        class Idle(FakeBatch):
            def apply_turn(self, state, phase, payload):
                return {"enabled": True,
                        "modules": {"alpha": True, "beta": True},
                        "activity": {"alpha": True, "beta": False},
                        "field_deltas": {}, "state_deltas": {}, "skipped": []}

        reg.tick(self.store, "s1", "turn_start", {}, state(), now=NOW,
                 hooks={"b": Idle()})
        doc = reg.read_monitor(self.store)
        self.assertEqual(doc["modules"]["b.alpha"]["calls"], 1)
        self.assertNotIn("b.beta", doc["modules"])

    def test_monitor_is_bounded(self):
        many = FakeBatch(modules=tuple("m%03d" % index for index in range(400)))
        reg.tick(self.store, "s1", "turn_start", {}, state(), now=NOW,
                 hooks={"b": many})
        doc = reg.read_monitor(self.store)
        self.assertLessEqual(len(doc["modules"]), reg.MODULE_LIMIT)

    def test_summary_totals(self):
        reg.tick(self.store, "s1", "turn_start", {}, state(), now=NOW,
                 hooks={"b": FakeBatch()})
        summary = reg.summary(self.store)
        self.assertEqual(summary["totals"]["calls"], 2)
        self.assertIn("b", summary["batches"])


class PipelineHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")

    def tearDown(self):
        self.tmp.cleanup()
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home

    def start(self, **extra):
        payload = {"session_id": "s1", "store": str(self.store),
                   "user_text": "小林上周说喜欢猫",
                   "state": {"core": {"v": -0.2, "a": 0.6, "stress": 0.55,
                                      "social": 0.45}},
                   "entries": [{"id": "e1", "text": "我叫小林，喜欢猫",
                                "role": "user", "ts": NOW - 3600,
                                "importance": 0.9, "strength": 0.9,
                                "retrieval_s": 0.8, "storage_s": 0.9}],
                   "recalled_ids": ["e1", "e2"],
                   "graph_tag": {"entities": [{"name": "小林", "type": "person"}],
                                 "relations": []},
                   "now": NOW}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def test_turn_start_returns_four_batches(self):
        out = self.start()
        batches = out["batches"]
        self.assertTrue(batches["enabled"])
        self.assertEqual(sorted(batches["batches"]), ["b", "c", "d", "e"])

    def test_turn_end_merges_batch_field_deltas(self):
        self.start()
        out = pl.dispatch("turn_end", {
            "session_id": "s1", "store": str(self.store),
            "assistant_text": "嗯，我记得。",
            "dims": {"goal": -0.3, "blame": 0.6, "hit": 0.6, "involve": 0.7},
            "confidence": 0.7, "now": NOW + 10})
        applied = (out.get("field") or {}).get("applied") or {}
        self.assertTrue(applied)
        self.assertIn("batches", out)

    def test_state_exposes_batches_and_monitor(self):
        self.start()
        body = pl.dispatch("state", {"session_id": "s1",
                                     "store": str(self.store)})["state"]
        self.assertIn("batches", body)
        self.assertIn("batch_monitor", body)
        self.assertIn("b", body["batches"])
        self.assertIn("totals", body["batch_monitor"])
        self.assertGreater(body["batch_monitor"]["totals"]["calls"], 0)

    def test_each_batch_can_be_switched_off(self):
        out = self.start(switches={"batch_b": False, "batch_c": False})
        self.assertNotIn("b", out["batches"]["batches"])
        self.assertNotIn("c", out["batches"]["batches"])
        self.assertIn("d", out["batches"]["batches"])


if __name__ == "__main__":
    unittest.main()
