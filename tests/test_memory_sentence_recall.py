# -*- coding: utf-8 -*-
"""Sentence-level recall: 40 coarse -> 12 reranked -> a block that FOLDS.

Budget decides how much detail is shown, never whether a memory survives: a
sentence is rendered whole, or replaced by its event's one-line note, or folded
into a single reference line whose ids are still recorded.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


def entries(n=20, chars=300):
    rows = []
    for i in range(n):
        rows.append({"id": "s%02d" % i,
                     "text": ("第%d条：" % i) + ("内容" * (chars // 2)),   # ~300 chars
                     "ts": 1777800000 + i * 86400,
                     "event_id": "EV%03d" % i,
                     "vector": [1.0 - i * 0.01, 0.1]})
    return rows


def events(n=20):
    return [{"event_id": "EV%03d" % i, "note": "事件%d的摘要" % i,
             "entries": [{"id": "s%02d" % i, "ts": 1777800000 + i * 86400}]}
            for i in range(n)]


class FoldingTest(unittest.TestCase):
    def _block(self, rows=None, evs=None, budget=None):
        old = P.RECALL_INJECT_CHARS
        if budget is not None:
            P.RECALL_INJECT_CHARS = budget
        try:
            return P._sentence_recall_block(
                "/tmp", "s1", "内容", rows if rows is not None else entries(),
                evs if evs is not None else events(),
                payload={"event_summarizer": lambda p: "[]"})
        finally:
            P.RECALL_INJECT_CHARS = old

    def test_a_block_over_budget_folds_instead_of_cutting(self):
        block = self._block(budget=2000)
        self.assertIsNotNone(block)
        self.assertLessEqual(block["chars"], 2000)          # ④
        self.assertGreater(block["folded"], 0)              # ② something folded
        self.assertIn("已折叠 %d 条" % block["folded"], block["text"])
        # ③ every folded id is still reachable
        self.assertEqual(len(block["folded_ids"]), block["folded"])
        for entry_id in block["folded_ids"]:
            self.assertIn(entry_id, [row["id"] for row in entries()])
        # ① no sentence is truncated: every rendered sentence line is a full text
        for line in block["text"].splitlines():
            if line.startswith("- "):
                body = line[2:].split("（")[0]
                self.assertFalse(body.endswith("…"))
                self.assertIn(body, [row["text"] for row in entries()])

    def test_reference_line_names_the_range_and_the_scores(self):
        block = self._block(budget=2000)
        self.assertRegex(block["text"], r"另有 \d+ 条相关记忆（.*相关度 \d\.\d\d-\d\.\d\d")

    def test_under_budget_renders_full_sentences_only(self):
        block = self._block(budget=100000)
        self.assertEqual(block["folded"], 0)
        self.assertNotIn("已折叠", block["text"])
        self.assertLessEqual(block["kept"], P.RECALL_FINAL_K)

    def test_coarse_pool_is_capped(self):
        block = self._block(budget=100000, rows=entries(60))
        self.assertLessEqual(block["coarse"], P.RECALL_COARSE_N)


if __name__ == "__main__":
    unittest.main()
