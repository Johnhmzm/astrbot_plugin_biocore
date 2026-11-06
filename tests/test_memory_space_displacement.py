# -*- coding: utf-8 -*-
"""Displacement between adjacent memories (TransE, Bordes 2013).

Two memories about the same (subject, attribute) are a pair: the later one
carries the displacement h -> t (d_semantic / d_time / d_affect). A change of
mind is time running forward while the valence flips sign ("revision"), every
other step is an "update". The displacement also answers the TransE question
-- h + r ~= t -- by ranking the entries nearest to the predicted point.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory import space as sp  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400.0
SUBJECT = "会议"
ATTRIBUTE = "时间"


def make_engine(flags=None, affect=None, now=NOW):
    return MemoryEngine(affect=dict(affect) if isinstance(affect, dict) else affect,
                        config={"flags": dict(flags or {})}, now=lambda: now)


def fact(text, ts, vector=None, **extra):
    event = {"text": text, "role": "user", "ts": ts,
             "subject": SUBJECT, "attribute": ATTRIBUTE}
    if vector is not None:
        event["vector"] = list(vector)
    event.update(extra)
    return event


class DisplacementTest(unittest.TestCase):
    """d_semantic / d_time / d_affect and the revision rule."""

    def test_adjacent_memories_get_a_displacement(self):
        engine = make_engine({"spatial_recall": True})
        first = engine.remember(fact("会议改到周四", NOW - DAY,
                                     vector=[1.0, 0.0]))
        second = engine.remember(fact("会议改到周五", NOW,
                                      vector=[0.0, 1.0]))
        shift = second["space"]["displacement"]
        self.assertEqual(shift["from_id"], first["id"])
        self.assertEqual(shift["d_semantic"], [-1.0, 1.0])
        self.assertAlmostEqual(shift["d_time"], DAY, places=3)
        self.assertEqual(shift["d_affect"], {"v": 0.0, "a": 0.0})
        self.assertEqual(shift["kind"], "update")
        self.assertEqual(shift["ts"], round(NOW, 3))

    def test_a_flipped_valence_is_a_revision(self):
        engine = make_engine({"spatial_recall": True}, affect={"v": 0.6, "a": 0.5})
        engine.remember(fact("会议很顺利", NOW - DAY))
        engine.affect = {"v": -0.5, "a": 0.5}
        second = engine.remember(fact("会议很糟糕", NOW))
        shift = second["space"]["displacement"]
        self.assertEqual(shift["kind"], "revision")
        self.assertAlmostEqual(shift["d_affect"]["v"], -1.1, places=6)

    def test_same_sign_affect_is_only_an_update(self):
        engine = make_engine({"spatial_recall": True}, affect={"v": 0.2, "a": 0.5})
        engine.remember(fact("会议安排了", NOW - DAY))
        engine.affect = {"v": 0.7, "a": 0.5}
        second = engine.remember(fact("会议提前了", NOW))
        self.assertEqual(second["space"]["displacement"]["kind"], "update")

    def test_revision_needs_time_running_forward(self):
        engine = make_engine({"spatial_recall": True}, affect={"v": 0.6, "a": 0.5})
        engine.remember(fact("会议很顺利", NOW - DAY))
        engine.affect = {"v": -0.5, "a": 0.5}
        second = engine.remember(fact("会议很糟糕", NOW - 2 * DAY))
        shift = second["space"]["displacement"]
        self.assertLess(shift["d_time"], 0.0)
        self.assertEqual(shift["kind"], "update")

    def test_no_subject_or_attribute_means_no_displacement(self):
        engine = make_engine({"spatial_recall": True})
        engine.remember({"text": "会议改到周四", "role": "user",
                         "ts": NOW - DAY})
        second = engine.remember({"text": "会议改到周五", "role": "user",
                                  "ts": NOW})
        self.assertNotIn("displacement", second["space"])


class HostDisplacementTest(unittest.TestCase):
    """The biocore_runtime write path records the same displacement."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = self._tmp.name
        Path(self.store, "flags.json").write_text(
            json.dumps({"spatial_recall": True}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def stored(self, session="s1"):
        path = Path(self.store) / "sessions" / session / "memory.json"
        return json.loads(path.read_text(encoding="utf-8"))["entries"]

    def test_host_remember_records_the_displacement(self):
        first = pipeline.tool_call(
            "remember", {"text": "会议改到周四", "ts": NOW - DAY,
                         "subject": SUBJECT, "attribute": ATTRIBUTE},
            self.store, session_id="s1")
        pipeline.tool_call(
            "remember", {"text": "会议改到周五", "ts": NOW,
                         "subject": SUBJECT, "attribute": ATTRIBUTE},
            self.store, session_id="s1")
        rows = self.stored()
        self.assertEqual(len(rows), 2)
        shift = rows[1]["space"]["displacement"]
        self.assertEqual(shift["from_id"], first["entry"]["id"])
        self.assertAlmostEqual(shift["d_time"], DAY, places=3)
        self.assertEqual(shift["kind"], "update")


class SimilarDisplacementTest(unittest.TestCase):
    """h + r ~= t: rank the entries near the point the displacement predicts."""

    def build(self):
        engine = make_engine({"spatial_recall": True})
        engine.remember(fact("会议改到周四", NOW - 3 * DAY,
                             vector=[1.0, 0.0]))
        source = engine.remember(fact("会议改到周五", NOW - 2 * DAY,
                                      vector=[0.8, 0.6]))
        near = engine.remember(fact("周五下午三点开会",
                                    NOW - 2 * DAY + 60, vector=[0.8, 0.6]))
        far = engine.remember({"text": "很久以前的事", "role": "user",
                               "ts": NOW - 200 * DAY, "vector": [-1.0, 0.0]})
        return engine, source, near, far

    def test_the_predicted_point_is_where_the_new_value_lives(self):
        engine, source, near, far = self.build()
        out = engine.displacement_similar(source["id"], limit=2)
        self.assertTrue(out["ok"])
        self.assertEqual(out["from_id"], source["space"]["displacement"]["from_id"])
        self.assertEqual([row["id"] for row in out["results"]],
                         [near["id"], far["id"]])
        self.assertLess(out["results"][0]["weighted"],
                        out["results"][1]["weighted"])

    def test_the_target_is_the_shifted_point(self):
        engine, source, near, far = self.build()
        shift = source["space"]["displacement"]
        anchor = engine.store.find(shift["from_id"])
        target = sp.shift_point(anchor["space"], shift)
        self.assertEqual(target["time"]["ts"], round(source["ts"], 3))
        self.assertEqual(target["semantic"]["vector"], [0.8, 0.6])

    def test_a_memory_without_a_displacement_cannot_be_queried(self):
        engine = make_engine({"spatial_recall": True})
        only = engine.remember({"text": "没有下文", "role": "user", "ts": NOW})
        out = engine.displacement_similar(only["id"])
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "no_displacement")


if __name__ == "__main__":
    unittest.main()
