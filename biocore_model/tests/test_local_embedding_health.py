# -*- coding: utf-8 -*-
"""task-193 本地 embedding 健康投影单测（/health + 面板，只读，不加载模型）。

main.py 无法在离线单测里 import（依赖 AstrBot），因此这里用 AST 从 main.py
抽取四个纯投影函数与 _local_embedding_health 方法并执行；面板断言读取
app.js / index.src.html / 构建后的 index.html 源码。
"""
import ast
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MAIN_SRC = (ROOT / "main.py").read_text(encoding="utf-8")
APP_SRC = (ROOT / "pages" / "dashboard" / "app.js").read_text(encoding="utf-8")
TPL_SRC = (ROOT / "pages" / "dashboard" / "index.src.html").read_text(encoding="utf-8")
BUILT_SRC = (ROOT / "pages" / "dashboard" / "index.html").read_text(encoding="utf-8")

HELPER_NAMES = ("_local_embedding_switch", "_local_embedding_value",
                "_probe_local_embedding", "_local_embedding_payload")


def _projection_namespace():
    tree = ast.parse(MAIN_SRC)
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)
                 and node.name in HELPER_NAMES}
    missing = [name for name in HELPER_NAMES if name not in functions]
    if missing:
        raise AssertionError("main.py is missing helpers: %s" % missing)
    plugin = next((node for node in tree.body
                   if isinstance(node, ast.ClassDef)
                   and node.name == "BioCorePlugin"), None)
    if plugin is None:
        raise AssertionError("BioCorePlugin not found")
    method = next((node for node in plugin.body
                   if isinstance(node, ast.FunctionDef)
                   and node.name == "_local_embedding_health"), None)
    if method is None:
        raise AssertionError("_local_embedding_health not found")
    module = ast.Module(
        body=[functions[name] for name in HELPER_NAMES] + [method],
        type_ignores=[])
    namespace = {}
    exec(compile(module, str(ROOT / "main.py"), "exec"), namespace)
    return namespace


class _FakeEngine:
    def __init__(self, status, detail=None):
        self.status = status
        self.detail = detail or {}

    def health(self):
        return {"local_embedding": self.status, "embedding": dict(self.detail)}


class _FakeSelf:
    def __init__(self, config, engines=None, switch=None):
        self.config = config
        self._memory_module_engines = engines or {}
        self._switch = switch

    def _local_embedding_enabled(self):
        if callable(self._switch):
            return bool(self._switch(self.config))
        return False


class ProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _projection_namespace()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _payload(self, config):
        return self.ns["_local_embedding_payload"](config)

    def test_switch_off_returns_no_field(self):
        self.assertIsNone(self._payload(
            {"embedding_local_fallback_enabled": False}))
        self.assertIsNone(self._payload(
            {"embedding_local_fallback_enabled": "off"}))

    def test_default_off_returns_no_field(self):
        self.assertIsNone(self._payload({}))
        self.assertIsNone(self._payload(
            {"embedding_local_fallback_enabled": False}))

    def test_missing_when_enabled_without_model_path(self):
        payload = self._payload(
            {"embedding_local_fallback_enabled": True})
        self.assertEqual(payload["local_embedding"], "missing")
        self.assertEqual(payload["local_embedding_model_path"], "")
        self.assertEqual(payload["local_embedding_threads"], 2)
        self.assertEqual(payload["local_embedding_timeout_s"], 8.0)
        self.assertEqual(payload["local_embedding_detail"]["status"], "missing")
        self.assertEqual(payload["local_embedding_detail"]["reason"], "未配置模型路径")
        for key in ("model_path", "threads", "timeout_s", "reason"):
            self.assertIn(key, payload["local_embedding_detail"])

    def test_failed_when_model_file_missing(self):
        path = str(self.root / "nope.onnx")
        payload = self._payload({"embedding_local_fallback_enabled": True,
                "embedding_local_model_path": path})
        self.assertEqual(payload["local_embedding"], "failed")
        self.assertEqual(payload["local_embedding_model_path"], path)
        self.assertIn("not found", payload["local_embedding_detail"]["reason"])

    def test_failed_when_tokenizer_missing(self):
        model = self.root / "model.onnx"
        model.write_bytes(b"fake")
        with mock.patch("importlib.util.find_spec", return_value=object()):
            payload = self._payload({"embedding_local_fallback_enabled": True,
                "embedding_local_model_path": str(model)})
        self.assertEqual(payload["local_embedding"], "failed")
        self.assertIn("tokenizer", payload["local_embedding_detail"]["reason"])

    def test_ok_when_component_files_ready(self):
        model = self.root / "model.onnx"
        model.write_bytes(b"fake")
        (self.root / "tokenizer.json").write_text(
            json.dumps({"model": {"vocab": {}}}), encoding="utf-8")
        with mock.patch("importlib.util.find_spec", return_value=object()):
            payload = self._payload({
                "embedding_local_fallback_enabled": True,
                "embedding_local_model_path": str(model),
                "embedding_local_threads": 3,
                "embedding_timeout_s": 6,
            })
        self.assertEqual(payload["local_embedding"], "ok")
        self.assertEqual(payload["local_embedding_threads"], 3)
        self.assertEqual(payload["local_embedding_timeout_s"], 6.0)
        self.assertEqual(payload["local_embedding_detail"]["status"], "ok")

    def test_failed_when_onnxruntime_missing(self):
        model = self.root / "model.onnx"
        model.write_bytes(b"fake")
        (self.root / "tokenizer.json").write_text("{}", encoding="utf-8")
        with mock.patch("importlib.util.find_spec", return_value=None):
            payload = self._payload({"embedding_local_fallback_enabled": True,
                "embedding_local_model_path": str(model)})
        self.assertEqual(payload["local_embedding"], "failed")
        self.assertIn("onnxruntime",
                      payload["local_embedding_detail"]["reason"])

    def test_engine_health_is_preferred(self):
        engine = _FakeEngine("ok", {"local_model_path": "C:/m.onnx",
                                    "local_threads": 2, "timeout_s": 8.0,
                                    "local_embedding": "ok"})
        method = self.ns["_local_embedding_health"]
        out = method(_FakeSelf({"embedding_local_fallback_enabled": True},
                               {"s1": engine},
                               switch=self.ns["_local_embedding_switch"]))
        self.assertEqual(out["local_embedding"], "ok")
        self.assertEqual(out["local_embedding_model_path"], "C:/m.onnx")
        failed = _FakeEngine("failed", {"local_model_path": "C:/bad.onnx"})
        out = method(_FakeSelf({"embedding_local_fallback_enabled": True},
                               {"s1": failed},
                               switch=self.ns["_local_embedding_switch"]))
        self.assertEqual(out["local_embedding"], "failed")

    def test_switch_off_never_probes(self):
        with mock.patch.dict(self.ns, {
                "_probe_local_embedding": mock.Mock(
                    side_effect=AssertionError("must not probe"))}):
            self.assertIsNone(self._payload(
                {"embedding_local_fallback_enabled": False}))

    def test_switch_off_beats_engine_health(self):
        engine = _FakeEngine("ok", {"local_model_path": "C:/m.onnx"})
        method = self.ns["_local_embedding_health"]
        out = method(_FakeSelf({"embedding_local_fallback_enabled": False},
                               {"s1": engine}))
        self.assertIsNone(out)

    def test_projection_never_loads_the_model(self):
        tree = ast.parse(MAIN_SRC)
        plugin = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef)
                      and node.name == "BioCorePlugin")
        method_node = next(node for node in plugin.body
                           if isinstance(node, ast.FunctionDef)
                           and node.name == "_local_embedding_health")
        probe_node = next(node for node in tree.body
                          if isinstance(node, ast.FunctionDef)
                          and node.name == "_probe_local_embedding")
        for source in (ast.get_source_segment(MAIN_SRC, probe_node),
                       ast.get_source_segment(MAIN_SRC, method_node),
                       ast.get_source_segment(
                           MAIN_SRC,
                           next(node for node in tree.body
                                if isinstance(node, ast.FunctionDef)
                                and node.name == "_local_embedding_payload"))):
            self.assertTrue(source)
            self.assertNotIn("InferenceSession", source)
            self.assertNotIn("warmup(", source)
            self.assertNotIn(".encode(", source)
            self.assertNotIn("import onnxruntime", source)


class WiringSourceTest(unittest.TestCase):
    def test_health_route_and_page_status_wiring(self):
        routes_src = (ROOT / "biocore_model" / "plugin_routes.py").read_text(
            encoding="utf-8")
        self.assertIn("_local_emb = self._local_embedding_health()", routes_src)
        self.assertIn("_data.update(_local_emb)", routes_src)
        self.assertIn("self._local_embedding_enabled()", routes_src)
        self.assertIn("embedding_local_fallback_enabled", routes_src)
        self.assertIn("/astrbot_plugin_biocore/health", MAIN_SRC)
        self.assertIn("self.page_health", MAIN_SRC)
        self.assertIn("async def page_health", MAIN_SRC)
        self.assertIn("_local_emb = self._local_embedding_health()", MAIN_SRC)
        self.assertIn("_data.update(_local_emb)", MAIN_SRC)
        self.assertIn("local_embedding_detail", MAIN_SRC)

    def test_schema_default_is_off(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(
            encoding="utf-8-sig"))
        entry = schema["embedding_local_fallback_enabled"]
        self.assertIs(entry["default"], False)
        self.assertIn("23MB", entry["hint"])
        self.assertIn("默认关", entry["description"])

    def test_panel_markup_has_switch_and_status(self):
        for source in (TPL_SRC, BUILT_SRC):
            self.assertIn('id="localEmbeddingRow"', source)
            self.assertIn('id="swLocalEmbedding"', source)
            self.assertIn('id="localEmbeddingState"', source)
            self.assertIn('id="localEmbeddingDetail"', source)
            self.assertIn("本地向量", source)
            self.assertIn("本地向量兜底", source)

    def test_panel_renderer_handles_ok_missing_failed_off(self):
        self.assertIn("function renderLocalEmbedding()", APP_SRC)
        self.assertIn("renderLocalEmbedding();", APP_SRC)
        self.assertIn("local_embedding_detail", APP_SRC)
        self.assertIn("embedding_local_fallback_enabled", APP_SRC)
        self.assertIn("swLocalEmbedding", APP_SRC)
        self.assertIn("本地向量：关（纯远程）", APP_SRC)
        self.assertIn("本地向量：失败", APP_SRC)
        self.assertIn("未配置模型路径", APP_SRC)
        self.assertIn("meta.model_path", APP_SRC)
        self.assertIn("renderLocalEmbedding", APP_SRC)


if __name__ == "__main__":
    unittest.main()
