# -*- coding: utf-8 -*-
"""ACT-R activation ranking: one score from quantities already in the store."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.recall import activation as act  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400.0


def entry(entry_id, ts, hits=1, last_hit=None, vector=None, **extra):
    row = {"id": entry_id, "text": entry_id, "role": "user", "ts": ts,
           "hits": hits, "scope": "default"}
    if last_hit is not None:
        row["last_hit"] = last_hit
    if vector is not None:
        row["vector"] = list(vector)
    row.update(extra)
    return row


class BaseLevelTest(unittest.TestCase):
    """B_i = ln(sum (now - t)^-d)."""

    def test_the_more_recent_access_scores_higher(self):
        recent = act.base_level(entry("a", NOW - 60), NOW, 0.5)
        old = act.base_level(entry("b", NOW - 10 * DAY), NOW, 0.5)
        self.assertGreater(recent, old)

    def test_more_hits_raise_the_base_level(self):
        once = act.base_level(entry("a", NOW - DAY, hits=1), NOW, 0.5)
        often = act.base_level(entry("b", NOW - DAY, hits=4), NOW, 0.5)
        self.assertGreater(often, once)

    def test_the_decay_is_configurable(self):
        data = entry("a", NOW - DAY)
        slow = act.base_level(data, NOW, 0.2)
        fast = act.base_level(data, NOW, 0.9)
        self.assertGreater(slow, fast)

    def test_no_access_time_is_the_floor(self):
        self.assertEqual(act.base_level({}, NOW, 0.5), 0.0)
        self.assertEqual(act.base_level({"ts": 0}, NOW, 0.5), 0.0)

    def test_hits_repeat_the_last_access(self):
        one = act.access_times({"ts": NOW - DAY, "hits": 1})
        three = act.access_times({"ts": NOW - DAY, "hits": 3})
        self.assertEqual(len(one), 1)
        self.assertEqual(len(three), 3)


class TermTest(unittest.TestCase):
    """Semantic, PPR and specificity terms."""

    def test_one_query_is_plain_cosine(self):
        value = act.semantic_term([[1.0, 0.0]], [1.0], [1.0, 0.0])
        self.assertAlmostEqual(value, 1.0, places=6)

    def test_several_queries_are_weighted(self):
        value = act.semantic_term([[1.0, 0.0], [0.0, 1.0]], [0.5, 0.5],
                                  [1.0, 0.0])
        self.assertAlmostEqual(value, 0.5, places=6)

    def test_no_entry_vector_is_zero(self):
        self.assertEqual(act.semantic_term([[1.0]], [1.0], []), 0.0)
        self.assertEqual(act.specificity_term([], [[1.0]]), 0.0)

    def test_specificity_is_one_minus_neighbour_similarity(self):
        value = act.specificity_term([1.0, 0.0], [[1.0, 0.0], [0.0, 1.0]], 1)
        self.assertAlmostEqual(value, 1.0, places=6)

    def test_ppr_without_edges_is_zero_and_silent(self):
        self.assertEqual(act.ppr_scores(["a"], []), {})

    def test_ppr_reaches_a_neighbour(self):
        scores = act.ppr_scores(["a"], [{"src": "a", "dst": "b", "weight": 1.0}])
        self.assertIn("b", scores)
        self.assertGreater(scores["b"], 0.0)

    def test_the_four_terms_add_up(self):
        self.assertAlmostEqual(act.combine(1.0, 0.5, 0.4, 0.25, 0.2, 0.4),
                               1.0 + 0.5 + 0.2 * 0.4 + 0.4 * 0.25, places=6)


class EngineTest(unittest.TestCase):
    """The switch and the reorder."""

    def engine(self, flags=None, entries=None):
        return MemoryEngine(store=MemoryStore(doc={"entries": entries or []}),
                            config={"flags": dict(flags or {})}, now=lambda: NOW)

    def rows(self):
        return [entry("old", NOW - 10 * DAY, hits=1, vector=[1.0, 0.0]),
                entry("new", NOW - 60, hits=3, vector=[0.9, 0.1])]

    def test_the_switch_off_keeps_the_old_order(self):
        engine = self.engine(entries=self.rows())
        rows = engine.recall("x", budget=5)
        self.assertFalse(any("activation_score" in row for row in rows))

    def test_the_switch_on_scores_every_row(self):
        engine = self.engine({"activation_rank": True}, self.rows())
        rows = engine.recall("x", budget=5, vector=[1.0, 0.0])
        self.assertTrue(rows)
        self.assertIn("activation_score", rows[0])
        self.assertIn("activation_rank", engine.monitor())


if __name__ == "__main__":
    unittest.main()
