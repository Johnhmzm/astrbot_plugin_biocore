# -*- coding: utf-8 -*-
"""spatial_cover_select: pick k from the pool by five-axis spread, not rank.

MMR (Carbonell & Goldstein 1998) with the redundancy term replaced by the
space distance. The pool and the rerank scores are untouched; only the choice
of which k go into the block changes.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.recall import cover  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402


def entry(entry_id, text, stamp, event_id="", index=0):
    row = {"id": entry_id, "text": text, "role": "user", "ts": stamp,
           "scope": "default", "event_index": index}
    if event_id:
        row["event_id"] = event_id
    return row


def store_with(rows, flags=None):
    root = tempfile.mkdtemp()
    if flags:
        Path(root, "flags.json").write_text(json.dumps(flags), encoding="utf-8")
    path = Path(root) / "sessions" / "s1" / "memory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"entries": rows}), encoding="utf-8")
    return root


def ts(mi):
    return datetime(2026, 3, 5, 9, mi).timestamp()


class SelectTest(unittest.TestCase):
    """The MMR loop itself."""

    def pool(self):
        return [entry("a", "a", ts(0)), entry("b", "b", ts(1)),
                entry("c", "c", ts(2)), entry("d", "d", ts(3))]

    def test_the_first_pick_is_the_highest_score(self):
        picked, stats = cover.select(self.pool(), [0.1, 0.9, 0.5, 0.2], 2)
        self.assertEqual(picked[0]["id"], "b")
        self.assertEqual(stats["kept"], 2)

    def test_lambda_zero_is_plain_score_order(self):
        picked, _ = cover.select(self.pool(), [0.1, 0.9, 0.5, 0.2], 3, 0.0)
        self.assertEqual([row["id"] for row in picked], ["b", "c", "d"])

    def test_a_larger_lambda_buys_spread(self):
        # score(i) = rel(i) + lambda * min_j dist_space(i, j): distance =
        # 1 - similarity, so a larger lambda spreads the chosen set.
        def dist(left, right):
            if left['id'] == right['id']:
                return 0.0
            if 'a' in (left['id'], right['id']):
                other = right if left['id'] == 'a' else left
                return 0.1 if other['id'] == 'b' else 1.0
            return 0.5
        plain, plain_stats = cover.select(self.pool(), [1.0, 0.9, 0.5, 0.1], 2,
                                           0.0, dist)
        spread, spread_stats = cover.select(self.pool(), [1.0, 0.9, 0.5, 0.1], 2,
                                            1.0, dist)
        self.assertEqual([row["id"] for row in plain], ["a", "b"])
        self.assertGreater(spread_stats["avg_pairwise_dist"],
                           plain_stats["avg_pairwise_dist"])

    def test_entries_without_coordinates_do_not_crash(self):
        picked, stats = cover.select(self.pool(), [1.0, 0.5, 0.4, 0.3], 2,
                                     0.9, lambda left, right: 0.0)
        self.assertEqual(len(picked), 2)
        self.assertEqual(stats["kept"], 2)

    def test_k_larger_than_the_pool_returns_the_pool(self):
        picked, stats = cover.select(self.pool(), [1, 2, 3, 4], 10)
        self.assertEqual(len(picked), 4)
        self.assertEqual(stats["dropped_by_cover"], 0)

    def test_dropped_counts_what_was_not_selected(self):
        _, stats = cover.select(self.pool(), [1, 2, 3, 4], 2)
        self.assertEqual(stats["pool"], 4)
        self.assertEqual(stats["kept"], 2)
        self.assertEqual(stats["dropped_by_cover"], 2)


class HostTest(unittest.TestCase):
    """The switch, the block and the state."""

    def rows(self):
        return [entry("e1a", "\u5f20\u4e09\u7ea6\u5468\u4e94\u770b\u7535\u5f71", ts(0), "E1", 0),
                entry("e1b", "\u5f20\u4e09\u8bf4\u8981\u4e70\u4e24\u5f20\u7968", ts(1), "E1", 1),
                entry("e2a", "\u5c0f\u674e\u8bf4\u660e\u5929\u4e0b\u96e8", ts(2), "E2", 0),
                entry("e2b", "\u5c0f\u674e\u63d0\u4e86\u5e26\u4f1e", ts(3), "E2", 1)]

    def test_switch_off_is_the_old_path(self):
        root = store_with(self.rows())
        out = pipeline.inject_block("s1", root, max_chars=600, top_k=2,
                                    mode="recent",
                                    payload={"spatial_cover_select": False})
        self.assertNotIn("cover", out)
        self.assertEqual(len(out["ids"]), 2)

    def test_switch_on_selects_with_the_cover_block(self):
        root = store_with(self.rows())
        out = pipeline.inject_block("s1", root, max_chars=600, top_k=2,
                                    mode="recent",
                                    payload={"spatial_cover_select": True})
        self.assertIn("cover", out)
        self.assertEqual(out["cover"]["kept"], 2)
        self.assertEqual(out["cover"]["pool"], 4)
        self.assertIn("[2026-03-05 09:", out["text"])

    def test_the_ids_are_unique_and_from_the_pool(self):
        root = store_with(self.rows())
        out = pipeline.inject_block("s1", root, max_chars=600, top_k=3,
                                    mode="recent",
                                    payload={"spatial_cover_select": True})
        self.assertEqual(len(out["ids"]), len(set(out["ids"])))
        pool = {row["id"] for row in self.rows()}
        self.assertTrue(set(out["ids"]) <= pool)

    def test_the_block_is_ordered_by_segment_then_time(self):
        root = store_with(self.rows())
        out = pipeline.inject_block("s1", root, max_chars=600, top_k=4,
                                    mode="recent",
                                    payload={"spatial_cover_select": True})
        positions = {row["id"]: row["ts"] for row in self.rows()}
        stamps = [positions[entry_id] for entry_id in out["ids"]]
        self.assertEqual(stamps, sorted(stamps))

    def test_state_reports_the_cover_block(self):
        root = store_with(self.rows())
        pipeline.inject_block("s1", root, max_chars=600, top_k=2,
                              mode="recent",
                              payload={"spatial_cover_select": True})
        state = pipeline.dispatch("state", {"session_id": "s1", "store": root})
        info = state["state"]["cover_select"]
        for key in ("pool", "kept", "lambda", "avg_pairwise_dist",
                    "dropped_by_cover"):
            self.assertIn(key, info)
        self.assertEqual(info["kept"], 2)

    def test_the_debug_action_compares_old_and_cover(self):
        root = store_with(self.rows())
        out = pipeline.dispatch("cover_select", {"session_id": "s1",
                                                 "store": root,
                                                 "query": "\u5f20\u4e09",
                                                 "limit": 2})
        self.assertTrue(out["ok"])
        self.assertIn("old", out)
        self.assertIn("cover", out)
        self.assertTrue(set(out["cover"]) <= set(out["pool"]))


if __name__ == "__main__":
    unittest.main()
