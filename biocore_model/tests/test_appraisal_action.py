# -*- coding: utf-8 -*-
import unittest
from biocore_model import appraisal_action as aa

class AppraisalTest(unittest.TestCase):
    def test_anxiety_rule(self):
        self.assertEqual(aa.appraise(-0.5, 0.8, 0.2, 0.6)['emotion'], 'anxiety')
    def test_anger_rule(self):
        self.assertEqual(aa.appraise(-0.5, 0.8, 0.8, 0.2)['emotion'], 'anger')
    def test_sadness_rule(self):
        self.assertEqual(aa.appraise(-0.5, 0.2, 0.5, 0.5)['emotion'], 'sadness')
    def test_joy_rule(self):
        self.assertEqual(aa.appraise(0.6, 0.8, 0.5, 0.5)['emotion'], 'joy')
    def test_same_event_differs_by_coping(self):
        low = aa.appraise(-0.5, 0.8, 0.2, 0.6)['emotion']
        high = aa.appraise(-0.5, 0.8, 0.8, 0.6)['emotion']
        self.assertNotEqual(low, high)
    def test_dimensions(self):
        data = aa.appraisal(0.5, 0.6, 0.7, 0.8, 0.9)
        for key in aa.DIMS: self.assertIn(key, data)
    def test_goal_congruence_clamped(self):
        self.assertLessEqual(aa.appraisal(goal_congruence=5)['goal_congruence'], 1.0)

class ActionTest(unittest.TestCase):
    def test_anxiety_action(self):
        a = aa.action_for('anxiety')
        self.assertGreater(a['drive_delta'], 0); self.assertLess(a['max_chars_mult'], 1.0)
    def test_sadness_action(self):
        self.assertLess(aa.action_for('sadness')['drive_delta'], 0)
    def test_anger_action(self):
        self.assertGreater(aa.action_for('anger')['drive_delta'], 0)
    def test_joy_action(self):
        self.assertGreater(aa.action_for('joy')['max_chars_mult'], 1.0)
    def test_guilt_action(self):
        self.assertEqual(aa.action_for('guilt')['repair_delta'], 0.05)
    def test_unknown_emotion_neutral(self):
        self.assertEqual(aa.action_for('bogus')['drive_delta'], 0.0)

class CuriosityTest(unittest.TestCase):
    def test_new_unanswered_raises(self):
        self.assertGreater(aa.curiosity_update(0.0, new_topic=True, answered=False), 0.0)
    def test_answered_lowers(self):
        self.assertLess(aa.curiosity_update(0.5, answered=True), 0.5)
    def test_decay_hours(self):
        self.assertLess(aa.curiosity_update(0.5, hours=2), 0.5)
    def test_effects(self):
        effects = aa.curiosity_effects(1.0)
        self.assertAlmostEqual(effects['question_probability_bonus'], 0.3)
        self.assertAlmostEqual(effects['drive_delta'], 0.02)
    def test_prompt_line(self):
        line = aa.prompt_line(aa.action_for('anxiety'), 0.5)
        self.assertIn('你现在想', line); self.assertIn('好奇', line)

if __name__ == '__main__':
    unittest.main()
