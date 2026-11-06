# -*- coding: utf-8 -*-
"""point_expand: hits first, then the neighbours of each hit.

The hit layer is unchanged (embedding + lexical + rerank). Expansion only
grows the immediate neighbourhood of a hit inside its own event segment;
entries without an event_id never expand; the token budget drops expanded
lines before it drops a hit.
"""
import json
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.recall import point_expand  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

HEADER = "\u4f60\u8bb0\u5f97\u8fd9\u4e9b\u4e8b\uff1a"


def ts(h, mi):
    return datetime(2026, 3, 5, h, mi).timestamp()


def entry(entry_id, text, stamp, event_id="", index=0):
    row = {"id": entry_id, "text": text, "role": "user", "ts": stamp,
           "scope": "default", "event_index": index}
    if event_id:
        row["event_id"] = event_id
    return row


def segment_five():
    return [entry("a%d" % index, "\u4e8b\u4ef6\u4e00\u7684\u7b2c\u4e8c\u6761".replace("\u4e8c", "\u4e00") if False else
                 "\u4e8b\u4ef6\u4e00\u7684\u7b2c%d\u6761" % (index + 1),
                 ts(9, index), "E1", index) for index in range(5)]


def store_with(rows, flags=None):
    root = tempfile.mkdtemp()
    if flags:
        Path(root, "flags.json").write_text(json.dumps(flags), encoding="utf-8")
    path = Path(root) / "sessions" / "s1" / "memory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"entries": rows}), encoding="utf-8")
    return root


def entries_of(root):
    return pipeline.load_memory(root, "s1").get("entries") or []


def texts_of(root):
    return {row["id"]: row["text"] for row in entries_of(root)}


class FakeRerank:
    """Stand-in for the existing rerank client: text -> relevance score."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def rerank_documents(self, query, texts, config, **kwargs):
        self.calls.append(list(texts))
        rows = [{"index": index,
                 "relevance_score": self.mapping.get(text, 0.0)}
                for index, text in enumerate(texts)]
        rows.sort(key=lambda row: -row["relevance_score"])
        return rows


def expand(hits, root, radius=1, budget=1500, rerank=False, query="",
           limit=None, rerank_config=None):
    return pipeline._inject_point_expand(
        "s1", root, hits, HEADER, True,
        {"point_expand_radius": radius, "point_expand_tokens": budget,
         "point_expand_rerank": rerank},
        query=query, limit=limit, rerank_config=rerank_config)


class ExpansionTest(unittest.TestCase):
    """What grows around a hit."""

    def test_only_the_neighbours_of_a_hit_are_added(self):
        root = store_with(segment_five())
        hit = [row for row in entries_of(root) if row["id"] == "a2"][0]
        out = expand([hit], root)
        self.assertEqual(out["point"]["hits"], 1)
        self.assertEqual(out["point"]["expanded"], 2)
        self.assertEqual(out["point"]["lines"], 3)
        self.assertEqual([row["id"] for row in entries_of(root)
                          if row["id"] in out["ids"]], ["a1", "a2", "a3"])

    def test_radius_two_reaches_further(self):
        root = store_with(segment_five())
        hit = [row for row in entries_of(root) if row["id"] == "a2"][0]
        out = expand([hit], root, radius=2)
        self.assertEqual(out["point"]["expanded"], 4)
        self.assertEqual(out["point"]["lines"], 5)

    def test_two_hits_share_a_neighbour_without_duplicating(self):
        root = store_with(segment_five())
        rows = entries_of(root)
        hits = [row for row in rows if row["id"] in ("a1", "a2")]
        out = expand(hits, root)
        self.assertEqual(len(out["ids"]), len(set(out["ids"])))
        self.assertEqual(sorted(out["ids"]), ["a0", "a1", "a2", "a3"])

    def test_a_boundary_hit_has_only_the_inner_neighbour(self):
        root = store_with(segment_five())
        hit = [row for row in entries_of(root) if row["id"] == "a0"][0]
        out = expand([hit], root)
        self.assertEqual(out["point"]["expanded"], 1)
        self.assertEqual(sorted(out["ids"]), ["a0", "a1"])

    def test_an_entry_without_event_id_is_not_expanded(self):
        rows = [entry("s1", "\u5b64\u7acb\u7684\u4e00\u6761", ts(9, 0)),
                entry("s2", "\u53e6\u4e00\u6761\u5b64\u7acb", ts(9, 1))]
        root = store_with(rows)
        hit = [row for row in entries_of(root) if row["id"] == "s1"][0]
        out = expand([hit], root)
        self.assertEqual(out["point"]["expanded"], 0)
        self.assertEqual(out["ids"], ["s1"])

    def test_a_missing_event_id_on_the_hit_is_not_an_error(self):
        rows = segment_five()
        root = store_with(rows)
        hit = dict(entries_of(root)[2])
        hit.pop("event_id", None)
        out = expand([hit], root)
        self.assertTrue(out["point"] is not None)
        self.assertEqual(out["point"]["expanded"], 0)

    def test_segments_are_ordered_by_their_best_hit(self):
        rows = segment_five() + [entry("b0", "\u4e8b\u4ef6\u4e8c", ts(8, 0), "E2", 0)]
        root = store_with(rows)
        by_id = {row["id"]: row for row in entries_of(root)}
        out = expand([by_id["b0"], by_id["a2"]], root)
        self.assertEqual(out["ids"][0], "b0")
        self.assertEqual([row for row in out["ids"] if row.startswith("a")],
                         ["a1", "a2", "a3"])

    def test_the_budget_drops_expanded_lines_first(self):
        root = store_with(segment_five())
        hit = [row for row in entries_of(root) if row["id"] == "a2"][0]
        out = expand([hit], root, radius=2, budget=50)
        self.assertIn("a2", out["ids"])          # a hit is never dropped
        self.assertEqual(out["point"]["hits"], 1)
        self.assertGreaterEqual(out["point"]["dropped_expanded"], 1)
        self.assertLess(len(out["ids"]), 3)      # one neighbour was cut


class HostTest(unittest.TestCase):
    """The switch, the prefix and the state block."""

    def test_the_switch_off_is_the_old_path(self):
        rows = segment_five()
        off = pipeline.inject_block("s1", store_with(rows), max_chars=600,
                                   top_k=2, mode="recent",
                                   payload={"point_expand": False})
        self.assertNotIn("point", off)
        self.assertEqual(len(off["ids"]), 2)

    def test_the_date_prefix_survives_in_the_block(self):
        root = store_with(segment_five())
        out = pipeline.inject_block("s1", root, max_chars=600, top_k=1,
                                    mode="recent",
                                    payload={"point_expand": True,
                                             "point_expand_rerank": False})
        self.assertIn("[2026-03-05 09:04]", out["text"])
        self.assertIn("[2026-03-05 09:03]", out["text"])

    def test_state_reports_the_counters(self):
        root = store_with(segment_five())
        pipeline.inject_block("s1", root, max_chars=600, top_k=1,
                              mode="recent",
                              payload={"point_expand": True,
                                       "point_expand_rerank": False})
        state = pipeline.dispatch("state", {"session_id": "s1", "store": root})
        info = state["state"]["point_expand"]
        self.assertIn("hits", info)
        self.assertIn("expanded", info)
        self.assertIn("lines", info)
        self.assertIn("tokens", info)
        self.assertIn("dropped_expanded", info)
        self.assertEqual(info["hits"], 1)
        self.assertEqual(info["lines"], 2)


class RerankOrderTest(unittest.TestCase):
    """v12: expand, rerank the pool, hits guaranteed, then order."""

    def cfg(self):
        return {"rerank_enabled": True, "base_url": "http://localhost"}

    def test_the_neighbour_joins_the_rerank_pool(self):
        root = store_with(segment_five())
        texts = texts_of(root)
        hit = [row for row in entries_of(root) if row["id"] == "a2"][0]
        fake = FakeRerank({texts["a1"]: 0.9, texts["a2"]: 0.8,
                          texts["a3"]: 0.1})
        with mock.patch.object(pipeline, "_rerank_mod", fake):
            out = expand([hit], root, rerank=True, query="q", limit=3,
                         rerank_config=self.cfg())
        self.assertEqual(fake.calls, [[texts["a2"], texts["a1"],
                                       texts["a3"]]])
        self.assertIn("a1", out["ids"])
        self.assertEqual(out["point"]["reranked"]["pool"], 3)

    def test_an_irrelevant_neighbour_is_dropped(self):
        root = store_with(segment_five())
        texts = texts_of(root)
        hit = [row for row in entries_of(root) if row["id"] == "a2"][0]
        fake = FakeRerank({texts["a2"]: 0.9, texts["a1"]: 0.4,
                          texts["a3"]: 0.1, texts["a0"]: 0.05,
                          texts["a4"]: 0.05})
        with mock.patch.object(pipeline, "_rerank_mod", fake):
            out = expand([hit], root, radius=2, rerank=True, query="q",
                         limit=2, rerank_config=self.cfg())
        self.assertIn("a2", out["ids"])
        self.assertIn("a1", out["ids"])
        self.assertNotIn("a0", out["ids"])
        self.assertNotIn("a3", out["ids"])
        self.assertGreaterEqual(out["point"]["reranked"]["dropped"], 1)

    def test_a_hit_is_never_pushed_out_by_a_neighbour(self):
        root = store_with(segment_five())
        rows = entries_of(root)
        hits = [row for row in rows if row["id"] in ("a0", "a1")]
        fake = FakeRerank({"t1": 0.9, "t2": 0.8, "t3": 0.7, "t0": 0.1})
        with mock.patch.object(pipeline, "_rerank_mod", fake):
            out = expand(hits, root, rerank=True, query="q", limit=2,
                         rerank_config=self.cfg())
        self.assertEqual(sorted(out["ids"]), ["a0", "a1"])
        self.assertEqual(out["point"]["reranked"]["kept"], 2)

    def test_without_a_reranker_only_the_hits_go_in(self):
        root = store_with(segment_five())
        hit = [row for row in entries_of(root) if row["id"] == "a2"][0]
        with mock.patch.object(pipeline, "_rerank_mod", None):
            out = expand([hit], root, rerank=True, query="q", limit=3)
        self.assertEqual(out["ids"], ["a2"])
        self.assertEqual(out["point"]["expanded"], 0)
        self.assertEqual(out["point"]["reranked"]["dropped"], 2)

    def test_the_pool_dedupes_a_shared_neighbour(self):
        root = store_with(segment_five())
        rows = entries_of(root)
        hits = [row for row in rows if row["id"] in ("a1", "a2")]
        fake = FakeRerank({"t0": 0.9, "t1": 0.8, "t2": 0.7, "t3": 0.6})
        with mock.patch.object(pipeline, "_rerank_mod", fake):
            out = expand(hits, root, rerank=True, query="q", limit=4,
                         rerank_config=self.cfg())
        self.assertEqual(len(fake.calls[0]), len(set(fake.calls[0])))
        self.assertEqual(out["point"]["reranked"]["pool"], 4)

    def test_the_switch_off_keeps_the_v11_order(self):
        root = store_with(segment_five())
        hit = [row for row in entries_of(root) if row["id"] == "a2"][0]
        fake = FakeRerank({"t2": 0.9})
        with mock.patch.object(pipeline, "_rerank_mod", fake):
            out = expand([hit], root, rerank=False, query="q", limit=3,
                         rerank_config=self.cfg())
        self.assertEqual(fake.calls, [])
        self.assertIn("a1", out["ids"])

    def test_the_state_carries_the_reranked_block(self):
        root = store_with(segment_five())
        fake = FakeRerank({"t4": 0.9, "t3": 0.8})
        with mock.patch.object(pipeline, "_rerank_mod", fake):
            pipeline.inject_block("s1", root, max_chars=600, top_k=2,
                                  mode="recent",
                                  payload={"point_expand": True},
                                  rerank_config=self.cfg())
        state = pipeline.dispatch("state", {"session_id": "s1", "store": root})
        block = state["state"]["point_expand"]
        self.assertIn("reranked", block)
        self.assertIn("pool", block["reranked"])
        self.assertIn("kept", block["reranked"])
        self.assertIn("dropped", block["reranked"])

if __name__ == "__main__":
    unittest.main()
