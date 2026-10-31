# -*- coding: utf-8 -*-
import time, unittest
from biocore_model import proactive_context as pc

NOW = 1_700_000_000

class FakeCore:
    labels = {'emotion': 'joy', 'intensity': 0.62}
    spectrum_probs = {'joy': 0.62, 'contentment': 0.23, 'amusement': 0.15}
    v = 0.42; a = 0.66; d = 0.52; social = 0.61; stress = 0.24; energy = 0.81
    homeostasis = {'drives': {'belong': 0.26, 'curiosity': 0.1}}
    interoception = {'label': 'steady'}

class ContextTest(unittest.TestCase):
    def test_state_block_fields(self):
        text = pc.render_state_block(FakeCore())
        self.assertIn('主导情绪：joy', text); self.assertIn('情绪谱', text); self.assertIn('维度', text)
    def test_state_block_missing_fields_no_crash(self):
        class Empty: pass
        self.assertIn('主导情绪', pc.render_state_block(Empty()))
    def test_relationship(self):
        text = pc.render_relationship({'state': {'closeness': 0.61, 'trust': 0.57, 'conflict': 0.22}, 'attachment': {'safe': 0.5}})
        self.assertIn('亲近 0.61', text); self.assertIn('依恋安全感 0.50', text)
    def test_gap_bands(self):
        self.assertIn('刚刚', pc.gap_text(0.5))
        self.assertIn('几小时前', pc.gap_text(3))
        self.assertIn('大半天', pc.gap_text(10))
        self.assertIn('两天多', pc.gap_text(38))
        self.assertIn('好几天', pc.gap_text(80))
    def test_gap_style_hint(self):
        self.assertIn('抗议', pc.attachment_gap_hint('anxious'))
        self.assertIn('不要提间隔', pc.attachment_gap_hint('avoidant'))
        self.assertIn('温和问候', pc.attachment_gap_hint('secure'))
    def test_event_next_date(self):
        hints = pc.render_event_hints([{'title': '体检', 'next_date_ts': NOW + 86400, 'importance': 0.8}], NOW)
        self.assertTrue(any('体检' in h and '明天' in h for h in hints))
    def test_event_unresolved(self):
        hints = pc.render_event_hints([{'title': '旧话题', 'unresolved': True, 'ts': NOW - 2 * 86400, 'importance': 0.8}], NOW)
        self.assertTrue(any('没收尾' in h for h in hints))
    def test_event_low_importance_filtered(self):
        self.assertEqual(pc.render_event_hints([{'title': 'x', 'next_date_ts': NOW + 3600, 'importance': 0.1}], NOW), [])
    def test_event_no_title_skipped(self):
        self.assertEqual(pc.render_event_hints([{'next_date_ts': NOW + 3600, 'importance': 0.9}], NOW), [])
    def test_event_max_two(self):
        events = [{'title': 'a', 'next_date_ts': NOW + 3600, 'importance': 0.9}, {'title': 'b', 'unresolved': True, 'ts': NOW - 2 * 86400, 'importance': 0.9}, {'title': 'c', 'unresolved': True, 'ts': NOW - 2 * 86400, 'importance': 0.9}]
        self.assertLessEqual(len(pc.render_event_hints(events, NOW)), 2)
    def test_l1_extra_lines(self):
        lines = pc.l1_extra_lines(38, [{'title': '体检', 'next_date_ts': NOW + 86400, 'importance': 0.9}], NOW)
        self.assertTrue(any(line.startswith('【间隔】') for line in lines))
        self.assertTrue(any(line.startswith('【你记得】') for line in lines))
    def test_prompt_order(self):
        prompt = pc.build_proactive_prompt('人设', '说话方式', '情绪块', '关系块', '间隔块', ['提示'], {'code': 'lonely', 'text': '有点闷', 'weight': 0.3}, 1.34)
        user = prompt['user']
        self.assertLess(user.index('【当前情绪】'), user.index('【关系】'))
        self.assertLess(user.index('【关系】'), user.index('【间隔】'))
        self.assertLess(user.index('【间隔】'), user.index('【动机】'))
        self.assertLess(user.index('【动机】'), user.index('【要求】'))
        self.assertIn('动机', user)
        self.assertIn('<bc>', prompt['system'])
        self.assertIn('【输出格式 · 必须遵守】', prompt['system'])
    def test_prompt_contains_event_hints(self):
        prompt = pc.build_proactive_prompt("人设", "说话", "x", "y", "z", ["他提过「体检」（明天）"], {"code": "memory_due", "text": "记得体检", "weight": 0.4}, 1.2)
        self.assertIn("你记得", prompt["user"]); self.assertIn("体检", prompt["user"])

    def test_system_contains_persona_and_speak(self):
        prompt = pc.build_proactive_prompt('人设', '说话方式', 'x', 'y', 'z', [], {})
        self.assertIn('人设', prompt['system']); self.assertIn('说话方式', prompt['system'])

if __name__ == '__main__':
    unittest.main()
