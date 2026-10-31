# -*- coding: utf-8 -*-
"""HUMAN-6 intent rendering tests: tendency text without numbers/emotion words."""
import unittest

from biocore_model import intent_render as ir

ACTIONS = ("approach", "share", "question", "withdraw", "repair", "rest")


class RenderTest(unittest.TestCase):
    def test_every_action_has_phrase(self):
        for action in ACTIONS:
            text = ir.render({"action": action})
            self.assertEqual(text, ir.PHRASES[action])

    def test_no_digits(self):
        for action in ACTIONS:
            self.assertTrue(ir.check(ir.render({"action": action}, tone="3 天后"))["ok"])

    def test_no_emotion_words(self):
        for action in ACTIONS:
            text = ir.render({"action": action}, tone="难过 5 分", guard="别生气")
            result = ir.check(text)
            self.assertTrue(result["ok"], text)

    def test_unknown_action_fallback(self):
        self.assertIn(ir.FALLBACK, ir.render({"action": "explode"}))

    def test_empty_intent_safe(self):
        self.assertTrue(ir.render(None))
        self.assertTrue(ir.render({}))

    def test_deterministic(self):
        self.assertEqual(ir.render({"action": "repair"}, tone="慢一点"),
                         ir.render({"action": "repair"}, tone="慢一点"))


class CheckSanitizeTest(unittest.TestCase):
    def test_check_detects_problems(self):
        result = ir.check("我有点难过 3 分")
        self.assertFalse(result["ok"])
        self.assertTrue(result["digits"])
        self.assertIn("难过", result["emotion_words"])

    def test_check_clean_text(self):
        self.assertTrue(ir.check("想和你说说话")["ok"])

    def test_sanitize_removes(self):
        text = ir.sanitize("焦虑 12 分，想靠近")
        self.assertTrue(ir.check(text)["ok"])

    def test_tendency_mapping(self):
        self.assertEqual(ir.tendency({"action": "approach"}), "approach")
        self.assertEqual(ir.tendency({"action": "withdraw"}), "withdraw")
        self.assertEqual(ir.tendency({"action": "rest"}), "withdraw")
        self.assertEqual(ir.tendency(None), "neutral")


if __name__ == "__main__":
    unittest.main()
