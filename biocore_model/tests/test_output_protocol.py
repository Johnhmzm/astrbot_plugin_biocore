# -*- coding: utf-8 -*-
"""Output-protocol tests: single constant, system placement, strong format."""
import unittest
from pathlib import Path

from biocore_model import expr_template as et


class ConstantTest(unittest.TestCase):
    def test_header_example_and_constraints(self):
        text = et.PROMPT_OUTPUT_PROTOCOL
        self.assertIn("【输出格式 · 必须遵守】", text)
        self.assertIn('<bc>{"e":"joy","i":0.6}</bc>', text)
        self.assertIn("e 只能取", text)
        self.assertIn("joy / trust / anxiety / sadness / anger / loneliness / neutral", text)
        self.assertIn("i 是 0 到 1 的小数", text)
        self.assertIn("不要包在代码块里", text)

    def test_old_weak_sentence_is_gone(self):
        self.assertNotIn("只输出正文 + 一个 <bc> 标签", et.PROMPT_OUTPUT_PROTOCOL)


class TemplatePlacementTest(unittest.TestCase):
    def test_reply_system_has_no_protocol(self):
        out = et.build_reply(opts={"persona": "你是小灰", "speak_style": "口语"})
        self.assertNotIn("【输出格式", out["system"])
        self.assertNotIn("<bc>", out["system"])
        self.assertNotIn("【输出格式", out["user"])

    def test_proactive_system_has_no_protocol(self):
        out = et.build_proactive(opts={"persona": "你是小灰"})
        self.assertNotIn("【输出格式", out["system"])
        self.assertNotIn("<bc>", out["system"])
        self.assertNotIn("【输出格式", out["user"])

    def test_protocol_absent_everywhere(self):
        out = et.build_reply(opts={})
        self.assertEqual(out["system"].count("【输出格式 · 必须遵守】"), 0)

    def test_order_no_protocol_in_user(self):
        out = et.build_reply(opts={})
        self.assertNotIn("输出协议", out["order"])

    def test_custom_protocol_is_ignored(self):
        out = et.build_reply(opts={"output_protocol": "CUSTOM-PROTOCOL"})
        self.assertNotIn("CUSTOM-PROTOCOL", out["system"])
        self.assertNotIn("CUSTOM-PROTOCOL", out["user"])


class WiringTest(unittest.TestCase):
    def test_main_uses_constant_not_old_literal(self):
        source = (Path(__file__).resolve().parents[2] / "main.py").read_text(encoding="utf-8")
        self.assertNotIn('_etpl.PROMPT_OUTPUT_PROTOCOL', source)
        self.assertNotIn('"output_protocol"', source)

    def test_runtime_has_no_protocol_default(self):
        from biocore_model import runtime
        ctx = runtime.make_request_ctx(plugin=None, event=None, core=None, text="x")
        ctx = runtime.enrich_ctx(ctx)
        opts = (ctx.get("meta") or {}).get("template_opts") or {}
        self.assertFalse(opts.get("output_protocol"))


if __name__ == "__main__":
    unittest.main()
