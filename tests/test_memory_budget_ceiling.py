# -*- coding: utf-8 -*-
"""The injected block never exceeds the budget the caller passed."""
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


def rows(count=40, per_event=3):
    out = []
    for event in range(count):
        for index in range(per_event):
            out.append(row("e%d-%d" % (event, index), 0.95 - event * 0.005,
                           1777800000 + event * 100 + index, "EV%03d" % event,
                           "事件%d第%d句。" % (event, index) + "填充字" * 12))
    return out


def build(budget):
    old = P._event_embed_fn
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    try:
        block = P._sentence_recall_block("/tmp", "s1", "查询", rows(), [],
                                         payload={}, budget_chars=budget, delivery="event")
    finally:
        P._event_embed_fn = old
    # the real call path renders the same text, so length is what matters
    return block


class BudgetCeilingTest(unittest.TestCase):
    def test_twoThousand(self):
        block = build(2000)
        self.assertLessEqual(len(block["text"]), 2000)

    def test_tenThousand(self):
        block = build(10000)
        self.assertLessEqual(len(block["text"]), 10000)

    def test_twoHundred_does_not_raise(self):
        block = build(200)
        self.assertLessEqual(len(block["text"]), 200)

    def test_the_accounting_is_complete(self):
        block = build(2000)
        total_events = len(block["events"])
        self.assertEqual(block["events_shown"] + len(block["folded_events"]),
                         total_events)


if __name__ == "__main__":
    unittest.main()