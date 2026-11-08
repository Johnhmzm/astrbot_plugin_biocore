# -*- coding: utf-8 -*-
"""The budget decides how many events ship; EVENT_TOP is only a clamp."""
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


def many_events(count=30):
    rows = []
    for event in range(count):
        rows.append(row("ev%d-0" % event, 0.95 - event * 0.01, 1777800000 + event * 100,
                        "EV%03d" % event, "事件%d的一句。" % event))
    return rows


def build(budget, top=None):
    old_embed, old_top = P._event_embed_fn, P.EVENT_TOP
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    if top is not None:
        P.EVENT_TOP = top
    try:
        return P._sentence_recall_block("/tmp", "s1", "查询", many_events(), [],
                                        payload={}, budget_chars=budget, delivery="event")
    finally:
        P._event_embed_fn, P.EVENT_TOP = old_embed, old_top


class CapTest(unittest.TestCase):
    def test_a_roomy_budget_delivers_every_event(self):
        block = build(4000)
        self.assertEqual(block["events_shown"], 30)
        for event in range(30):
            self.assertIn("事件%d的一句" % event, block["text"])

    def test_a_positive_clamp_still_limits(self):
        block = build(4000, top=3)
        self.assertEqual(block["events_shown"], 3)
        self.assertEqual(len(block["folded_events"]), 27)
        self.assertEqual(block["folded"], 27)

    def test_a_tight_budget_fills_in_order_and_accounts_for_the_rest(self):
        block = build(200)
        shown = block["events_shown"]      # 0 is fine: a tight budget may fold everything
        self.assertLessEqual(len(block["text"]), 200)
        self.assertEqual(shown + len(block["folded_events"]), 30)
        self.assertEqual(block["folded"], len(block["folded_ids"]))


if __name__ == "__main__":
    unittest.main()