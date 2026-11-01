# -*- coding: utf-8 -*-
import unittest

from biocore_model import turn_memory as tm


def _trace_row(rank, eid, text, score=0.6, source="direct", **extra):
    row = {"entry_id": eid, "rank": rank, "score": score, "source": source,
           "text": text, "cosine": 0.55, "importance": 0.5,
           "components": {"lexical": 0.5, "recency": 0.3}}
    row.update(extra)
    return row


class TurnMemoryTest(unittest.TestCase):
    def test_build_gives_four_rows_with_source_and_score(self):
        trace = [_trace_row(i, "id%d" % i, "记忆 %d" % i, score=0.5 + i * 0.05)
                 for i in range(1, 6)]
        rows = tm.build(trace)
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(row["source"], "direct")
            self.assertGreater(row["score"], 0)
            self.assertTrue(row["reason"])
        self.assertEqual([row["rank"] for row in rows], [1, 2, 3, 4])

    def test_build_limit_is_clamped(self):
        trace = [_trace_row(i, "id%d" % i, "记忆 %d" % i) for i in range(1, 9)]
        self.assertEqual(len(tm.build(trace, limit=2)), 2)
        self.assertEqual(tm.build(trace, limit=0), [])
        self.assertEqual(len(tm.build(trace, limit=99)), tm.HARD_ROWS)
        self.assertEqual(len(tm.build(trace)), tm.MAX_ROWS)

    def test_reason_uses_top_two_components(self):
        reason = tm.reason_text({"lexical": 0.58, "recency": 0.22,
                                 "retention": 0.10})
        self.assertIn("关键词 0.58", reason)
        self.assertIn("近期 0.22", reason)
        self.assertNotIn("留存", reason)

    def test_reason_falls_back_to_similarity_and_importance(self):
        reason = tm.reason_text(None, cosine=0.61, importance=0.5)
        self.assertIn("相似度 0.61", reason)
        self.assertIn("重要度 0.50", reason)

    def test_reason_defaults_to_rule_score(self):
        self.assertEqual(tm.reason_text(), "规则打分")

    def test_build_skips_unusable_rows(self):
        rows = tm.build([None, {}, {"entry_id": ""}, "x",
                         {"entry_id": "e1", "text": "保留", "score": 0.7}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "保留")
        self.assertEqual(rows[0]["source"], "unknown")
        self.assertEqual(rows[0]["rank"], 1)

    def test_build_record_fields(self):
        rows = tm.build([_trace_row(1, "e1", "记忆")])
        record = tm.build_record(rows, reply="回" * 300, ts=1700000000)
        self.assertEqual(record["count"], 1)
        self.assertEqual(record["ts"], 1700000000.0)
        self.assertLessEqual(len(record["reply"]), 121)
        self.assertIn("…", record["reply"])

    def test_render_receipt_lists_rows(self):
        trace = [_trace_row(i, "e%d" % i, "记忆内容 %d" % i)
                 for i in range(1, 5)]
        record = tm.build_record(tm.build(trace), ts=1700000000)
        text = tm.render_receipt(record)
        lines = text.splitlines()
        self.assertEqual(lines[0], "本轮记忆：用了 4 条")
        self.assertEqual(len(lines), 5)
        for line in lines[1:]:
            self.assertIn("[direct]", line)
            self.assertIn("score", line)
            self.assertIn("原因：关键词", line)

    def test_render_receipt_empty(self):
        self.assertIn("暂无", tm.render_receipt(None))
        self.assertIn("暂无", tm.render_receipt({"rows": []}))

    def test_merge_history_is_bounded_newest_first(self):
        old = [{"ts": 1, "rows": []}, {"ts": 2, "rows": []}]
        new = {"ts": 3, "rows": []}
        merged = tm.merge_history(old, new)
        self.assertEqual([item["ts"] for item in merged], [3, 1, 2])
        long = [{"ts": i} for i in range(6)]
        self.assertEqual(len(tm.merge_history(long, {"ts": 9})),
                         tm.HISTORY_LIMIT)
        self.assertIsInstance(tm.merge_history(None, {"ts": 9}), list)
        self.assertEqual(len(tm.merge_history(None, {"ts": 9})), 1)
        self.assertEqual(tm.merge_history(old, None), old)

    def test_text_trim_and_receipt_budget(self):
        rows = tm.build([{"entry_id": "e1", "text": "长" * 300,
                          "score": 0.5, "components": {}}])
        self.assertLessEqual(len(rows[0]["text"]), tm.MAX_TEXT + 1)
        self.assertTrue(rows[0]["text"].endswith("…"))
        record = tm.build_record(rows)
        self.assertLessEqual(len(tm.render_receipt(record)),
                             tm.RECEIPT_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
