# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_reason as ar

class ReasonTest(unittest.TestCase):
    def test_social_gap(self):
        r = ar.extract({'social_gap': 0.8})
        self.assertEqual(r['code'], 'social_gap'); self.assertIn('很久', r['text'])
    def test_lonely(self):
        self.assertEqual(ar.extract({'lonely': 0.5})['code'], 'lonely')
    def test_anxiety(self):
        self.assertEqual(ar.extract({'anxiety_fear': 0.6})['code'], 'anxiety')
    def test_anger(self):
        self.assertEqual(ar.extract({'anger_conflict': 0.7})['code'], 'anger')
    def test_repair(self):
        self.assertEqual(ar.extract({'repair_urge': 0.4})['code'], 'repair')
    def test_memory_due_with_title(self):
        r = ar.extract({'memory_due': 0.5}, memory_title='明天体检')
        self.assertEqual(r['code'], 'memory_due'); self.assertIn('明天体检', r['text'])
    def test_prompt_contains_motive(self):
        prompt = ar.build_prompt({'code': 'lonely', 'text': '有点闷', 'weight': 0.3})
        self.assertIn('动机：', prompt); self.assertIn('有点闷', prompt); self.assertIn('<bc>', prompt)
    def test_fallback_contains_reason(self):
        text = ar.fallback_text({'text': '很久没联系了'}, '在。')
        self.assertIn('很久没联系了', text); self.assertIn('在。', text)
    def test_empty_parts_default(self):
        self.assertEqual(ar.extract({})['code'], 'lonely')
    def test_priority_social_gap_over_memory(self):
        r = ar.extract({'social_gap': 0.2, 'memory_due': 0.9}, memory_due=0.0)
        self.assertEqual(r['code'], 'memory_due')

if __name__ == '__main__':
    unittest.main()
