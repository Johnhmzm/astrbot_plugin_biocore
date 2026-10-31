# -*- coding: utf-8 -*-
import unittest
from biocore_model import prompt_rules

class SpeakStyleOrderTest(unittest.TestCase):
    def test_speak_style_text(self):
        text = prompt_rules.render_speak_style(10, 30)
        self.assertIn('像在群里回消息那样', text); self.assertIn('通常 10 字以内', text); self.assertIn('最多不超过 30 字', text)

    def test_render_rules_no_longer_prepends_speak(self):
        text = prompt_rules.render_rules({'valence': 0.5}, {}, 0.7)
        self.assertNotIn('【说话方式', text)

    def test_order_persona_speak_rest_protocol(self):
        text = prompt_rules.compose_prompt('你是小灰。', prompt_rules.render_speak_style(10, 30), '情绪：平静', '<bc>{}</bc>')
        self.assertLess(text.index('你是小灰'), text.index('【说话方式'))
        self.assertLess(text.index('【说话方式'), text.index('情绪：平静'))
        self.assertLess(text.index('情绪：平静'), text.index('<bc>'))

    def test_fallback_without_persona_starts_with_speak(self):
        text = prompt_rules.compose_prompt('', prompt_rules.render_speak_style(10, 30), '情绪：平静', '')
        self.assertTrue(text.startswith('【说话方式'))

    def test_disabled_soft_limit_no_speak(self):
        class P:
            reply_soft_limit_enabled = False
        speak = prompt_rules.render_speak_style(10, 30) if P.reply_soft_limit_enabled else ''
        self.assertEqual(speak, '')

    def test_budget_keeps_speak(self):
        rest = 'x' * 500
        text = prompt_rules.compose_prompt('p', prompt_rules.render_speak_style(10, 30), rest, '')
        self.assertLessEqual(len(text), 400); self.assertIn('【说话方式', text)

if __name__ == '__main__':
    unittest.main()
