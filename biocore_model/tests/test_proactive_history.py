# -*- coding: utf-8 -*-
"""Proactive message -> AstrBot conversation history + 3-item [BC] context."""
import ast
import asyncio
import json
import types
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load(name):
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    node = next(f for f in cls.body
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                and f.name == name)
    kind = (ast.AsyncFunctionDef if isinstance(node, ast.AsyncFunctionDef)
            else ast.FunctionDef)
    clone = kind(name=node.name, args=node.args, body=node.body,
                 decorator_list=[], returns=node.returns, type_comment=None,
                 lineno=node.lineno, col_offset=node.col_offset,
                 end_lineno=node.end_lineno, end_col_offset=node.end_col_offset)
    ns = {"json": json, "logger": types.SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None)}
    exec(compile(ast.Module(body=[clone], type_ignores=[]), "<h>", "exec"), ns)
    return ns[name]


class FakeCM:
    def __init__(self):
        self.history = [{"role": "user", "content": "old"}]
        self.updated = None

    async def get_curr_conversation_id(self, umo):
        return "cid-1"

    async def get_conversation(self, umo, cid):
        return types.SimpleNamespace(history=json.dumps(self.history))

    async def update_conversation(self, umo, cid, history=None, **kwargs):
        self.updated = list(history or [])


class HistoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_appends_assistant_message(self):
        cm = FakeCM()
        plugin = types.SimpleNamespace(
            context=types.SimpleNamespace(conversation_manager=cm))
        fn = types.MethodType(_load("_persist_proactive_history"), plugin)
        ok = await fn("umo-1", "哟，老板！今晚好")
        self.assertTrue(ok)
        self.assertEqual(cm.updated[-1]["role"], "assistant")
        self.assertEqual(cm.updated[-1]["content"], "哟，老板！今晚好")
        self.assertEqual(cm.updated[0]["content"], "old")

    async def test_no_curr_conversation_is_safe(self):
        class NoConv:
            async def get_curr_conversation_id(self, umo):
                return None
        plugin = types.SimpleNamespace(
            context=types.SimpleNamespace(conversation_manager=NoConv()))
        fn = types.MethodType(_load("_persist_proactive_history"), plugin)
        self.assertFalse(await fn("umo", "x"))


class ContextTest(unittest.TestCase):
    def test_three_items_in_context(self):
        plugin = types.SimpleNamespace(
            _recent_proactive=["甲", "乙", "丙", "丁"],
            _load_recent_proactive=lambda: ["甲", "乙", "丙", "丁"])
        fn = _load("_recent_proactive_context")
        fn = types.MethodType(fn, plugin)
        text = fn()
        self.assertIn("乙", text)
        self.assertIn("丙", text)
        self.assertIn("丁", text)
        self.assertNotIn("甲", text)

    def test_ctx_log_and_bc_fallback_wired(self):
        self.assertIn("[biocore] ctx contexts=%s prompt_len=%s sys_len=%s", SOURCE)
        self.assertIn("_recent_ctx = self._recent_proactive_context()", SOURCE)
        self.assertIn("await self._persist_proactive_history(umo, final)", SOURCE)


if __name__ == "__main__":
    unittest.main()
