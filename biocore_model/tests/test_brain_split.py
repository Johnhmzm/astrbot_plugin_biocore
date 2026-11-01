# -*- coding: utf-8 -*-
"""Class-brain split: reply speaks, one probe appraises user+reply."""
import ast
import time
import types
import unittest
from pathlib import Path

from biocore_model import appraisal as ap

MAIN = Path(__file__).resolve().parents[2] / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")


def _load(name):
    tree = ast.parse(SOURCE)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
    node = next(f for f in cls.body if isinstance(f, ast.FunctionDef)
                and f.name == name)
    import interpretation as _interp
    ns = {"time": time, "interpretation": _interp}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<b>", "exec"), ns)
    return ns[name]


class ProbePromptTest(unittest.TestCase):
    def test_prompt_has_user_and_reply(self):
        prompt = ap.build_prompt("你真废物", "我没有不理你")
        self.assertIn("对方：你真废物", prompt)
        self.assertIn("你：我没有不理你", prompt)
        self.assertIn('"dims"', prompt)

    def test_parse_dims_contract(self):
        out = ap.parse('{"dims":{"goal":-0.6,"blame":0.8,"control":0.2,'
                       '"certainty":0.5,"novelty":0.3,"involve":0.9,'
                       '"hit":0.6},"why":"被骂","c":0.8}')
        self.assertEqual(out["dims"]["hit"], 0.6)
        deltas = ap.appraise(out["dims"], confidence=out["confidence"])
        self.assertLess(deltas.get("self_esteem", 0), 0)


class CallCountTest(unittest.TestCase):
    def test_no_user_llm_on_request_path(self):
        # The request hook must not schedule the old separate user appraisal.
        self.assertNotIn("self._schedule_user_appraisal(event, core, text)", SOURCE)
        self.assertIn("self._user_appraisal_immediate(event, text)", SOURCE)

    def test_single_combined_probe_has_user_and_reply(self):
        self.assertIn("_appraisal_mod.probe(\n                            _user_text, _reply_text", SOURCE)
        # probe failure falls back to the word table once
        self.assertIn("self._lexical_user_feedback(", SOURCE)

    def test_immediate_insult_has_no_llm_call(self):
        plugin = types.SimpleNamespace(_last_insult_ts=0.0,
                                       _user_appraisal_key=lambda event: "k")
        fn = _load("_user_appraisal_immediate")
        fn = types.MethodType(fn, plugin)
        fn(types.SimpleNamespace(unified_msg_origin="u", message_id="m"),
           "你真废物，闭嘴")
        # item-5: the lexical classifier is off by default, so no insult cooling.
        self.assertEqual(plugin._last_insult_ts, 0.0)


class LlmCallCountTest(unittest.TestCase):
    def test_one_reply_plus_one_probe(self):
        tree = ast.parse(SOURCE)
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "BioCorePlugin")
        req = next(f for f in cls.body
                   if isinstance(f, ast.AsyncFunctionDef)
                   and f.name == "on_llm_request")
        resp = next(f for f in cls.body
                    if isinstance(f, ast.AsyncFunctionDef)
                    and f.name == "on_llm_response")
        def calls(node):
            out = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    name = getattr(fn, "attr", getattr(fn, "id", ""))
                    if name in ("_llm_v2_call", "probe"):
                        out.append(name)
            return out
        self.assertEqual(calls(req), [])
        self.assertEqual(calls(resp).count("_llm_v2_call"), 1)
        self.assertEqual(calls(resp).count("probe"), 1)


class NoProtocolTest(unittest.TestCase):
    def test_reply_system_has_no_protocol(self):
        from biocore_model import expr_template as et
        out = et.build_reply(opts={"persona": "你是小灰"})
        self.assertNotIn("【输出格式", out["system"])
        self.assertNotIn("<bc>", out["system"])


if __name__ == "__main__":
    unittest.main()
