# -*- coding: utf-8 -*-
"""Seed sentences expand to their whole event; expansion is never pruned."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402


def row(entry_id, text, ts, event_id, vec):
    return {"id": entry_id, "text": text, "ts": ts, "event_id": event_id,
            "role": "user", "vector": vec}


def pool():
    long_a1 = "灯箱坏了。" + "细节" * 30
    long_a2 = "物业来看过。" + "细节" * 30
    long_a3 = "约了明天九点半。" + "细节" * 30
    return [row("a1", long_a1, 1777800000, "EV001", [1.0, 0.0]),
            row("a2", long_a2, 1777800060, "EV001", [0.0, 1.0]),
            row("a3", long_a3, 1777800120, "EV001", [0.0, 1.0]),
            row("b1", "先记着别急。", 1777800200, "EV002", [0.0, 1.0])]


class EmbedStub:
    mode = "stub"

    def __call__(self, text):
        return [1.0, 0.0]

    def embed_many(self, texts):
        return [[1.0, 0.0] for _ in texts]


def build(budget=None, expand=None, seed_k=1):
    old_embed, old_expand, old_seed = P._event_embed_fn, P.EXPAND_EVENTS, P.SENTENCE_SEED_K
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    P.SENTENCE_SEED_K = seed_k
    if expand is not None:
        P.EXPAND_EVENTS = expand
    try:
        return P._sentence_recall_block("/tmp", "s1", "灯箱", pool(), [],
                                        payload={}, budget_chars=budget)
    finally:
        P._event_embed_fn, P.EXPAND_EVENTS, P.SENTENCE_SEED_K = old_embed, old_expand, old_seed


class ExpansionTest(unittest.TestCase):
    def test_a_seed_pulls_its_whole_event(self):
        text = build(budget=4000)["text"]
        for sentence in ("灯箱坏了", "物业来看过", "约了明天九点半"):
            self.assertIn(sentence, text)
        self.assertNotIn("先记着别急", text)

    def test_expanded_rows_survive_a_tight_budget_as_folds(self):
        block = build(budget=200)
        self.assertIn("已折叠", block["text"])
        self.assertTrue(block.get("folded_ids"))

    def test_the_switch_restores_the_old_behaviour(self):
        text = build(budget=4000, expand=False)["text"]
        self.assertNotIn("物业来看过", text)
        self.assertIn("灯箱坏了", text)


if __name__ == "__main__":
    unittest.main()