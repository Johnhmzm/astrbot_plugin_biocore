# -*- coding: utf-8 -*-
import random, unittest
from biocore_model import memory_forgetting as mf

NOW = 1_700_000_000

class ForgettingTest(unittest.TestCase):
    def test_decay_1h(self):
        self.assertLess(mf.strength(1.0, 1), 1.0)
    def test_decay_monotonic(self):
        self.assertGreater(mf.strength(1.0, 1), mf.strength(1.0, 24))
        self.assertGreater(mf.strength(1.0, 24), mf.strength(1.0, 24 * 7))
    def test_power_law_value(self):
        self.assertAlmostEqual(mf.strength(1.0, 24), round(2 ** -0.5, 6), places=5)
    def test_recall_boost(self):
        entry = mf.recall({'strength': 0.3}, NOW)
        self.assertGreater(entry['strength'], 0.3); self.assertEqual(entry['recall_count'], 1)
    def test_recall_cap(self):
        entry = mf.recall({'strength': 0.95}, NOW)
        self.assertLessEqual(entry['strength'], 1.0)
    def test_core_after_five(self):
        entry = {'strength': 0.5}
        for _ in range(6): entry = mf.recall(entry, NOW)
        self.assertTrue(entry.get('core_memory'))
    def test_core_never_decays(self):
        entry = mf.decayed({'strength': 0.6, 'core_memory': True, 'last_decay_ts': NOW - 86400 * 30}, NOW)
        self.assertEqual(entry['strength'], 0.6)
    def test_forgotten_threshold(self):
        self.assertFalse(mf.injectable({'strength': 0.1}))
        self.assertTrue(mf.injectable({'strength': 0.2}))
    def test_memory_view(self):
        view = mf.memory_view([{'id': 'a', 'strength': 0.9}, {'id': 'b', 'strength': 0.05}])
        self.assertEqual(view['top'][0]['id'], 'a'); self.assertEqual(view['forgotten_count'], 1)
    def test_rumination_requires_negative(self):
        items = mf.add_rumination([], 'message', 'm1', 'text', NOW, valence=0.2)
        self.assertEqual(items, [])
    def test_rumination_added(self):
        items = mf.add_rumination([], 'message', 'm1', 'text', NOW, valence=-0.6)
        self.assertEqual(len(items), 1); self.assertEqual(items[0]['count'], 1)
    def test_rumination_dedupe(self):
        items = mf.add_rumination([], 'message', 'm1', 't', NOW, conflict=True)
        items = mf.add_rumination(items, 'message', 'm1', 't', NOW + 60, conflict=True)
        self.assertEqual(len(items), 1); self.assertEqual(items[0]['count'], 2)
    def test_rumination_removed_at_count5(self):
        items = [{'target_type': 'message', 'target_id': 'm', 'count': 5, 'first_ts': NOW - 100, 'last_ts': NOW - 100, 'intensity': 1.0}]
        self.assertEqual(mf.tick_rumination(items, NOW, random.Random(1)), [])
    def test_rumination_removed_after_72h(self):
        items = [{'target_type': 'message', 'target_id': 'm', 'count': 1, 'first_ts': NOW - 80 * 3600, 'last_ts': NOW - 80 * 3600}]
        self.assertEqual(mf.tick_rumination(items, NOW, random.Random(1)), [])
    def test_rumination_same_now_idempotent(self):
        items = [{'target_type': 'message', 'target_id': 'm', 'count': 1, 'first_ts': NOW, 'last_ts': NOW, 'last_tick_ts': NOW}]
        kept = mf.tick_rumination(items, NOW, random.Random(1))
        self.assertEqual(len(kept), 1); self.assertEqual(kept[0]['count'], 1)
    def test_rumination_text(self):
        self.assertIn('你还在想', mf.rumination_text([{'text_snippet': '那句话'}]))

if __name__ == '__main__':
    unittest.main()
