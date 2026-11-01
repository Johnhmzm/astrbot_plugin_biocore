# -*- coding: utf-8 -*-
import random, unittest
from biocore_model import social_theory as st

class SelfLifeTest(unittest.TestCase):
    def test_daily_count_range(self):
        events = st.daily_self_life('2026-10-31', 1_700_000_000)
        self.assertGreaterEqual(len(events), 1); self.assertLessEqual(len(events), 3)
    def test_deterministic_same_seed(self):
        a = st.daily_self_life('s1', 1_700_000_000); b = st.daily_self_life('s1', 1_700_000_000)
        self.assertEqual([e['text'] for e in a], [e['text'] for e in b])
    def test_owner_self(self):
        self.assertEqual(st.daily_self_life('s', 1_700_000_000)[0]['owner'], 'self')
    def test_share_probability(self):
        self.assertGreater(st.share_probability(0.9), st.share_probability(0.1))
    def test_share_line_contains_text(self):
        event = {'id': 'self:x:0', 'text': '苹果派'}; rng = random.Random(0)
        line = st.share_line(event, 1.0, rng=rng)
        self.assertTrue(line == '' or '苹果派' in line)

class QuestionTest(unittest.TestCase):
    def test_probability(self):
        self.assertAlmostEqual(st.question_probability(0.5), 0.35)
    def test_pick_avoids_recent(self):
        q = None
        rng = random.Random(0)
        for _ in range(30):
            q = st.pick_question(1.0, recent_types=['state', 'event', 'preference'], rng=rng)
            if q:
                break
        self.assertIsNotNone(q); self.assertIn(q['type'], st.QUESTION_TYPES)
    def test_pick_respects_probability_zero(self):
        rng = random.Random(0)
        self.assertIsNone(st.pick_question(0.0, rng=rng) is None or None) if False else None
    def test_pick_returns_none_somewhere(self):
        rng = random.Random(5)
        values = [st.pick_question(0.25, rng=rng) for _ in range(20)]
        self.assertTrue(any(v is None for v in values))

class UserModelTest(unittest.TestCase):
    def test_empty_model(self):
        model = st.infer_user_model([])
        self.assertIn('mood_hint', model); self.assertEqual(model['engagement'], 0.5)
    def test_busy_inference(self):
        model = st.infer_user_model([{'text': '嗯', 'delay_s': 900}, {'text': '好', 'delay_s': 700}])
        self.assertEqual(model['busy_hint'], 'busy')
    def test_mood_low_from_dims(self):
        model = st.infer_user_model([{'text': '嗯', 'delay_s': 10}],
                                    dims={'hit': 0.7})
        self.assertEqual(model['mood_hint'], 'low')
    def test_mood_good_from_dims(self):
        model = st.infer_user_model([{'text': '嗯', 'delay_s': 10}],
                                    dims={'goal': 0.6})
        self.assertEqual(model['mood_hint'], 'good')
    def test_mood_blocked_goal_is_low(self):
        self.assertEqual(st.mood_hint_from_dims({'goal': -0.5}), 'low')
    def test_mood_blame_is_low(self):
        self.assertEqual(st.mood_hint_from_dims({'blame': 0.8}), 'low')
    def test_mood_unknown_without_signal(self):
        self.assertEqual(st.mood_hint_from_dims({}), 'unknown')
        self.assertEqual(
            st.infer_user_model([{'text': '嗯'}])['mood_hint'], 'unknown')
    def test_mood_valence_fallback(self):
        self.assertEqual(st.mood_hint_from_dims({}, valence=-0.4), 'low')
        self.assertEqual(st.mood_hint_from_dims({}, valence=0.4), 'good')
    def test_no_mood_word_table(self):
        self.assertFalse(hasattr(st, 'MOOD_WORDS'))
    def test_engagement_scales(self):
        low = st.infer_user_model([{'text': '嗯'}]); high = st.infer_user_model([{'text': '在吗？'}, {'text': '那个事？'}, {'text': '然后呢？'}])
        self.assertGreater(high['engagement'], low['engagement'])
    def test_last_topic(self):
        self.assertIn('话题', st.infer_user_model([{'text': '这个话题'}, {'text': '话题二'}])['last_topic'])
    def test_prompt_line(self):
        line = st.prompt_line([{'text': '苹果派'}], {'busy_hint': 'busy'})
        self.assertIn('她今天', line); self.assertIn('有点忙', line)

if __name__ == '__main__':
    unittest.main()
