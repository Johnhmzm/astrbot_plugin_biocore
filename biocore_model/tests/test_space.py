# -*- coding: utf-8 -*-
"""task-244 ①: shadow coordinates on memory entries (write-only).

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_space.py"
"""
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from biocore_memory import space as sp
from biocore_runtime import pipeline as pl


NOW = 1700000000.0


def entry(**kw):
    base = {"id": "e1", "text": "我的猫叫团子", "ts": NOW, "tags": ["猫", "宠物"],
            "importance": 0.5, "hits": 1}
    base.update(kw)
    return base


def unit(*values):
    return list(values)


class CoordinateTest(unittest.TestCase):
    """The five axes, the embedding names and the distances."""

    def test_five_axes_are_present(self):
        space = sp.build(entry(), {"trust": 0.6, "closeness": 0.7}, now=NOW)
        self.assertEqual(sorted(sp.AXES), sorted(
            ["semantic", "time", "affect", "social", "activation"]))
        for axis in sp.AXES:
            self.assertIn(axis, space)
        self.assertEqual(space["schema"], sp.SCHEMA)
        self.assertEqual(sorted(space["semantic"]),
                         ["entities", "fallback", "fingerprint", "model",
                          "provider", "topics", "vector", "vector_dim"])
        self.assertTrue(space["semantic"]["fallback"])   # no vector: tags only
        self.assertEqual(sorted(space["time"]),
                         ["age_minutes", "half_life_minutes", "last_hit_ts", "ts"])
        self.assertEqual(sorted(space["affect"]), ["a", "v"])
        self.assertEqual(sorted(space["social"]),
                         ["closeness", "scope", "trust"])
        self.assertEqual(sorted(space["activation"]),
                         ["hits", "importance", "last_hit_ts", "retrieval_count"])

    def test_embedding_provider_and_model_are_kept(self):
        from_entry = sp.build(entry(embedding_provider="local",
                                    embedding_model="bge-m3"), now=NOW)
        self.assertEqual(from_entry["semantic"]["provider"], "local")
        self.assertEqual(from_entry["semantic"]["model"], "bge-m3")
        from_call = sp.build(entry(), now=NOW,
                             embed={"provider": "remote", "model": "text-3"})
        self.assertEqual(from_call["semantic"]["provider"], "remote")
        self.assertEqual(from_call["semantic"]["model"], "text-3")

    def test_semantic_distance_is_one_minus_cosine(self):
        a = sp.build(entry(vector=unit(1.0, 0.0, 0.0)), now=NOW)
        same = sp.build(entry(vector=unit(1.0, 0.0, 0.0)), now=NOW)
        orth = sp.build(entry(vector=unit(0.0, 1.0, 0.0)), now=NOW)
        opp = sp.build(entry(vector=unit(-1.0, 0.0, 0.0)), now=NOW)
        self.assertAlmostEqual(sp.distance(a, same)["semantic"], 0.0)
        self.assertAlmostEqual(sp.distance(a, orth)["semantic"], 1.0)
        self.assertAlmostEqual(sp.distance(a, opp)["semantic"], 2.0)
        cosine = sum(x * y for x, y in zip(a["semantic"]["vector"],
                                           orth["semantic"]["vector"])) / (
            math.hypot(*a["semantic"]["vector"]) * math.hypot(*orth["semantic"]["vector"]))
        self.assertAlmostEqual(sp.distance(a, orth)["semantic"], 1.0 - cosine)

    def test_missing_vector_falls_back_to_tag_overlap(self):
        no_vector = sp.build(entry(tags=["猫", "宠物"]), now=NOW)
        self.assertEqual(no_vector["semantic"]["vector"], [])
        self.assertEqual(no_vector["semantic"]["vector_dim"], 0)
        self.assertIn("猫", no_vector["semantic"]["topics"])
        twin = sp.build(entry(tags=["猫", "宠物"]), now=NOW)
        other = sp.build(entry(tags=["工作"]), now=NOW)
        self.assertAlmostEqual(sp.distance(no_vector, twin)["semantic"], 0.0)
        self.assertGreater(sp.distance(no_vector, other)["semantic"], 0.5)

    def test_distance_is_per_axis_only(self):
        a = sp.build(entry(vector=unit(1.0, 0.0), tags=["猫"]), now=NOW)
        b = sp.build(entry(vector=unit(0.0, 1.0), tags=["工作"], ts=NOW + 7200,
                           importance=0.9), now=NOW)
        distances = sp.distance(a, b)
        self.assertEqual(sorted(distances),
                         ["activation", "affect", "semantic", "social", "time"])
        self.assertNotIn("total", distances)
        self.assertNotIn("score", distances)
        for value in distances.values():
            self.assertGreaterEqual(value, 0.0)

    def test_time_axis_uses_the_entry_half_life(self):
        low = sp.build(entry(importance=0.0), now=NOW)
        high = sp.build(entry(importance=1.0), now=NOW)
        self.assertAlmostEqual(low["time"]["half_life_minutes"], 90.0)
        self.assertAlmostEqual(high["time"]["half_life_minutes"], 270.0)
        near = sp.build(entry(ts=NOW), now=NOW)
        far = sp.build(entry(ts=NOW + 3 * 3600), now=NOW)
        self.assertAlmostEqual(sp.distance(near, far)["time"], 1.0)

    def test_build_is_deterministic(self):
        first = sp.build(entry(), {"trust": 0.6, "closeness": 0.7}, now=NOW)
        second = sp.build(entry(), {"trust": 0.6, "closeness": 0.7}, now=NOW)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_a_broken_entry_never_raises(self):
        self.assertIsNone(sp.build(None))
        self.assertIsNone(sp.build("nope"))
        broken = sp.build({"text": "x", "vector": "not-a-vector",
                           "importance": "many"})
        self.assertIsInstance(broken, dict)
        self.assertEqual(broken["semantic"]["vector"], [])


class PipelineSpaceTest(unittest.TestCase):
    """Write path, the switch, the probe action and recall staying untouched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self.store.mkdir(parents=True, exist_ok=True)
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")
        self._saved = {key: os.environ.pop(key, None)
                       for key in ("BIOCORE_SPATIAL_RECALL",)}

    def tearDown(self):
        self.tmp.cleanup()
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def switch(self, on):
        (self.store / "flags.json").write_text(
            json.dumps({"spatial_recall": bool(on)}), encoding="utf-8")

    def remember(self, text, session="s1", **extra):
        args = {"text": text, "ts": NOW}
        args.update(extra)
        return pl.tool_call("remember", args, str(self.store), session_id=session)

    def stored(self, session="s1"):
        path = self.store / "sessions" / session / "memory.json"
        return json.loads(path.read_text(encoding="utf-8"))["entries"]

    def test_off_by_default_writes_nothing(self):
        out = self.remember("我的猫叫团子")
        self.assertTrue(out["ok"])
        self.assertNotIn("space", self.stored()[0])

    def test_on_writes_all_five_axes(self):
        self.switch(True)
        self.remember("我的猫叫团子", tags=["猫"])
        space = self.stored()[0]["space"]
        for axis in sp.AXES:
            self.assertIn(axis, space)
        self.assertEqual(space["social"]["scope"], "default")

    def test_the_same_memory_twice_keeps_identical_coordinates(self):
        self.switch(True)
        first = self.remember("我的猫叫团子", tags=["猫"])
        before = self.stored()[0]["space"]
        second = self.remember("我的猫叫团子", tags=["猫"])
        self.assertTrue(second.get("deduped"))
        after = self.stored()[0]["space"]
        self.assertEqual(json.dumps(before, sort_keys=True),
                         json.dumps(after, sort_keys=True))
        self.assertEqual(self.stored()[0]["hits"], 2)
        self.assertEqual(first["entry"]["id"], second["entry"]["id"])

    def test_probe_by_id_returns_the_five_axes(self):
        self.switch(True)
        self.remember("我的猫叫团子", tags=["猫"])
        target = self.stored()[0]["id"]
        out = pl.dispatch("space", {"session_id": "s1", "store": str(self.store),
                                    "id": target})
        self.assertTrue(out["ok"])
        self.assertEqual(out["probe"]["source"], "entry")
        for axis in sp.AXES:
            self.assertIn(axis, out["probe"]["space"])
        missing = pl.dispatch("space", {"session_id": "s1",
                                        "store": str(self.store), "id": "nope"})
        self.assertFalse(missing["ok"])

    def test_probe_by_query_returns_neighbours_with_per_axis_distances(self):
        self.switch(True)
        self.remember("我的猫叫团子，三岁", tags=["猫", "宠物"])
        self.remember("今天加班到很晚", tags=["工作"])
        self.remember("周末想去看海", tags=["旅行"])
        out = pl.dispatch("space", {"session_id": "s1", "store": str(self.store),
                                    "query": "团子", "limit": 2, "now": NOW + 60})
        self.assertTrue(out["ok"])
        results = out["probe"]["results"]
        self.assertLessEqual(len(results), 2)
        self.assertIn("猫", results[0]["text"])
        for row in results:
            self.assertEqual(sorted(row["distance"]),
                             ["activation", "affect", "semantic", "social",
                              "time"])
        keys = [sp.order_key(row["distance"]) for row in results]
        self.assertEqual(keys, sorted(keys))

    def test_recall_is_untouched_by_the_switch(self):
        texts = ["我的猫叫团子", "今天加班到很晚", "周末想去看海"]
        for text in texts:
            self.remember(text, session="off")
        for text in texts:
            self.remember(text, session="on")
        self.switch(False)
        quiet = pl.tool_call("recall", {"query": "加班", "limit": 3},
                             str(self.store), session_id="off")
        self.switch(True)
        loud = pl.tool_call("recall", {"query": "加班", "limit": 3},
                            str(self.store), session_id="on")
        self.assertEqual([row["id"] for row in quiet["results"]],
                         [row["id"] for row in loud["results"]])
        self.assertEqual([row["score"] for row in quiet["results"]],
                         [row["score"] for row in loud["results"]])
