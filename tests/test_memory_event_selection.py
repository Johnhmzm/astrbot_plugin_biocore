# -*- coding: utf-8 -*-
"""Event-level selection: score = 0.9 * max + 0.1 * rest_mean, whole events."""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


def row(entry_id, cos, ts, event_id, text=None):
    return {"id": entry_id, "text": text or ("句子" + entry_id),
            "ts": ts, "event_id": event_id, "role": "user",
            "vector": [float(cos), math.sqrt(max(0.0, 1.0 - cos * cos))]}


class EmbedStub:
    mode = "stub"

    def __call__(self, text):
        return [1.0, 0.0]

    def embed_many(self, texts):
        return [[1.0, 0.0] for _ in texts]


def build(rows, budget=4000, top=None):
    old_embed, old_top = P._event_embed_fn, P.EVENT_TOP
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    if top is not None:
        P.EVENT_TOP = top
    try:
        return P._sentence_recall_block("/tmp", "s1", "查询", rows, [],
                                        payload={}, budget_chars=budget)
    finally:
        P._event_embed_fn, P.EVENT_TOP = old_embed, old_top


def mixed(event_id, head, tail, base_ts):
    rows = [row(event_id + "-head", head, base_ts, event_id)]
    rows += [row("%s-t%d" % (event_id, i), tail, base_ts + 60 * (i + 1), event_id)
             for i in range(5)]
    return rows


def consistent(event_id, values, base_ts):
    return [row("%s-%d" % (event_id, i), value, base_ts + 60 * i, event_id)
            for i, value in enumerate(values)]


class ScoreTest(unittest.TestCase):
    def test_one_strong_line_beats_a_consistent_weaker_event(self):
        rows = mixed("EVA", 0.90, 0.10, 1777800000)
        rows += consistent("EVB", [0.80, 0.78, 0.76], 1777860000)
        order = [item["event_id"] for item in build(rows)["events"]]
        self.assertEqual(order[0], "EVA")

    def test_a_small_gap_lets_the_rest_of_the_event_decide(self):
        rows = mixed("EVC", 0.81, 0.10, 1777800000)
        rows += consistent("EVD", [0.80, 0.79, 0.78], 1777860000)
        order = [item["event_id"] for item in build(rows)["events"]]
        self.assertEqual(order[0], "EVD")

    def test_a_single_line_event_is_not_penalised(self):
        rows = consistent("EVE", [0.85], 1777800000)
        first = build(rows)["events"][0]
        self.assertAlmostEqual(first["score"], 0.85, places=6)
        self.assertAlmostEqual(first["rest_mean"], 0.85, places=6)
        self.assertEqual(first["sentence_count"], 1)

    def test_meta_carries_the_arithmetic(self):
        rows = mixed("EVA", 0.90, 0.10, 1777800000)
        first = build(rows)["events"][0]
        for key in ("max_cos", "rest_mean", "score", "sentence_count"):
            self.assertIn(key, first)
        self.assertAlmostEqual(first["score"], 0.9 * 0.90 + 0.1 * 0.10, places=3)


class WholeEventTest(unittest.TestCase):
    def test_an_event_that_does_not_fit_is_folded_whole(self):
        rows = [row("e%d" % i, 0.9 - i * 0.01, 1777800000 + i, "EVONE",
                    text="句子" + str(i) + "字" * 40) for i in range(6)]
        block = build(rows, budget=200)
        self.assertEqual(block["text"].count("句子"), 0)
        self.assertIn("EVONE 共6句，已折叠", block["text"])
        self.assertEqual(block["folded"], 6)

    def test_a_fitting_event_is_rendered_whole_in_ts_order(self):
        rows = [row("e2", 0.90, 1777800200, "EVONE", text="第二句。"),
                row("e1", 0.80, 1777800000, "EVONE", text="第一句。"),
                row("e3", 0.70, 1777800400, "EVONE", text="第三句。")]
        text = build(rows, budget=4000)["text"]
        self.assertLess(text.index("第一句"), text.index("第二句"))
        self.assertLess(text.index("第二句"), text.index("第三句"))


if __name__ == "__main__":
    unittest.main()