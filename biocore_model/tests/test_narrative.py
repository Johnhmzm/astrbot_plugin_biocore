# -*- coding: utf-8 -*-
"""Narrative: chapters plus the three coherence metrics."""
import unittest

from biocore_model import narrative as nv

DAY = 86400.0
BASE = 1790000000.0


def ev(kind, text, valence, day=0.0, importance=0.6):
    return {"kind": kind, "text": text, "valence": valence,
            "ts": BASE + day * DAY, "importance": importance}


class EntriesTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(nv.entries([]), [])

    def test_theme_mapping(self):
        rows = nv.entries([ev("rupture", "吵了一架", -0.6)])
        self.assertEqual(rows[0]["theme"], "关系裂缝")

    def test_unknown_kind_falls_back(self):
        rows = nv.entries([ev("weird", "小事", 0.1)])
        self.assertEqual(rows[0]["theme"], nv.DEFAULT_THEME)

    def test_limit_and_newest_first(self):
        events = [ev("gift", "第%d次" % i, 0.4, day=i) for i in range(10)]
        rows = nv.entries(events, limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["ts"], BASE + 9 * DAY)

    def test_dedupes_same_text(self):
        events = [ev("gift", "同一句话", 0.4, day=0),
                  ev("gift", "同一句话", 0.4, day=1)]
        self.assertEqual(len(nv.entries(events)), 1)

    def test_malformed_skipped(self):
        rows = nv.entries([None, "x", {"text": ""}, ev("gift", "好", 0.3)])
        self.assertEqual(len(rows), 1)


class ConsistencyTest(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(nv.consistency([]), 0.0)

    def test_all_positive(self):
        events = [ev("gift", "a", 0.5), ev("gift", "b", 0.3)]
        self.assertEqual(nv.consistency(events), 1.0)

    def test_mixed_lowers(self):
        events = [ev("gift", "a", 0.5), ev("gift", "b", -0.5)]
        self.assertLess(nv.consistency(events), 1.0)


class ContradictionTest(unittest.TestCase):
    def test_none_when_same_sign(self):
        events = [ev("rupture", "a", -0.5), ev("rupture", "b", -0.2)]
        self.assertEqual(nv.contradiction(events), 0.0)

    def test_detects_opposites(self):
        events = [ev("rupture", "a", -0.5), ev("rupture", "b", 0.4)]
        self.assertEqual(nv.contradiction(events), 1.0)


class RepairTest(unittest.TestCase):
    def test_none_without_negative(self):
        self.assertEqual(nv.repair([ev("gift", "a", 0.5)]), 0.0)

    def test_repair_within_window(self):
        events = [ev("rupture", "吵", -0.6, day=0),
                  ev("repair", "和好", 0.5, day=2)]
        self.assertEqual(nv.repair(events), 1.0)

    def test_no_repair_outside_window(self):
        events = [ev("rupture", "吵", -0.6, day=0),
                  ev("repair", "和好", 0.5, day=30)]
        self.assertEqual(nv.repair(events), 0.0)

    def test_repair_needs_same_theme(self):
        events = [ev("rupture", "吵", -0.6, day=0),
                  ev("gift", "收到礼物", 0.5, day=1)]
        self.assertEqual(nv.repair(events), 0.0)


class SummaryTest(unittest.TestCase):
    def test_summary_shape(self):
        events = [ev("rupture", "吵", -0.6, day=0), ev("repair", "和好", 0.5, day=1)]
        out = nv.summarize(events)
        self.assertEqual(out["events"], 2)
        self.assertIn("consistency", out["metrics"])
        self.assertIn("contradiction", out["metrics"])
        self.assertIn("repair", out["metrics"])
        self.assertTrue(out["entries"])

    def test_disabled(self):
        out = nv.summarize([ev("gift", "a", 0.5)], flags={"enabled": False})
        self.assertEqual(out["entries"], [])
        self.assertEqual(out["metrics"]["consistency"], 0.0)


class DirectiveTest(unittest.TestCase):
    def test_contradiction_invites_clarify(self):
        out = nv.directives({"enabled": True, "metrics": {"contradiction": 0.9}})
        self.assertTrue(out["allow_clarify"])

    def test_clean_story_no_prompt(self):
        out = nv.directives({"enabled": True, "metrics": {"contradiction": 0.0}})
        self.assertFalse(out["allow_clarify"])


if __name__ == "__main__":
    unittest.main()
