# -*- coding: utf-8 -*-
"""memory_date_prefix: an injected memory carries its own local date.

The date is rendered from the entry ts in the local time zone and prefixed as
[YYYY-MM-DD HH:MM]. No instruction text is added; an entry without ts gets no
prefix;
switching the flag off restores the old block byte for byte.
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

from biocore_runtime import pipeline  # noqa: E402


def local_ts(year, month, day, hour=12, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second).timestamp()


def store_with(texts, flags=None):
    root = tempfile.mkdtemp()
    if flags:
        Path(root, "flags.json").write_text(json.dumps(flags), encoding="utf-8")
    for text, ts in texts:
        pipeline.tool_call("remember", {"text": text, "ts": ts}, root, "s1")
    return root


def block(root, **kwargs):
    return pipeline.inject_block("s1", root, max_chars=kwargs.pop("max_chars", 420),
                                 top_k=kwargs.pop("top_k", 3), mode="recent",
                                 **kwargs)


class DatePrefixTest(unittest.TestCase):
    """The rendered line."""

    def test_a_memory_with_ts_gets_its_local_date(self):
        ts = local_ts(2026, 3, 5)
        root = store_with([("\u5979\u8bf4\u751f\u65e5\u662f3\u67085\u65e5", ts)])
        out = block(root)
        self.assertIn("[2026-03-05 12:00] \u5979\u8bf4\u751f\u65e5\u662f3\u67085\u65e5",
                      out["text"])

    def test_an_entry_without_ts_gets_no_prefix(self):
        root = tempfile.mkdtemp()
        path = Path(root) / "sessions" / "s1" / "memory.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"entries": [
            {"id": "noTs", "text": "\u6ca1\u6709\u65f6\u95f4\u7684\u4e00\u53e5\u8bdd",
             "role": "user", "scope": "default"}]}), encoding="utf-8")
        out = block(root)
        self.assertIn("- \u6ca1\u6709\u65f6\u95f4\u7684\u4e00\u53e5\u8bdd", out["text"])
        self.assertNotIn("[", out["text"])

    def test_the_date_uses_the_local_zone(self):
        early = block(tempfile.mkdtemp()) if False else None
        start = local_ts(2026, 3, 5, 0, 0, 1)
        end = local_ts(2026, 3, 5, 23, 59, 59)
        root = store_with([("\u4e00\u5929\u7684\u5f00\u5934", start),
                           ("\u4e00\u5929\u7684\u5c3e\u5df4", end)])
        out = block(root)
        self.assertEqual(out["text"].count("[2026-03-05 "), 2)

    def test_two_times_on_the_same_day_are_distinguishable(self):
        root = store_with([("\u4e0a\u5348\u7684\u4f1a", local_ts(2026, 3, 5, 9, 15)),
                           ("\u4e0b\u5348\u7684\u4f1a", local_ts(2026, 3, 5, 14, 32))])
        out = block(root)
        self.assertIn("[2026-03-05 09:15]", out["text"])
        self.assertIn("[2026-03-05 14:32]", out["text"])

    def test_cross_day_times_are_distinguishable(self):
        root = store_with([("\u6628\u665a", local_ts(2026, 3, 5, 23, 59)),
                           ("\u4eca\u65e9", local_ts(2026, 3, 6, 0, 1))])
        out = block(root)
        self.assertIn("[2026-03-05 23:59]", out["text"])
        self.assertIn("[2026-03-06 00:01]", out["text"])

    def test_the_same_minute_keeps_the_write_order(self):
        ts = local_ts(2026, 3, 5, 14, 32, 5)
        # identical stamps: the block must keep the order they were written in
        root = store_with([("\u7b2c\u4e00\u6761", ts), ("\u7b2c\u4e8c\u6761", ts)])
        out = block(root)
        self.assertLess(out["text"].index("\u7b2c\u4e00\u6761"),
                        out["text"].index("\u7b2c\u4e8c\u6761"))
        self.assertEqual(out["text"].count("[2026-03-05 14:32]"), 2)

    def test_switch_off_restores_the_old_format(self):
        texts = [("\u5979\u8bf4\u751f\u65e5\u662f3\u67085\u65e5", local_ts(2026, 3, 5))]
        on = block(store_with(texts))
        off = block(store_with(texts, {"memory_date_prefix": False}))
        self.assertIn("[2026-03-05 12:00]", on["text"])
        self.assertNotIn("[", off["text"])
        self.assertIn("- \u5979\u8bf4\u751f\u65e5\u662f3\u67085\u65e5", off["text"])

    def test_the_prefix_does_not_change_the_order(self):
        texts = [("\u7b2c\u4e00\u6761", local_ts(2026, 3, 1)),
                 ("\u7b2c\u4e8c\u6761", local_ts(2026, 3, 2))]
        on = block(store_with(texts))
        off = block(store_with(texts, {"memory_date_prefix": False}))
        self.assertEqual(on["ids"], off["ids"])

    def test_the_budget_still_holds_when_clipping(self):
        long_text = "\u5f88\u957f\u7684\u4e00\u53e5\u8bdd" * 20
        root = store_with([(long_text, local_ts(2026, 3, 5))])
        out = block(root, max_chars=40)
        self.assertLessEqual(out["chars"], 40)
        self.assertIn("[2026-03-05 12:00]", out["text"])
        self.assertIn("\u2026", out["text"])

    def test_no_instruction_text_is_added(self):
        texts = [("\u5979\u8bf4\u751f\u65e5\u662f3\u67085\u65e5", local_ts(2026, 3, 5))]
        on = block(store_with(texts))
        off = block(store_with(texts, {"memory_date_prefix": False}))
        stripped = on["text"].replace("[2026-03-05 12:00] ", "")
        self.assertEqual(stripped, off["text"])


if __name__ == "__main__":
    unittest.main()
