# -*- coding: utf-8 -*-
"""task-235 (batch A2): the remaining eleven perception modules + needs_events.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_perception_batch_a2.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import perception as pc
from biocore_runtime import pipeline as pl


NOW = 1700000000.0
DIMS_HARD = {"goal": -0.4, "blame": 0.8, "control": 0.3, "certainty": 0.4,
             "novelty": 0.3, "involve": 0.8, "hit": 0.9}
ACTIONS = ("approach", "share", "question", "withdraw", "repair", "rest")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def base_state(v=-0.35, a=0.62, stress=0.70, social=0.40):
    return {"core": {"v": v, "a": a, "stress": stress, "social": social,
                     "energy": 0.40},
            "relationship": {"trust": 0.55, "closeness": 0.65,
                             "conflict": 0.25, "attachment_style": "anxious"},
            "needs": {"belonging": 0.60, "self_esteem": 0.60, "control": 0.60,
                      "meaningful_existence": 0.60},
            "sleep": {"debt_hours": 6.0},
            "frustration_n": 4}


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

    def snapshot(self, payload=None, state=None, now=NOW, **kwargs):
        data = {"user_text": "你每次都不回我，我等了好久。",
                "dims": DIMS_HARD, "confidence": 0.7}
        data.update(payload or {})
        return pc.snapshot(str(self.store), "s1", payload=data,
                           state=state or base_state(), now=now, **kwargs)

    def writeback(self, payload=None, state=None, now=NOW + 10, **kwargs):
        data = {"user_text": "你每次都不回我", "assistant_text": "我在。",
                "dims": DIMS_HARD, "confidence": 0.7}
        data.update(payload or {})
        return pc.writeback(str(self.store), "s1", payload=data,
                            state=state or base_state(), now=now, **kwargs)


class SnapshotA2Test(Case):
    def test_a2_modules_are_all_present_and_enabled(self):
        snap = self.snapshot()
        self.assertEqual(snap["counts"], {"modules": 23, "a1": 12, "a2": 11,
                                          "enabled": 23})
        for name in pc.MODULES_A2:
            self.assertTrue(snap["modules"][name], name)
        self.assertEqual(set(pc.MODULES_A2) & set(pc.MODULES_A1), set())

    def test_needs_and_bias_come_from_needs_events(self):
        snap = self.snapshot()
        self.assertEqual(set(snap["needs"]), set(pc.NEED_CAPS))
        self.assertEqual(set(snap["needs_bias"]),
                         {"seek_contact", "self_assert", "ask_clarify",
                          "share_meaning"})
        self.assertAlmostEqual(snap["needs"]["belonging"], 0.60, places=4)

    def test_needs_bias_follows_a_deficit(self):
        state = base_state()
        state["needs"]["belonging"] = 0.30
        snap = self.snapshot(state=state)
        self.assertAlmostEqual(snap["needs_bias"]["seek_contact"], 0.90,
                               places=4)

    def test_esteem_reads_the_state_appraisal_block(self):
        state = base_state()
        state["appraisal"] = {"self_esteem": 0.40}
        snap = self.snapshot(state=state)
        self.assertAlmostEqual(snap["esteem"]["self_esteem"], 0.40, places=4)

    def test_sleep_debt_costs_energy_and_patience(self):
        snap = self.snapshot()
        self.assertAlmostEqual(snap["sleep_debt"]["debt"], 6.0, places=3)
        self.assertAlmostEqual(snap["sleep_debt"]["energy_penalty"], 0.25,
                               places=4)
        self.assertAlmostEqual(snap["sleep_debt"]["irritability"], 0.5,
                               places=4)

    def test_circadian_snapshot_stays_in_range(self):
        sleep = self.snapshot()["sleep"]
        self.assertGreaterEqual(sleep["circadian"], 0.0)
        self.assertLessEqual(sleep["circadian"], 1.0)
        self.assertGreaterEqual(sleep["hour"], 0.0)
        self.assertLess(sleep["hour"], 24.0)
        self.assertIn("sleeping", sleep)

    def test_frustration_phase_reads_the_counter(self):
        snap = self.snapshot()
        self.assertEqual(snap["frustration"]["n"], 4)
        self.assertEqual(snap["frustration"]["phase"], "plateau")
        self.assertAlmostEqual(snap["frustration"]["drive_mult"], 1.2, places=3)

    def test_envy_needs_a_third_person(self):
        quiet = self.snapshot()
        self.assertAlmostEqual(quiet["envy"]["intensity"], 0.0, places=4)
        self.assertEqual(quiet["envy"]["kind"], "")
        loud = self.snapshot(payload={"envy": {"third_party": 0.9,
                                               "fairness": 0.1,
                                               "self_evaluation": 0.3}})
        self.assertGreater(loud["envy"]["intensity"], 0.0)
        self.assertTrue(loud["envy"]["kind"])

    def test_regulation_reads_a_strategy_and_an_action(self):
        regulation = self.snapshot()["regulation"]
        self.assertTrue(regulation["strategy"])
        self.assertIn(regulation["action"], ACTIONS)
        self.assertGreaterEqual(regulation["effect"], 0.0)
        self.assertLessEqual(regulation["effect"], 1.0)

    def test_situation_is_at_most_three_lines(self):
        situation = self.snapshot()["situation"]
        self.assertTrue(situation["enabled"])
        self.assertLessEqual(len(situation["lines"]), 3)
        self.assertGreater(situation["chars"], 0)

    def test_social_theory_scales_with_closeness(self):
        snap = self.snapshot()
        self.assertTrue(snap["social"]["mood_hint"])
        far = self.snapshot(state=dict(base_state(),
                                       relationship={"closeness": 0.0,
                                                     "trust": 0.5}))
        near = self.snapshot(state=dict(base_state(),
                                        relationship={"closeness": 1.0,
                                                      "trust": 0.5}))
        self.assertLess(far["social"]["share_probability"],
                        near["social"]["share_probability"])
        self.assertLess(far["social"]["question_probability"],
                        near["social"]["question_probability"])

    def test_waiting_sense_grows_with_the_gap(self):
        close = base_state()
        close["last_human_ts"] = NOW - 60.0
        far = base_state()
        far["last_human_ts"] = NOW - 86400.0
        self.assertLess(self.snapshot(state=close)["waiting"]["sense"],
                        self.snapshot(state=far)["waiting"]["sense"])
        self.assertGreater(self.snapshot(state=far)["waiting"]["sense"], 0.0)


class WritebackA2Test(Case):
    def test_needs_events_move_the_needs(self):
        out = self.writeback()
        needs = out["needs"]
        self.assertTrue(needs["events"])
        kinds = [row.get("kind") for row in needs["events"]]
        self.assertIn("rejected", kinds)
        self.assertLess(needs["after"]["self_esteem"],
                        needs["before"]["self_esteem"])

    def test_each_need_moves_at_most_its_cap(self):
        out = self.writeback()
        for key, delta in out["needs"]["delta"].items():
            self.assertLessEqual(abs(delta), pc.NEED_CAPS[key] + 1e-9, key)

    def test_regulation_absorbs_part_of_the_pressure(self):
        out = self.writeback()
        absorbed = out["regulation"]["absorbed"]
        self.assertGreater(absorbed, 0.0)
        self.assertLess(absorbed, 0.5)
        proposals = out["field_deltas"]["appraisal"]
        self.assertLess(abs(proposals["stress"]), 0.08)
        self.assertGreater(abs(proposals["stress"]), 0.0)

    def test_self_esteem_moves_on_the_event_not_the_raw_delta(self):
        # needs_esteem scores the event (replied / praised / ignored / rejected)
        # instead of adding appraisal's raw self_esteem delta.
        silent = self.writeback(payload={"assistant_text": ""})
        replied = self.writeback(payload={"assistant_text": "我在。"},
                                 now=NOW + 30, state=silent["_state"])
        self.assertNotAlmostEqual(replied["esteem"]["after"],
                                  silent["esteem"]["after"], places=4)
        self.assertAlmostEqual(
            replied["_state"]["appraisal"]["esteem_delta"],
            round(replied["esteem"]["after"] - replied["esteem"]["before"], 4),
            places=4)

    def test_sleep_debt_only_moves_when_the_host_says_so(self):
        silent = self.writeback()
        self.assertAlmostEqual(silent["sleep"]["debt"], 6.0, places=3)
        self.assertAlmostEqual(silent["sleep"]["delta"], 0.0, places=3)
        repaid = self.writeback(payload={"slept_hours": 6.0})
        self.assertAlmostEqual(repaid["sleep"]["debt"], 1.5, places=3)
        self.assertLess(repaid["sleep"]["delta"], 0.0)

    def test_writeback_is_idempotent_per_timestamp(self):
        first = self.writeback()
        second = self.writeback(state=first["_state"])
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(second["field_deltas"], {})

    def test_disabled_writeback_covers_a2_too(self):
        state = base_state()
        before = json.dumps(state, sort_keys=True, ensure_ascii=False)
        out = self.writeback(state=state, enabled_override=False)
        self.assertFalse(out["enabled"])
        self.assertEqual(json.dumps(state, sort_keys=True, ensure_ascii=False),
                         before)  # not one A2 write landed
        self.assertNotIn("perception", state)
        self.assertFalse(pc.path(str(self.store)).exists())


class PipelineA2Test(Case):
    def start(self, session="s1", **extra):
        payload = {"session_id": session, "store": str(self.store),
                   "user_text": "你每次都不回我，我等了好久。",
                   "state": base_state()}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def end(self, session="s1", **extra):
        payload = {"session_id": session, "store": str(self.store),
                   "assistant_text": "我在。",
                   "user_text": "你每次都不回我，我等了好久。",
                   "state": base_state(), "dims": DIMS_HARD,
                   "confidence": 0.7}
        payload.update(extra)
        return pl.dispatch("turn_end", payload)

    def state_file(self, session="s1"):
        return json.loads((self.store / "sessions" / session / "state.json")
                          .read_text(encoding="utf-8"))

    def test_state_exposes_the_a2_fields(self):
        self.start()
        self.end()
        body = pl.dispatch("state", {"session_id": "s1",
                                     "store": str(self.store)})["state"]
        for key in ("regulation", "sleep", "situation", "waiting", "esteem"):
            self.assertIn(key, body)
        self.assertTrue(body["regulation"]["strategy"])
        self.assertIn("debt", body["sleep"])
        self.assertLessEqual(len(body["situation"]["lines"]), 3)
        self.assertEqual(body["perception"]["counts"]["a2"], 11)

    def test_turn_end_persists_needs_and_sleep(self):
        self.start()
        self.end(slept_hours=6.0)
        state = self.state_file()
        self.assertIn("needs", state)
        self.assertIn("sleep", state)
        self.assertAlmostEqual(state["sleep"]["debt_hours"], 1.5, places=3)
        self.assertGreater(state["needs"]["meaningful_existence"], 0.0)

    def test_switch_off_hides_every_a2_field(self):
        self.start(perception_batch=False)
        self.end(perception_batch=False)
        body = pl.dispatch("state", {"session_id": "s1", "store": str(self.store),
                                     "perception_batch": False})["state"]
        for key in ("regulation", "sleep", "situation", "waiting", "esteem",
                    "perception"):
            self.assertNotIn(key, body)
        self.assertFalse((self.store / "perception.json").exists())

    def test_turn_end_returns_a2_writeback(self):
        self.start()
        out = self.end()
        payload = out["perception"]
        self.assertTrue(payload["enabled"])
        self.assertIn("regulation", payload)
        self.assertIn("esteem", payload)
        self.assertIn("sleep", payload)
        self.assertIn("needs", payload)


if __name__ == "__main__":
    unittest.main()
