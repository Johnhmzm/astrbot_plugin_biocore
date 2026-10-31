# -*- coding: utf-8 -*-
import unittest
from biocore_model import expr_tone as et

class ToneTest(unittest.TestCase):
    def test_anxiety(self):
        out = et.tone_block('anxiety')
        self.assertAlmostEqual(out['chars_mult'], 0.8); self.assertIn('想问清楚', out['text'])
    def test_sadness(self):
        out = et.tone_block('sadness'); self.assertAlmostEqual(out['chars_mult'], 0.7)
    def test_anger(self):
        self.assertAlmostEqual(et.tone_block('anger')['chars_mult'], 0.9)
    def test_joy(self):
        out = et.tone_block('joy'); self.assertAlmostEqual(out['chars_mult'], 1.2); self.assertIn('分享', out['text'])
    def test_guilt(self):
        self.assertAlmostEqual(et.tone_block('guilt')['chars_mult'], 0.75)
    def test_calm(self):
        self.assertEqual(et.tone_block('calm')['chars_mult'], 1.0)
    def test_suppress_shrinks(self):
        out = et.tone_block('joy', regulation='suppress')
        self.assertTrue(out['suppressed']); self.assertLess(out['chars_mult'], 1.2); self.assertIn('收一点', out['text'])
    def test_reappraise_steady(self):
        self.assertIn('讲道理', et.tone_block('sadness', regulation='reappraise')['text'])
    def test_low_esteem_uncertain(self):
        out = et.tone_block('calm', self_esteem=0.3)
        self.assertIn('也许', out['text']); self.assertEqual(out['text'].count('也许'), 1)
    def test_high_esteem_no_uncertain(self):
        self.assertNotIn('也许', et.tone_block('calm', self_esteem=0.8)['text'])
    def test_deterministic(self):
        self.assertEqual(et.tone_block('anger', 'joy', 0.4, 0.5, 'suppress'), et.tone_block('anger', 'joy', 0.4, 0.5, 'suppress'))
    def test_unknown_falls_back_calm(self):
        self.assertEqual(et.tone_block('bogus')['tendency'], 'calm')
    def test_emotion_fallback(self):
        self.assertEqual(et.tone_block(None, 'sadness')['tendency'], 'sadness')
    def test_no_psych_terms(self):
        for tendency in et.BASE:
            text = et.tone_block(tendency)['text']
            self.assertNotIn('行动倾向', text); self.assertNotIn('焦虑值', text)

if __name__ == '__main__':
    unittest.main()
