# -*- coding: utf-8 -*-
import unittest
from biocore_model import mood as mood_bio

class MoodTest(unittest.TestCase):
    def test_update_toward_target(self):
        m = mood_bio.mood_update({'valence': 0.0, 'arousal': 0.0}, 1.0, 0.0)
        self.assertGreater(m['valence'], 0); self.assertLess(m['valence'], 1)
    def test_rate(self):
        m = mood_bio.mood_update({'valence': 0.0, 'arousal': 0.0}, 1.0, 0.0, rate=0.05)
        self.assertAlmostEqual(m['valence'], 0.05)
    def test_idempotent_same_now(self):
        m = mood_bio.mood_update({'valence': 0.0, 'arousal': 0.0}, 1.0, 0.0, now=100)
        again = mood_bio.mood_update(m, 1.0, 0.0, now=100)
        self.assertEqual(again['valence'], m['valence'])
    def test_label_quadrants(self):
        self.assertEqual(mood_bio.label({'valence': -0.5, 'arousal': 0.8}), '低落')
        self.assertEqual(mood_bio.label({'valence': 0.5, 'arousal': 0.8}), '愉快')
        self.assertEqual(mood_bio.label({'valence': 0.2, 'arousal': 0.2}), '平静偏正')
        self.assertEqual(mood_bio.label({'valence': -0.2, 'arousal': 0.2}), '平静')
    def test_view_fields(self):
        v = mood_bio.mood_view({'valence': 0.1, 'arousal': 0.2})
        for key in ('valence', 'arousal', 'label'): self.assertIn(key, v)
    def test_half_life_ticks(self):
        ticks = mood_bio.ticks_to_target(0.0, 1.0)
        self.assertGreater(ticks, 40); self.assertLess(ticks, 100)
    def test_clamp(self):
        self.assertLessEqual(mood_bio.mood_update({'valence': 1.0}, 5.0, 0.0)['valence'], 1.0)
        self.assertGreaterEqual(mood_bio.mood_update({'valence': -1.0}, -5.0, 0.0)['valence'], -1.0)
    def test_zero_dt_no_change_without_now(self):
        m = {'valence': 0.3, 'arousal': 0.2}
        self.assertEqual(mood_bio.mood_update(m, 0.3, 0.2)['valence'], 0.3)

if __name__ == '__main__':
    unittest.main()
