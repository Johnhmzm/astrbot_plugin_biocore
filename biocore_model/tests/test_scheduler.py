# -*- coding: utf-8 -*-
"""HUMAN-1 scheduler tests: dimensions, lazy decay, ranking."""
import unittest

from biocore_model import scheduler as sc


def items():
    return [
        {"id": "a", "due_ts": 1000.0, "entity": "u1", "channel": "chat", "weight": 1.0, "last_ts": 0.0},
        {"id": "b", "due_ts": 1000.0, "entity": "u2", "channel": "chat", "weight": 1.0, "last_ts": 0.0},
        {"id": "c", "due_ts": 100.0, "entity": "u1", "channel": "note", "weight": 1.0, "last_ts": 0.0},
    ]


class TimeTest(unittest.TestCase):
    def test_time_score_peaks_at_due(self):
        row = {"due_ts": 1000.0}
        self.assertAlmostEqual(sc.time_score(row, 1000.0), 1.0)
        self.assertLess(sc.time_score(row, 1000.0 + 3600.0), 1.0)

    def test_time_score_symmetric_distance(self):
        row = {"due_ts": 1000.0}
        self.assertAlmostEqual(sc.time_score(row, 1000.0 - 7200.0),
                               sc.time_score(row, 1000.0 + 7200.0))


class DimensionTest(unittest.TestCase):
    def test_entity_match_beats_miss(self):
        self.assertGreater(sc.entity_score({"entity": "u1"}, "u1"),
                           sc.entity_score({"entity": "u1"}, "u2"))

    def test_channel_match_beats_miss(self):
        self.assertGreater(sc.channel_score({"channel": "chat"}, "chat"),
                           sc.channel_score({"channel": "chat"}, "note"))

    def test_no_filter_is_neutral(self):
        self.assertEqual(sc.entity_score({"entity": "u1"}), 1.0)
        self.assertEqual(sc.channel_score({"channel": "chat"}), 1.0)

    def test_custom_weights_change_order(self):
        now = 1000.0
        default = sc.score(items()[1], now, entity="u1", channel="chat")
        entity_heavy = sc.score(items()[1], now, entity="u1", channel="chat",
                                weights={"time": 0.1, "entity": 0.8, "channel": 0.1})
        self.assertNotAlmostEqual(default, entity_heavy)


class DecayRankTest(unittest.TestCase):
    def test_lazy_decay_halves_in_one_half_life(self):
        row = sc.lazy_decay({"weight": 1.0, "last_ts": 0.0}, 12 * 3600.0)
        self.assertAlmostEqual(row["weight"], 0.5, places=4)

    def test_lazy_decay_does_not_mutate(self):
        source = {"weight": 1.0, "last_ts": 0.0, "id": "x"}
        sc.lazy_decay(source, 999999.0)
        self.assertEqual(source, {"weight": 1.0, "last_ts": 0.0, "id": "x"})

    def test_rank_is_descending_and_deterministic(self):
        rows = sc.rank(items(), 1000.0, entity="u1", channel="chat")
        scores = [row["score"] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(rows, sc.rank(items(), 1000.0, entity="u1", channel="chat"))

    def test_pick_and_limit(self):
        self.assertEqual(sc.pick(items(), 1000.0, entity="u1", channel="chat")["item"]["id"], "a")
        self.assertEqual(len(sc.rank(items(), 1000.0, limit=2)), 2)
        self.assertEqual(sc.rank([], 1000.0), [])

    def test_due_window_filters(self):
        rows = sc.due(items(), 1000.0, window_seconds=600.0)
        ids = [row["id"] for row in rows]
        self.assertIn("a", ids)
        self.assertIn("b", ids)
        self.assertNotIn("c", ids)


if __name__ == "__main__":
    unittest.main()
