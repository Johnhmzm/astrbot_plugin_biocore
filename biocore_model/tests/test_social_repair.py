# -*- coding: utf-8 -*-
import unittest
from biocore_model import social_repair as sr

class GratitudeTest(unittest.TestCase):
    def test_kindness_raises(self):
        self.assertAlmostEqual(sr.gratitude_event(0.0, True), 0.15)
    def test_message_references_event(self):
        events = [{'owner': 'user', 'valence': 0.5, 'text': '帮我拿快递'}]
        msg = sr.gratitude_message(events, 0.8)
        self.assertIn('帮我拿快递', msg); self.assertIn('谢了', msg)
    def test_no_event_falls_back(self):
        self.assertEqual(sr.gratitude_message([{'owner': 'self', 'text': 'x'}], 0.8), '')
    def test_low_gratitude_no_message(self):
        self.assertEqual(sr.gratitude_message([{'owner': 'user', 'valence': 1, 'text': 'x'}], 0.2), '')

class BoundaryTest(unittest.TestCase):
    def test_depth_by_stage(self):
        self.assertLess(sr.boundaries('stranger')['disclosure_depth'], sr.boundaries('close')['disclosure_depth'])
    def test_blocked_reply(self):
        self.assertEqual(sr.boundary_reply('ex', ['ex']), '这个先不说。')
    def test_normal_topic(self):
        self.assertEqual(sr.boundary_reply('天气', ['ex']), '')

class EmpathyTest(unittest.TestCase):
    def test_affective_shift(self):
        self.assertAlmostEqual(sr.empathy(1.0, cognitive_accuracy=0.0)['valence_shift'], 0.3)
    def test_four_modes(self):
        self.assertEqual(sr.empathy(1.0, cognitive_accuracy=1.0)['mode'], 'comfort')
        self.assertEqual(sr.empathy(0.0, cognitive_accuracy=1.0)['mode'], 'reason')
        self.assertEqual(sr.empathy(1.0, cognitive_accuracy=0.0)['mode'], 'resonance')
        self.assertEqual(sr.empathy(0.0, cognitive_accuracy=0.0)['mode'], 'cold')

class RepairTest(unittest.TestCase):
    def test_trigger(self):
        self.assertTrue(sr.repair_check('你说什么？', '这是一句比较长的上一条回复内容')['needed'])
    def test_no_trigger_short(self):
        self.assertFalse(sr.repair_check('嗯', '长回复长回复长回复长回复')['needed'])
    def test_failure_degrades(self):
        out = sr.repair_check('没懂？', '这是一句比较长的上一条回复内容', clarify_failures=2)
        self.assertIn('简单点说', out['text'])

class TimeTest(unittest.TestCase):
    def test_gap_bands(self):
        self.assertEqual(sr.time_gap_text(0.5), '刚刚'); self.assertEqual(sr.time_gap_text(3), '几小时前')
        self.assertEqual(sr.time_gap_text(48), '两天多'); self.assertEqual(sr.time_gap_text(200), '一周前')
    def test_future(self):
        self.assertEqual(sr.future_text(3), '还有 3 天'); self.assertEqual(sr.future_text(0), '已经过了')
    def test_memory_label(self):
        self.assertIn('你说过', sr.memory_time_label(3))

    def test_trust_raises_depth(self):
        self.assertGreater(sr.boundaries('stranger', trust=0.9)['disclosure_depth'], sr.boundaries('stranger', trust=0.1)['disclosure_depth'])

    def test_empathy_fields(self):
        info = sr.empathy(0.5, cognitive_accuracy=0.6)
        for key in ('affective', 'cognitive', 'mode', 'valence_shift'):
            self.assertIn(key, info)

    def test_view_fields(self):
        view = sr.view(0.4, sr.boundaries('friend'), sr.empathy(0.5), sr.repair_check('嗯'), {'gap': '刚刚'})
        for key in ('gratitude', 'boundaries', 'empathy', 'repair', 'time_sense'):
            self.assertIn(key, view)


if __name__ == '__main__':
    unittest.main()
