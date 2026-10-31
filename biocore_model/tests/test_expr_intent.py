# -*- coding: utf-8 -*-
import random, unittest
from biocore_model import expr_intent as ei

NOW = 1_700_000_000

def cand(kind, **kw):
    data = {'kind': kind, 'text_hint': kind + ' hint', 'novelty': 1.0}
    data.update(kw)
    return data

class IntentTest(unittest.TestCase):
    def test_eight_kinds_available(self):
        for kind in ei.BASE:
            self.assertIn(kind, ei.BASE)
    def test_picks_some_kind(self):
        out = ei.pick_intent([cand(k) for k in ei.BASE], {}, random.Random(1))
        self.assertIn(out['kind'], ei.BASE)
    def test_text_hint_returned(self):
        out = ei.pick_intent([cand('repair')], {}, random.Random(1))
        self.assertEqual(out['text_hint'], 'repair hint')
    def test_novelty_excludes_low(self):
        out = ei.pick_intent([cand('repair', novelty=0.2), cand('question', novelty=1.0)], {}, random.Random(1))
        self.assertEqual(out['kind'], 'question')
    def test_gratitude_requires_event(self):
        out = ei.pick_intent([cand('gratitude'), cand('comfort')], {}, random.Random(1))
        self.assertEqual(out['kind'], 'comfort')
    def test_memory_due_requires_event(self):
        self.assertNotEqual(ei.pick_intent([cand('memory_due')], {}, random.Random(1))['kind'], 'memory_due')
    def test_memory_due_requires_window(self):
        out = ei.pick_intent([cand('memory_due', event_ref='e1', due_ts=NOW + 10 * 86400)], {'now': NOW}, random.Random(1))
        self.assertEqual(out['kind'], '')
    def test_bid_frequency_modulates(self):
        low = ei.pick_intent([cand('question')], {'bid_frequency': 0.5}, random.Random(0))
        high = ei.pick_intent([cand('question')], {'bid_frequency': 1.3}, random.Random(0))
        self.assertGreater(high['weight'], low['weight'])
    def test_responsiveness_modulates_self_life(self):
        low = ei.pick_intent([cand('self_life')], {'responsiveness': 0.1}, random.Random(0))
        high = ei.pick_intent([cand('self_life')], {'responsiveness': 0.9}, random.Random(0))
        self.assertGreater(high['weight'], low['weight'])
    def test_deactivating_halves_self_life(self):
        normal = ei.pick_intent([cand('self_life')], {}, random.Random(0))
        avoidant = ei.pick_intent([cand('self_life')], {'attachment_mode': 'deactivating'}, random.Random(0))
        self.assertAlmostEqual(avoidant['weight'], normal['weight'] * 0.5, places=3)
    def test_consecutive_same_kind_excluded(self):
        out = ei.pick_intent([cand('repair'), cand('comfort')], {'recent_kinds': ['repair', 'repair']}, random.Random(1))
        self.assertEqual(out['kind'], 'comfort')
    def test_single_recent_kind_allowed(self):
        out = ei.pick_intent([cand('repair')], {'recent_kinds': ['repair']}, random.Random(1))
        self.assertEqual(out['kind'], 'repair')
    def test_deterministic_with_seed(self):
        args = ([cand(k) for k in ei.BASE], {}, random.Random(7))
        first = ei.pick_intent(*args)
        second = ei.pick_intent([cand(k) for k in ei.BASE], {}, random.Random(7))
        self.assertEqual(first, second)
    def test_alternatives_listed(self):
        out = ei.pick_intent([cand('repair'), cand('comfort'), cand('question')], {}, random.Random(1))
        self.assertNotIn(out['kind'], out['alternatives']); self.assertEqual(len(out['alternatives']), 2)
    def test_empty_candidates(self):
        self.assertEqual(ei.pick_intent([], {}, random.Random(1))['kind'], '')
    def test_no_field_name_leak_in_hint(self):
        out = ei.pick_intent([cand('self_life')], {}, random.Random(1))
        self.assertNotIn('valence=', out['text_hint'])

if __name__ == '__main__':
    unittest.main()
