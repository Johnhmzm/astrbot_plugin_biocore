# -*- coding: utf-8 -*-
"""task-211: embedding_mode auto probe tests (>=8 cases).

Pure resolver tests plus one loader integration check. No model/onnxruntime
import is ever required: the probe is resolved from injectable booleans.
"""
import tempfile
import unittest
from pathlib import Path

from biocore_memory.embedding_mode import (
    resolve_mode, remote_complete, local_model_file, onnxruntime_available)
from biocore_memory.recall import embedding


REMOTE = {"embedding_base_url": "https://api.example.com/v1",
          "embedding_model": "bge-m3", "embedding_api_key": "sk-test"}


class RemoteProbeTest(unittest.TestCase):
    def test_remote_complete_requires_all_three(self):
        self.assertTrue(remote_complete(REMOTE)[0])
        for key in ("embedding_base_url", "embedding_model", "embedding_api_key"):
            partial = dict(REMOTE)
            partial[key] = ""
            self.assertFalse(remote_complete(partial)[0], key)

    def test_remote_aliases(self):
        alias = {"base_url": "https://x/v1", "model": "m", "api_key": "k"}
        self.assertTrue(remote_complete(alias)[0])


class AutoMatrixTest(unittest.TestCase):
    def test_auto_remote_when_complete(self):
        out = resolve_mode({"embedding_mode": "auto", **REMOTE},
                           remote_ready=True, model_exists=False,
                           onnx_available=False)
        self.assertEqual(out["mode"], "remote")
        self.assertEqual(out["source"], "auto")
        self.assertIn("远程配置齐全", out["reason"])

    def test_auto_local_when_remote_missing(self):
        out = resolve_mode({"embedding_mode": "auto"},
                           remote_ready=False, model_exists=True,
                           onnx_available=True)
        self.assertEqual(out["mode"], "local")
        self.assertEqual(out["source"], "auto")
        self.assertIn("本地模型存在", out["reason"])

    def test_auto_off_when_neither(self):
        out = resolve_mode({"embedding_mode": "auto"},
                           remote_ready=False, model_exists=False,
                           onnx_available=False)
        self.assertEqual(out["mode"], "off")
        self.assertIn("无本地模型", out["reason"])

    def test_auto_off_when_onnx_missing(self):
        out = resolve_mode({"embedding_mode": "auto"},
                           remote_ready=False, model_exists=True,
                           onnx_available=False)
        self.assertEqual(out["mode"], "off")
        self.assertIn("onnxruntime 不可导入", out["reason"])

    def test_auto_prefers_remote_over_local(self):
        out = resolve_mode({"embedding_mode": "auto", **REMOTE},
                           remote_ready=True, model_exists=True,
                           onnx_available=True)
        self.assertEqual(out["mode"], "remote")


class ExplicitOverrideTest(unittest.TestCase):
    def test_explicit_off_wins(self):
        out = resolve_mode({"embedding_mode": "off", **REMOTE},
                           remote_ready=True, model_exists=True,
                           onnx_available=True)
        self.assertEqual(out["mode"], "off")
        self.assertEqual(out["source"], "explicit")

    def test_explicit_remote_wins_even_if_incomplete(self):
        out = resolve_mode({"embedding_mode": "remote"},
                           remote_ready=False, model_exists=True,
                           onnx_available=True)
        self.assertEqual(out["mode"], "remote")
        self.assertEqual(out["source"], "explicit")

    def test_explicit_local_wins_even_without_model(self):
        out = resolve_mode({"embedding_mode": "local", **REMOTE},
                           remote_ready=True, model_exists=False,
                           onnx_available=False)
        self.assertEqual(out["mode"], "local")
        self.assertEqual(out["source"], "explicit")

    def test_explicit_fallback_wins(self):
        out = resolve_mode({"embedding_mode": "remote_with_local_fallback"},
                           remote_ready=True, model_exists=True,
                           onnx_available=True)
        self.assertEqual(out["mode"], "remote_with_local_fallback")
        self.assertEqual(out["source"], "explicit")

    def test_unknown_value_falls_back_to_off(self):
        out = resolve_mode({"embedding_mode": "bogus"},
                           remote_ready=True, model_exists=True,
                           onnx_available=True)
        self.assertEqual(out["mode"], "off")
        self.assertEqual(out["source"], "explicit")

    def test_legacy_config_keeps_old_behaviour(self):
        out = resolve_mode({}, remote_ready=True, model_exists=True,
                           onnx_available=True)
        self.assertEqual(out["mode"], "")
        self.assertEqual(out["source"], "legacy")


class FilesystemProbeTest(unittest.TestCase):
    def test_local_model_file_accepts_dir_and_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model.onnx"
            model.write_bytes(b"fake")
            self.assertEqual(local_model_file(tmp), model)
            self.assertEqual(local_model_file(str(model)), model)
            self.assertIsNone(local_model_file(""))

    def test_real_probe_with_injected_find_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model.onnx"
            model.write_bytes(b"fake")
            out = resolve_mode(
                {"embedding_mode": "auto", "embedding_local_model_path": str(model)},
                find_spec=lambda name: object())
            self.assertEqual(out["mode"], "local")
            self.assertTrue(out["local_model_exists"])
            self.assertTrue(out["onnxruntime_available"])

    def test_onnxruntime_probe_is_boolean(self):
        self.assertIsInstance(onnxruntime_available(), bool)


class LoaderIntegrationTest(unittest.TestCase):
    def test_loader_auto_remote_attaches_mode(self):
        provider = embedding.load_provider(
            {"embedding_mode": "auto", **REMOTE})
        self.assertIsNotNone(provider)
        self.assertEqual(getattr(provider, "embedding_mode", ""), "remote")
        self.assertEqual(getattr(provider, "embedding_mode_source", ""), "auto")

    def test_loader_auto_off_returns_none(self):
        provider = embedding.load_provider({"embedding_mode": "auto"})
        self.assertIsNone(provider)

    def test_loader_health_reports_mode(self):
        provider = embedding.load_provider(
            {"embedding_mode": "auto", **REMOTE})
        health = embedding.embedding_health(provider)
        self.assertEqual(health.get("embedding_mode"), "remote")
        self.assertEqual(health.get("embedding_mode_source"), "auto")

    @unittest.skipUnless(onnxruntime_available(),
                         "auto local probe needs onnxruntime importable")
    def test_loader_auto_local_is_lazy(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model.onnx"
            model.write_bytes(b"not-a-real-onnx")
            provider = embedding.load_provider({
                "embedding_mode": "auto",
                "embedding_local_model_path": str(model),
            })
            self.assertIsNotNone(provider)
            self.assertEqual(getattr(provider, "embedding_mode", ""), "local")
            # Model load is deferred to the first real encode.
            self.assertIsInstance(provider.local_embedder,
                                  embedding._LazyLocalEmbedder)


if __name__ == "__main__":
    unittest.main()
