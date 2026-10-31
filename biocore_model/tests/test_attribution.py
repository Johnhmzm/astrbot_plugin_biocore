# -*- coding: utf-8 -*-
import unittest
from biocore_model import attribution as at

NOW = 1_700_000_000

class InferTest(unittest.TestCase):
    def test_shame_quadrant(self):
        a = at.infer({'text': '我总是做不好，没办法改'})
        self.assertEqual(a['locus'], 'internal'); self.assertEqual(a['stability'], 'stable'); self.assertEqual(a['controllability'], 'uncontrollable'); self.assertEqual(a['emotion_hint'], 'shame')
    def test_anger_quadrant(self):
        a = at.infer({'text': '他总是这样，我可以解决'})
        self.assertEqual(a['locus'], 'external'); self.assertEqual(a['emotion_hint'], 'anger')
    def test_sadness_quadrant(self):
        a = at.infer({'text': '老板这次没办法改'})
        self.assertEqual(a['emotion_hint'], 'sadness')
    def test_guilt_quadrant(self):
        a = at.infer({'text': '这次是我的错，可以改'})
        self.assertEqual(a['emotion_hint'], 'guilt')
    def test_neutral_when_ambiguous(self):
        a = at.infer({'text': '今天天气如何'})
        self.assertEqual(a['emotion_hint'], 'neutral'); self.assertEqual(a['locus'], 'neutral')
    def test_conversation_hint_used(self):
        a = at.infer({}, conversation_hint='他总是这样')
        self.assertEqual(a['locus'], 'external')

class ApplyTest(unittest.TestCase):
    def test_apply_returns_deltas(self):
        deltas = at.apply({}, {'emotion_hint': 'anger'}, NOW)
        self.assertGreater(deltas['anger'], 0); self.assertGreater(deltas['stress'], 0)
    def test_apply_shame(self):
        deltas = at.apply({}, {'emotion_hint': 'shame'}, NOW)
        self.assertGreater(deltas['self_blame'], 0); self.assertLess(deltas['valence'], 0)
    def test_apply_guilt_repair(self):
        deltas = at.apply({}, {'emotion_hint': 'guilt'}, NOW)
        self.assertGreater(deltas['repair'], 0)
    def test_apply_idempotent_same_now(self):
        first = at.apply({}, {'emotion_hint': 'anger'}, NOW)
        self.assertTrue(at.apply(first, {'emotion_hint': 'anger'}, NOW) == {})
    def test_apply_neutral_empty(self):
        self.assertEqual(at.apply({}, {'emotion_hint': 'neutral'}, NOW), {})
    def test_apply_does_not_touch_appraisal(self):
        deltas = at.apply({}, {'emotion_hint': 'anger'}, NOW)
        self.assertNotIn('goal_congruence', deltas); self.assertNotIn('ego_involvement', deltas)

class ViewTest(unittest.TestCase):
    def test_view_fields(self):
        view = at.view({}, at.infer({'text': '老板这次没办法改'}))
        for key in ('locus', 'stability', 'controllability', 'emotion_hint'):
            self.assertIn(key, view)
    def test_view_quadrant_recompute(self):
        view = at.view({}, {'locus': 'external', 'stability': 'stable', 'controllability': 'uncontrollable'})
        self.assertEqual(view['emotion_hint'], 'sadness')

if __name__ == '__main__':
    unittest.main()
