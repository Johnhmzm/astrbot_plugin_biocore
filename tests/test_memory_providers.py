# -*- coding: utf-8 -*-
"""Pluggable embedding/rerank providers: dimension safety and scoring kinds.

Two things are proven here and nothing else is:
  1. vectors from two models/dimensions can never be mixed silently -- reading a
     store built for another space raises, and rebuild() is the way out;
  2. the rerank scoring kind is configuration, and the two kinds order the same
     response differently (that difference is the bug this key prevents).
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.recall import providers as prov  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402


def embed_transport(dim):
    """OpenAI-compatible /embeddings answer of a fixed dimension."""
    def call(url, payload, timeout, headers):
        rows = [{"embedding": [0.01 * (i + 1) for i in range(dim)]}
                for _text in payload.get("input") or []]
        return 200, json.dumps({"data": rows}).encode("utf-8")
    return call


class MockEmbedder:
    """Provider protocol only: embed(texts) -> vectors."""

    model = "mock"

    def __init__(self, dim):
        self.dim = dim
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[0.5] * self.dim for _ in texts]


class EmbeddingDimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = self.tmp.name
        # the loader reads core_config.json (configure() writes it); config.json is
        # the older name, so the test seeds the file the runtime actually reads
        self.config = Path(self.store) / "core_config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _set_model(self, model, dim):
        self.config.write_text(json.dumps(
            {"embedding": {"model": model, "dim": dim, "base_url": "http://x/v1"}}),
            encoding="utf-8")

    def test_a_dimension_change_is_refused_with_an_actionable_error(self):
        self._set_model("m-1024", 1024)
        pipeline.ensure_vector_space(self.store, "s1")
        meta = pipeline._read_vector_meta(self.store, "s1")
        self.assertEqual(meta["dim"], "1024")
        self.assertEqual(meta["embed_model"], "m-1024")

        self._set_model("m-768", 768)
        with self.assertRaises(prov.EmbeddingSpaceMismatch) as caught:
            pipeline.ensure_vector_space(self.store, "s1")
        message = str(caught.exception)
        self.assertIn("1024", message)
        self.assertIn("768", message)
        self.assertIn("reembed", message)          # the way out is in the error

    def test_rebuild_moves_the_store_to_the_new_space(self):
        self._set_model("m-1024", 1024)
        pipeline.ensure_vector_space(self.store, "s1")
        pipeline.tool_call("remember", {"text": "一条足够长的记忆内容", "ts": 1.79e9},
                           self.store, session_id="s1")
        self._set_model("m-768", 768)
        with self.assertRaises(prov.EmbeddingSpaceMismatch):
            pipeline.ensure_vector_space(self.store, "s1")

        mock = MockEmbedder(768)
        result = pipeline.reembed_store(self.store, "s1", provider=mock)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["dim"], 768)
        meta = pipeline._read_vector_meta(self.store, "s1")
        self.assertEqual(meta["dim"], "768")
        self.assertEqual(meta["embed_model"], "m-768")
        pipeline.ensure_vector_space(self.store, "s1")     # no longer raises
        vectors = pipeline._entry_vectors(self.store, "s1")
        self.assertTrue(vectors)
        self.assertEqual(len(next(iter(vectors.values()))), 768)

    def test_the_provider_rejects_a_wrong_dimension_before_any_write(self):
        adapter = prov.OpenAICompatEmbeddings(
            {"base_url": "http://x/v1", "model": "m", "dim": 1024},
            transport=embed_transport(768))
        with self.assertRaises(prov.ProviderError) as caught:
            adapter.embed(["hello"])
        self.assertIn("768", str(caught.exception))
        self.assertIn("1024", str(caught.exception))

    def test_the_provider_batches_and_keeps_order(self):
        seen = []

        def call(url, payload, timeout, headers):
            seen.append(len(payload["input"]))
            return embed_transport(4)(url, payload, timeout, headers)

        adapter = prov.OpenAICompatEmbeddings(
            {"base_url": "http://x/v1", "model": "m", "dim": 4, "batch_size": 2},
            transport=call)
        vectors = adapter.embed(["a", "b", "c", "d", "e"])
        self.assertEqual(len(vectors), 5)
        self.assertEqual(seen, [2, 2, 1])          # batching respects the config


class RerankScoringTest(unittest.TestCase):
    """One response, two declared scoring kinds, two different orders."""

    DOCS = ["文档甲", "文档乙"]
    # 甲: a high logit margin but a low relevance score; 乙 the opposite
    PAYLOAD_A = {"index": 0, "relevance_score": 0.30, "logits": [-1.0, 5.0]}
    PAYLOAD_B = {"index": 1, "relevance_score": 0.80, "logits": [5.0, -1.0]}

    def _transport(self, want):
        def call(url, payload, timeout, headers):
            if want == "score":
                results = [{"index": 0, "relevance_score": 0.30},
                           {"index": 1, "relevance_score": 0.80}]
            else:
                results = [{"index": 0, "logits": [-1.0, 5.0]},
                           {"index": 1, "logits": [5.0, -1.0]}]
            return 200, json.dumps({"results": results}).encode("utf-8")
        return call

    def _order(self, scoring):
        adapter = prov.RerankProvider(
            {"enabled": True, "base_url": "http://x/v1", "model": "r",
             "scoring": scoring}, transport=self._transport(
                 "score" if scoring == "score_array" else "logit"))
        scores = adapter.rerank("问题", self.DOCS, top_k=2)
        return [index for index, _score in
                sorted(enumerate(scores), key=lambda pair: -pair[1])]

    def test_score_array_orders_by_relevance(self):
        self.assertEqual(self._order("score_array"), [1, 0])

    def test_logit_margin_orders_by_the_margin(self):
        # same query, same docs: the margin puts 甲 first, the raw score 乙
        self.assertEqual(self._order("logit_margin"), [0, 1])

    def test_reading_a_logit_answer_as_a_score_would_invert_the_order(self):
        adapter = prov.RerankProvider(
            {"enabled": True, "base_url": "http://x/v1", "model": "r",
             "scoring": "score_array"}, transport=self._transport("logit"))
        with self.assertRaises(prov.ProviderError):
            adapter.rerank("问题", self.DOCS)

    def test_an_unknown_scoring_kind_is_rejected_not_guessed(self):
        with self.assertRaises(prov.UnknownScoring):
            prov.resolve_rerank_config({"scoring": "magic"})

    def test_probability_pair_is_read_as_log_odds(self):
        score = prov.RerankProvider({})._logit_margin({"scores": [0.1, 0.9]})
        self.assertAlmostEqual(score, 2.1972245, places=5)


class ConfigTest(unittest.TestCase):
    def test_defaults_are_one_explicit_combination(self):
        embed = prov.resolve_embedding_config({})
        rerank = prov.resolve_rerank_config({})
        self.assertEqual(embed["model"], "BAAI/bge-m3")
        self.assertEqual(embed["dim"], 1024)
        self.assertEqual(rerank["model"], "BAAI/bge-reranker-v2-m3")
        self.assertEqual(rerank["scoring"], "score_array")

    def test_the_old_flat_rerank_keys_still_work(self):
        cfg = prov.resolve_rerank_config({
            "rerank_enabled": True, "rerank_model": "m", "rerank_scoring": "logit_margin"})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["model"], "m")
        self.assertEqual(cfg["scoring"], "logit_margin")


if __name__ == "__main__":
    unittest.main()
