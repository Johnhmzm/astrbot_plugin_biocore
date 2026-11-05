# -*- coding: utf-8 -*-
"""task-228: 学习耦合仲裁层 -- field 单一真源 + 写回仲裁.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_field_arbiter.py"
"""
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from biocore_memory.engine import MemoryEngine
from biocore_runtime import arbiter as arb
from biocore_runtime import field as fld
from biocore_runtime import pipeline as pl


NOW = 1700000000.0


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def entry(i, text, affect=None, importance=0.5, ts=NOW):
    value = {"id": i, "text": text, "role": "user", "ts": ts,
             "importance": importance, "vector": [], "hits": 1,
             "self_relevance": 0.0, "pin": False, "memory_source": "direct",
             "memory_confidence": 0.7, "previous_versions": [],
             "module": "biocore_memory", "scope": "default"}
    if affect is not None:
        value["affect"] = affect
    return value


class FieldValueTest(unittest.TestCase):
    """Pure field: ranges, defaults, read-only copies, state projection."""

    def test_defaults_and_range_clip(self):
        value = fld.Field()
        self.assertEqual(value.read(), {"v": 0.0, "a": 0.5, "stress": 0.5,
                                        "social": 0.5, "trust": 0.5,
                                        "closeness": 0.5})
        clipped = fld.Field({"v": 9.0, "a": -3.0}, version=2)
        self.assertEqual(clipped.get("v"), 1.0)
        self.assertEqual(clipped.get("a"), 0.0)
        self.assertEqual(clipped.version, 2)
        self.assertFalse(clipped.set("nope", 1.0))  # unknown name is ignored

    def test_read_returns_a_copy(self):
        value = fld.Field({"v": 0.25})
        snapshot = value.read()
        snapshot["v"] = -1.0
        self.assertEqual(value.get("v"), 0.25)  # learners cannot mutate the field
        self.assertEqual(value.read(), {"v": 0.25, "a": 0.5, "stress": 0.5,
                                        "social": 0.5, "trust": 0.5,
                                        "closeness": 0.5})

    def test_from_state_reads_core_and_relationship(self):
        state = {"core": {"v": 0.4, "a": 0.7, "social": 0.2},
                 "stress": 0.6,
                 "relationship": {"trust": 0.8, "closeness": 0.3}}
        value = fld.from_state(state)
        self.assertAlmostEqual(value.get("v"), 0.4)
        self.assertAlmostEqual(value.get("a"), 0.7)
        self.assertAlmostEqual(value.get("social"), 0.2)
        self.assertAlmostEqual(value.get("stress"), 0.6)  # top-level fallback
        self.assertAlmostEqual(value.get("trust"), 0.8)
        self.assertAlmostEqual(value.get("closeness"), 0.3)

    def test_from_state_accepts_legacy_aliases(self):
        value = fld.from_state({"valence": -0.5, "arousal": 0.9})
        self.assertAlmostEqual(value.get("v"), -0.5)
        self.assertAlmostEqual(value.get("a"), 0.9)

    def test_to_state_projects_affect_only_without_relationship(self):
        value = fld.Field({"v": 0.3, "a": 0.6, "stress": 0.2, "social": 0.9,
                           "trust": 0.7})
        out = fld.to_state({"session_id": "s", "core": {"energy": 0.4}}, value)
        self.assertAlmostEqual(out["core"]["v"], 0.3)
        self.assertAlmostEqual(out["core"]["a"], 0.6)
        self.assertAlmostEqual(out["core"]["stress"], 0.2)
        self.assertAlmostEqual(out["core"]["social"], 0.9)
        self.assertAlmostEqual(out["core"]["energy"], 0.4)  # untouched
        self.assertNotIn("relationship", out)  # never invents the sidecar key

    def test_to_state_writes_relationship_when_present(self):
        value = fld.Field({"trust": 0.9, "closeness": 0.1})
        out = fld.to_state({"relationship": {"trust": 0.5, "closeness": 0.5,
                                             "conflict": 0.2}}, value)
        self.assertAlmostEqual(out["relationship"]["trust"], 0.9)
        self.assertAlmostEqual(out["relationship"]["closeness"], 0.1)
        self.assertAlmostEqual(out["relationship"]["conflict"], 0.2)

    def test_switch_defaults_on_and_can_be_turned_off(self):
        self.assertTrue(fld.enabled())
        self.assertFalse(fld.enabled(flags={"field_arbiter": False}))
        self.assertFalse(fld.enabled(env={"BIOCORE_FIELD_ARBITER": "0"}))
        self.assertTrue(fld.enabled(env={"BIOCORE_FIELD_ARBITER": "1"}))
        self.assertTrue(fld.enabled(flags={}, env={}))  # default ON


class ArbiterTest(unittest.TestCase):
    """Conflict resolution, caps, rejections, idempotency."""

    def test_weighted_median_picks_the_heavier_side(self):
        self.assertAlmostEqual(
            arb.weighted_median([(0.06, 1.0), (-0.02, 0.6)]), 0.06)
        self.assertAlmostEqual(
            arb.weighted_median([(0.03, 0.5), (-0.01, 3.0)]), -0.01)
        # 0.2 weight ties: the lower delta is reached first -> deterministic
        self.assertAlmostEqual(
            arb.weighted_median([(0.10, 1.0), (0.02, 1.0)]), 0.02)

    def test_conflict_resolved_by_weighted_median(self):
        value = fld.Field({"v": 0.20})
        a = arb.Arbiter()
        out = a.apply(value, {"memory_feedback": {"v": 0.06},
                              "mood_recall": {"v": -0.02}})
        self.assertAlmostEqual(out["applied"]["v"], 0.06)
        self.assertAlmostEqual(out["field"]["v"], 0.26)
        self.assertEqual(len(out["conflicts"]), 1)
        self.assertEqual(out["conflicts"][0]["field"], "v")
        self.assertAlmostEqual(out["conflicts"][0]["winner"], 0.06)
        self.assertEqual(a.stats(), {"applied": 1, "rejected": 0,
                                     "conflicts": 1})

    def test_single_apply_cap(self):
        value = fld.Field({"v": 0.20})
        a = arb.Arbiter()
        out = a.apply(value, [{"learner": "memory_feedback", "field": "v",
                               "delta": 0.50}])
        self.assertAlmostEqual(out["resolved"]["v"]["capped"], 0.10)
        self.assertAlmostEqual(out["applied"]["v"], 0.10)
        self.assertAlmostEqual(out["field"]["v"], 0.30)

    def test_trust_uses_the_relationship_cap(self):
        value = fld.Field({"trust": 0.50})
        a = arb.Arbiter()
        out = a.apply(value, {"preference_drift": {"trust": 0.40}})
        self.assertAlmostEqual(out["resolved"]["trust"]["capped"], 0.02)
        self.assertAlmostEqual(out["field"]["trust"], 0.52)

    def test_bad_proposals_are_rejected_not_applied(self):
        value = fld.Field({"v": 0.10})
        a = arb.Arbiter()
        out = a.apply(value, [{"learner": "x", "field": "nope", "delta": 0.1},
                              {"learner": "x", "field": "v", "delta": "abc"},
                              {"learner": "x", "field": "v", "delta": 0.0}])
        reasons = sorted(item["reason"] for item in out["rejected"])
        self.assertEqual(reasons, ["bad_delta", "unknown_field", "zero_delta"])
        self.assertEqual(out["applied"], {})
        self.assertAlmostEqual(out["field"]["v"], 0.10)
        self.assertEqual(a.stats()["rejected"], 3)

    def test_range_clip_is_reported_then_no_effect(self):
        value = fld.Field({"v": 0.98})
        a = arb.Arbiter()
        first = a.apply(value, {"memory_feedback": {"v": 0.10}})
        self.assertAlmostEqual(first["resolved"]["v"]["capped"], 0.10)
        self.assertAlmostEqual(first["field"]["v"], 1.0)
        self.assertAlmostEqual(first["applied"]["v"], 0.02)  # only 0.02 was usable
        second = a.apply(value, {"memory_feedback": {"v": 0.10}})
        self.assertEqual(second["applied"], {})
        self.assertEqual(second["rejected"][0]["reason"], "no_effect")
        self.assertAlmostEqual(second["field"]["v"], 1.0)

    def test_txid_makes_apply_idempotent(self):
        value = fld.Field({"v": 0.20})
        a = arb.Arbiter()
        first = a.apply(value, {"memory_feedback": {"v": 0.05}}, txid="turn-7")
        self.assertFalse(first["duplicate"])
        self.assertAlmostEqual(first["field"]["v"], 0.25)
        before = value.read()
        second = a.apply(value, {"memory_feedback": {"v": 0.05}}, txid="turn-7")
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["applied"], {})
        self.assertEqual(value.read(), before)
        self.assertEqual(a.snapshot()["duplicates"], 1)
        # the ledger survives a round trip through field.json
        again = arb.Arbiter(state=a.snapshot())
        third = again.apply(value, {"memory_feedback": {"v": 0.05}},
                            txid="turn-7")
        self.assertTrue(third["duplicate"])

    def test_disabled_apply_is_a_noop(self):
        value = fld.Field({"v": 0.20})
        a = arb.Arbiter()
        out = a.apply(value, {"memory_feedback": {"v": 0.05}}, enabled=False)
        self.assertFalse(out["enabled"])
        self.assertEqual(out["applied"], {})
        self.assertAlmostEqual(value.get("v"), 0.20)
        self.assertEqual(a.stats()["applied"], 0)


class FieldStoreTest(unittest.TestCase):
    """<store>/sessions/<sid>/field.json persistence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_is_per_session(self):
        one = fld.Field({"v": 0.30}, version=3, session_id="s1")
        two = fld.Field({"v": -0.40}, version=1, session_id="s2")
        self.assertTrue(fld.save(self.store, fld.doc(one, {}, now=NOW), "s1"))
        self.assertTrue(fld.save(self.store, fld.doc(two, {}, now=NOW), "s2"))
        self.assertTrue((self.store / "sessions" / "s1" / "field.json").exists())
        self.assertAlmostEqual(fld.from_doc(fld.load(self.store, "s1")).get("v"), 0.30)
        self.assertAlmostEqual(fld.from_doc(fld.load(self.store, "s2")).get("v"), -0.40)
        self.assertEqual(fld.load(self.store, "s3"), {})  # never invented

    def test_reconcile_keeps_field_and_adopts_external_writes(self):
        stored = fld.Field({"v": 0.30}, version=4, session_id="s1")
        same = fld.reconcile(stored, fld.from_state({"core": {"v": 0.30}}))
        self.assertFalse(same[1])
        self.assertEqual(same[0].version, 4)
        self.assertEqual(same[0].source, "field")
        moved = fld.reconcile(stored, fld.from_state({"core": {"v": 0.50}}))
        self.assertTrue(moved[1])
        self.assertAlmostEqual(moved[0].get("v"), 0.50)
        self.assertEqual(moved[0].version, 5)
        self.assertEqual(moved[0].source, "state")


class FieldPipelineTest(unittest.TestCase):
    """turn_start / turn_end / state wiring."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self._saved = os.environ.pop("BIOCORE_FIELD_ARBITER", None)
        # hermetic persona lookup: no ~/.dsh/biocore/persona_profile.json
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")

    def tearDown(self):
        self.tmp.cleanup()
        if self._saved is None:
            os.environ.pop("BIOCORE_FIELD_ARBITER", None)
        else:
            os.environ["BIOCORE_FIELD_ARBITER"] = self._saved
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home

    def start(self, session="s1", v=0.20, a=0.60, trust=0.50, **extra):
        payload = {"session_id": session, "store": str(self.store),
                   "user_text": "今天有点累",
                   "state": {"core": {"v": v, "a": a, "stress": 0.40,
                                      "social": 0.50},
                             "relationship": {"trust": trust, "closeness": 0.50}}}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def end(self, session="s1", deltas=None, **extra):
        payload = {"session_id": session, "store": str(self.store),
                   "assistant_text": "那就先歇一会儿吧。"}
        if deltas is not None:
            payload["learner_deltas"] = deltas
        payload.update(extra)
        return pl.dispatch("turn_end", payload)

    def test_turn_start_seeds_and_persists_the_field(self):
        out = self.start()
        self.assertTrue(out["field"]["enabled"])
        self.assertTrue(out["field"]["reconciled"])
        self.assertEqual(out["field"]["source"], "state")
        self.assertAlmostEqual(out["field"]["field"]["v"], 0.20)
        self.assertAlmostEqual(out["field"]["field"]["a"], 0.60)
        self.assertAlmostEqual(out["field"]["field"]["trust"], 0.50)
        self.assertTrue((self.store / "sessions" / "s1" / "field.json").exists())

    def test_turn_start_reuses_the_field_until_the_state_drifts(self):
        self.start()
        again = self.start()
        self.assertFalse(again["field"]["reconciled"])
        self.assertEqual(again["field"]["source"], "field")
        state_file = self.store / "sessions" / "s1" / "state.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["core"]["v"] = 0.55  # host wrote the affect outside the arbiter
        write_json(state_file, state)
        # no state payload: turn_start reads what the host persisted
        adopted = pl.dispatch("turn_start", {
            "session_id": "s1", "store": str(self.store),
            "user_text": "今天有点累"})
        self.assertTrue(adopted["field"]["reconciled"])
        self.assertAlmostEqual(adopted["field"]["field"]["v"], 0.55)
        self.assertEqual(adopted["field"]["version"], 1)

    def test_turn_end_arbitrates_and_writes_state_and_state_action(self):
        self.start()
        out = self.end(deltas={"memory_feedback": {"v": 0.06, "a": -0.02},
                               "mood_recall": {"v": -0.02},
                               "preference_drift": {"trust": 0.05}},
                       txid="turn-1")
        self.assertAlmostEqual(out["field"]["field"]["v"], 0.26)
        self.assertAlmostEqual(out["field"]["field"]["a"], 0.58)
        self.assertAlmostEqual(out["field"]["field"]["trust"], 0.52)  # capped
        self.assertEqual(out["field"]["conflicts"][0]["field"], "v")
        state = json.loads((self.store / "sessions" / "s1" / "state.json")
                           .read_text(encoding="utf-8"))
        self.assertAlmostEqual(state["core"]["v"], 0.26)
        self.assertAlmostEqual(state["core"]["a"], 0.58)
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store)})
        self.assertAlmostEqual(shown["state"]["field"]["v"], 0.26)
        self.assertEqual(shown["state"]["arbiter"]["applied"], 3)
        self.assertEqual(shown["state"]["arbiter"]["conflicts"], 1)
        self.assertEqual(shown["state"]["arbiter"]["rejected"], 0)

    def test_turn_end_retry_with_same_txid_is_idempotent(self):
        self.start()
        first = self.end(deltas={"memory_feedback": {"v": 0.06}}, txid="turn-1")
        self.assertAlmostEqual(first["field"]["field"]["v"], 0.26)
        second = self.end(deltas={"memory_feedback": {"v": 0.06}}, txid="turn-1")
        self.assertTrue(second["field"]["duplicate"])
        self.assertAlmostEqual(second["field"]["field"]["v"], 0.26)
        self.assertEqual(second["field"]["applied"], {})

    def test_host_state_push_is_capped_like_any_other_write(self):
        self.start(v=0.20)
        out = self.end(state={"core": {"v": 0.90}})
        self.assertAlmostEqual(out["field"]["applied"]["v"], 0.10)
        self.assertAlmostEqual(out["field"]["field"]["v"], 0.30)

    def test_switch_off_restores_old_behaviour(self):
        out = self.start(field_arbiter=False)
        self.assertFalse(out["field"]["enabled"])
        self.assertFalse((self.store / "sessions" / "s1" / "field.json").exists())
        ended = self.end(deltas={"memory_feedback": {"v": 0.06}},
                         field_arbiter=False)
        self.assertFalse(ended["field"]["enabled"])
        self.assertEqual(ended["field"]["applied"], {})
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store),
                                      "field_arbiter": False})
        self.assertNotIn("field", shown["state"])
        self.assertNotIn("arbiter", shown["state"])
        # the same read with the switch on still works (default ON)
        on = pl.dispatch("state", {"session_id": "s1", "store": str(self.store)})
        self.assertIn("field", on["state"])

    def test_switch_off_via_flags_file(self):
        write_json(self.store / "flags.json", {"field_arbiter": False})
        out = self.start()
        self.assertFalse(out["field"]["enabled"])


class EngineFieldBindingTest(unittest.TestCase):
    """Learners read the field and propose deltas instead of writing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = [NOW]
        self._env = {key: os.environ.pop(key, None) for key in (
            "BIOCORE_MEMORY_FEEDBACK", "BIOCORE_MOOD_RECALL",
            "BIOCORE_AFFECT_ENCODING")}

    def tearDown(self):
        self.tmp.cleanup()
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def write(self, entries):
        (self.dir / "memory.json").write_text(
            json.dumps({"entries": entries, "tombstones": [],
                        "schema_version": 1}), encoding="utf-8")

    def engine(self, affect):
        return MemoryEngine(data_dir=str(self.dir), affect=affect,
                            now=lambda: self.clock[0])

    def test_mood_recall_reads_the_field_not_the_cached_affect(self):
        self.write([entry("warm", "beach warm",
                          {"valence": 0.5, "arousal": 0.5})])
        affect = {"v": -1.0, "a": 0.5}          # stale private copy
        e = self.engine(affect)
        e.flags["mood_recall"] = True
        e.bind_field({"v": 0.5, "a": 0.5})      # the field says otherwise
        rows = e.recall("beach", budget=3)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["mood_cos"], 1.0, places=6)

    def test_memory_feedback_proposes_instead_of_writing(self):
        self.write([entry("warm", "beach warm",
                          {"valence": 0.8, "arousal": 0.9})])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.flags["memory_feedback"] = True
        e.bind_field({"v": 0.0, "a": 0.5})
        e.recall("beach", budget=3)
        report = e._last_memory_feedback
        self.assertTrue(report["deferred"])
        self.assertEqual(report["field_write"], "proposal")
        self.assertAlmostEqual(affect["v"], 0.0, places=6)  # nothing written
        proposals = e.drain_field_proposals()
        self.assertEqual([(p["learner"], p["field"]) for p in proposals],
                         [("memory_feedback", "v"), ("memory_feedback", "a")])
        self.assertAlmostEqual(proposals[0]["delta"], 0.02, places=6)
        self.assertAlmostEqual(proposals[1]["delta"], 0.02, places=6)
        # and the proposal is exactly what the arbiter then applies
        value = fld.Field({"v": 0.0, "a": 0.5})
        out = arb.Arbiter().apply(value, proposals)
        self.assertAlmostEqual(out["field"]["v"], 0.02)
        self.assertAlmostEqual(out["field"]["a"], 0.52)

    def test_unbound_engine_keeps_the_old_direct_write(self):
        self.write([entry("warm", "beach warm",
                          {"valence": 0.8, "arousal": 0.9})])
        affect = {"v": 0.0, "a": 0.5}
        e = self.engine(affect)
        e.flags["memory_feedback"] = True
        e.recall("beach", budget=3)
        self.assertAlmostEqual(affect["v"], 0.02, places=4)
        self.assertEqual(e.drain_field_proposals(), [])
        self.assertIsNone(e.field_view())

    def test_bind_field_copies_and_can_be_released(self):
        e = self.engine(None)
        view = {"v": 0.3, "a": 0.6}
        bound = e.bind_field(view)
        view["v"] = -1.0
        self.assertAlmostEqual(bound["v"], 0.3)  # a copy, not a reference
        e.bind_field(None)
        self.assertIsNone(e.field_view())


if __name__ == "__main__":
    unittest.main()
