# -*- coding: utf-8 -*-
"""Fill skips a sentence that does not fit and keeps scanning."""
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
    huge = "超长句" + "字" * 300
    return [row("s1", huge, 1777800000, "EV001", [1.0, 0.0]),
            row("s2", "短句一，是证据。", 1777800060, "EV001", [1.0, 0.0]),
            row("s3", "短句二，也是证据。", 1777800120, "EV001", [1.0, 0.0]),
            row("s4", "第三句短的。", 1777800180, "EV001", [1.0, 0.0])]


class EmbedStub:
    mode = "stub"

    def __call__(self, text):
        return [1.0, 0.0]

    def embed_many(self, texts):
        return [[1.0, 0.0] for _ in texts]


def build(budget):
    old_embed, old_seed = P._event_embed_fn, P.SENTENCE_SEED_K
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    P.SENTENCE_SEED_K = 2      # s1 (huge) and s2 are the seeds
    try:
        return P._sentence_recall_block("/tmp", "s1", "证据", pool(), [],
                                        payload={}, budget_chars=budget)
    finally:
        P._event_embed_fn, P.SENTENCE_SEED_K = old_embed, old_seed


class SkipFillTest(unittest.TestCase):
    def test_a_huge_sentence_is_skipped_and_the_short_ones_still_land(self):
        block = build(200)
        text = block["text"]
        self.assertNotIn("字" * 200, text)          # the huge line was skipped
        self.assertIn("短句一", text)
        self.assertIn("短句二", text)
        self.assertIn("第三句短的", text)

    def test_the_fold_count_matches_the_skipped_rows(self):
        block = build(200)
        self.assertEqual(block["folded"], len(block["folded_ids"]))
        self.assertIn("已折叠 %d 条" % block["folded"], block["text"])
        self.assertIn("s1", block["folded_ids"])


if __name__ == "__main__":
    unittest.main()