# -*- coding: utf-8 -*-
import unittest
from biocore_model import needs_esteem as ne

class NeedsTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(ne.defaults()['belonging'], 0.6)
    def test_silence_belonging(self):
        self.assertAlmostEqual(ne.silence_effects(10)['belonging'], -0.2)
    def test_belonging_cap(self):
        self.assertAlmostEqual(ne.silence_effects(100)['belonging'], -0.4)
    def test_meaning_after_48h(self):
        self.assertEqual(ne.silence_effects(24)['meaningful_existence'], 0.0)
        self.assertLess(ne.silence_effects(60)['meaningful_existence'], 0.0)
    def test_control_when_stalled(self):
        self.assertLess(ne.silence_effects(10, phases_stalled=True)['control'], 0.0)
    def test_responded_repairs_all(self):
        needs = ne.on_responded(ne.defaults())
        for key in ne.NEED_KEYS:
            self.assertGreater(needs[key], 0.6)
    def test_ignored_lowers_esteem(self):
        self.assertLess(ne.on_ignored(ne.defaults())['self_esteem'], 0.6)
    def test_rejected_bigger_drop(self):
        self.assertLess(ne.on_ignored(ne.defaults(), rejected=True)['self_esteem'], ne.on_ignored(ne.defaults())['self_esteem'])
    def test_praised_raises_esteem(self):
        self.assertGreater(ne.on_praised(ne.defaults())['self_esteem'], 0.6)
    def test_dominant(self):
        needs = ne.defaults(); needs['meaningful_existence'] = 0.2
        self.assertEqual(ne.dominant(needs), 'meaningful_existence')
    def test_dominant_empty_when_full(self):
        needs = {key: 0.9 for key in ne.NEED_KEYS}
        self.assertEqual(ne.dominant(needs), '')
    def test_four_behaviours_differ(self):
        tones = set()
        for key in ne.NEED_KEYS:
            needs = ne.defaults(); needs[key] = 0.2
            b = ne.behaviour(needs); tones.add(b['tone'])
        self.assertEqual(len(tones), 4)
    def test_self_esteem_regress(self):
        self.assertGreater(ne.self_esteem_update(0.2), 0.2)
        self.assertLess(ne.self_esteem_update(0.9), 0.9)
    def test_esteem_respond_boost(self):
        self.assertGreater(ne.self_esteem_update(0.5, responded=True), 0.5)
    def test_confidence_lower_with_low_esteem(self):
        self.assertLess(ne.confidence_from_esteem(0.2), ne.confidence_from_esteem(0.55))
    def test_clamp(self):
        self.assertLessEqual(ne.self_esteem_update(1.0, praised=True), 1.0)
        self.assertGreaterEqual(ne.self_esteem_update(0.0, ignored=True), 0.0)

if __name__ == '__main__':
    unittest.main()
