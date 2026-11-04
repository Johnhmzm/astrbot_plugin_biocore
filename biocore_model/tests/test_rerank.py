# -*- coding: utf-8 -*-
"""Rerank core tests: config, protocols, sorting, truncation, silent fallback."""
import json
import unittest

from biocore_runtime import rerank


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, payload, timeout, headers):
        self.calls.append({"url": url, "payload": payload,
                           "timeout": timeout, "headers": dict(headers)})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def ok(results):
    return (200, json.dumps({"results": results}).encode("utf-8"))


def cfg(**overrides):
    data = {
        "rerank_enabled": True,
        "rerank_base_url": "https://api.example.com",
        "rerank_model": "bge-reranker",
    }
    data.update(overrides)
    return data


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        data = rerank.normalize_config({})
        self.assertFalse(data["rerank_enabled"])
        self.assertEqual(data["rerank_base_url"], "")
        self.assertEqual(data["rerank_model"], "")
        self.assertEqual(data["rerank_api_key"], "")
        self.assertEqual(data["rerank_timeout"], 8.0)
        self.assertEqual(data["rerank_top_n"], 20)

    def test_clamps_timeout_and_top_n(self):
        data = rerank.normalize_config(cfg(rerank_timeout=999, rerank_top_n=0))
        self.assertEqual(data["rerank_timeout"], 60.0)
        self.assertEqual(data["rerank_top_n"], 1)
        data = rerank.normalize_config(cfg(rerank_timeout=-1, rerank_top_n=9999))
        self.assertEqual(data["rerank_timeout"], 0.1)
        self.assertEqual(data["rerank_top_n"], 1000)


class DegradeTest(unittest.TestCase):
    def test_disabled_never_calls_transport(self):
        transport = FakeTransport([AssertionError("should not call")])
        reasons = []
        out = rerank.rerank_documents(
            "q", ["a", "b"], {"rerank_enabled": False},
            transport=transport, on_reason=reasons.append)
        self.assertIsNone(out)
        self.assertEqual(transport.calls, [])
        self.assertEqual(reasons, ["disabled"])

    def test_missing_config_degrades(self):
        transport = FakeTransport([AssertionError("should not call")])
        reasons = []
        out = rerank.rerank_documents(
            "q", ["a"], {"rerank_enabled": True, "rerank_model": "m"},
            transport=transport, on_reason=reasons.append)
        self.assertIsNone(out)
        self.assertEqual(transport.calls, [])
        self.assertEqual(reasons, ["missing_config"])

    def test_non_2xx_degrades(self):
        transport = FakeTransport([(500, b"oops"), (503, b"nope")])
        reasons = []
        out = rerank.rerank_documents("q", ["a", "b"], cfg(),
                                      transport=transport,
                                      on_reason=reasons.append)
        self.assertIsNone(out)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(reasons, ["http_503"])

    def test_timeout_degrades_one_attempt(self):
        transport = FakeTransport([TimeoutError("slow")])
        reasons = []
        out = rerank.rerank_documents("q", ["a"], cfg(),
                                      transport=transport,
                                      on_reason=reasons.append)
        self.assertIsNone(out)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(reasons, ["timeout"])

    def test_bad_json_degrades(self):
        transport = FakeTransport([(200, b"not json"), (200, b"not json")])
        reasons = []
        out = rerank.rerank_documents("q", ["a"], cfg(),
                                      transport=transport,
                                      on_reason=reasons.append)
        self.assertIsNone(out)
        self.assertEqual(reasons, ["bad_json"])


class ProtocolTest(unittest.TestCase):
    def test_rerank_endpoint_first_and_payload(self):
        transport = FakeTransport([ok([{"index": 0, "relevance_score": 0.3}])])
        out = rerank.rerank_documents("query", ["doc-a", "doc-b"], cfg(),
                                      transport=transport)
        self.assertEqual(len(out), 1)
        self.assertEqual(transport.calls[0]["url"],
                         "https://api.example.com/rerank")
        payload = transport.calls[0]["payload"]
        self.assertEqual(payload["model"], "bge-reranker")
        self.assertEqual(payload["query"], "query")
        self.assertEqual(payload["documents"], ["doc-a", "doc-b"])
        self.assertEqual(payload["top_n"], 2)
        self.assertEqual(transport.calls[0]["timeout"], 8.0)

    def test_v1_rerank_fallback(self):
        transport = FakeTransport([(404, b"no"), ok([{"index": 1, "relevance_score": 0.9}])])
        out = rerank.rerank_documents("q", ["a", "b"], cfg(),
                                      transport=transport)
        self.assertIsNotNone(out)
        self.assertEqual([call["url"] for call in transport.calls], [
            "https://api.example.com/rerank",
            "https://api.example.com/v1/rerank",
        ])
        self.assertEqual(out[0]["index"], 1)

    def test_v1_base_does_not_double_v1(self):
        transport = FakeTransport([ok([{"index": 0, "relevance_score": 0.5}])])
        rerank.rerank_documents("q", ["a"], cfg(
            rerank_base_url="https://api.example.com/v1"),
            transport=transport)
        self.assertEqual(transport.calls[0]["url"],
                         "https://api.example.com/v1/rerank")

    def test_auth_header_and_timeout_forwarded(self):
        transport = FakeTransport([ok([{"index": 0, "relevance_score": 0.5}])])
        rerank.rerank_documents("q", ["a"], cfg(
            rerank_api_key="secret", rerank_timeout=3.5),
            transport=transport)
        call = transport.calls[0]
        self.assertEqual(call["headers"].get("Authorization"),
                         "Bearer secret")
        self.assertEqual(call["timeout"], 3.5)


class RankingTest(unittest.TestCase):
    def test_sorted_by_relevance(self):
        transport = FakeTransport([ok([
            {"index": 0, "relevance_score": 0.2},
            {"index": 1, "relevance_score": 0.9},
            {"index": 2, "relevance_score": 0.5},
        ])])
        out = rerank.rerank_documents("q", ["a", "b", "c"], cfg(),
                                      transport=transport)
        self.assertEqual([row["index"] for row in out], [1, 2, 0])
        self.assertEqual([row["document"] for row in out], ["b", "c", "a"])

    def test_top_n_truncates(self):
        transport = FakeTransport([ok([
            {"index": index, "relevance_score": index / 10.0}
            for index in range(5)
        ])])
        out = rerank.rerank_documents("q", ["a", "b", "c", "d", "e"],
                                      cfg(rerank_top_n=2),
                                      transport=transport)
        self.assertEqual(len(out), 2)
        self.assertEqual([row["index"] for row in out], [4, 3])
        self.assertEqual(transport.calls[0]["payload"]["top_n"], 2)

    def test_invalid_results_skipped(self):
        transport = FakeTransport([ok([
            {"index": 0, "relevance_score": 0.4},
            {"index": 99, "relevance_score": 0.9},
            {"index": 1, "relevance_score": "bad"},
            "garbage",
        ])])
        out = rerank.rerank_documents("q", ["a", "b"], cfg(),
                                      transport=transport)
        self.assertEqual([row["index"] for row in out], [0])

    def test_ties_keep_index_order(self):
        transport = FakeTransport([ok([
            {"index": 2, "relevance_score": 0.5},
            {"index": 0, "relevance_score": 0.5},
            {"index": 1, "relevance_score": 0.5},
        ])])
        out = rerank.rerank_documents("q", ["a", "b", "c"], cfg(),
                                      transport=transport)
        self.assertEqual([row["index"] for row in out], [0, 1, 2])


class PipelineHookTest(unittest.TestCase):
    def test_tool_recall_uses_rerank_hook(self):
        import tempfile
        from unittest.mock import patch
        from biocore_runtime import pipeline as pl
        root = tempfile.mkdtemp(prefix="biocore-rerank-hook-")
        pl.tool_call("remember", {"text": "第一条记忆"}, root, session_id="s")
        pl.tool_call("remember", {"text": "第二条记忆"}, root, session_id="s")
        fake = lambda query, docs, config=None, **kwargs: [
            {"index": 0, "document": docs[0], "relevance_score": 0.9},
            {"index": 1, "document": docs[1], "relevance_score": 0.1},
        ]
        with patch.object(pl._rerank_mod, "rerank_documents", fake):
            out = pl.tool_call("recall", {
                "query": "记忆", "limit": 2,
                "rerank_config": {"rerank_enabled": True},
            }, root, session_id="s")
        self.assertEqual([row["text"] for row in out["results"]],
                         ["第二条记忆", "第一条记忆"])

    def test_recall_action_falls_back_without_config(self):
        from biocore_runtime import pipeline
        out = pipeline.dispatch("recall", {
            "query": "q", "documents": ["a", "b"],
            "config": {"rerank_enabled": False}})
        self.assertTrue(out["ok"])
        self.assertFalse(out["reranked"])
        self.assertEqual([row["index"] for row in out["results"]], [0, 1])


if __name__ == "__main__":
    unittest.main()
