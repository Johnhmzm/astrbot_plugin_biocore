# -*- coding: utf-8 -*-
"""task-244 ②: vectors on write, rerank as an optional recall stage, A/B/C/D bench.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_spatial_recall.py"
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from biocore_memory import space as sp
from biocore_runtime import pipeline as pl


NOW = 1700000000.0


class FakeProvider:
    mode = "remote"
    model = "fake-embed"

    def embed_text(self, text):
        return [0.1, 0.2, 0.3]


def fake_rerank(order):
    """A rerank_documents stand-in: documents are reordered by the given list."""
    calls = []

    def call(query, documents, config=None, transport=None, on_reason=None):
        calls.append({"query": query, "documents": list(documents or []),
                      "config": dict(config or {})})
        return [{"index": index, "document": documents[index],
                 "relevance_score": 1.0 - index * 0.1}
                for index in order if 0 <= index < len(documents)]
    call.calls = calls
    return call


class SpatialBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self.store.mkdir(parents=True, exist_ok=True)
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")
        self._saved = {key: os.environ.pop(key, None) for key in
                       ("BIOCORE_SPATIAL_RECALL", "BIOCORE_SPATIAL_RERANK",
                        "BIOCORE_RERANK_BASE_URL", "BIOCORE_RERANK_MODEL")}

    def tearDown(self):
        self.tmp.cleanup()
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def flags(self, **values):
        (self.store / "flags.json").write_text(json.dumps(values),
                                               encoding="utf-8")

    def remember(self, text, session="s1", **extra):
        args = {"text": text, "ts": NOW}
        args.update(extra)
        return pl.tool_call("remember", args, str(self.store), session_id=session)

    def entries(self, session="s1"):
        # sqlite is the store now: ask the pipeline for the JSON view
        return pl.export_session_json(str(self.store), session)["entries"]

    def seed(self, session="s1"):
        for text, tags in (("我的猫叫团子，三岁", ["猫"]),
                           ("今天加班到很晚", ["工作"]),
                           ("周末想去看海", ["旅行"])):
            self.remember(text, session=session, tags=tags)


class VectorOnWriteTest(SpatialBase):
    """Item 1: the remember path keeps the embedding, or says it fell back."""

    def test_vector_is_written_when_a_provider_exists(self):
        self.flags(spatial_recall=True)
        with mock.patch("biocore_memory.recall.embedding.load_provider",
                        return_value=FakeProvider()), \
                mock.patch("biocore_memory.recall.embedding.embed",
                           return_value=[0.1, 0.2, 0.3]):
            self.remember("我的猫叫团子")
        entry = self.entries()[0]
        self.assertEqual(entry["vector"], [0.1, 0.2, 0.3])
        semantic = entry["space"]["semantic"]
        self.assertEqual(semantic["vector"], [0.1, 0.2, 0.3])
        self.assertEqual(semantic["vector_dim"], 3)
        self.assertFalse(semantic["fallback"])
        self.assertEqual(semantic["provider"], "remote")
        self.assertEqual(semantic["model"], "fake-embed")

    def test_no_provider_falls_back_to_tags_and_says_so(self):
        self.flags(spatial_recall=True)
        with mock.patch("biocore_memory.recall.embedding.load_provider",
                        return_value=None):
            self.remember("我的猫叫团子", tags=["猫"])
        entry = self.entries()[0]
        self.assertNotIn("vector", entry)
        semantic = entry["space"]["semantic"]
        self.assertEqual(semantic["vector"], [])
        self.assertEqual(semantic["vector_dim"], 0)
        self.assertTrue(semantic["fallback"])     # never pretends
        self.assertIn("猫", semantic["topics"])

    def test_switch_off_skips_the_embedding_call(self):
        called = []
        with mock.patch("biocore_memory.recall.embedding.load_provider",
                        side_effect=lambda *a, **k: called.append(1) or FakeProvider()):
            self.remember("我的猫叫团子")
        self.assertEqual(called, [])


class RerankStageTest(SpatialBase):
    """Item 2: rerank is an optional recall post-stage, silent on failure."""

    def setUp(self):
        super().setUp()
        # two entries share 加班, so the candidate list has something to reorder
        for text, tags in (("我的猫叫团子，三岁", ["猫"]),
                           ("今天加班到很晚", ["工作"]),
                           ("周末还要加班", ["工作"])):
            self.remember(text, tags=tags)
        self.ids = [entry["id"] for entry in self.entries()]

    def recall(self, query="加班", **extra):
        payload = {"query": query, "limit": 3}
        payload.update(extra)
        return pl.tool_call("recall", payload, str(self.store), session_id="s1")

    def test_off_by_default_keeps_the_old_order(self):
        out = self.recall()
        self.assertFalse(out["retrieval"]["enabled"])
        self.assertFalse(out["retrieval"]["reranked"])
        self.assertEqual(out["retrieval"]["reason"], "disabled")
        self.assertIn("加班", out["results"][0]["text"])
        last = pl._retrieval_last(str(self.store))
        self.assertEqual(last["stage"], "recall")
        self.assertFalse(last["reranked"])

    def test_on_reorders_the_candidates(self):
        self.flags(spatial_rerank=True)
        fake = fake_rerank([2, 1, 0])
        with mock.patch.object(pl._rerank_mod, "rerank_documents", fake):
            out = self.recall()
        self.assertTrue(out["retrieval"]["enabled"])
        self.assertTrue(out["retrieval"]["reranked"])
        self.assertEqual(out["retrieval"]["reason"], "ok")
        self.assertEqual([row["id"] for row in out["results"]],
                         [self.ids[2], self.ids[1]])
        self.assertIn("rerank_score", out["results"][0])

    def test_a_failing_rerank_returns_the_original_order(self):
        self.flags(spatial_rerank=True)

        def boom(*args, **kwargs):
            raise RuntimeError("down")
        with mock.patch.object(pl._rerank_mod, "rerank_documents", boom):
            out = self.recall()
        self.assertFalse(out["retrieval"]["reranked"])
        self.assertEqual(out["retrieval"]["reason"], "error")
        self.assertIn("加班", out["results"][0]["text"])

    def test_missing_config_is_a_silent_fallback(self):
        self.flags(spatial_rerank=True)
        # no BIOCORE_RERANK_BASE_URL / MODEL and no rerank block in config
        out = self.recall()
        self.assertTrue(out["retrieval"]["enabled"])
        self.assertFalse(out["retrieval"]["reranked"])
        self.assertEqual(out["retrieval"]["reason"], "missing_config")

    def test_real_module_with_a_dead_transport_falls_back(self):
        self.flags(spatial_rerank=True)
        os.environ["BIOCORE_RERANK_BASE_URL"] = "http://127.0.0.1:9"
        os.environ["BIOCORE_RERANK_MODEL"] = "fake"

        def dead(url, payload, timeout, headers):
            raise ConnectionError("no route")
        rows = [{"id": "a", "text": "今天加班到很晚"},
                {"id": "b", "text": "周末想去看海"}]
        ordered, status = pl._rerank_rows(str(self.store), "加班", rows,
                                          {"session_id": "s1"},
                                          transport=dead)
        self.assertEqual([row["id"] for row in ordered], ["a", "b"])
        self.assertFalse(status["reranked"])
        self.assertEqual(status["reason"], "request_failed")

    def test_state_exposes_retrieval_last(self):
        self.flags(spatial_rerank=True)
        fake = fake_rerank([1, 0])
        with mock.patch.object(pl._rerank_mod, "rerank_documents", fake):
            self.recall()
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store)})["state"]
        last = shown["retrieval_last"]
        self.assertEqual(last["stage"], "recall")
        self.assertTrue(last["reranked"])
        self.assertEqual(last["reason"], "ok")


class BenchTest(SpatialBase):
    """Item 3: the four-way comparison A/B/C/D."""

    def setUp(self):
        super().setUp()
        self.flags(spatial_recall=True)
        for text, tags in (("我的猫叫团子，三岁", ["猫"]),
                           ("今天加班到很晚", ["工作"]),
                           ("周末想去看海", ["旅行"]),
                           ("团子今天打了疫苗", ["猫", "健康"])):
            self.remember(text, tags=tags)
        self.entries_rows = self.entries()

    def bench(self, **extra):
        payload = {"session_id": "s1", "store": str(self.store)}
        payload.update(extra)
        return pl.dispatch("space_bench", payload)

    def test_four_combos_carry_metrics(self):
        fake = fake_rerank([0, 1, 2, 3])
        with mock.patch.object(pl._rerank_mod, "rerank_documents", fake):
            out = self.bench()
        self.assertTrue(out["ok"])
        self.assertEqual(sorted(out["combos"]), ["A", "B", "C", "D"])
        for key in ("A", "B", "C", "D"):
            row = out["combos"][key]
            self.assertIn("overlap@5", row)
            self.assertIn("mrr", row)
            self.assertIn("ms", row)
            self.assertGreater(row["queries"], 0)
        self.assertEqual(out["queries"], 4)

    def test_pseudo_queries_come_from_the_store(self):
        with mock.patch.object(pl._rerank_mod, "rerank_documents",
                               fake_rerank([0, 1])):
            out = self.bench()
        self.assertEqual(out["queries"], len(self.entries_rows))
        self.assertTrue(out["details"])

    def test_external_queries_with_ground_truth(self):
        target = [entry for entry in self.entries_rows
                  if "加班" in entry["text"]][0]
        with mock.patch.object(pl._rerank_mod, "rerank_documents",
                               fake_rerank([0])):
            out = self.bench(queries=[{"query": "加班", "ids": [target["id"]]}])
        self.assertEqual(out["queries"], 1)
        self.assertEqual(out["skipped"], 0)
        self.assertGreaterEqual(out["combos"]["A"]["mrr"], 1.0)

    def test_bench_metrics_math(self):
        self.assertEqual(pl.bench_metrics(["a", "b"], ["b"], 5),
                         {"overlap": 1.0, "mrr": 0.5, "found": 1})
        self.assertAlmostEqual(pl.bench_metrics(["a", "b", "c"], ["c"], 5)["mrr"],
                               1.0 / 3.0, places=6)
        self.assertEqual(pl.bench_metrics(["a"], ["z"], 5),
                         {"overlap": 0.0, "mrr": 0.0, "found": 0})
        self.assertIsNone(pl.bench_metrics(["a"], [], 5)["mrr"])

    def test_bench_shows_rerank_helping_where_it_should(self):
        # a reranker that always puts the last candidate first cannot help the
        # old recall ordering but can help the spatial one
        fake = fake_rerank([3, 2, 1, 0])
        with mock.patch.object(pl._rerank_mod, "rerank_documents", fake):
            out = self.bench()
        for key in ("A", "B", "C", "D"):
            self.assertGreaterEqual(out["combos"][key]["mrr"], 0.0)
            self.assertLessEqual(out["combos"][key]["overlap@5"], 1.0)
        self.assertEqual(out["rerank"]["transport"], "urllib")

    def test_bench_without_rerank_keeps_b_equal_to_a(self):
        fake = mock.Mock(side_effect=lambda *a, **k: None)
        with mock.patch.object(pl._rerank_mod, "rerank_documents", fake):
            out = self.bench(queries=[{"query": "猫",
                                       "ids": [self.entries_rows[0]["id"]]}])
        self.assertEqual(out["combos"]["A"]["mrr"], out["combos"]["B"]["mrr"])
        self.assertEqual(out["combos"]["A"]["overlap@5"],
                         out["combos"]["B"]["overlap@5"])
