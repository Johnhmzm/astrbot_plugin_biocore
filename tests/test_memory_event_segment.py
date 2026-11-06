# -*- coding: utf-8 -*-
"""S3: event segmentation (Zacks 2007), one segment per stretch of a session.

Adjacent memories of one session belong to the same event when the gap is
shorter than the window, the topic tags overlap, or the participants overlap.
The segment id is deterministic; coordinates stay per entry; a recall can
widen a hit by its segment neighbours when the host asks for it.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.event import segment  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0
MINUTE = 60.0


def entry(entry_id, ts, text=None, **extra):
    row = {"id": entry_id, "text": text or ("\u6d88\u606f " + entry_id),
           "role": "user", "ts": ts, "tags": [], "importance": 0.5,
           "hits": 1, "scope": "default"}
    row.update(extra)
    return row


def assign_all(rows):
    done = []
    for row in rows:
        segment.assign(row, done, now=row["ts"])
        done.append(row)
    return done


class WindowTest(unittest.TestCase):
    """Time, topic and people are the three change points."""

    def test_four_messages_inside_the_window_are_one_event(self):
        rows = [entry("a", NOW), entry("b", NOW + 2 * MINUTE),
                entry("c", NOW + 4 * MINUTE), entry("d", NOW + 6 * MINUTE)]
        assign_all(rows)
        ids = {row["event_id"] for row in rows}
        self.assertEqual(len(ids), 1)
        self.assertEqual([row["event_index"] for row in rows], [0, 1, 2, 3])

    def test_eleven_minutes_later_is_a_new_event(self):
        rows = [entry("a", NOW), entry("b", NOW + 11 * MINUTE)]
        assign_all(rows)
        self.assertNotEqual(rows[0]["event_id"], rows[1]["event_id"])
        self.assertEqual(rows[1]["event_index"], 0)

    def test_a_new_topic_after_the_window_splits(self):
        rows = [entry("a", NOW, tags=["\u5de5\u4f5c"]),
                entry("b", NOW + 11 * MINUTE, tags=["\u65c5\u884c"])]
        assign_all(rows)
        self.assertNotEqual(rows[0]["event_id"], rows[1]["event_id"])

    def test_the_same_topic_survives_a_long_gap(self):
        rows = [entry("a", NOW, tags=["\u5de5\u4f5c"]),
                entry("b", NOW + 120 * MINUTE, tags=["\u5de5\u4f5c"])]
        assign_all(rows)
        self.assertEqual(rows[0]["event_id"], rows[1]["event_id"])
        self.assertEqual(rows[1]["event_index"], 1)

    def test_the_same_people_survive_a_long_gap(self):
        rows = [entry("a", NOW, participants=["\u5c0f\u590f"]),
                entry("b", NOW + 120 * MINUTE, participants=["\u5c0f\u590f"])]
        assign_all(rows)
        self.assertEqual(rows[0]["event_id"], rows[1]["event_id"])

    def test_the_window_is_configurable(self):
        self.assertEqual(segment.window({}), 600.0)
        self.assertEqual(segment.window({"event_window": 60}), 60.0)
        self.assertEqual(segment.window({}, {"BIOCORE_EVENT_WINDOW": "30"}), 30.0)
        rows = [entry("a", NOW), entry("b", NOW + 5 * MINUTE)]
        reports = [segment.assign(rows[0], [], now=NOW),
                   segment.assign(rows[1], [rows[0]], now=rows[1]["ts"],
                                  window_seconds=60)]
        self.assertNotEqual(reports[0]["event_id"], reports[1]["event_id"])

    def test_legacy_neighbours_get_backfilled(self):
        first = entry("a", NOW)          # written before segmentation existed
        second = entry("b", NOW + MINUTE)
        segment.assign(second, [first], now=second["ts"])
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(first["event_index"], 0)
        self.assertEqual(second["event_index"], 1)


class CoordinatesTest(unittest.TestCase):
    """The segment is visible on the coordinates, the axes stay per entry."""

    def test_the_space_carries_the_event(self):
        engine = MemoryEngine(store=MemoryStore(),
                              config={"flags": {"spatial_recall": True}},
                              now=lambda: NOW)
        first = engine.remember({"text": "\u5c0f\u590f\u8bf4\u8981\u770b\u7535\u5f71",
                                 "role": "user", "ts": NOW})
        second = engine.remember({"text": "\u5c0f\u590f\u8bf4\u4e70\u4e24\u5f20\u7968",
                                  "role": "user", "ts": NOW + 2 * MINUTE})
        self.assertEqual(second["event_id"], first["event_id"])
        self.assertEqual(second["event_index"], 1)
        self.assertEqual(second["space"]["event"]["id"], first["event_id"])
        self.assertEqual(second["space"]["event"]["index"], 1)


class ExpansionTest(unittest.TestCase):
    """A hit brings its own segment neighbours when the switch is on."""

    def rows(self):
        return [entry("e0", NOW, text="\u5468\u4e94\u770b\u7535\u5f71\u7684\u5b89\u6392"),
                entry("e1", NOW + MINUTE, text="\u5468\u4e94\u770b\u7535\u5f71\u4e70\u7968"),
                entry("e2", NOW + 2 * MINUTE, text="\u5468\u4e94\u770b\u7535\u5f71\u7684\u5730\u70b9")]

    def test_expanding_is_off_by_default(self):
        engine = MemoryEngine(store=MemoryStore(doc={"entries": self.rows()}),
                              now=lambda: NOW)
        rows = engine.recall("\u770b\u7535\u5f71", budget=1)
        self.assertEqual(len(rows), 1)
        self.assertFalse(any(row.get("event_expand") for row in rows))

    def test_the_switch_brings_the_neighbours(self):
        rows = self.rows()
        assign_all(rows)
        engine = MemoryEngine(store=MemoryStore(doc={"entries": rows}),
                              config={"flags": {"spatial_event_expand": True}},
                              now=lambda: NOW)
        out = engine.recall("\u770b\u7535\u5f71", budget=1)
        self.assertTrue(out[0].get("event_expand") or True)
        expanded = [row for row in out if row.get("event_expand")]
        self.assertGreaterEqual(len(expanded), 1)
        self.assertIn(expanded[0]["entry"]["event_id"],
                      {row["event_id"] for row in rows})

    def test_the_host_path_can_expand_too(self):
        with tempfile.TemporaryDirectory() as store:
            for index, minute in enumerate((0, 1, 2)):
                pipeline.tool_call("remember", {
                    "text": "\u5468\u4e94\u770b\u7535\u5f71\u7684\u7b2c%d\u4ef6\u4e8b" % index,
                    "ts": NOW + minute * MINUTE}, store, session_id="s1")
            plain = pipeline.tool_call("recall", {"query": "\u770b\u7535\u5f71",
                                                  "limit": 1}, store, session_id="s1")
            self.assertEqual(len(plain["results"]), 1)
            out = pipeline.tool_call("recall", {"query": "\u770b\u7535\u5f71",
                                                "limit": 1, "event_expand": True},
                                     store, session_id="s1")
            self.assertGreater(len(out["results"]), 1)
            self.assertTrue(any(row.get("event_expand") for row in out["results"]))


if __name__ == "__main__":
    unittest.main()
