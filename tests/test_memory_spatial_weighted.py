# -*- coding: utf-8 -*-
"""Time-anchored retrieval with a weighted five-axis distance.

distance = sum(w_axis * d_axis). The default weights are EQUAL (0.20 per
axis): a neutral engineering default, not a fitted one. Wording never moves
the axes unless a store turns on temporal_boost (default OFF), in which case
the cue list comes from core/config.py. query_ts anchors the time axis to the
moment the question was asked (Howard & Kahana 2002). spatial_weighted OFF
restores the old lexicographic order_key.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory import space as sp  # noqa: E402
from biocore_memory.core import config  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400.0
QUERY_VECTOR = [1.0, 0.0]
CUE_QUERY = "上次我们去海边是什么时候"
PLAIN_QUERY = "我们去海边"


def entry(entry_id, text, ts, **extra):
    row = {"id": entry_id, "text": text, "role": "user", "ts": ts,
           "tags": [], "importance": 0.5, "hits": 1, "scope": "default",
           "vector": list(QUERY_VECTOR)}
    row.update(extra)
    return row


def pair():
    """Same feel, one ten days back, one an hour back."""
    far = entry("far", "周末去海边看日出", NOW - 10 * DAY,
                affect={"v": 0.0, "a": 0.5}, vector=[1.0, 0.0])
    near = entry("near", "周末又去了海边", NOW - 3600,
                 affect={"v": 0.0, "a": 0.5}, vector=[0.99, 0.14])
    return far, near


def engine(entries, flags=None, now=NOW):
    return MemoryEngine(store=MemoryStore(doc={"entries": entries}),
                        config={"flags": dict(flags or {})},
                        now=lambda: now)


def lexicographic(entries, query, now=NOW):
    target = sp.query_space(query, vector=QUERY_VECTOR, now=now)
    ordered = sorted(entries, key=lambda row: sp.order_key(
        sp.distance(sp.build(row, now=now), target)))
    return [row["id"] for row in ordered]


class WeightTest(unittest.TestCase):
    """Equal default weights and their configuration knobs."""

    def test_default_weights_are_equal(self):
        weights = sp.weights({})
        self.assertEqual(weights, {"semantic": 0.20, "time": 0.20,
                                   "affect": 0.20, "social": 0.20,
                                   "activation": 0.20})
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        self.assertEqual(config.SPATIAL_WEIGHTS, weights)

    def test_weights_are_configurable(self):
        weights = sp.weights({"spatial_weights": {"semantic": 0.80,
                                                  "time": 0.20, "affect": 0.0,
                                                  "social": 0.0,
                                                  "activation": 0.0}})
        self.assertEqual(weights["semantic"], 0.8)
        self.assertEqual(weights["time"], 0.2)
        self.assertEqual(weights["affect"], 0.0)

    def test_weights_from_env(self):
        env = {"BIOCORE_SPATIAL_WEIGHTS":
               json.dumps({"semantic": 0.8, "time": 0.2, "affect": 0.0,
                           "social": 0.0, "activation": 0.0})}
        weights = sp.weights({}, env)
        self.assertEqual(weights["semantic"], 0.8)
        self.assertEqual(weights["affect"], 0.0)

    def test_weighted_distance_is_the_sum(self):
        distances = {"semantic": 0.2, "time": 0.4, "affect": 0.1,
                     "social": 0.0, "activation": 0.3}
        self.assertAlmostEqual(sp.weighted_distance(distances), 0.2, places=6)
        self.assertAlmostEqual(
            sp.weighted_distance(distances, {"semantic": 1.0}), 0.2, places=6)


class TemporalBoostTest(unittest.TestCase):
    """The cue list is gone: wording never moves the axes."""

    def test_no_time_cue_machinery_exists(self):
        self.assertFalse(hasattr(sp, "has_time_cue"))
        self.assertFalse(hasattr(sp, "temporal_cues"))
        self.assertFalse(hasattr(sp, "cue_weights"))
        self.assertFalse(hasattr(sp, "temporal_boost_enabled"))
        self.assertFalse(hasattr(config, "TEMPORAL_CUES"))

    def test_the_question_wording_never_moves_the_weights(self):
        self.assertEqual(sp.weights({"temporal_boost": True}), sp.weights({}))
        self.assertEqual(sp.weights({"temporal_cues": ["\u90a3\u5929"]}),
                         sp.weights({}))

class QueryTsTest(unittest.TestCase):
    """Retrieval is anchored to the question time, not to now."""

    def test_query_ts_moves_the_time_axis(self):
        far, near = pair()
        at_now = sp.rank([far, near], PLAIN_QUERY, query_ts=NOW,
                         vector=QUERY_VECTOR)
        at_past = sp.rank([far, near], PLAIN_QUERY, query_ts=NOW - 10 * DAY,
                          vector=QUERY_VECTOR)
        self.assertEqual(at_now["query_ts"], round(NOW, 3))
        self.assertEqual(at_now["results"][0]["id"], "near")
        self.assertEqual(at_past["results"][0]["id"], "far")
        self.assertNotEqual(at_now["results"][0]["distance"]["time"],
                            at_past["results"][0]["distance"]["time"])

    def test_recall_uses_query_ts(self):
        far, near = pair()
        rows = engine([far, near]).recall(PLAIN_QUERY, budget=5, query_ts=NOW,
                                          vector=QUERY_VECTOR)
        self.assertEqual([row["entry"]["id"] for row in rows], ["near", "far"])
        rows = engine([far, near]).recall(PLAIN_QUERY, budget=5,
                                          query_ts=NOW - 10 * DAY,
                                          vector=QUERY_VECTOR)
        self.assertEqual([row["entry"]["id"] for row in rows], ["far", "near"])

    def test_rank_payload(self):
        far, near = pair()
        out = sp.rank([far, near], PLAIN_QUERY, query_ts=NOW,
                      vector=QUERY_VECTOR)
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "weighted")
        self.assertNotIn("time_cue", out)
        self.assertNotIn("temporal_boost", out)
        self.assertEqual(out["weights"], sp.weights({}))
        self.assertEqual(out["count"], 2)
        self.assertIn("lexicographic", out["results"][0])
        self.assertIn("weighted", out["results"][0])


class EqualWeightOrderingTest(unittest.TestCase):
    """The acceptance case: ordering follows the equal weights only."""

    def test_same_query_ranks_the_same_with_or_without_cue_words(self):
        far, near = pair()
        cued = sp.rank([far, near], CUE_QUERY, query_ts=NOW, vector=QUERY_VECTOR)
        plain = sp.rank([far, near], PLAIN_QUERY, query_ts=NOW, vector=QUERY_VECTOR)
        self.assertEqual([row["id"] for row in cued["results"]],
                         [row["id"] for row in plain["results"]])
        self.assertEqual(cued["weights"], plain["weights"])
        self.assertEqual(cued["weights"], sp.weights({}))
        self.assertEqual([row["weighted"] for row in cued["results"]],
                         [row["weighted"] for row in plain["results"]])

    def test_equal_weights_still_differ_from_the_old_order(self):
        far, near = pair()
        old = lexicographic([far, near], PLAIN_QUERY)
        new = [row["id"] for row in sp.rank([far, near], PLAIN_QUERY,
                                            query_ts=NOW,
                                            vector=QUERY_VECTOR)["results"]]
        self.assertEqual(old, ["far", "near"])   # semantic-first axis order
        self.assertEqual(new, ["near", "far"])   # equal-weight trade-off

    def test_recall_returns_the_recent_entry_first(self):
        far, near = pair()
        rows = engine([far, near]).recall(PLAIN_QUERY, budget=5, query_ts=NOW,
                                          vector=QUERY_VECTOR)
        self.assertEqual(rows[0]["entry"]["id"], "near")
        self.assertNotIn("space_cue", rows[0])
        self.assertAlmostEqual(
            rows[0]["space_weighted"],
            sp.weighted_distance(rows[0]["space_distance"], sp.weights({})),
            places=6)


class FallbackTest(unittest.TestCase):
    """spatial_weighted OFF: the old lexicographic order_key, unchanged."""

    def test_switch_reads_flags_and_env(self):
        self.assertTrue(sp.weighted_enabled({}))
        self.assertFalse(sp.weighted_enabled({"spatial_weighted": False}))
        self.assertFalse(sp.weighted_enabled(
            {}, {"BIOCORE_SPATIAL_WEIGHTED": "off"}))

    def test_sort_key_falls_back_to_order_key(self):
        distances = {"semantic": 0.2, "time": 0.4, "affect": 0.1,
                     "social": 0.0, "activation": 0.3}
        self.assertEqual(sp.sort_key(distances,
                                     flags={"spatial_weighted": False}),
                         sp.order_key(distances))
        self.assertIsInstance(sp.sort_key(distances), float)

    def test_recall_falls_back_to_the_old_order(self):
        far, near = pair()
        rows = engine([far, near],
                      flags={"spatial_weighted": False}).recall(
            PLAIN_QUERY, budget=5, query_ts=NOW, vector=QUERY_VECTOR)
        self.assertEqual([row["entry"]["id"] for row in rows],
                         lexicographic([far, near], PLAIN_QUERY))
        self.assertEqual(rows[0]["entry"]["id"], "far")

    def test_probe_falls_back_to_the_old_order(self):
        far, near = pair()
        weighted = sp.probe([far, near], query=PLAIN_QUERY, now=NOW,
                            vector=QUERY_VECTOR)
        lexic = sp.probe([far, near], query=PLAIN_QUERY, now=NOW,
                         vector=QUERY_VECTOR,
                         flags={"spatial_weighted": False})
        self.assertEqual(weighted["mode"], "weighted")
        self.assertEqual(lexic["mode"], "lexicographic")
        self.assertEqual(weighted["results"][0]["id"], "near")
        self.assertEqual(lexic["results"][0]["id"], "far")


class CompatibilityTest(unittest.TestCase):
    """No anchor: recall keeps its old order and its old fields."""

    def test_recall_without_anchor_is_untouched(self):
        far, near = pair()
        quiet = engine([far, near], flags={"spatial_weighted": False})
        loud = engine([far, near])
        a = [row["entry"]["id"] for row in quiet.recall(PLAIN_QUERY, budget=5,
                                                        vector=QUERY_VECTOR)]
        b = [row["entry"]["id"] for row in loud.recall(PLAIN_QUERY, budget=5,
                                                       vector=QUERY_VECTOR)]
        self.assertEqual(a, b)
        self.assertIsNone(loud._last_spatial)

    def test_explicit_spatial_switch_forces_the_stage(self):
        far, near = pair()
        e = engine([far, near])
        rows = e.recall(PLAIN_QUERY, budget=5, vector=QUERY_VECTOR, spatial=True)
        self.assertEqual(rows[0]["entry"]["id"], "near")
        self.assertEqual(e._last_spatial["mode"], "weighted")


if __name__ == "__main__":
    unittest.main()
