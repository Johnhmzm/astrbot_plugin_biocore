# -*- coding: utf-8 -*-
"""Packing never loses a sentence: shown plus folded always accounts for all."""
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


def make_rows():
    rows = []
    for event in range(3):
        for index in range(4):
            rows.append(row("e%d-%d" % (event, index), 0.9 - event * 0.05 - index * 0.01,
                            1777800000 + event * 1000 + index, "EV%d" % event,
                            "事件%d原句%d。" % (event, index) + "字" * 20))
    return rows


def build(budget):
    old = P._event_embed_fn
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    try:
        return P._sentence_recall_block("/tmp", "s1", "查询", make_rows(), [],
                                        payload={}, budget_chars=budget)
    finally:
        P._event_embed_fn = old


class NoLossTest(unittest.TestCase):
    def test_a_roomy_budget_delivers_every_sentence_of_every_selected_event(self):
        block = build(4000)
        for event in range(3):
            for index in range(4):
                self.assertIn("事件%d原句%d" % (event, index), block["text"])
        self.assertEqual(block["folded"], 0)

    def test_a_tight_budget_accounts_for_every_sentence(self):
        block = build(300)
        shown = len(block["ids"])
        self.assertEqual(shown + len(block["folded_ids"]), 12)
        self.assertEqual(block["folded"], len(block["folded_ids"]))

    def test_folded_ids_never_overlap_shown_ids(self):
        block = build(300)
        self.assertFalse(set(block["ids"]) & set(block["folded_ids"]))


if __name__ == "__main__":
    unittest.main()