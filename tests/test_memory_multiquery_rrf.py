# -*- coding: utf-8 -*-
"""Multi-query rewrite and RRF fusion: both fail soft, both switchable."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


def rewriter(*answers):
    rows = list(answers)
    def ask(prompt):
        return rows.pop(0) if rows else '[]'
    return ask


class RewriteTest(unittest.TestCase):
    def test_three_paraphrases_are_kept_alongside_the_original(self):
        ask = rewriter('["灯箱什么时候修", "门口灯箱 维修 时间", "灯箱不亮了怎么办"]')
        out = P._rewrite_queries("灯箱什么时候修", payload={"query_rewriter": ask})
        self.assertEqual(out[0], "灯箱什么时候修")
        self.assertEqual(len(out), 3)          # original + 2 new, deduped, capped

    def test_garbage_falls_back_to_the_original_with_a_warning(self):
        ask = rewriter("模型说：不用 JSON 啦")
        with self.assertLogs(P.logger, level="WARNING") as logs:
            out = P._rewrite_queries("灯箱什么时候修", payload={"query_rewriter": ask})
        self.assertEqual(out, ["灯箱什么时候修"])
        self.assertTrue(any("multiquery" in line for line in logs.output))

    def test_the_switch_turns_rewriting_off(self):
        old = P.MULTIQUERY_ON
        P.MULTIQUERY_ON = False
        try:
            called = {"n": 0}
            def ask(prompt):
                called["n"] += 1
                return '["x"]'
            out = P._rewrite_queries("q", payload={"query_rewriter": ask})
        finally:
            P.MULTIQUERY_ON = old
        self.assertEqual(out, ["q"])
        self.assertEqual(called["n"], 0)


class RrfTest(unittest.TestCase):
    def test_a_document_in_both_lists_wins(self):
        fused = P._rrf_fuse([["a", "b", "c"], ["c", "d"]], k=60)
        keys = [key for key, _score in fused]
        self.assertEqual(keys[0], "c")          # present in both lists
        self.assertEqual(set(keys), {"a", "b", "c", "d"})

    def test_ranks_decide_not_raw_scores(self):
        # 'a' is first in list 1 only; 'b' is second in both: b must win
        fused = P._rrf_fuse([["a", "b"], ["c", "b"]], k=60)
        self.assertEqual([key for key, _s in fused][0], "b")


if __name__ == "__main__":
    unittest.main()