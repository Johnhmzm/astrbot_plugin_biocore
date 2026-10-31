# -*- coding: utf-8 -*-
import unittest
from biocore_model import attachment_regulation as ar

class AttachmentTest(unittest.TestCase):
    def test_anxious_drive(self):
        self.assertAlmostEqual(ar.activation('anxious', threat=1.0)['drive_mult'], 1.2)
    def test_avoidant_drive(self):
        self.assertAlmostEqual(ar.activation('avoidant', threat=1.0)['drive_mult'], 0.7)
    def test_secure_mode(self):
        self.assertEqual(ar.activation('secure', threat=1.0)['mode'], 'comfort')
    def test_activation_rises(self):
        self.assertGreater(ar.activation('secure', threat=1.0)['activation'], 0)
    def test_response_drop(self):
        state = ar.activation('secure', threat=0.0, current=0.8, responded=True)
        self.assertAlmostEqual(state['activation'], 0.4)
    def test_decay_per_hour(self):
        state = ar.activation('secure', threat=0.0, current=1.0, hours=5)
        self.assertAlmostEqual(state['activation'], 0.5)

class RegulationTest(unittest.TestCase):
    def test_avoidant_suppresses(self):
        self.assertEqual(ar.choose_strategy('avoidant'), 'suppress')
    def test_low_energy_suppresses(self):
        self.assertEqual(ar.choose_strategy('secure', energy=0.2), 'suppress')
    def test_reappraise_mult(self):
        self.assertAlmostEqual(ar.regulate('reappraise')['negative_mult'], 0.6)
    def test_suppress_mult_and_stress(self):
        out = ar.regulate('suppress')
        self.assertAlmostEqual(out['negative_mult'], 0.5); self.assertGreater(out['stress_delta'], 0)
    def test_effort_accumulates(self):
        first = ar.regulate('suppress')['effort']; second = ar.regulate('suppress', effort=first)['effort']
        self.assertGreater(second, first)
    def test_regulation_risk(self):
        self.assertFalse(ar.regulation_risk(0.5)); self.assertTrue(ar.regulation_risk(1.6))

class MoodTest(unittest.TestCase):
    def test_mood_toward_emotion(self):
        mood = ar.mood_update({'valence': 0.0, 'arousal': 0.0}, valence=1.0)
        self.assertGreater(mood['valence'], 0); self.assertLess(mood['valence'], 1)
    def test_mood_converges_slowly(self):
        mood = {'valence': 0.0, 'arousal': 0.0}
        for _ in range(10): mood = ar.mood_update(mood, valence=1.0)
        self.assertLess(mood['valence'], 0.5)  # 10 ticks ≈ 50 min, still far from target
    def test_mood_half_life_ticks(self):
        ticks = ar.mood_ticks_to_zero(-0.5)
        self.assertGreaterEqual(ticks, 40); self.assertLessEqual(ticks, 80)
    def test_view_fields(self):
        v = ar.view('anxious', 0.5, 'hyperactivating', 'suppress', 0.3, True, {'valence': -0.2, 'arousal': 0.4})
        for key in ('attachment', 'regulation', 'mood'): self.assertIn(key, v)

    def test_unknown_style_falls_back(self):
        self.assertEqual(ar.activation('bogus')['style'], 'secure')

    def test_invalid_strategy_falls_back(self):
        self.assertEqual(ar.regulate('bogus')['strategy'], 'reappraise')

    def test_activation_clamped(self):
        self.assertLessEqual(ar.activation('anxious', threat=5.0)['activation'], 1.0)


if __name__ == '__main__':
    unittest.main()
