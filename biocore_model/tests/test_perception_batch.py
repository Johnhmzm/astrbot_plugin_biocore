# -*- coding: utf-8 -*-
"""task-234 (batch A1): the twelve perception/appraisal modules in one turn.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_perception_batch.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_model import appraisal as ap
from biocore_model import emotion_geometry
from biocore_runtime import perception as pc
from biocore_runtime import pipeline as pl


NOW = 1700000000.0
DIMS_HARD = {"goal": -0.4, "blame": 0.6, "control": 0.3, "certainty": 0.4,
             "novelty": 0.3, "involve": 0.8, "hit": 0.5}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def base_state(v=-0.30, a=0.62, stress=0.65, social=0.35):
    return {"core": {"v": v, "a": a, "stress": stress, "social": social,
                     "energy": 0.45},
            "relationship": {"trust": 0.55, "closeness": 0.50,
                             "conflict": 0.25,
                             "attachment_style": "anxious"},
            "needs": {"belonging": 0.40, "self_esteem": 0.55,
                      "control": 0.45, "meaningful_existence": 0.50}}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self._env = {key: os.environ.pop(key, None)
                     for key in ("BIOCORE_PERCEPTION_BATCH",
                                 "BIOCORE_FIELD_ARBITER")}
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")

    def tearDown(self):
        self.tmp.cleanup()
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home

    # -- helpers ------------------------------------------------------
    def snapshot(self, payload=None, state=None, now=NOW, **kwargs):
        data = {"user_text": "你每次都这样，我有点难受。", "dims": DIMS_HARD,
                "confidence": 0.7}
        data.update(payload or {})
        return pc.snapshot(str(self.store), "s1", payload=data,
                           state=state or base_state(), now=now, **kwargs)

    def sidecar(self):
        return json.loads(pc.path(str(self.store)).read_text(encoding="utf-8"))


class SwitchTest(Case):
    def test_default_is_on(self):
        self.assertTrue(pc.enabled())
        self.assertTrue(pc.enabled(overrides={}))
        self.assertTrue(pc.enabled(env={}))

    def test_payload_can_turn_the_whole_batch_off(self):
        self.assertFalse(pc.enabled(overrides={"perception_batch": False}))
        self.assertFalse(pc.enabled(overrides={"switches": {
            "perception_batch": False}}))

    def test_env_can_turn_the_whole_batch_off(self):
        self.assertFalse(pc.enabled(env={"BIOCORE_PERCEPTION_BATCH": "0"}))
        self.assertTrue(pc.enabled(env={"BIOCORE_PERCEPTION_BATCH": "1"}))

    def test_flags_file_wins_over_env(self):
        write_json(self.store / "flags.json", {"perception_batch": False})
        self.assertFalse(pc.enabled(store=str(self.store),
                                    env={"BIOCORE_PERCEPTION_BATCH": "1"}))


class SnapshotTest(Case):
    def test_all_twelve_modules_run(self):
        snap = self.snapshot()
        self.assertTrue(snap["enabled"])
        # A2 extended the batch to 23; the A1 twelve must all still be there.
        self.assertEqual(snap["counts"], {"modules": 23, "a1": 12, "a2": 11,
                                          "enabled": 23})
        self.assertEqual(set(snap["modules"]), set(pc.MODULES))
        self.assertTrue(all(snap["modules"][name] for name in pc.MODULES_A1))
        self.assertTrue(all(snap["modules"].values()))

    def test_emotion_is_read_from_the_affect_point(self):
        snap = self.snapshot()
        emotion = snap["emotion"]
        self.assertIn(emotion["label"], emotion_geometry.LABELS)
        self.assertGreaterEqual(emotion["confidence"], 0.0)
        self.assertLessEqual(len(emotion["top"]), 3)
        self.assertAlmostEqual(sum(row["prob"] for row in emotion["top"]) <= 1.0,
                               True)

    def test_needs_start_from_the_baseline(self):
        state = {"core": {"v": 0.0, "a": 0.5}}
        snap = self.snapshot(state=state)
        self.assertEqual(set(snap["needs"]),
                         {"belonging", "self_esteem", "control",
                          "meaningful_existence"})
        self.assertAlmostEqual(snap["needs"]["belonging"], 0.6)
        self.assertAlmostEqual(snap["needs_bias"]["seek_contact"], 0.0,
                               places=6)

    def test_needs_bias_reads_a_deficit(self):
        state = base_state()
        state["needs"]["belonging"] = 0.30
        snap = self.snapshot(state=state)
        # needs_events weights a belonging deficit by 3.0
        self.assertAlmostEqual(snap["needs_bias"]["seek_contact"], 0.9, places=4)

    def test_attachment_style_and_mode_come_from_the_relationship(self):
        snap = self.snapshot()
        attachment = snap["attachment"]
        self.assertEqual(attachment["style"], "anxious")
        self.assertEqual(attachment["mode"], "hyperactivating")
        self.assertAlmostEqual(attachment["drive_mult"], 1.2, places=4)
        self.assertTrue(attachment["tone"])
        self.assertIn(attachment["strategy"], ("reappraise", "suppress"))

    def test_attribution_is_rule_based_and_never_guesses(self):
        external = self.snapshot(payload={"user_text": "对方总是这样，没办法"})
        self.assertEqual(external["attribution"]["locus"], "external")
        self.assertEqual(external["attribution"]["stability"], "stable")
        neutral = self.snapshot(payload={"user_text": "今天天气不错"})
        self.assertEqual(neutral["attribution"]["locus"], "neutral")

    def test_criticality_is_deterministic_per_session_and_tick(self):
        first = self.snapshot()["criticality"]["burst"]
        second = self.snapshot()["criticality"]["burst"]
        self.assertEqual(first, second)
        self.assertIsInstance(first, float)

    def test_autonomic_threshold_stays_in_the_physiological_band(self):
        threshold = self.snapshot()["autonomic"]["threshold"]
        self.assertGreaterEqual(threshold, 0.15)
        self.assertLessEqual(threshold, 0.60)

    def test_snapshot_is_prompt_free(self):
        snap = self.snapshot()
        blob = json.dumps(snap, ensure_ascii=False).lower()
        self.assertNotIn("prompt", blob)
        self.assertNotIn("[biocore", blob)

    def test_snapshot_is_recorded_once_per_turn(self):
        self.snapshot()
        self.snapshot(now=NOW + 60)
        doc = self.sidecar()
        self.assertEqual(len(doc["history"]), 2)
        self.assertAlmostEqual(doc["latest"]["ts"], NOW + 60, places=3)

    def test_disabled_snapshot_touches_nothing(self):
        snap = self.snapshot(enabled_override=False)
        self.assertFalse(snap["enabled"])
        self.assertFalse(pc.path(str(self.store)).exists())

    def test_one_broken_module_does_not_break_the_batch(self):
        original = pc._mod

        def broken(name):
            return None if name == "autonomic" else original(name)

        pc._mod = broken
        try:
            snap = self.snapshot()
        finally:
            pc._mod = original
        self.assertFalse(snap["modules"]["autonomic"])
        self.assertEqual(snap["counts"]["enabled"], 22)
        self.assertTrue(snap["modules"]["emotion_geometry"])


class WritebackTest(Case):
    def writeback(self, payload=None, state=None, now=NOW + 10, **kwargs):
        data = {"user_text": "你每次都这样", "assistant_text": "……我在听。",
                "dims": DIMS_HARD, "confidence": 0.7}
        data.update(payload or {})
        return pc.writeback(str(self.store), "s1", payload=data,
                            state=state or base_state(), now=now, **kwargs)

    def test_appraisal_field_deltas_are_capped(self):
        out = self.writeback()
        proposals = out["field_deltas"]["appraisal"]
        # A2: the chosen strategy absorbs part of the negative pressure; the
        # share is per dimension (strategy x dimension), not one global keep.
        strategy = out["regulation"]["strategy"]
        effect = out["regulation"]["effect"]
        per_dim = out["regulation"]["per_dim"]
        self.assertGreater(out["regulation"]["absorbed"], 0.0)
        for name, raw in (("v", -0.10), ("stress", 0.08), ("trust", -0.02)):
            self.assertAlmostEqual(
                proposals[name],
                round(raw * (1.0 - pc.dim_absorb(strategy, name, effect)), 6),
                places=6)
        self.assertNotAlmostEqual(per_dim["v"], per_dim["trust"], places=4)
        for name, value in proposals.items():
            self.assertLessEqual(abs(value),
                                 pc.FIELD_CAPS[name] + 1e-9)

    def test_d_and_self_esteem_never_touch_the_body(self):
        out = self.writeback()
        state = out["_state"]
        expected_d = ap.appraise(DIMS_HARD, confidence=0.7, v2=True).get("d", 0.0)
        expected_d = round(max(-pc.OWN_CAPS["d"], min(pc.OWN_CAPS["d"],
                                                      expected_d)), 6)
        self.assertAlmostEqual(out["own_deltas"]["d"], expected_d, places=4)
        self.assertNotIn("d", state["core"])
        self.assertNotIn("self_esteem", state["core"])
        self.assertAlmostEqual(state["appraisal"]["d"], expected_d, places=4)
        # A2: the state-level self-esteem now moves through needs_esteem
        self.assertAlmostEqual(state["appraisal"]["self_esteem"],
                               out["esteem"]["after"], places=4)

    def test_needs_move_within_their_caps(self):
        out = self.writeback()
        needs = out["needs"]
        for key, delta in needs["delta"].items():
            self.assertLessEqual(abs(delta), pc.NEED_CAPS[key] + 1e-9)
        self.assertLess(needs["after"]["self_esteem"],
                        needs["before"]["self_esteem"])
        self.assertGreaterEqual(needs["after"]["self_esteem"], 0.0)

    def test_attachment_activation_is_bounded(self):
        out = self.writeback(payload={"attachment_signal": 1.0,
                                      "assistant_text": ""})
        attachment = out["attachment"]
        self.assertLessEqual(abs(attachment["delta"]), pc.ATTACH_CAP + 1e-9)
        self.assertGreater(attachment["activation"], attachment["before"])
        self.assertLessEqual(attachment["activation"], 1.0)

    def test_writeback_is_idempotent_per_timestamp(self):
        first = self.writeback()
        self.assertTrue(first["enabled"])
        second = self.writeback(state=first["_state"])
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(second["applied"], {})
        self.assertEqual(second["field_deltas"], {})

    def test_disabled_writeback_changes_nothing(self):
        state = base_state()
        out = self.writeback(state=state, enabled_override=False)
        self.assertFalse(out["enabled"])
        self.assertEqual(out["applied"], {})
        self.assertNotIn("perception", state)
        self.assertFalse(pc.path(str(self.store)).exists())


class PipelineTest(Case):
    def start(self, session="s1", perception=None):
        payload = {"session_id": session, "store": str(self.store),
                   "user_text": "你每次都这样，我有点难受。",
                   "state": base_state()}
        if perception is not None:
            payload["perception_batch"] = perception
        return pl.dispatch("turn_start", payload)

    def end(self, session="s1", perception=None, dims=None):
        payload = {"session_id": session, "store": str(self.store),
                   "assistant_text": "……我在听。",
                   "user_text": "你每次都这样，我有点难受。",
                   "state": base_state()}
        if dims is not None:
            payload["dims"] = dims
            payload["confidence"] = 0.7
        if perception is not None:
            payload["perception_batch"] = perception
        return pl.dispatch("turn_end", payload)

    def state_file(self, session="s1"):
        return json.loads((self.store / "sessions" / session / "state.json")
                          .read_text(encoding="utf-8"))

    def core_state(self):
        path = self.store / "core_state.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_turn_start_returns_the_snapshot(self):
        out = self.start()
        view = out["perception"]
        self.assertTrue(view["enabled"])
        self.assertEqual(view["counts"]["modules"], 23)
        self.assertEqual(view["counts"]["a2"], 11)
        self.assertIn(view["emotion"]["label"], emotion_geometry.LABELS)

    def test_turn_end_appraisal_reaches_field_and_body(self):
        self.start()
        before = self.core_state()["v"]
        out = self.end(dims=DIMS_HARD)
        self.assertTrue(out["perception"]["enabled"])
        applied_v = out["field"]["applied"]["v"]
        self.assertLess(applied_v, 0.0)
        self.assertGreaterEqual(applied_v, -0.10 - 1e-9)  # capped
        self.assertAlmostEqual(self.core_state()["v"], before + applied_v,
                               places=4)
        self.assertAlmostEqual(self.state_file()["core"]["v"], before + applied_v,
                               places=4)

    def test_turn_end_writes_needs_and_attachment(self):
        self.start()
        self.end(dims=DIMS_HARD)
        state = self.state_file()
        self.assertLess(state["needs"]["self_esteem"], 0.55)
        self.assertGreater(state["attachment"]["activation"], 0.0)
        self.assertIn("ts", state["perception"])

    def test_state_exposes_the_six_new_fields(self):
        self.start()
        self.end(dims=DIMS_HARD)
        body = pl.dispatch("state", {"session_id": "s1",
                                     "store": str(self.store)})["state"]
        for key in ("emotion", "affect", "attachment", "needs", "appraisal",
                    "perception"):
            self.assertIn(key, body)
        self.assertEqual(body["perception"]["counts"]["modules"], 23)
        self.assertIn("writeback", body["perception"])

    def test_state_affect_matches_the_field(self):
        self.start()
        self.end(dims=DIMS_HARD)
        body = pl.dispatch("state", {"session_id": "s1",
                                     "store": str(self.store)})["state"]
        for name in ("v", "a", "stress", "social", "trust", "closeness"):
            self.assertAlmostEqual(body["affect"][name], body["field"][name],
                                   places=4)

    def test_switch_off_restores_the_old_turn(self):
        start = self.start(perception=False)
        self.assertFalse(start["perception"]["enabled"])
        self.assertFalse((self.store / "perception.json").exists())
        ended = self.end(perception=False, dims=DIMS_HARD)
        self.assertFalse(ended["perception"]["enabled"])
        self.assertEqual(ended["perception"]["applied"], {})
        state = self.state_file()
        self.assertNotIn("perception", state)
        self.assertNotIn("appraisal", state)
        body = pl.dispatch("state", {"session_id": "s1", "store": str(self.store),
                                     "perception_batch": False})["state"]
        for key in ("emotion", "affect", "attachment", "needs", "perception"):
            self.assertNotIn(key, body)

    def test_switch_off_via_flags_file(self):
        write_json(self.store / "flags.json", {"perception_batch": False})
        out = self.start()
        self.assertFalse(out["perception"]["enabled"])
        self.assertFalse((self.store / "perception.json").exists())


if __name__ == "__main__":
    unittest.main()
