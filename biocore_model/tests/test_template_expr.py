# -*- coding: utf-8 -*-
"""Safe template engine: substitution, conditionals, loops, no code execution."""
import unittest

from biocore_model import template_expr as t
from biocore_model import expr_template as et


class RenderTest(unittest.TestCase):
    def test_plain_text_untouched(self):
        self.assertEqual(t.render("你好", {}), "你好")

    def test_substitution(self):
        self.assertEqual(t.render("你好{{name}}", {"name": "老板"}), "你好老板")

    def test_missing_variable_is_empty(self):
        self.assertEqual(t.render("[{{missing}}]", {}), "[]")

    def test_if_else(self):
        self.assertEqual(t.render("{% if trust > 0.5 %}亲近{% else %}疏远{% endif %}",
                                  {"trust": 0.7}), "亲近")
        self.assertEqual(t.render("{% if trust > 0.5 %}亲近{% else %}疏远{% endif %}",
                                  {"trust": 0.1}), "疏远")

    def test_elif_chain(self):
        v = {"trust": 0.3}
        self.assertEqual(t.render("{% if trust > 0.5 %}a{% elif trust > 0.2 %}b{% else %}c{% endif %}", v), "b")

    def test_for_loop(self):
        self.assertEqual(t.render("{% for x in tags %}[{{x}}]{% endfor %}", {"tags": ["a", "b"]}), "[a][b]")

    def test_nested_if(self):
        tpl = "{% if a %}A{% if b %}B{% endif %}{% endif %}"
        self.assertEqual(t.render(tpl, {"a": 1, "b": 1}), "AB")
        self.assertEqual(t.render(tpl, {"a": 1, "b": 0}), "A")

    def test_arithmetic_and_helpers(self):
        self.assertEqual(t.render("{{ len(tags) }}", {"tags": [1, 2, 3]}), "3")
        self.assertEqual(t.render("{{ min(a, b) }}", {"a": 2, "b": 5}), "2")

    def test_no_code_execution(self):
        out = t.render('{{ __import__("os").system("echo pwn") }}', {})
        self.assertEqual(out, "")
        self.assertEqual(t.render("{{ ().__class__ }}", {}), "")

    def test_bad_syntax_is_safe(self):
        self.assertEqual(t.render("{% if %}x{% endif %}", {}), "")


class WiringTest(unittest.TestCase):
    def test_build_reply_renders_template_vars(self):
        built = et.build_reply({}, relationship={},
                               state_ctx={"state_block": "{% if trust > 0.5 %}亲近{% else %}疏远{% endif %}"},
                               tone="", guard="", opts={"template_vars": {"trust": 0.8}})
        self.assertIn("亲近", built["user"])
        self.assertNotIn("{%", built["user"])

    def test_bulit_reply_without_vars_keeps_text(self):
        built = et.build_reply({}, relationship={}, state_ctx={"state_block": "情绪：平静"},
                               tone="", guard="", opts={})
        self.assertIn("情绪：平静", built["user"])


if __name__ == "__main__":
    unittest.main()
