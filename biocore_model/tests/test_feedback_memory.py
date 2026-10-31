# -*- coding: utf-8 -*-
import random, re, unittest
from pathlib import Path
from biocore_model import feedback_memory as fm

NOW = 1_700_000_000

def entry(eid, strength=1.0, last=None):
    return {'id': eid, 'strength': strength, 'last_decay_ts': last if last is not None else NOW}

class MemoryFeedbackTest(unittest.TestCase):
    def test_touch_boost(self):
        out = fm.touch([entry('e1', 0.3)], 'e1', NOW + 10)
        self.assertGreater(out['entries'][0]['strength'], 0.3); self.assertEqual(out['entries'][0]['recall_count'], 1)
    def test_touch_cap(self):
        out = fm.touch([entry('e1', 0.95)], 'e1', NOW + 10)
        self.assertLessEqual(out['entries'][0]['strength'], 1.0)
    def test_touch_missing_id_noop(self):
        out = fm.touch([entry('e1')], 'nope', NOW + 10)
        self.assertEqual(out['entries'][0]['strength'], 1.0); self.assertEqual(out['audit'], [])
    def test_touch_idempotent_same_now(self):
        first = fm.touch([entry('e1', 0.3)], 'e1', NOW + 10)
        second = fm.touch(first['entries'], 'e1', NOW + 10)
        self.assertTrue(second['idempotent']); self.assertEqual(second['deltas'], {})
    def test_core_memory_after_six(self):
        entries = [entry('e1', 0.5)]
        for step in range(6):
            entries = fm.touch(entries, 'e1', NOW + 10 + step)['entries']
        self.assertTrue(entries[0]['core_memory'])
    def test_power_law_decay(self):
        out = fm.decay_all([entry('e1', 1.0, NOW - 86400)], NOW)
        self.assertAlmostEqual(out['entries'][0]['strength'], round(2 ** -0.5, 4), places=3)
    def test_core_memory_no_decay(self):
        e = entry('e1', 0.6, NOW - 86400 * 10); e['core_memory'] = True
        self.assertEqual(fm.decay_all([e], NOW)['entries'][0]['strength'], 0.6)
    def test_forgotten_threshold(self):
        out = fm.decay_all([entry('e1', 0.2, NOW - 86400 * 10)], NOW)
        self.assertLess(out['entries'][0]['strength'], 0.15); self.assertIn('e1', out['forgotten_ids'])
    def test_select_skips_weak(self):
        out = fm.select_for_prompt([entry('a', 0.9), entry('b', 0.05)], limit=2)
        self.assertEqual([e['id'] for e in out['selected']], ['a']); self.assertIn('b', out['skipped'])
    def test_select_limit(self):
        entries = [entry('e%d' % i, 0.5 + i / 10) for i in range(6)]
        out = fm.select_for_prompt(entries, limit=3, rng=random.Random(1))
        self.assertEqual(len(out['selected']), 3)
    def test_select_deterministic_seed(self):
        entries = [entry('e%d' % i, 0.3 + i / 10) for i in range(5)]
        a = fm.select_for_prompt(entries, limit=2, rng=random.Random(7))
        b = fm.select_for_prompt(entries, limit=2, rng=random.Random(7))
        self.assertEqual([e['id'] for e in a['selected']], [e['id'] for e in b['selected']])
    def test_audit_fields(self):
        row = fm.touch([entry('e1', 0.3)], 'e1', NOW + 10)['audit'][0]
        for key in ('field', 'old', 'new', 'source', 'reason'): self.assertIn(key, row)
    def test_no_core_assignment(self):
        source = Path(__file__).resolve().parent.parent.joinpath('feedback_memory.py').read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'core\.[A-Za-z_]+\s*=', source))
    def test_only_memory_fields(self):
        out = fm.touch([entry('e1', 0.3)], 'e1', NOW + 10)
        allowed = {'strength', 'recall_count', 'last_touched', 'last_decay_ts', 'last_touch_ts', 'last_touch_kind', 'core_memory'}
        self.assertTrue(set(out['deltas']['e1']).issubset(allowed))

if __name__ == '__main__':
    unittest.main()
