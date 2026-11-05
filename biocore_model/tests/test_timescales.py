# -*- coding: utf-8 -*-
"""task-229 (P0-2): seconds / minutes / hours, each with its own rates.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_timescales.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import pipeline as pl
from biocore_runtime import timescales as ts


NOW = 1700000000.0


def step(model=None, v=-0.6, a=0.6, dt=60.0, now=NOW):
    model = model if model is not None else ts.initial(NOW)
    return ts.step(model, {"v": v, "a": a}, dt, now=now)


class LayerTest(unittest.TestCase):
    def test_defaults_and_repair(self):
        model = ts.load({})
        self.assertEqual(model["fast"]["v"], 0.0)
        self.assertEqual(model["medium"]["mood"], 0.0)
        self.assertEqual(model["slow"]["baseline"], 0.0)
        repaired = ts.load({"timescales": {"fast": {"v": 0.4},
                                           "slow": {"baseline": 0.2}}})
        self.assertAlmostEqual(repaired["fast"]["v"], 0.4, places=6)
        self.assertAlmostEqual(repaired["slow"]["baseline"], 0.2, places=6)
        self.assertEqual(repaired["medium"]["mood"], 0.0)

    def test_fast_moves_first_and_fastest(self):
        model, report = step()
        self.assertAlmostEqual(report["fast"]["after"], -0.35, places=6)
        self.assertLess(report["fast"]["after"], report["medium"]["after"])
        self.assertEqual(report["medium"]["after"], -0.12)
        self.assertEqual(report["slow"]["committed"], 0.0)

    def test_fast_is_capped_per_turn(self):
        model, report = step(v=-1.0)
        self.assertAlmostEqual(report["fast"]["after"], -0.35, places=6)
        model, again = ts.step(model, {"v": -1.0, "a": 0.5}, 1.0, now=NOW + 1)
        self.assertGreaterEqual(again["fast"]["after"],
                                report["fast"]["after"] - ts.FAST_STEP_CAP - 1e-6)

    def test_fast_decays_with_time(self):
        model = ts.initial(NOW)
        model["fast"]["v"] = 0.8
        decayed, _ = ts.step(model, {"v": 0.8, "a": 0.5}, 3600.0, now=NOW + 3600)
        self.assertLess(decayed["fast"]["v"], 0.8)

    def test_medium_decays_towards_the_slow_baseline(self):
        model = ts.initial(NOW)
        model["medium"]["mood"] = 0.6
        model["slow"]["baseline"] = 0.2
        moved, _ = ts.step(model, {"v": 0.2, "a": 0.5}, 5400.0, now=NOW + 5400)
        self.assertGreater(moved["medium"]["mood"], 0.2)
        self.assertLess(moved["medium"]["mood"], 0.6)

    def test_medium_moves_slower_than_fast_for_the_same_sample(self):
        _, report = step(v=0.5)
        self.assertLess(abs(report["medium"]["delta"]),
                        abs(report["fast"]["delta"]))


class SlowLayerTest(unittest.TestCase):
    def test_slow_needs_three_repeats_before_writing(self):
        model = ts.initial(NOW)
        for index in range(2):
            model, report = ts.step(model, {"v": -0.6, "a": 0.5}, 60.0,
                                    now=NOW + index * 60)
            self.assertEqual(report["slow"]["committed"], 0.0)
            self.assertEqual(report["slow"]["streak"], index + 1)
            self.assertAlmostEqual(model["slow"]["baseline"], 0.0, places=6)
        model, report = ts.step(model, {"v": -0.6, "a": 0.5}, 60.0, now=NOW + 180)
        self.assertAlmostEqual(report["slow"]["committed"], -0.05, places=6)
        self.assertAlmostEqual(model["slow"]["baseline"], -0.05, places=6)
        self.assertEqual(report["slow"]["streak"], 0)
        self.assertEqual(model["slow"]["commits"], 1)

    def test_slow_streak_resets_on_a_flip_and_counts_a_reject(self):
        model = ts.initial(NOW)
        model, _ = ts.step(model, {"v": -0.6, "a": 0.5}, 60.0, now=NOW)
        model, _ = ts.step(model, {"v": -0.6, "a": 0.5}, 60.0, now=NOW + 60)
        model, report = ts.step(model, {"v": 0.6, "a": 0.5}, 60.0, now=NOW + 120)
        self.assertEqual(report["slow"]["streak"], 1)
        self.assertEqual(model["slow"]["rejects"], 1)
        self.assertEqual(report["slow"]["committed"], 0.0)

    def test_slow_commit_is_capped(self):
        model = ts.initial(NOW)
        for index in range(3):
            model, report = ts.step(model, {"v": 1.0, "a": 0.5}, 60.0,
                                    now=NOW + index * 60)
        self.assertAlmostEqual(report["slow"]["committed"], ts.SLOW_STEP_CAP,
                               places=6)

    def test_noise_does_not_start_a_streak(self):
        model = ts.initial(NOW)
        model, report = ts.step(model, {"v": 1e-5, "a": 0.5}, 60.0, now=NOW)
        self.assertEqual(report["slow"]["direction"], 0)
        self.assertEqual(report["slow"]["streak"], 0)


class ProjectionTest(unittest.TestCase):
    def test_projection_has_three_layers(self):
        model, _ = step()
        row = ts.project(model)
        self.assertEqual(set(row), {"enabled", "ts", "fast", "medium", "slow"})
        self.assertEqual(row["fast"]["decay_seconds"], ts.DECAY_SECONDS["fast"])
        self.assertEqual(row["slow"]["repeats_needed"], ts.REPEAT["slow"])
        self.assertEqual(row["slow"]["decay_seconds"], 21600.0)

    def test_switch_defaults_on_and_can_be_off(self):
        self.assertTrue(ts.enabled())
        self.assertFalse(ts.enabled({"timescales": False}))
        self.assertFalse(ts.summary({}, enabled_override=False)["enabled"])
        self.assertTrue(ts.summary({"timescales": ts.initial(NOW)})["enabled"])

    def test_step_is_pure(self):
        model = ts.initial(NOW)
        snapshot = json.dumps(model, sort_keys=True)
        ts.step(model, {"v": -0.6, "a": 0.5}, 60.0, now=NOW)
        self.assertEqual(json.dumps(model, sort_keys=True), snapshot)


class PipelineTest(unittest.TestCase):
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

    def turn(self, v, now):
        payload = {"session_id": "s1", "store": str(self.store),
                   "user_text": "在吗", "assistant_text": "嗯，我在。",
                   "state": {"core": {"v": v, "a": 0.6, "stress": 0.55,
                                      "social": 0.45}}, "now": now}
        pl.dispatch("turn_start", payload)
        return pl.dispatch("turn_end", payload)

    def test_turn_end_advances_and_state_exposes_three_layers(self):
        self.turn(-0.6, NOW)
        body = pl.dispatch("state", {"session_id": "s1",
                                     "store": str(self.store)})["state"]
        scales = body["timescales"]
        self.assertEqual(set(scales), {"fast", "medium", "slow", "ts"})
        self.assertLess(scales["fast"]["v"], 0.0)
        self.assertEqual(scales["slow"]["baseline"], 0.0)  # not yet, needs 3

    def test_three_turns_commit_the_slow_layer(self):
        for index in range(3):
            self.turn(-0.6, NOW + index * 60)
        body = pl.dispatch("state", {"session_id": "s1",
                                     "store": str(self.store)})["state"]
        self.assertAlmostEqual(body["timescales"]["slow"]["baseline"], -0.05,
                               places=4)
        self.assertEqual(body["timescales"]["slow"]["commits"], 1)

    def test_switch_off_hides_the_block(self):
        self.turn(-0.6, NOW)
        body = pl.dispatch("state", {"session_id": "s1", "store": str(self.store),
                                     "switches": {"timescales": False}})["state"]
        self.assertNotIn("timescales", body)


if __name__ == "__main__":
    unittest.main()
