# -*- coding: utf-8 -*-
"""task-192 远程优先 + 本地 int8 降级单测。

远程成功/抛错/超时、本地成功/缺失/维度错误、缓存命中、关闭、健康状态、
启动预检与一次性 warning；用 stub 取代真实模型与网络，不需要 onnxruntime。
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from biocore_memory.recall import embedding as emb


class StubLocal:
    dim = 4
    model_path = "stub.onnx"
    tokenizer_path = ""
    threads = 2

    def __init__(self, vector=None, fail=False):
        self.vector = list(vector or [1.0, 0.0, 0.0, 0.0])
        self.fail = fail
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("local boom")
        return [list(self.vector) for _ in texts]


class Remote:
    def __init__(self, vector=None, fail=False, delay=0.0):
        self.vector = list(vector or [0.0, 1.0, 0.0, 0.0])
        self.fail = fail
        self.delay = delay
        self.calls = 0
        self.timeout = 5.0
        self.fallback_config = {"enabled": True, "model_path": "stub.onnx",
                                "tokenizer_path": "", "threads": 2,
                                "timeout_s": 8.0}
        self.local_embedder = None
        self.local_status = "missing"

    def embed_text(self, text):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("remote down")
        return list(self.vector)


class FallbackBehaviorTest(unittest.TestCase):
    def test_remote_success_skips_local(self):
        provider = Remote()
        local = StubLocal()
        provider.local_embedder = local
        cache = {}
        vector = emb.embed("你好", provider, cache)
        self.assertEqual(vector, [0.0, 1.0, 0.0, 0.0])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(local.calls, 0)
        self.assertIn(emb.cache_key("你好"), cache)

    def test_remote_failure_uses_local_and_caches(self):
        provider = Remote(fail=True)
        local = StubLocal()
        provider.local_embedder = local
        cache = {}
        vector = emb.embed("你好", provider, cache)
        self.assertEqual(vector, [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(local.calls, 1)
        self.assertEqual(provider.local_status, "missing")
        self.assertEqual(emb.embed("你好", provider, cache),
                         [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(local.calls, 1)

    def test_remote_timeout_uses_local(self):
        provider = Remote(delay=0.3)
        local = StubLocal()
        provider.local_embedder = local
        started = time.perf_counter()
        vector = emb.embed("你好", provider, {}, timeout=0.1)
        elapsed = time.perf_counter() - started
        self.assertEqual(vector, [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(local.calls, 1)
        self.assertLess(elapsed, 1.0)

    def test_fallback_disabled_stays_remote_only(self):
        provider = Remote(fail=True)
        provider.fallback_config["enabled"] = False
        local = StubLocal()
        provider.local_embedder = local
        self.assertIsNone(emb.embed("你好", provider))
        self.assertEqual(local.calls, 0)

    def test_local_sentinel_means_no_retry(self):
        provider = Remote(fail=True)
        provider.local_embedder = False
        self.assertIsNone(emb.embed("你好", provider))

    def test_local_failure_returns_none_and_disables(self):
        provider = Remote(fail=True)
        provider.local_embedder = StubLocal(fail=True)
        self.assertIsNone(emb.embed("你好", provider))
        self.assertIs(provider.local_embedder, False)
        self.assertEqual(provider.local_status, "failed")

    def test_local_wrong_dimension_rejected(self):
        provider = Remote(fail=True)
        local = StubLocal(vector=[1.0, 0.0, 0.0])
        local.dim = 4
        provider.local_embedder = local
        self.assertIsNone(emb.embed("你好", provider))

    def test_local_non_finite_rejected(self):
        provider = Remote(fail=True)
        local = StubLocal(vector=[float("nan"), 0.0, 0.0, 0.0])
        provider.local_embedder = local
        self.assertIsNone(emb.embed("你好", provider))

    def test_empty_and_malformed_texts(self):
        provider = Remote()
        self.assertIsNone(emb.embed("", provider))
        self.assertIsNone(emb.embed(None, provider))
        self.assertIsNone(emb.embed("  ", provider))
        self.assertEqual(provider.calls, 0)
        self.assertIsNone(emb.embed("你好", None))

    def test_cache_hit_skips_everything(self):
        provider = Remote()
        cache = {emb.cache_key("你好"): [0.0, 0.0, 1.0, 0.0]}
        vector = emb.embed("你好", provider, cache)
        self.assertEqual(vector, [0.0, 0.0, 1.0, 0.0])
        self.assertEqual(provider.calls, 0)


class ConfigTest(unittest.TestCase):
    def test_local_config_defaults(self):
        cfg = emb.local_config({})
        self.assertFalse(cfg["enabled"])  # task-198: opt-in, default off
        self.assertEqual(cfg["model_path"], "")
        self.assertEqual(cfg["threads"], 2)
        self.assertEqual(cfg["timeout_s"], 8.0)

    def test_local_config_reads_nested_keys(self):
        cfg = emb.local_config({"embedding": {
            "embedding_local_fallback_enabled": False,
            "embedding_local_model_path": "x.onnx",
            "embedding_local_threads": 4,
            "embedding_timeout_s": 3,
        }})
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["model_path"], "x.onnx")
        self.assertEqual(cfg["threads"], 4)
        self.assertEqual(cfg["timeout_s"], 3.0)

    def test_load_provider_attaches_fallback_config(self):
        provider = emb.load_provider({"base_url": "http://127.0.0.1:9/v1",
                                      "model": "missing-model",
                                      "embedding_local_fallback_enabled": True})
        self.assertIsNotNone(provider)
        self.assertEqual(provider.fallback_config["enabled"], True)
        self.assertEqual(provider.local_status, "missing")
        self.assertEqual(provider.timeout, 8.0)

    def test_load_provider_disabled_fallback(self):
        provider = emb.load_provider({
            "base_url": "http://127.0.0.1:9/v1", "model": "m",
            "embedding_local_fallback_enabled": False})
        self.assertFalse(provider.fallback_config["enabled"])
        self.assertEqual(provider.timeout, emb.DEFAULT_TIMEOUT)

    def test_load_provider_nothing_configured(self):
        self.assertIsNone(emb.load_provider({}))

    def test_default_off_does_not_touch_local_model(self):
        with mock.patch("biocore_memory.embedding_local.LocalEmbedder",
                        side_effect=AssertionError("must not load")):
            provider = emb.load_provider({
                "base_url": "http://127.0.0.1:9/v1", "model": "m",
                "embedding_local_model_path": "nope.onnx"})
        self.assertFalse(provider.fallback_config["enabled"])
        self.assertEqual(provider.local_status, "missing")
        self.assertIsNone(provider.local_embedder)
        self.assertIsNone(emb.embed("你好", provider))

    def test_enabled_without_path_is_missing_pure_remote(self):
        provider = emb.load_provider({
            "base_url": "http://127.0.0.1:9/v1", "model": "m",
            "embedding_local_fallback_enabled": True})
        self.assertTrue(provider.fallback_config["enabled"])
        self.assertEqual(provider.local_status, "missing")
        with self.assertNoLogs("biocore_memory.embedding", level="WARNING"):
            self.assertIsNone(emb.embed("你好", provider))

    def test_load_provider_local_only(self):
        with mock.patch.object(emb, "_load_local_embedder",
                               return_value=StubLocal()):
            provider = emb.load_provider({
                "embedding_local_fallback_enabled": True,
                "embedding_local_model_path": "stub.onnx"})
        self.assertIsNotNone(provider)
        self.assertTrue(provider.local_only)
        self.assertEqual(emb.local_embedding_status(provider), "ok")
        self.assertEqual(provider.embed_text("你好"), [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(emb.embed("你好", provider), [1.0, 0.0, 0.0, 0.0])


class StartupAndHealthTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        emb._LOCAL_WARNED.clear()

    def tearDown(self):
        self._tmp.cleanup()
        emb._LOCAL_WARNED.clear()

    def test_configured_missing_model_warns_once(self):
        path = str(Path(self._tmp.name) / "nope.onnx")
        with self.assertLogs("biocore_memory.embedding", level="WARNING") as logs:
            emb.load_provider({"base_url": "http://127.0.0.1:9/v1",
                               "model": "m",
                               "embedding_local_fallback_enabled": True,
                               "embedding_local_model_path": path})
            emb.load_provider({"base_url": "http://127.0.0.1:9/v1",
                               "model": "m",
                               "embedding_local_fallback_enabled": True,
                               "embedding_local_model_path": path})
        self.assertEqual(len(logs.output), 1)

    def test_failed_preload_never_retries(self):
        path = str(Path(self._tmp.name) / "nope.onnx")
        provider = emb.load_provider({"base_url": "http://127.0.0.1:9/v1",
                                      "model": "m",
                                      "embedding_local_fallback_enabled": True,
                                      "embedding_local_model_path": path})
        self.assertEqual(provider.local_status, "failed")
        self.assertIs(provider.local_embedder, False)
        with mock.patch.object(emb, "_load_local_embedder",
                               side_effect=AssertionError("must not retry")):
            self.assertIsNone(emb._fallback_embed(provider, "你好"))

    def test_health_statuses(self):
        self.assertEqual(emb.local_embedding_status(None), "missing")
        self.assertEqual(emb.embedding_health(None)["local_embedding"],
                         "missing")
        remote = Remote()
        remote.local_status = "failed"
        self.assertEqual(emb.local_embedding_status(remote), "failed")
        remote.local_status = "ok"
        self.assertEqual(emb.local_embedding_status(remote), "ok")
        local_only = emb.LocalOnlyEmbeddingProvider(StubLocal())
        self.assertEqual(emb.local_embedding_status(local_only), "ok")
        health = emb.embedding_health(remote)
        for key in ("local_embedding", "remote_configured", "local_only",
                    "local_model_path", "local_threads", "timeout_s"):
            self.assertIn(key, health)

    def test_engine_health_exposes_local_embedding(self):
        from biocore_memory.engine import MemoryEngine

        engine = MemoryEngine()
        self.assertEqual(engine.health()["local_embedding"], "missing")
        self.assertEqual(engine.monitor()["local_embedding"], "missing")
        failed = Remote()
        failed.local_status = "failed"
        engine.embedder = failed
        self.assertEqual(engine.health()["local_embedding"], "failed")


if __name__ == "__main__":
    unittest.main()
