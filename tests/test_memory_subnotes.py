# -*- coding: utf-8 -*-
"""Long events deliver hits + all subnotes; short events deliver raw text."""
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


def row(entry_id, cos, ts, event_id, text):
    return {"id": entry_id, "text": text, "ts": ts, "event_id": event_id,
            "role": "user",
            "vector": [float(cos), math.sqrt(max(0.0, 1.0 - cos * cos))]}


class EmbedStub:
    mode = "stub"

    def __call__(self, text):
        return [1.0, 0.0]

    def embed_many(self, texts):
        return [[1.0, 0.0] for _ in texts]


def long_rows(count=12):
    return [row("s%02d" % i, 0.95 - i * 0.02, 1777800000 + i * 60, "EVBIG",
                "原句%d" % i + "字" * 30) for i in range(count)]


def long_subs():
    return [{"sentence_ids": ["s%02d" % i for i in range(0, 4)], "note": "第一段小结",
             "turn_range": [1, 4]},
            {"sentence_ids": ["s%02d" % i for i in range(4, 8)], "note": "第二段小结",
             "turn_range": [5, 8]},
            {"sentence_ids": ["s%02d" % i for i in range(8, 12)], "note": "第三段小结",
             "turn_range": [9, 12]}]


def build(rows, events, budget, switch=None):
    old_embed, old_switch = P._event_embed_fn, P.SUBNOTES_ON
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    if switch is not None:
        P.SUBNOTES_ON = switch
    try:
        return P._sentence_recall_block("/tmp", "s1", "查询", rows, events,
                                        payload={}, budget_chars=budget, delivery="event")
    finally:
        P._event_embed_fn, P.SUBNOTES_ON = old_embed, old_switch


class DeliveryTest(unittest.TestCase):
    def test_a_long_event_delivers_hits_plus_every_subnote(self):
        block = build(long_rows(), [{"event_id": "EVBIG", "subnotes": long_subs()}], 420)
        text = block["text"]
        self.assertIn("第一段小结", text)
        self.assertIn("第二段小结", text)
        self.assertIn("第三段小结", text)
        hits = [i for i in range(12) if ("原句%d" % i) in text]
        self.assertGreaterEqual(len(hits), 1)      # the evidence line stays raw
        self.assertLessEqual(len(hits), 3)
        self.assertEqual(len(hits) + len(block["folded_ids"]), 12)

    def test_a_short_event_delivers_raw_text(self):
        rows = [row("q%d" % i, 0.9 - i * 0.01, 1777800000 + i, "EVSMALL", "短句%d。" % i)
                for i in range(6)]
        block = build(rows, [{"event_id": "EVSMALL"}], 4000)
        for i in range(6):
            self.assertIn("短句%d" % i, block["text"])

    def test_a_long_event_that_still_does_not_fit_folds_whole(self):
        block = build(long_rows(), [{"event_id": "EVBIG", "subnotes": long_subs()}], 200)
        self.assertIn("EVBIG 共12句，已折叠", block["text"])
        self.assertEqual(len(block["folded_ids"]), 12)

    def test_the_switch_restores_raw_delivery(self):
        block = build(long_rows(), [{"event_id": "EVBIG", "subnotes": long_subs()}], 420,
                      switch=False)
        self.assertNotIn("第一段小结", block["text"])
        self.assertIn("已折叠", block["text"])


class WriteSideTest(unittest.TestCase):
    def test_a_short_event_never_calls_the_model(self):
        called = {"n": 0}

        def summarizer(prompt):
            called["n"] += 1
            return "[]"

        # 12 lines x ~15 chars is ~180 chars: short, despite the line count
        rows = [{"id": "s%02d" % i, "text": "短短一句十五字左右" + str(i), "turn": i + 1}
                for i in range(12)]
        self.assertEqual(P._build_subnotes({"entries": rows}, summarizer), [])
        self.assertEqual(called["n"], 0)

    def test_a_genuinely_long_event_gets_id_based_subnotes(self):
        # 40 lines x ~25 chars is ~1000 chars: that is worth compressing
        rows = [{"id": "s%02d" % i, "text": "这一句大概有二十五个字左右的长度吧" + str(i),
                 "turn": i + 1} for i in range(40)]
        payload = json.dumps([{"start": 1, "end": 20, "note": "前半"},
                              {"start": 21, "end": 40, "note": "后半"}], ensure_ascii=False)
        notes = P._build_subnotes({"entries": rows}, lambda prompt: payload)
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["sentence_ids"], ["s%02d" % i for i in range(20)])
        self.assertEqual(notes[1]["turn_range"], [21, 40])

    def test_the_switch_disables_subnotes_entirely(self):
        called = {"n": 0}

        def summarizer(prompt):
            called["n"] += 1
            return "[]"

        rows = [{"id": "s%02d" % i, "text": "这一句大概有二十五个字左右的长度吧" + str(i),
                 "turn": i + 1} for i in range(40)]
        old = P.SUBNOTES_ON
        P.SUBNOTES_ON = False
        try:
            self.assertEqual(P._build_subnotes({"entries": rows}, summarizer), [])
        finally:
            P.SUBNOTES_ON = old
        self.assertEqual(called["n"], 0)

if __name__ == "__main__":
    unittest.main()