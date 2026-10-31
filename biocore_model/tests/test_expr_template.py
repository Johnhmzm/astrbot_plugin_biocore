# -*- coding: utf-8 -*-
import re, unittest
from pathlib import Path
from biocore_model import expr_template as et, expr_guard as eg

OPTS = {'persona': '你是小灰', 'speak_style': '像在群里回消息', 'output_protocol': '只输出正文 + <bc>'}
CTX = {'state_block': '她现在有点低落', 'relationship': '亲近', 'gap': '几小时前', 'event_hints': ['他提过体检']}

class TemplateTest(unittest.TestCase):
    def test_system_persona_then_speak(self):
        out = et.build_proactive(state_ctx=CTX, opts=OPTS)
        self.assertLess(out['system'].index('小灰'), out['system'].index('群里'))
    def test_user_order(self):
        out = et.build_proactive(state_ctx=CTX, intent={'kind': 'comfort', 'text_hint': '想关心'}, tone='语气自然', guard=eg.guard_block(), opts=OPTS)
        self.assertEqual(out['order'], ['状态', '关系', '间隔', '你记得', '意图', '语气'])
    def test_user_text_order(self):
        out = et.build_proactive(state_ctx=CTX, intent={'text_hint': '想关心'}, tone='语气自然', guard=eg.guard_block(), opts=OPTS)
        user = out['user']
        self.assertLess(user.index('低落'), user.index('亲近'))
        self.assertLess(user.index('亲近'), user.index('几小时前'))
        self.assertLess(user.index('想关心'), user.index('语气自然'))
        self.assertNotIn('【输出格式', user)
        self.assertIn('<bc>', out['system'])
    def test_missing_optional_skipped(self):
        out = et.build_proactive(state_ctx={'state_block': '平静'}, opts=OPTS)
        self.assertEqual(out['order'], ['状态'])
    def test_intent_kind_fallback(self):
        out = et.build_proactive(intent={'kind': 'repair'}, opts=OPTS)
        self.assertIn('repair', out['user'])
    def test_deterministic(self):
        a = et.build_proactive(state_ctx=CTX, intent={'text_hint': 'x'}, tone='t', guard='g', opts=OPTS)
        b = et.build_proactive(state_ctx=CTX, intent={'text_hint': 'x'}, tone='t', guard='g', opts=OPTS)
        self.assertEqual(a, b)
    def test_no_core_assignment(self):
        for name in ('expr_template.py', 'expr_guard.py'):
            source = Path(__file__).resolve().parent.parent.joinpath(name).read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'core\.[A-Za-z_]+\s*=', source), name)
    def test_build_reply_has_no_intent(self):
        out = et.build_reply(state_ctx=CTX, tone='语气自然', guard='g', opts=OPTS)
        self.assertNotIn('意图', out['order'])
    def test_hints_list_joined(self):
        out = et.build_reply(state_ctx={'event_hints': ['a', 'b']}, opts=OPTS)
        self.assertIn('a；b', out['user'])
    def test_protocol_default_present_in_system(self):
        out = et.build_reply(opts={})
        self.assertIn('【输出格式 · 必须遵守】', out['system'])
        self.assertIn('<bc>{"e":"joy","i":0.6}</bc>', out['system'])
        self.assertNotIn('【输出格式', out['user'])

class GuardTest(unittest.TestCase):
    def test_block_mentions_four(self):
        block = eg.guard_block()
        for token in ('编造', '数值', '内疚', '系统'):
            self.assertIn(token, block)
    def test_forbidden_cases(self):
        for text in ('你不理我我就难过', '我这么难受你也不管', '系统说', '模型觉得', '触发了一次', '权限不足'):
            ok, reason = eg.assert_clean(text)
            self.assertFalse(ok, text); self.assertTrue(reason)
    def test_clean_positive(self):
        ok, _reason = eg.assert_clean('今天吃了苹果派，想跟你说一句。')
        self.assertTrue(ok)
    def test_assert_clean_deterministic(self):
        self.assertEqual(eg.assert_clean('系统'), eg.assert_clean('系统'))
    def test_guard_block_deterministic(self):
        self.assertEqual(eg.guard_block(), eg.guard_block())
    def test_no_assignment_in_guard(self):
        source = Path(__file__).resolve().parent.parent.joinpath('expr_guard.py').read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'core\.[A-Za-z_]+\s*=', source))

if __name__ == '__main__':
    unittest.main()
