# -*- coding: utf-8 -*-
"""segment_recall: the retrieval unit is the event, not the entry.

Grouping reuses event_id (a missing one is a solo segment). A segment scores
by its best member and breaks ties by its newest anchor; the budget is counted
in lines and a segment is kept or dropped whole. The injected block keeps the
[YYYY-MM-DD HH:MM] prefix and orders members by time inside the segment.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.recall import segments  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402


def ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi).timestamp()


def entry(entry_id, text, stamp, event_id="", index=0):
    row = {"id": entry_id, "text": text, "role": "user", "ts": stamp,
           "scope": "default", "event_index": index}
    if event_id:
        row["event_id"] = event_id
    return row


def store_with(rows, flags=None):
    root = tempfile.mkdtemp()
    if flags:
        Path(root, "flags.json").write_text(json.dumps(flags), encoding="utf-8")
    path = Path(root) / "sessions" / "s1" / "memory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"entries": rows}), encoding="utf-8")
    return root


def block(root, query="", top_k=5, mode="recent", segment=True):
    return pipeline.inject_block("s1", root, max_chars=600, top_k=top_k,
                                 query=query, mode=mode,
                                 payload={"segment_recall": segment})


class GroupTest(unittest.TestCase):
    """Segments come from event_id; a missing id is a solo segment."""

    def test_entries_with_the_same_event_are_one_segment(self):
        rows = [entry("a", "\u5f20\u4e09\u7ea6\u5468\u4e94", ts(2026, 3, 5, 9, 0), "E1", 0),
                entry("b", "\u5468\u4e94\u665a\u4e0a\u4e03\u70b9", ts(2026, 3, 5, 9, 1), "E1", 1),
                entry("c", "\u5c0f\u674e\u4e0d\u53bb", ts(2026, 3, 5, 9, 2), "E1", 2),
                entry("d", "\u5929\u6c14\u4e0d\u9519", ts(2026, 3, 5, 10, 0), "E2", 0)]
        grouped = segments.group(rows)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(sorted(len(row["members"]) for row in grouped), [1, 3])

    def test_entries_without_event_id_are_solo_segments(self):
        rows = [entry("a", "\u4e00", ts(2026, 3, 5, 9, 0)),
                entry("b", "\u4e8c", ts(2026, 3, 5, 9, 1))]
        grouped = segments.group(rows)
        self.assertEqual(len(grouped), 2)
        self.assertEqual([row["key"] for row in grouped], ["solo:a", "solo:b"])

    def test_the_segment_score_is_its_best_member(self):
        rows = [entry("a", "a", 1.0, "E1"), entry("b", "b", 2.0, "E1"),
                entry("c", "c", 3.0, "E1")]
        grouped = segments.group(rows)
        marks = {"a": 0.1, "b": 0.8, "c": 0.3}
        ranked = segments.rank(grouped, lambda row: marks[row["id"]])
        self.assertAlmostEqual(ranked[0]["score"], 0.8)

    def test_rank_uses_the_newest_member_as_the_anchor(self):
        rows = [entry("a", "a", ts(2026, 3, 1, 9, 0), "E1"),
                entry("b", "b", ts(2026, 3, 2, 9, 0), "E2")]
        grouped = segments.group(rows)
        ranked = segments.rank(grouped, lambda row: 0.5)
        self.assertEqual(ranked[0]["segment"]["event_id"], "E2")


class InjectTest(unittest.TestCase):
    """The block: whole segments, best-first, time inside."""

    def rows(self):
        return [entry("a", "\u5f20\u4e09\u7ea6\u5468\u4e94\u770b\u7535\u5f71", ts(2026, 3, 5, 9, 0), "E1", 0),
                entry("b", "\u5f20\u4e09\u8bf4\u8981\u4e70\u4e24\u5f20\u7968", ts(2026, 3, 5, 9, 1), "E1", 1),
                entry("c", "\u5c0f\u674e\u8bf4\u660e\u5929\u4e0b\u96e8", ts(2026, 3, 4, 8, 0), "E2", 0)]

    def test_members_are_injected_in_time_order(self):
        rows = [entry("b", "\u7b2c\u4e8c\u53e5", ts(2026, 3, 5, 9, 5), "E1", 1),
                entry("a", "\u7b2c\u4e00\u53e5", ts(2026, 3, 5, 9, 0), "E1", 0)]
        out = block(store_with(rows))
        self.assertLess(out["text"].index("\u7b2c\u4e00\u53e5"),
                        out["text"].index("\u7b2c\u4e8c\u53e5"))

    def test_the_date_prefix_survives_in_segment_mode(self):
        out = block(store_with(self.rows()))
        self.assertIn("[2026-03-05 09:00]", out["text"])
        self.assertIn("[2026-03-04 08:00]", out["text"])

    def test_a_segment_is_kept_whole_within_the_budget(self):
        out = block(store_with(self.rows()), top_k=3)
        self.assertEqual(out["segment"]["segments"], 2)
        self.assertEqual(out["segment"]["lines"], 3)
        self.assertEqual(out["segment"]["dropped_segments"], 0)
        self.assertIn("\u5f20\u4e09\u7ea6\u5468\u4e94\u770b\u7535\u5f71", out["text"])
        self.assertIn("\u5f20\u4e09\u8bf4\u8981\u4e70\u4e24\u5f20\u7968", out["text"])

    def test_an_over_budget_segment_is_dropped_whole(self):
        rows = self.rows() + [entry("d", "\u7b2c\u56db\u6761", ts(2026, 3, 3, 8, 0), "E3"),
                              entry("e", "\u7b2c\u4e94\u6761", ts(2026, 3, 3, 8, 1), "E4")]
        out = block(store_with(rows), top_k=3)
        self.assertEqual(out["segment"]["lines"], 3)
        self.assertGreaterEqual(out["segment"]["dropped_segments"], 1)
        self.assertNotIn("\u7b2c\u4e94\u6761", out["text"])
        self.assertNotIn("\u7b2c\u56db\u6761", out["text"])

    def test_the_switch_off_is_the_old_per_entry_path(self):
        rows = self.rows()
        off = block(store_with(rows), segment=False)
        on = block(store_with(rows))
        self.assertNotIn("segment", off)
        self.assertEqual(len(off["ids"]), 3)
        self.assertEqual(off["text"].count("\n- "), 3)
        self.assertIn("segment", on)

    def test_a_solo_entry_is_a_one_line_segment(self):
        rows = [entry("a", "\u4e00\u53e5\u6ca1\u6709\u4e8b\u4ef6\u7684\u8bdd", ts(2026, 3, 5, 9, 0))]
        out = block(store_with(rows))
        self.assertEqual(out["segment"]["segments"], 1)
        self.assertEqual(out["segment"]["avg_len"], 1.0)

    def test_the_budget_counts_lines_not_entries(self):
        rows = [entry("a", "\u4e00", ts(2026, 3, 5, 9, 0), "E1", 0),
                entry("b", "\u4e8c", ts(2026, 3, 5, 9, 1), "E1", 1),
                entry("c", "\u4e09", ts(2026, 3, 5, 9, 2), "E1", 2)]
        out = block(store_with(rows), top_k=2)
        self.assertEqual(out["segment"]["segments"], 0)
        self.assertEqual(out["segment"]["lines"], 0)
        self.assertEqual(out["segment"]["dropped_segments"], 1)
        self.assertEqual(out["text"], "")


class StateTest(unittest.TestCase):
    """The /state counters of the last segment recall."""

    def test_state_reports_segments_lines_and_avg_len(self):
        root = store_with([entry("a", "\u5f20\u4e09", ts(2026, 3, 5, 9, 0), "E1", 0),
                           entry("b", "\u5c0f\u674e", ts(2026, 3, 5, 9, 1), "E1", 1)],
                          {"segment_recall": True})
        block(root)
        state = pipeline.dispatch("state", {"session_id": "s1", "store": root})
        info = state["state"]["segment_recall"]
        self.assertEqual(info["segments"], 1)
        self.assertEqual(info["lines"], 2)
        self.assertEqual(info["dropped_segments"], 0)
        self.assertEqual(info["avg_len"], 2.0)


if __name__ == "__main__":
    unittest.main()
