# -*- coding: utf-8 -*-
"""Step-3 dispatcher text tests: prompt / fallback / punctuation cleanup.

The two methods live on BioCorePlugin in main.py, which cannot be imported
without AstrBot. They are pure (no astrbot names inside), so the test extracts
them from the main.py AST and binds them to a fake plugin object -- the same
technique as the step-3 engine smoke harness.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

PLUG = Path(__file__).resolve().parents[2]
if str(PLUG) not in sys.path:
    sys.path.insert(0, str(PLUG))
import interpretation  # noqa: E402


class _Log:
    def __getattr__(self, _name):
        return lambda *a, **k: None


def load_methods():
    tree = ast.parse((PLUG / "main.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    names = ("_build_proactive_text", "_sanitize_proactive_text")
    nodes = [f for f in cls.body if isinstance(f, ast.FunctionDef) and f.name in names]
    if len(nodes) != 2:
        raise AssertionError("expected 2 methods, got %d" % len(nodes))
    ns = {"re": re, "interpretation": interpretation, "logger": _Log()}
    for node in nodes:
        exec(compile(ast.Module(body=[node], type_ignores=[]),
                     "<main-extract>", "exec"), ns)
    _sanitize_fn = ns["_sanitize_proactive_text"]
    return (ns["_build_proactive_text"],
            lambda value, max_chars=0: _sanitize_fn(None, value, max_chars))


class _Core:
    relationship_context = {"state": {"closeness": 0.4, "trust": 0.55}}

    def __init__(self, parts):
        self._parts = parts

    def autonomy_state(self, relationship=None, now=None, persist=False):
        return {"enabled": True, "max_chars": 80, "parts": dict(self._parts)}

    def snapshot(self):
        return {"labels": {"emotion": "loneliness", "need": "talk"},
                "v": -0.2, "a": 0.4, "d": 0.5, "social": 0.4,
                "stress": 0.3, "energy": 0.5, "parts": dict(self._parts)}


class _Plugin:
    persona_text = "你是小灰，短句。"

    def _relationship_of(self, user_data):
        return {"state": {"closeness": 0.4, "trust": 0.55}}

    def _autonomy_template(self, core):
        return "在。"


class AutonomyModuleTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _build, _sanitize = load_methods()
        cls.build = staticmethod(_build)
        cls.sanitize = staticmethod(_sanitize)
        cls.plugin = _Plugin()
        cls.now = 1761700000.0
        cls.acc = {"last_user_msg_ts": cls.now - 2 * 3600.0}

    def test_prompt_non_empty(self):
        built = self.build(self.plugin, _Core({"social_gap": 0.6, "lonely": 0.3}),
                           self.acc, self.now)
        self.assertTrue(str(built.get("prompt") or "").strip())
        self.assertIn("【输出格式 · 必须遵守】", built["prompt"])
        self.assertTrue(str(built.get("text") or "").strip())
        # 2026-10-31: hard cap removed by product decision (no truncation).
        self.assertEqual(int(built.get("max_chars") or 0), 0)

    def test_fallback_path(self):
        built = self.build(self.plugin, _Core({}), self.acc, self.now)
        text = str(built.get("text") or "")
        self.assertTrue(text.startswith("（"))
        self.assertTrue(text.endswith("在。"))
        self.assertIn("你是小灰", built["prompt"])  # persona/system block present

    def test_sanitize_punctuation_and_cap(self):
        self.assertEqual(self.sanitize("想听听你今天的碎片。。 。", 0),
                         "想听听你今天的碎片。")
        self.assertEqual(self.sanitize('你好<bc>{"e":"joy"}</bc>。。', 0), "你好。")
        capped = self.sanitize("一二三四五六。", 3)
        self.assertLessEqual(len(capped), 3)
        self.assertEqual(self.sanitize("  在。。。  ", 0), "在。")


if __name__ == "__main__":
    unittest.main()
