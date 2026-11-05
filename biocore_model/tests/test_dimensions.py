# -*- coding: utf-8 -*-
"""task-243 step 1: four-channel read-only projection + pipeline wiring.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_dimensions.py"
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import dimensions as dim
from biocore_runtime import pipeline as pl


NOW = 1700000000.0


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


class ProjectionTest(unittest.TestCase):
    """project(): four channels, a partition, copies only."""

    def test_channels_partition_the_axes(self):
        seen = []
        for axes in dim.CHANNEL_AXES.values():
            seen.extend(axes)
        self.assertEqual(sorted(seen), sorted(dim.DIMS))
        self.assertEqual(len(seen), len(set(seen)))        # no axis twice
        self.assertEqual(tuple(dim.CHANNEL_AXES),
                         ("affect", "tension", "relational", "needs"))

    def test_project_returns_copies_and_never_writes_back(self):
        model = dim.absorb(dim.initial(NOW), explicit={"v": 0.2, "trust": 0.1},
                           source="appraisal", now=NOW)
        before = copy.deepcopy(model)
        view = dim.project(model)
        self.assertEqual(model, before)                    # pure read
        view["projection"]["affect"]["v"]["explicit"] = 0.99
        view["dims"]["v"]["explicit"] = 0.99
        self.assertEqual(model, before)                    # no write-back
        self.assertAlmostEqual(model["dims"]["v"]["explicit"], 0.2)

    def test_projection_keeps_every_axis_separate(self):
        model = dim.initial(NOW)
        model = dim.absorb(model, explicit={"v": 0.10, "a": 0.20,
                                            "stress": 0.30, "social": 0.40,
                                            "trust": 0.50}, now=NOW)
        view = dim.project(model)
        self.assertEqual(sorted(view["projection"]),
                         ["affect", "needs", "relational", "tension"])
        for channel, axes in dim.CHANNEL_AXES.items():
            self.assertEqual(sorted(view["projection"][channel]), sorted(axes))
            for axis in axes:
                self.assertEqual(view["projection"][channel][axis],
                                 view["dims"][axis])
        # no channel value is a sum of its axes
        self.assertAlmostEqual(view["projection"]["affect"]["v"]["explicit"], 0.10)
        self.assertAlmostEqual(view["projection"]["affect"]["a"]["explicit"], 0.20)
        self.assertAlmostEqual(view["projection"]["relational"]["trust"]["explicit"],
                               0.50)

    def test_projection_never_invents_an_axis(self):
        model = dim.absorb(dim.initial(NOW),
                           explicit={"energy": 0.4, "mood": 0.3,
                                     "self_esteem": 0.1}, now=NOW)
        view = dim.project(model)
        self.assertNotIn("energy", view["dims"])
        self.assertNotIn("mood", view["dims"])
        self.assertAlmostEqual(view["dims"]["needs.self_esteem"]["explicit"], 0.1)
        self.assertAlmostEqual(view["projection"]["needs"]
                               ["needs.self_esteem"]["explicit"], 0.1)


class ChannelTest(unittest.TestCase):
    """explicit / implicit stay separate; ambivalence reads the round."""

    def test_same_axis_opposite_signs_keep_both_values(self):
        model = dim.absorb(dim.initial(NOW), explicit={"v": 0.10},
                           source="said", now=NOW)
        model = dim.absorb(model, implicit={"v": -0.06}, source="body", now=NOW)
        row = model["dims"]["v"]
        self.assertAlmostEqual(row["explicit"], 0.10)
        self.assertAlmostEqual(row["implicit"], -0.06)
        self.assertAlmostEqual(row["ambivalence"], 0.06)
        self.assertEqual(len(row["evidence"]), 2)          # both kept, no mean

    def test_ambivalence_also_works_on_a_bounded_axis(self):
        model = dim.absorb(dim.initial(NOW), explicit={"trust": 0.06},
                           source="field_applied", now=NOW)
        model = dim.absorb(model, implicit={"trust": -0.04},
                           source="state_sync", now=NOW)
        row = model["dims"]["trust"]
        self.assertAlmostEqual(row["explicit"], 0.06)
        self.assertAlmostEqual(row["implicit"], 0.0)       # level is clamped
        self.assertAlmostEqual(row["ambivalence"], 0.04)   # the round disagrees

    def test_same_direction_is_not_ambivalent(self):
        model = dim.absorb(dim.initial(NOW), explicit={"trust": 0.06},
                           source="a", now=NOW)
        model = dim.absorb(model, implicit={"trust": 0.04}, source="b", now=NOW)
        self.assertAlmostEqual(model["dims"]["trust"]["ambivalence"], 0.0)

    def test_ambivalence_is_read_from_the_current_round_only(self):
        model = dim.absorb(dim.initial(NOW), explicit={"trust": 0.06},
                           source="a", now=NOW)
        model = dim.absorb(model, implicit={"trust": -0.04}, source="b", now=NOW)
        self.assertAlmostEqual(model["dims"]["trust"]["ambivalence"], 0.04)
        model = dim.absorb(model, explicit={"trust": 0.02}, source="c", now=NOW + 60)
        row = model["dims"]["trust"]
        self.assertAlmostEqual(row["ambivalence"], 0.0)    # new round, no opposite
        self.assertAlmostEqual(row["explicit"], 0.08)      # levels still separate
        self.assertAlmostEqual(row["implicit"], 0.0)

    def test_absorb_never_adds_two_axes_together(self):
        model = dim.absorb(dim.initial(NOW),
                           explicit={"v": 0.10, "trust": 0.20,
                                     "needs.belonging": 0.30}, now=NOW)
        dims = model["dims"]
        self.assertAlmostEqual(dims["v"]["explicit"], 0.10)
        self.assertAlmostEqual(dims["trust"]["explicit"], 0.20)
        self.assertAlmostEqual(dims["needs.belonging"]["explicit"], 0.30)
        self.assertAlmostEqual(dims["a"]["explicit"], 0.0)
        self.assertAlmostEqual(dims["social"]["explicit"], 0.0)

    def test_alias_maps_onto_the_same_axis_without_summing(self):
        model = dim.absorb(dim.initial(NOW), explicit={"d": 0.3}, now=NOW)
        self.assertAlmostEqual(model["dims"]["dominance"]["explicit"], 0.3)
        mixed = dim.absorb(dim.initial(NOW),
                           explicit={"d": 0.3, "dominance": 0.2}, now=NOW)
        self.assertAlmostEqual(mixed["dims"]["dominance"]["explicit"], 0.2)
        self.assertEqual(len(mixed["dims"]["dominance"]["evidence"]), 1)

    def test_decide_ignores_axes_without_evidence(self):
        self.assertEqual(dim.decide(dim.initial(NOW)), [])
        model = dim.absorb(dim.initial(NOW), explicit={"social": 0.10}, now=NOW)
        actions = dim.decide(model)
        self.assertEqual([row["id"] for row in actions], ["withdraw_urge"])


class DimensionPipelineTest(unittest.TestCase):
    """turn_start read / turn_end write / state.dimensions."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")
        self._saved = {key: os.environ.pop(key, None) for key in
                       ("BIOCORE_DIMENSIONS_V2",)}

    def tearDown(self):
        self.tmp.cleanup()
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def start(self, session="s1", **extra):
        payload = {"session_id": session, "store": str(self.store),
                   "user_text": "今天有点累"}
        payload.update(extra)
        return pl.dispatch("turn_start", payload)

    def end(self, session="s1", dimension_deltas=None, **extra):
        payload = {"session_id": session, "store": str(self.store),
                   "assistant_text": "那就先歇一会儿吧。"}
        if dimension_deltas is not None:
            payload["dimension_deltas"] = dimension_deltas
        payload.update(extra)
        return pl.dispatch("turn_end", payload)

    def state_file(self, session="s1"):
        return json.loads((self.store / "sessions" / session / "state.json")
                          .read_text(encoding="utf-8"))

    def test_turn_start_reads_without_creating_the_model(self):
        out = self.start()
        view = out["dimensions"]
        self.assertTrue(view["enabled"])
        self.assertEqual(sorted(view["axes"]), sorted(dim.DIMS))
        self.assertEqual(sorted(view["projection"]),
                         ["affect", "needs", "relational", "tension"])
        self.assertEqual(view["actions"], [])
        self.assertTrue(all(row["explicit"] == 0.0
                            for row in view["axes"].values()))
        self.assertNotIn("dimensions", self.state_file())

    def test_turn_end_writes_and_state_shows_axes_and_projection(self):
        self.start()
        ended = self.end(dimension_deltas={
            "explicit": {"trust": 0.06, "needs.self_esteem": 0.05},
            "implicit": {"trust": -0.04}})
        self.assertTrue(ended["dimensions"]["enabled"])
        self.assertEqual(ended["dimensions"]["written"], 3)
        self.assertAlmostEqual(
            ended["dimensions"]["axes"]["trust"]["ambivalence"], 0.04)
        stored = self.state_file()["dimensions"]
        self.assertEqual(int(stored["schema"]), dim.SCHEMA)
        self.assertAlmostEqual(stored["dims"]["trust"]["explicit"], 0.06)
        self.assertAlmostEqual(stored["dims"]["trust"]["ambivalence"], 0.04)
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store)})
        shown_dim = shown["state"]["dimensions"]
        self.assertEqual(sorted(shown_dim),
                         ["actions", "axes", "hops", "projection", "schema",
                          "ts"])
        self.assertAlmostEqual(shown_dim["axes"]["trust"]["ambivalence"], 0.04)
        self.assertEqual(sorted(shown_dim["projection"]["relational"]),
                         ["closeness", "conflict", "social", "trust"])
        self.assertAlmostEqual(
            shown_dim["projection"]["relational"]["trust"]["explicit"], 0.06)

    def test_turn_end_keeps_every_source_on_its_own_line(self):
        self.start()
        ended = self.end(dimension_deltas={"explicit": {"v": 0.10},
                                           "implicit": {"v": -0.06}},
                         deltas={"v": 0.05})
        sources = {(row["channel"], row["source"])
                   for row in ended["dimensions"]["sources"]}
        self.assertIn(("explicit", "payload.explicit"), sources)
        self.assertIn(("implicit", "payload.implicit"), sources)
        self.assertIn(("implicit", "state_sync"), sources)
        row = self.state_file()["dimensions"]["dims"]["v"]
        self.assertEqual([item["source"] for item in row["evidence"]],
                         ["payload.explicit", "payload.implicit", "state_sync"])
        self.assertAlmostEqual(row["implicit"], -0.01)     # levels, not a sum
        self.assertAlmostEqual(row["ambivalence"], 0.06)

    def test_switch_off_leaves_the_old_path_alone(self):
        write_json(self.store / "flags.json", {"dimensions_v2": False})
        self.assertFalse(self.start()["dimensions"]["enabled"])
        ended = self.end(dimension_deltas={"explicit": {"trust": 0.06}})
        self.assertFalse(ended["dimensions"]["enabled"])
        self.assertNotIn("dimensions", self.state_file())
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store)})
        self.assertNotIn("dimensions", shown["state"])
