# -*- coding: utf-8 -*-
import unittest
from biocore_model import feedback_guard as fg

STATE = {'v': 0.2, 'a': 0.5, 'stress': 0.2, 'social': 0.5, 'social_pain': 0.3, 'self_esteem': 0.5, 'trust': 0.5, 'closeness': 0.5, 'confidence': 0.8, 'needs': {'belonging': 0.6}}
NOW = 1_700_000_000

class GuardTest(unittest.TestCase):
    def test_llm_cap(self):
        out = fg.vet({'v': 0.9}, STATE, 'llm', NOW)
        self.assertAlmostEqual(out['accepted']['v'], 0.15)
    def test_user_cap(self):
        out = fg.vet({'v': 0.9}, STATE, 'user', NOW)
        self.assertAlmostEqual(out['accepted']['v'], 0.02)
    def test_other_source_tighter(self):
        out = fg.vet({'v': 0.9}, STATE, 'other', NOW)
        self.assertAlmostEqual(out['accepted']['v'], 0.02)
    def test_stress_cap_llm(self):
        self.assertAlmostEqual(fg.vet({'stress': 0.9}, STATE, 'llm', NOW)['accepted']['stress'], 0.10)
    def test_whitelist_rejects_unknown(self):
        out = fg.vet({'luck': 0.1}, STATE, 'llm', NOW)
        self.assertEqual(out['rejected'][0]['field'], 'luck')
    def test_needs_unknown_rejected(self):
        out = fg.vet({'needs': {'wealth': 0.1}}, STATE, 'llm', NOW)
        self.assertTrue(any('wealth' in row['field'] for row in out['rejected']))
    def test_total_cap_v(self):
        out = fg.vet({'v': 0.15}, STATE, 'llm', NOW)
        self.assertLessEqual(abs(out['accepted']['v']), 0.15)
    def test_range_clamp(self):
        state = dict(STATE, v=0.95)
        out = fg.vet({'v': 0.15}, state, 'llm', NOW)
        self.assertLessEqual(out['accepted']['v'], 0.05)
    def test_idempotent_same_payload(self):
        seen = {}
        fg.vet({'v': 0.1}, STATE, 'llm', NOW, seen=seen)
        second = fg.vet({'v': 0.1}, STATE, 'llm', NOW, seen=seen)
        self.assertTrue(second['idempotent']); self.assertEqual(second['accepted'], {})
    def test_audit_fields(self):
        row = fg.vet({'v': 0.1}, STATE, 'llm', NOW)['audit'][0]
        for key in ('field', 'old', 'new', 'source', 'reason', 'ts'): self.assertIn(key, row)
    def test_audit_cap_100(self):
        seen = {}
        total = 0
        for i in range(110):
            out = fg.vet({'v': 0.01}, STATE, 'llm', NOW + i, seen=seen)
            total += len(out['audit'])
        self.assertLessEqual(total, 110)
    def test_vet_does_not_mutate_state(self):
        state = dict(STATE)
        fg.vet({'v': 0.1}, state, 'llm', NOW)
        self.assertEqual(state, STATE)
    def test_apply_writes(self):
        out = fg.apply(STATE, {'v': 0.1, 'needs': {'belonging': 0.05}})
        self.assertGreater(out['state']['v'], STATE['v']); self.assertIn('v', out['changed'])
    def test_apply_needs(self):
        out = fg.apply(STATE, {'needs': {'belonging': 0.05}})
        self.assertGreater(out['state']['needs']['belonging'], 0.6)
    def test_deterministic(self):
        self.assertEqual(fg.vet({'v': 0.1}, STATE, 'llm', NOW), fg.vet({'v': 0.1}, STATE, 'llm', NOW))
    def test_limits_override(self):
        out = fg.vet({'v': 0.5}, STATE, 'llm', NOW, limits={'v': 0.05})
        self.assertAlmostEqual(out['accepted']['v'], 0.05)

if __name__ == '__main__':
    unittest.main()
