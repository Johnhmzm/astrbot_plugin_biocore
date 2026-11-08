# -*- coding: utf-8 -*-
"""S1: the affect axis belongs to the entry (Bower 1981; McGaugh 2004).

An entry carries its own (v, a). Only when it does not may a caller pass the
session state that stood AT THE ENTRY TS; the state as it stands now must
never be substituted for a historical entry. With neither, the axis is
neutral and flagged fallback=True.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory import space as sp  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400.0


def entry(entry_id, ts, affect=None, **extra):
    row = {"id": entry_id, "text": "\u8bb0\u5fc6 " + entry_id, "role": "user",
           "ts": ts, "tags": [], "importance": 0.5, "hits": 1,
           "scope": "default"}
    if affect is not None:
        row["affect"] = dict(affect)
    row.update(extra)
    return row


class PerEntryAffectTest(unittest.TestCase):
    """Which affect reaches the axis."""

    def test_the_entry_affect_wins(self):
        coords = sp.build(entry("a", NOW, {"v": 0.7, "a": 0.2}),
                          now=NOW, affect={"v": -0.9, "a": 0.9})
        self.assertEqual(coords["affect"]["v"], 0.7)
        self.assertEqual(coords["affect"]["a"], 0.2)
        self.assertFalse(coords["affect"]["fallback"])

    def test_valence_arousal_aliases_are_read(self):
        coords = sp.build(entry("a", NOW, {"valence": -0.4, "arousal": 0.8}),
                          now=NOW)
        self.assertAlmostEqual(coords["affect"]["v"], -0.4, places=6)
        self.assertAlmostEqual(coords["affect"]["a"], 0.8, places=6)
        self.assertFalse(coords["affect"]["fallback"])

    def test_the_state_at_ts_is_used_when_the_entry_has_none(self):
        coords = sp.build(entry("a", NOW), now=NOW,
                          affect={"v": 0.3, "a": 0.9})
        self.assertAlmostEqual(coords["affect"]["v"], 0.3, places=6)
        self.assertAlmostEqual(coords["affect"]["a"], 0.9, places=6)
        self.assertFalse(coords["affect"]["fallback"])

    def test_no_affect_anywhere_is_flagged(self):
        coords = sp.build(entry("a", NOW), now=NOW)
        self.assertEqual(coords["affect"]["v"], 0.0)
        self.assertEqual(coords["affect"]["a"], 0.5)
        self.assertTrue(coords["affect"]["fallback"])

    def test_the_state_at_ts_never_looks_past_the_entry(self):
        series = [{"ts": NOW - 10 * DAY, "v": 0.9, "a": 0.1},
                  {"ts": NOW + DAY, "v": -0.9, "a": 0.9}]
        self.assertIsNone(sp.affect_at(series, NOW - 20 * DAY))
        self.assertEqual(sp.affect_at(series, NOW - 5 * DAY),
                         {"v": 0.9, "a": 0.1})


class StoreVarianceTest(unittest.TestCase):
    """Real per-entry affects give the axis variance; ranking does not forge it."""

    def rows(self):
        return [entry("e%d" % index, NOW - index * DAY,
                      {"v": -1.0 + index * 0.2, "a": 0.1 + index * 0.1})
                for index in range(10)]

    def test_the_affect_axis_has_variance(self):
        values = [sp.build(item, now=NOW)["affect"]["v"]
                  for item in self.rows()]
        self.assertGreater(max(values) - min(values), 0.5)

    def test_ranking_never_writes_the_current_affect_into_an_entry(self):
        rows = self.rows()
        engine = MemoryEngine(store=MemoryStore(doc={"entries": rows}),
                              affect={"v": 0.95, "a": 0.95}, now=lambda: NOW)
        engine.spatial_rank("\u8bb0\u5fc6", query_ts=NOW, limit=3)
        for row in rows:
            # a read never stamps the engine affect onto a stored entry
            self.assertNotIn("space", row)
            self.assertNotEqual(row["affect"]["v"], 0.95)

    def test_a_missing_entry_affect_stays_flagged(self):
        coords = sp.build(entry("e0", NOW), now=NOW)
        self.assertTrue(coords["affect"]["fallback"])
        self.assertEqual(coords["affect"]["v"], 0.0)


class HostAffectTest(unittest.TestCase):
    """A turn writes the affect it has; the coordinates agree with the entry."""

    def test_turn_affect_reaches_the_coordinates(self):
        with tempfile.TemporaryDirectory() as store:
            (Path(store) / "flags.json").write_text(
                json.dumps({"spatial_recall": True}), encoding="utf-8")
            with mock.patch("biocore_runtime.pipeline.time.time",
                            return_value=NOW):
                out = pipeline.dispatch("turn_start", {
                    "session_id": "s1",
                    "user_text": "\u6211\u4eca\u5929\u7279\u522b\u5f00\u5fc3\u5440\uff0c\u54c8\u54c8",
                    "store": store,
                    "state": {"core": {"v": 0.6, "a": 0.7}},
                    "now": NOW})
                reported = (out.get("state") or {}).get("core") or {}
                rows = pipeline.export_session_json(store, "s1")["entries"]
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertAlmostEqual(row["affect"]["v"], reported["v"], places=6)
                self.assertAlmostEqual(row["affect"]["a"], reported["a"], places=6)
                self.assertEqual(row["space"]["affect"]["v"],
                                 round(row["affect"]["v"], 6))
                self.assertFalse(row["space"]["affect"]["fallback"])


if __name__ == "__main__":
    unittest.main()
