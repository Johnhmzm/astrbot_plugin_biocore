# -*- coding: utf-8 -*-
"""Reconsolidation: a recall hit rewrites its own coordinates (Nader 2000).

The five axes are re-sampled with the relationship and affect that are current
at recall time, then stamped: version+1, refreshed_at, and drift -- the
per-axis distance the coordinates moved. The switch spatial_reconsolidate is
OFF by default: with it off a recall never mutates the store.
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
TEXT = "今天拿到奖学金了"


def make_engine(flags=None, affect=None, relationship=None, now=NOW):
    config = {"flags": dict(flags or {})}
    if isinstance(relationship, dict):
        config["relationship"] = dict(relationship)
    return MemoryEngine(affect=dict(affect) if isinstance(affect, dict) else affect,
                        config=config, now=lambda: now)


class RefreshTest(unittest.TestCase):
    """A hit rewrites: version, refreshed_at and drift."""

    def test_a_hit_bumps_the_version_and_stamps_the_time(self):
        engine = make_engine({"spatial_recall": True},
                             affect={"v": 0.6, "a": 0.5})
        entry = engine.remember({"text": TEXT, "role": "user", "ts": NOW - DAY})
        self.assertEqual(entry["space"]["version"], 1)
        self.assertEqual(entry["space"]["refreshed_at"], 0.0)
        rows = engine.recall("奖学金", budget=1, reconsolidate=True)
        fresh = rows[0]["entry"]["space"]
        self.assertEqual(fresh["version"], 2)
        self.assertEqual(fresh["refreshed_at"], round(NOW, 3))
        self.assertEqual(set(fresh["drift"]),
                         set(sp.AXES) | {"weighted"})

    def test_drift_records_how_far_the_affect_moved(self):
        engine = make_engine({"spatial_recall": True},
                             affect={"v": 0.8, "a": 0.5})
        engine.remember({"text": TEXT, "role": "user", "ts": NOW - DAY})
        engine.affect = {"v": -0.8, "a": 0.5}      # the feeling flipped
        fresh = engine.recall("奖学金", budget=1,
                              reconsolidate=True)[0]["entry"]["space"]
        self.assertAlmostEqual(fresh["affect"]["v"], -0.8, places=6)
        self.assertGreater(fresh["drift"]["affect"], 0.5)
        self.assertGreater(fresh["drift"]["weighted"], 0.0)
        self.assertEqual(fresh["drift"]["semantic"], 0.0)
        self.assertEqual(fresh["drift"]["time"], 0.0)

    def test_the_switch_drives_the_same_refresh(self):
        engine = make_engine({"spatial_recall": True,
                              "spatial_reconsolidate": True},
                             affect={"v": 0.8, "a": 0.5})
        engine.remember({"text": TEXT, "role": "user", "ts": NOW - DAY})
        engine.affect = {"v": -0.8, "a": 0.5}
        engine.recall("奖学金", budget=1)
        report = engine._last_space_refresh
        self.assertIsNotNone(report)
        self.assertEqual(report["refreshed"], 1)
        self.assertGreater(report["drift"], 0.0)

    def test_off_by_default_never_mutates(self):
        engine = make_engine({"spatial_recall": True},
                             affect={"v": 0.8, "a": 0.5})
        entry = engine.remember({"text": TEXT, "role": "user", "ts": NOW - DAY})
        engine.affect = {"v": -0.8, "a": 0.5}
        rows = engine.recall("奖学金", budget=1)
        self.assertEqual(rows[0]["entry"]["space"]["version"], 1)
        self.assertEqual(rows[0]["entry"]["space"]["refreshed_at"], 0.0)
        self.assertIsNone(engine._last_space_refresh)

    def test_only_the_returned_rows_are_rewritten(self):
        engine = make_engine({"spatial_recall": True,
                              "spatial_reconsolidate": True})
        engine.remember({"text": TEXT, "role": "user", "ts": NOW - 2 * DAY})
        other = engine.remember({"text": "明天要早起开会", "role": "user",
                                 "ts": NOW - DAY})
        rows = engine.recall("奖学金", budget=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry"]["space"]["version"], 2)
        self.assertEqual(other["space"]["version"], 1)
        self.assertEqual(engine._last_space_refresh["ids"],
                         [rows[0]["entry"]["id"]])

    def test_relationship_change_moves_the_social_axis(self):
        engine = make_engine({"spatial_recall": True},
                             relationship={"trust": 0.2, "closeness": 0.2})
        engine.remember({"text": TEXT, "role": "user", "ts": NOW - DAY})
        engine.config["relationship"] = {"trust": 0.9, "closeness": 0.9}
        fresh = engine.recall("奖学金", budget=1,
                              reconsolidate=True)[0]["entry"]["space"]
        self.assertAlmostEqual(fresh["social"]["trust"], 0.9, places=6)
        self.assertGreater(fresh["drift"]["social"], 0.1)

    def test_a_hit_can_create_missing_coordinates(self):
        engine = make_engine({})          # nothing written at recall-entry time
        entry = engine.remember({"text": TEXT, "role": "user", "ts": NOW - DAY})
        self.assertNotIn("space", entry)
        fresh = engine.recall("奖学金", budget=1,
                              reconsolidate=True)[0]["entry"]["space"]
        self.assertEqual(fresh["version"], 1)
        self.assertEqual(fresh["refreshed_at"], round(NOW, 3))
        self.assertEqual(fresh["drift"], sp.zero_drift())


class MergeTest(unittest.TestCase):
    """A merge keeps the snapshot written last and records merged_from."""

    def test_merge_keeps_the_refreshed_coordinates(self):
        engine = make_engine({"spatial_recall": True,
                              "spatial_reconsolidate": True,
                              "dedupe": True})
        first = engine.remember({"text": "会议改到周四", "role": "user",
                                 "ts": NOW - 2 * DAY,
                                 "event_key": "meeting"})
        engine.recall("会议", budget=1)          # reconsolidate: version 2
        kept = first["space"]
        self.assertEqual(kept["version"], 2)
        second = engine.remember({"text": "会议改到周四下午三点", "role": "user",
                                  "ts": NOW, "event_key": "meeting"})
        merged = engine.store.find(first["id"])
        self.assertIsNotNone(merged)
        self.assertIsNone(engine.store.find(second["id"]))
        self.assertEqual(merged["space"]["version"], 2)
        self.assertEqual(merged["space"]["refreshed_at"], kept["refreshed_at"])
        self.assertEqual(merged["space"]["merged_from"], [second["id"]])

    def test_merge_without_coordinates_adds_none(self):
        engine = make_engine({"dedupe": True})
        first = engine.remember({"text": "会议改到周四", "role": "user",
                                 "ts": NOW - 2 * DAY, "event_key": "meeting"})
        engine.remember({"text": "会议改到周四下午三点", "role": "user",
                         "ts": NOW, "event_key": "meeting"})
        merged = engine.store.find(first["id"])
        self.assertNotIn("space", merged)


class SurvivalTest(unittest.TestCase):
    """Consolidation and eviction never strip coordinates."""

    def test_consolidation_marks_and_keeps_the_source_coordinates(self):
        engine = make_engine({"spatial_recall": True})
        entry = engine.remember({"text": TEXT, "role": "user", "ts": NOW - DAY})
        summary = engine._consolidate_summary(
            {"reflections": [{"text": "整理一下奖学金这件事"}]},
            [entry["id"]], NOW)
        self.assertIsNotNone(summary)
        self.assertIn("space", entry)
        self.assertEqual(entry["space"]["version"], 1)
        self.assertIn("space", summary)          # the summary is its own memory
        self.assertEqual(summary["space"]["refreshed_at"], 0.0)

    def test_eviction_keeps_the_coordinates(self):
        engine = make_engine({"spatial_recall": True, "apply_evictions": True})
        entry = engine.remember({"text": "很久以前的一件小事", "role": "user",
                                 "ts": NOW - 500 * DAY})
        entry["importance"] = 0.05
        report = engine.tick(now=NOW, apply_evictions=True)
        deleted = (report.get("apply_evictions") or {}).get("deleted") or []
        self.assertIn(entry["id"], deleted)
        self.assertTrue(entry.get("deleted"))
        self.assertIn("space", entry)
        self.assertEqual(entry["space"]["version"], 1)


class HostRefreshTest(unittest.TestCase):
    """The biocore_runtime host path reconsolidates and persists the rewrite."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = self._tmp.name
        Path(self.store, "flags.json").write_text(
            json.dumps({"spatial_recall": True,
                        "spatial_reconsolidate": True}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def stored(self, session="s1"):
        path = Path(self.store) / "sessions" / session / "memory.json"
        return json.loads(path.read_text(encoding="utf-8"))["entries"]

    def test_host_recall_rewrites_and_saves(self):
        pipeline.tool_call("remember", {"text": TEXT, "ts": NOW - DAY},
                           self.store, session_id="s1")
        self.assertEqual(self.stored()[0]["space"]["version"], 1)
        out = pipeline.tool_call("recall", {"query": "奖学金", "limit": 1,
                                            "ts": NOW},
                                 self.store, session_id="s1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["space_refresh"]["refreshed"], 1)
        after = self.stored()[0]["space"]
        self.assertEqual(after["version"], 2)
        self.assertEqual(after["refreshed_at"], round(NOW, 3))

    def test_host_recall_without_the_switch_leaves_the_file_alone(self):
        Path(self.store, "flags.json").write_text(
            json.dumps({"spatial_recall": True}), encoding="utf-8")
        pipeline.tool_call("remember", {"text": TEXT, "ts": NOW - DAY},
                           self.store, session_id="s1")
        out = pipeline.tool_call("recall", {"query": "奖学金", "limit": 1},
                                 self.store, session_id="s1")
        self.assertNotIn("space_refresh", out)
        self.assertEqual(self.stored()[0]["space"]["version"], 1)


if __name__ == "__main__":
    unittest.main()
