# -*- coding: utf-8 -*-
"""task-62: normalized channels, chunks, shards, predictive exploration."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from biocore_runtime import pipeline, retrieval_plus as rp


def entry(i, text, ts=None):
    return {"id": i, "text": text, "role": "user",
            "ts": ts if ts is not None else time.time()}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.store = self.data_dir / "memory"
        (self.store / "sessions" / "s1").mkdir(parents=True)
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()


class NormalizeTest(Case):
    def test_min_max(self):
        self.assertEqual(rp.normalize([0.0, 5.0, 10.0]), [0.0, 0.5, 1.0])

    def test_flat_positive_is_one(self):
        self.assertEqual(rp.normalize([2.0, 2.0]), [1.0, 1.0])

    def test_flat_zero_is_zero(self):
        self.assertEqual(rp.normalize([0.0, 0.0]), [0.0, 0.0])

    def test_channels_are_independent(self):
        rows = [entry("a", "苹果 苹果 苹果"), entry("b", "香蕉")]
        ranked = rp.rank(self.store, "s1", "苹果", rows, now=self.now)
        by_id = {item["entry"]["id"]: item for item in ranked}
        self.assertEqual(by_id["a"]["channels"]["bm25"], 1.0)
        self.assertEqual(by_id["b"]["channels"]["bm25"], 0.0)
        self.assertIn("vector", by_id["a"]["channels"])


class ChunkTest(Case):
    def test_sentences_split(self):
        chunks = rp.split_chunks("第一句。第二句！第三句？")
        self.assertEqual(len(chunks), 3)

    def test_index_persists(self):
        rp.build_chunks(self.store, [entry("a", "第一句。第二句。")])
        doc = json.loads((self.data_dir / "retrieval" / "chunks.json")
                         .read_text(encoding="utf-8"))
        self.assertIn("a", doc["entries"])
        self.assertEqual(len(doc["entries"]["a"]["chunks"]), 2)

    def test_best_chunk_snippet(self):
        rows = [entry("a", "今天很累。苹果很甜，想再买一次。")]
        ranked = rp.rank(self.store, "s1", "苹果", rows, now=self.now)
        self.assertIn("苹果", ranked[0]["chunk"])
        self.assertGreaterEqual(ranked[0]["chunk_hits"], 1)


class ShardTest(Case):
    def test_session_shard(self):
        shards = rp.assign_shards(self.store, [entry("a", "x")], session_id="s1")
        self.assertEqual(shards["a"], "s-s1")
        self.assertTrue((self.data_dir / "retrieval" / "shards"
                         / "s-s1.json").exists())

    def test_month_shard_without_session(self):
        row = entry("a", "x", ts=time.mktime((2024, 3, 15, 12, 0, 0, 0, 0, -1)))
        shards = rp.assign_shards(self.store, [row])
        self.assertEqual(shards["a"], "2024-03")

    def test_rollover_over_cap(self):
        rows = [entry(str(index), "x") for index in range(5)]
        shards = rp.assign_shards(self.store, rows, session_id="s1", limit=2)
        names = list(shards.values())
        self.assertEqual(names.count("s-s1"), 2)
        self.assertIn("s-s1-r1", names)
        self.assertIn("s-s1-r2", names)


class PredictionTest(Case):
    def test_expectation_weights(self):
        rp.record_query(self.store, "苹果 咖啡")
        rp.record_query(self.store, "苹果 咖啡 甜")
        rows = [entry("expected", "苹果 咖啡"), entry("novel", "维修 螺丝")]
        ranked = rp.rank(self.store, "s1", "苹果", rows, now=self.now)
        by_id = {item["entry"]["id"]: item for item in ranked}
        self.assertGreater(by_id["novel"]["expectation_weight"],
                           by_id["expected"]["expectation_weight"])

    def test_topic_history_bounded(self):
        for index in range(25):
            rp.record_query(self.store, "话题%d" % index)
        doc = json.loads((self.data_dir / "topic_history.json")
                         .read_text(encoding="utf-8"))
        self.assertEqual(len(doc["turns"]), 20)

    def test_off_fallback(self):
        rows = [entry("a", "苹果"), entry("b", "香蕉")]
        ranked = rp.rank(self.store, "s1", "苹果", rows, now=self.now,
                         enabled=False)
        self.assertEqual([item["entry"]["id"] for item in ranked], ["a", "b"])
        self.assertEqual(ranked[0]["reason"], "fallback")


class DebugTest(Case):
    def test_debug_rows_and_state(self):
        rows = [entry("a", "苹果很甜"), entry("b", "香蕉")]
        ranked = rp.rank(self.store, "s1", "苹果", rows, now=self.now)
        rp.record_debug(self.store, "苹果", ranked, now=self.now)
        summary = rp.summary(self.store)
        self.assertEqual(summary["query"], "苹果")
        for key in ("channels", "reason", "chunk", "chunk_hits", "shard"):
            self.assertIn(key, summary["rows"][0])
        body = pipeline.dispatch("state", {
            "store": str(self.store), "session_id": "s1",
            "persona_profile": str(Path(self.tmp.name) / "missing.json")})["state"]
        self.assertIn("recall_debug", body)

    def test_switch_off_keeps_engine_order(self):
        rows = [entry("old", "苹果 很甜", ts=self.now - 100),
                entry("new", "苹果 今天", ts=self.now)]
        (self.store / "sessions" / "s1" / "memory.json").write_text(
            json.dumps({"entries": rows}), encoding="utf-8")
        on = pipeline.inject_block("s1", str(self.store), query="苹果",
                                   mode="query", top_k=2)
        path = self.data_dir / "core_config.json"
        path.write_text(json.dumps({"switches": {"retrieval_plus": False}}),
                        encoding="utf-8")
        off = pipeline.inject_block("s1", str(self.store), query="苹果",
                                    mode="query", top_k=2)
        self.assertEqual(len(on["ids"]), len(off["ids"]))


if __name__ == "__main__":
    unittest.main()
