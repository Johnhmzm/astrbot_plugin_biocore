# -*- coding: utf-8 -*-
"""recall.inject_chars / recall.delivery: configurable, validated, honoured."""
import json
import math
import sys
import tempfile
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


def rows(count=40):
    return [row("s%02d" % i, 0.95 - i * 0.01, 1777800000 + i, "EV%02d" % i,
                "句子内容" + str(i) * 2 + "填充" * 20) for i in range(count)]


def build(budget, delivery="event"):
    old = P._event_embed_fn
    P._event_embed_fn = lambda *a, **k: EmbedStub()
    try:
        return P._sentence_recall_block("/tmp", "s1", "查询", rows(), [],
                                        payload={}, budget_chars=budget,
                                        delivery=delivery)
    finally:
        P._event_embed_fn = old


class BudgetConfigTest(unittest.TestCase):
    def test_a_small_budget_caps_the_block(self):
        self.assertLessEqual(len(build(1000)["text"]), 1000)

    def test_a_large_budget_caps_the_block(self):
        self.assertLessEqual(len(build(40000)["text"]), 40000)

    def test_sentence_mode_orders_by_score(self):
        block = build(2000, delivery="sentence")
        lines = [line for line in block["text"].splitlines() if line.startswith("- ")]
        seen = [line[2:8] for line in lines[:5]]
        self.assertEqual(seen, [("句子内容" + str(i) * 2)[:6] for i in range(5)])
        self.assertEqual(block["events_picked"], 0)   # no event grouping in this mode

    def test_event_mode_still_groups(self):
        block = build(2000, delivery="event")
        self.assertGreater(block["events_picked"], 0)


class ConfigValidationTest(unittest.TestCase):
    def _settings(self, block):
        tmp = tempfile.TemporaryDirectory()
        Path(tmp.name, "core_config.json").write_text(json.dumps(block), encoding="utf-8")
        try:
            return P.recall_settings(tmp.name, None)
        finally:
            tmp.cleanup()

    def test_the_defaults_are_exposed(self):
        settings = self._settings({})
        self.assertEqual(settings["inject_chars"], P.RECALL_INJECT_DEFAULT)
        self.assertEqual(settings["delivery"], "event")

    def test_a_configured_budget_is_used(self):
        settings = self._settings({"recall": {"inject_chars": 40000,
                                               "delivery": "event"}})
        self.assertEqual(settings["inject_chars"], 40000)
        self.assertEqual(settings["delivery"], "event")

    def test_bad_values_raise_with_the_legal_range(self):
        for bad in (0, -1, "abc", 100, 500000):
            with self.assertRaises(RuntimeError) as caught:
                self._settings({"recall": {"inject_chars": bad}})
            self.assertIn(str(P.RECALL_INJECT_MIN), str(caught.exception))
            self.assertIn(str(P.RECALL_INJECT_MAX), str(caught.exception))

    def test_a_bad_delivery_raises(self):
        with self.assertRaises(RuntimeError):
            self._settings({"recall": {"delivery": "paragraph"}})


if __name__ == "__main__":
    unittest.main()