# -*- coding: utf-8 -*-
"""task-199 通用 embedding provider 单测。

覆盖四种模式（off / remote / local / remote_with_local_fallback）、通用
OpenAI 兼容请求体与鉴权头、超时、维度校验与降级、off 无 IO、旧键兼容。
用 stub 取代真实网络与本地模型，不需要 onnxruntime。
"""
import json
import os
import unittest
from unittest import mock

from biocore_memory.recall import embedding as emb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_KEYS = (
    "BIOCORE_EMBEDDING_MODE", "BIOCORE_EMBEDDING_BASE_URL",
    "BIOCORE_EMBEDDING_KEY", "BIOCORE_EMBEDDING_MODEL",
    "BIOCORE_EMBEDDING_DIM", "BIOCORE_EMBEDDING_TIMEOUT",
    "BIOCORE_EMBEDDING_LOCAL_MODEL", "BIOCORE_EMBEDDING_LOCAL_FALLBACK",
    "BIOCORE_EMBEDDING_LOCAL_TOKENIZER", "BIOCORE_EMBEDDING_LOCAL_THREADS",
)


class FakeResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")
        self.closed = False

    def read(self):
        return self._data

    def close(self):
        self.closed = True


def payload(vector, model="m"):
    return {"data": [{"embedding": list(vector)}], "model": model}


class StubLocal:
    def __init__(self, vector=None, dim=4, fail=False):
        self.vector = list(vector if vector is not None else [1.0, 0.0, 0.0, 0.0])
        self.dim = int(dim)
        self.fail = bool(fail)
        self.calls = 0
        self.model_path = "stub.onnx"
        self.tokenizer_path = ""
        self.threads = 2

    def encode(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("local boom")
        return [list(self.vector) for _ in texts]


class EnvIsolated(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {key: "" for key in ENV_KEYS},
                                    clear=False)
        self._env.start()
        emb._LOCAL_WARNED.clear()

    def tearDown(self):
        emb._LOCAL_WARNED.clear()
        self._env.stop()


class ModeDispatchTest(EnvIsolated):
    def test_off_mode_returns_none_without_network_or_local_load(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("no network")), \
                mock.patch.object(emb, "_load_local_embedder",
                                  side_effect=AssertionError("no local load")):
            provider = emb.load_provider({
                "embedding_mode": "off",
                "embedding_base_url": "https://api.example.com/v1",
                "embedding_model": "bge-m3",
                "embedding_local_model_path": "stub.onnx",
            })
        self.assertIsNone(provider)

    def test_unknown_mode_behaves_like_off(self):
        with mock.patch("urllib.request.urlopen") as urlopen, \
                mock.patch.object(emb, "_load_local_embedder") as loader:
            self.assertIsNone(emb.load_provider({
                "embedding_mode": "wired-mode",
                "embedding_base_url": "https://api.example.com/v1",
                "embedding_model": "m",
                "embedding_local_model_path": "stub.onnx",
            }))
        self.assertFalse(urlopen.called)
        self.assertFalse(loader.called)

    def test_legacy_config_without_mode_stays_remote(self):
        provider = emb.load_provider({
            "base_url": "http://127.0.0.1:9/v1", "model": "legacy-model"})
        self.assertIsNotNone(provider)
        self.assertEqual(provider.mode, "remote")
        self.assertEqual(provider.endpoint, "http://127.0.0.1:9/v1/embeddings")
        self.assertEqual(provider.dim, 0)

    def test_legacy_local_only_config_still_loads(self):
        stub = StubLocal()
        with mock.patch.object(emb, "_load_local_embedder", return_value=stub):
            provider = emb.load_provider({
                "embedding_local_fallback_enabled": True,
                "embedding_local_model_path": "stub.onnx",
            })
        self.assertIsNotNone(provider)
        self.assertTrue(provider.local_only)
        self.assertEqual(emb.local_embedding_status(provider), "ok")

    def test_mode_aliases_are_accepted(self):
        with mock.patch.object(emb, "_load_local_embedder", return_value=StubLocal()):
            provider = emb.load_provider({
                "embedding_mode": "local_onnx",
                "embedding_local_model_path": "stub.onnx",
            })
        self.assertIsNotNone(provider)
        self.assertEqual(provider.mode, "local")
        remote = emb.load_provider({
            "embedding_mode": "remote_generic",
            "embedding_base_url": "https://api.example.com/v1",
            "embedding_model": "m",
        })
        self.assertIsNotNone(remote)
        self.assertEqual(remote.mode, "remote")


class RemoteGenericModeTest(EnvIsolated):
    def _provider(self, **extra):
        cfg = {"embedding_mode": "remote",
               "embedding_base_url": "https://api.example.com/v1",
               "embedding_model": "bge-m3"}
        cfg.update(extra)
        return emb.load_provider(cfg)

    def test_remote_request_is_generic_openai_compatible(self):
        provider = self._provider(embedding_api_key="sk-test")
        self.assertIsNotNone(provider)
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload([1.0, 0.0, 0.0, 0.0]))) as urlopen:
            vector = provider.embed_text("  你好  世界 ")
        self.assertEqual(vector, [1.0, 0.0, 0.0, 0.0])
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.example.com/v1/embeddings")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "bge-m3")
        self.assertEqual(body["input"], ["你好 世界"])
        self.assertEqual(body["encoding_format"], "float")
        headers = {key.lower(): value for key, value in request.headers.items()}
        self.assertEqual(headers.get("authorization"), "Bearer sk-test")
        self.assertEqual(urlopen.call_args.kwargs.get("timeout"), emb.DEFAULT_TIMEOUT)

    def test_remote_without_key_sends_no_authorization_header(self):
        provider = self._provider()
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload([1.0, 0.0]))) as urlopen:
            provider.embed_text("hi")
        request = urlopen.call_args[0][0]
        headers = {key.lower(): value for key, value in request.headers.items()}
        self.assertNotIn("authorization", headers)

    def test_base_url_already_ending_in_embeddings_is_not_duplicated(self):
        provider = self._provider(
            embedding_base_url="https://gateway.example.com/v1/embeddings")
        self.assertEqual(provider.endpoint,
                         "https://gateway.example.com/v1/embeddings")

    def test_timeout_from_seconds_and_from_milliseconds(self):
        provider = self._provider(embedding_timeout_s=2.5)
        self.assertAlmostEqual(provider.timeout, 2.5)
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload([1.0]))) as urlopen:
            provider.embed_text("hi")
        self.assertAlmostEqual(urlopen.call_args.kwargs.get("timeout"), 2.5)
        provider_ms = self._provider(embedding_timeout_ms=1500)
        self.assertAlmostEqual(provider_ms.timeout, 1.5)

    def test_dim_match_accepts_vector(self):
        provider = self._provider(embedding_dim=4)
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload([0.1, 0.2, 0.3, 0.4]))):
            self.assertEqual(provider.embed_text("hi"), [0.1, 0.2, 0.3, 0.4])

    def test_dim_mismatch_degrades_to_no_vector(self):
        provider = self._provider(embedding_dim=8)
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload([1.0, 0.0, 0.0, 0.0]))):
            with self.assertRaises(ValueError):
                provider.embed_text("hi")
            self.assertIsNone(emb.embed("hi", provider))

    def test_remote_missing_base_or_model_returns_none(self):
        self.assertIsNone(emb.load_provider({"embedding_mode": "remote"}))
        self.assertIsNone(emb.load_provider({
            "embedding_mode": "remote",
            "embedding_base_url": "https://api.example.com/v1"}))
        self.assertIsNone(emb.load_provider({
            "embedding_mode": "remote", "embedding_model": "m"}))


class LocalModeTest(EnvIsolated):
    def test_local_mode_uses_local_embedder_without_network(self):
        stub = StubLocal(dim=4)
        with mock.patch.object(emb, "_load_local_embedder",
                               return_value=stub) as loader, \
                mock.patch("urllib.request.urlopen") as urlopen:
            provider = emb.load_provider({
                "embedding_mode": "local",
                "embedding_local_model_path": "stub.onnx",
            })
            self.assertIsNotNone(provider)
            self.assertEqual(provider.mode, "local")
            vector = emb.embed("你好", provider)
        self.assertEqual(vector, [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(stub.calls, 1)
        self.assertTrue(loader.called)
        self.assertFalse(urlopen.called)

    def test_local_mode_without_model_path_returns_none(self):
        with mock.patch.object(emb, "_load_local_embedder") as loader:
            self.assertIsNone(emb.load_provider({"embedding_mode": "local"}))
        self.assertFalse(loader.called)

    def test_local_mode_load_failure_returns_none(self):
        with mock.patch.object(emb, "_load_local_embedder", return_value=False):
            self.assertIsNone(emb.load_provider({
                "embedding_mode": "local",
                "embedding_local_model_path": "missing.onnx",
            }))

    def test_local_mode_dim_mismatch_degrades(self):
        stub = StubLocal(dim=4, vector=[1.0, 0.0, 0.0])
        with mock.patch.object(emb, "_load_local_embedder", return_value=stub):
            provider = emb.load_provider({
                "embedding_mode": "local",
                "embedding_local_model_path": "stub.onnx",
                "embedding_dim": 4,
            })
        self.assertIsNone(emb.embed("你好", provider))

    def test_local_mode_keeps_legacy_local_keys(self):
        captured = {}

        def fake_load(cfg):
            captured.update(cfg)
            return StubLocal(dim=4)

        with mock.patch.object(emb, "_load_local_embedder", side_effect=fake_load):
            provider = emb.load_provider({
                "embedding_mode": "local",
                "embedding_local_model_path": "stub.onnx",
                "embedding_local_tokenizer_path": "tok",
                "embedding_local_threads": 3,
            })
        self.assertIsNotNone(provider)
        self.assertEqual(captured.get("model_path"), "stub.onnx")
        self.assertEqual(captured.get("tokenizer_path"), "tok")
        self.assertEqual(captured.get("threads"), 3)


class FallbackModeTest(EnvIsolated):
    def _config(self, **extra):
        cfg = {"embedding_mode": "remote_with_local_fallback",
               "embedding_base_url": "https://api.example.com/v1",
               "embedding_model": "m",
               "embedding_local_model_path": "stub.onnx"}
        cfg.update(extra)
        return cfg

    def test_fallback_remote_success_skips_local(self):
        stub = StubLocal(dim=4)
        with mock.patch.object(emb, "_load_local_embedder", return_value=stub):
            provider = emb.load_provider(self._config())
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload([0.0, 1.0, 0.0, 0.0]))):
            vector = emb.embed("你好", provider)
        self.assertEqual(vector, [0.0, 1.0, 0.0, 0.0])
        self.assertEqual(stub.calls, 0)

    def test_fallback_remote_failure_uses_local(self):
        stub = StubLocal(dim=4)
        with mock.patch.object(emb, "_load_local_embedder", return_value=stub):
            provider = emb.load_provider(self._config())
        with mock.patch("urllib.request.urlopen", side_effect=OSError("remote down")):
            vector = emb.embed("你好", provider)
        self.assertEqual(vector, [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(stub.calls, 1)

    def test_fallback_dim_mismatch_uses_local(self):
        stub = StubLocal(dim=8, vector=[1.0] + [0.0] * 7)
        with mock.patch.object(emb, "_load_local_embedder", return_value=stub):
            provider = emb.load_provider(self._config(embedding_dim=8))
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(payload([1.0, 0.0, 0.0, 0.0]))):
            vector = emb.embed("你好", provider)
        self.assertEqual(vector, [1.0] + [0.0] * 7)
        self.assertEqual(stub.calls, 1)

    def test_fallback_without_remote_uses_local_only(self):
        stub = StubLocal(dim=4)
        with mock.patch.object(emb, "_load_local_embedder", return_value=stub):
            provider = emb.load_provider({
                "embedding_mode": "remote_with_local_fallback",
                "embedding_local_model_path": "stub.onnx",
            })
        self.assertIsNotNone(provider)
        self.assertTrue(provider.local_only)
        self.assertEqual(emb.embed("你好", provider), [1.0, 0.0, 0.0, 0.0])

    def test_fallback_without_local_path_is_disabled(self):
        provider = emb.load_provider({
            "embedding_mode": "remote_with_local_fallback",
            "embedding_base_url": "https://api.example.com/v1",
            "embedding_model": "m",
        })
        self.assertIsNotNone(provider)
        self.assertFalse(provider.fallback_config["enabled"])


class SchemaDefaultsTest(unittest.TestCase):
    def test_new_keys_exist_and_mode_defaults_auto(self):
        with open(os.path.join(ROOT, "_conf_schema.json"),
                  encoding="utf-8-sig") as handle:
            schema = json.loads(handle.read())
        mode = schema["embedding_mode"]
        self.assertEqual(mode["default"], "auto")
        self.assertEqual(set(mode["options"]),
                         {"auto", "off", "remote", "local",
                          "remote_with_local_fallback"})
        for key in ("embedding_base_url", "embedding_model",
                    "embedding_api_key"):
            self.assertIn(key, schema)
            self.assertEqual(schema[key]["default"], "")
        self.assertEqual(schema["embedding_dim"]["default"], 0)


if __name__ == "__main__":
    unittest.main()
