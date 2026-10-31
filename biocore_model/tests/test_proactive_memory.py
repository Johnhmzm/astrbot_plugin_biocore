# -*- coding: utf-8 -*-
"""B/C: proactive opening de-dup + self-memory (events/prompt/persistence)."""
import ast
import tempfile
import types
import unittest
from pathlib import Path

from biocore_model import expr_template as et
from biocore_model import runtime as rt
from biocore_model import ui_settings

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load_methods(names):
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    ns = {"time": __import__("time")}
    fns = {}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                                    decorator_list=[], returns=node.returns,
                                    type_comment=None, lineno=node.lineno,
                                    col_offset=node.col_offset,
                                    end_lineno=node.end_lineno,
                                    end_col_offset=node.end_col_offset)
            exec(compile(ast.Module(body=[clone], type_ignores=[]), "<pm>", "exec"), ns)
            fns[node.name] = ns[node.name]
    return fns


FNS = _load_methods(("_load_recent_proactive", "_recent_proactive_prompt",
                     "_recent_proactive_context", "_opening_key",
                     "_opening_repeats", "_rewrite_proactive_opening",
                     "_record_proactive_sent"))


class FakePlugin:
    def __init__(self, tmp):
        self.data_dir = tmp
        self._recent_proactive = []
        self._recent_proactive_loaded = False
        self.events = []
        for name in FNS:
            setattr(self, name, types.MethodType(FNS[name], self))

    def _append_event_archive(self, record):
        self.events.append(dict(record))


class OpeningTest(unittest.TestCase):
    def test_opening_key_and_repeat(self):
        plugin = FakePlugin(tempfile.mkdtemp())
        plugin._recent_proactive = ["哟，老板！今天也来啦"]
        self.assertTrue(plugin._opening_repeats("哟，老板！今天又来了"))
        self.assertFalse(plugin._opening_repeats("晚上好，今天忙吗"))

    def test_rewrite_once_changes_opening(self):
        plugin = FakePlugin(tempfile.mkdtemp())
        plugin._recent_proactive = ["哟，老板！今天也来啦"]
        out = plugin._rewrite_proactive_opening("哟，老板！今天又来了")
        self.assertNotEqual(plugin._opening_key(out),
                            plugin._opening_key("哟，老板！今天又来了"))

    def test_recent_prompt(self):
        plugin = FakePlugin(tempfile.mkdtemp())
        plugin._recent_proactive = ["第一句", "第二句", "第三句", "第四句"]
        text = plugin._recent_proactive_prompt()
        self.assertIn("你最近说过", text)
        self.assertIn("第二句", text)
        self.assertIn("不要重复以上任何一句的前 6 个字", text)

    def test_no_recent_prompt(self):
        plugin = FakePlugin(tempfile.mkdtemp())
        self.assertEqual(plugin._recent_proactive_prompt(), "")


class RecordTest(unittest.TestCase):
    def test_record_event_memory_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = FakePlugin(tmp)
            plugin._record_proactive_sent("umo-1", "哟，老板！今晚好",
                                         reason="lonely")
            self.assertEqual(plugin.events[0]["type"], "proactive_sent")
            self.assertEqual(plugin.events[0]["text"], "哟，老板！今晚好")
            self.assertEqual(plugin.events[0]["umo"], "umo-1")
            self.assertEqual(len(plugin._recent_proactive), 1)
            saved = ((ui_settings.load(plugin).get("autonomy") or {})
                     .get("recent_proactive") or [])
            self.assertEqual(saved, ["哟，老板！今晚好"])

    def test_recent_capped_five(self):
        plugin = FakePlugin(tempfile.gettempdir())
        for i in range(7):
            plugin._record_proactive_sent("u", "第%d条主动消息" % i)
        self.assertEqual(len(plugin._recent_proactive), 5)
        self.assertEqual(plugin._recent_proactive[-1], "第6条主动消息")

    def test_context_last_two(self):
        plugin = FakePlugin(tempfile.gettempdir())
        plugin._recent_proactive = ["甲", "乙", "丙"]
        ctx = plugin._recent_proactive_context()
        self.assertIn("我刚说过", ctx)
        self.assertIn("乙", ctx)
        self.assertIn("丙", ctx)
        self.assertNotIn("甲", ctx)


class PromptInjectionTest(unittest.TestCase):
    def test_expr_template_recent_block(self):
        out = et.build_reply(state_ctx={"recent_proactive": "我刚说过：吃了没"})
        self.assertIn("我刚说过：吃了没", out["user"])

    def test_runtime_enrich_sets_recent(self):
        plugin = types.SimpleNamespace(_recent_proactive=["甲", "乙", "丙"])
        core = types.SimpleNamespace(snapshot=lambda: {"v": 0.0})
        ctx = rt.enrich_ctx({"plugin": plugin, "core": core,
                             "user": {}, "meta": {}})
        self.assertIn("我刚说过", ctx.get("recent_proactive", ""))
        self.assertIn("乙", ctx["recent_proactive"])


class UntouchedCooldownTest(unittest.TestCase):
    def test_apply_params_still_conditional(self):
        self.assertIn("if key not in out:", SOURCE)

    def test_wiring_static(self):
        self.assertIn("_recent_proactive_prompt()", SOURCE)
        self.assertIn("_opening_repeats(final)", SOURCE)
        self.assertIn("_record_proactive_sent(", SOURCE)
        self.assertIn("proactive_sent", SOURCE)


if __name__ == "__main__":
    unittest.main()