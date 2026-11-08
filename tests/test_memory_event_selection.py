# -*- coding: utf-8 -*-
"""Event score = 0.8 * rank position + 0.2 * share of top-40 sentences."""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline as P  # noqa: E402

TOTAL = 583          # the N used in the arithmetic below


def cosine_rank(rank, total=TOTAL):
    # distinct cosines that keep the intended order
    return 0.99 - (rank - 1) * (0.59 / max(1, total - 1))


def row(entry_id, cos, ts, event_id):
    return {"id": entry_id, "text": "句子" + entry_id, "ts": ts,
            "event_id": event_id, "role": "user",
            "vector": [float(cos), math.sqrt(max(0.0, 1.0 - cos * cos))]}


class EmbedStub:
    mode = "stub"

    def __call__(self, text):
        return [1.0, 0.0]

    def embed_many(self, texts):
        return [[1.0, 0.0] for _ in texts]


def build(spec):
    """spec: list of (event_id, [global ranks]). Filler goes to one noise event."""
    rows = []
    placed = set()
    for event_id, ranks in spec:
        for offset, rank in enumerate(ranks):
            placed.add(rank)
            rows.append(row("%s-%d" % (event_id, offset), cosine_rank(rank),
                            1777800000 + offset, event_id))
    for rank in range(1, TOTAL + 1):
        if rank in placed:
            continue
        rows.append(row("noise-%d" % rank, cosine_rank(rank),
                         1777900000 + rank, "EVNOISE"))
    old_embed = P._event_embed_fn
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    try:
        block = P._sentence_recall_block("/tmp", "s1", "查询", rows, [],
                                         payload={}, budget_chars=4000)
    finally:
        P._event_embed_fn = old_embed
    by_event = {item["event_id"]: item for item in block["events"]}
    return block, by_event

class ArithmeticTest(unittest.TestCase):
    def test_a_strong_single_line_beats_a_slightly_later_cluster(self):
        block, meta = build([("EVA", [1]), ("EVB", [5, 6, 7])])
        self.assertAlmostEqual(meta["EVA"]["p"], 1.0, places=6)
        self.assertGreater(meta["EVA"]["score"], meta["EVB"]["score"])
        self.assertLess(block["events"].index(meta["EVA"]),
                        block["events"].index(meta["EVB"]))

    def test_a_cluster_at_the_top_beats_a_later_single_line(self):
        block, meta = build([("EVC", [20]), ("EVD", [1, 2, 3])])
        self.assertGreater(meta["EVD"]["score"], meta["EVC"]["score"])
        self.assertLess(block["events"].index(meta["EVD"]),
                        block["events"].index(meta["EVC"]))

    def test_when_ranks_diverge_the_size_does_not_matter(self):
        block, meta = build([("EVE", [300]), ("EVF", [50, 51, 52, 53, 54, 55])])
        self.assertEqual(meta["EVF"]["r"], 0.0)   # 50..55 are outside the top-40
        self.assertGreater(meta["EVF"]["score"], meta["EVE"]["score"])
        self.assertEqual(meta["EVE"]["r"], 0.0)

    def test_meta_carries_the_arithmetic(self):
        block, meta = build([("EVA", [1])])
        first = meta["EVA"]
        for key in ("rank_best", "p", "r", "score", "sentence_count"):
            self.assertIn(key, first)
        self.assertEqual(first["rank_best"], 1)
        self.assertEqual(first["sentence_count"], 1)


class WholeEventTest(unittest.TestCase):
    def test_an_event_that_does_not_fit_is_folded_whole(self):
        rows = [row("e%d" % i, 0.9 - i * 0.01, 1777800000 + i, "EVONE") for i in range(6)]
        for item in rows:
            item["text"] = "句子" + str(len(item["text"])) + "字" * 40
        old_embed = P._event_embed_fn
        P._event_embed_fn = lambda *a, **k: EmbedStub()
        try:
            block = P._sentence_recall_block("/tmp", "s1", "查询", rows, [],
                                             payload={}, budget_chars=200)
        finally:
            P._event_embed_fn = old_embed
        self.assertEqual(block["text"].count("句子"), 0)
        self.assertIn("EVONE 共6句，已折叠", block["text"])
        self.assertEqual(block["folded"], 6)

    def test_a_fitting_event_is_rendered_whole_in_ts_order(self):
        rows = [row("e2", 0.90, 1777800200, "EVONE"),
                row("e1", 0.80, 1777800000, "EVONE"),
                row("e3", 0.70, 1777800400, "EVONE")]
        rows[0]["text"] = "第二句。"
        rows[1]["text"] = "第一句。"
        rows[2]["text"] = "第三句。"
        old_embed = P._event_embed_fn
        P._event_embed_fn = lambda *a, **k: EmbedStub()
        try:
            block = P._sentence_recall_block("/tmp", "s1", "查询", rows, [],
                                             payload={}, budget_chars=4000)
        finally:
            P._event_embed_fn = old_embed
        text = block["text"]
        self.assertLess(text.index("第一句"), text.index("第二句"))
        self.assertLess(text.index("第二句"), text.index("第三句"))


if __name__ == "__main__":
    unittest.main()