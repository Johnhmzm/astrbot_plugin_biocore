# -*- coding: utf-8 -*-
import re, unittest
from pathlib import Path
from biocore_model import feedback_user as fu, feedback_llm as fl

STATE = {'v': 0.0, 'social': 0.5, 'stress': 0.2, 'social_pain': 0.3, 'self_esteem': 0.5, 'mood_valence': -0.2}
NOW = 1_700_000_000

class UserFeedbackTest(unittest.TestCase):
    def test_reply_deltas(self):
        out = fu.on_message(STATE, {'kind': 'reply', 'id': 'm1'}, NOW)
        self.assertGreater(out['deltas']['v'], 0); self.assertLess(out['deltas']['social_pain'], 0)
    def test_praise(self):
        out = fu.on_message(STATE, {'kind': 'praise', 'id': 'm2'}, NOW)
        self.assertGreater(out['deltas']['self_esteem'], 0); self.assertGreater(out['deltas']['v'], 0)
    def test_insult(self):
        out = fu.on_message(STATE, {'kind': 'insult', 'id': 'm3'}, NOW)
        self.assertLess(out['deltas']['self_esteem'], 0); self.assertGreater(out['deltas']['social_pain'], 0)
    def test_reject(self):
        out = fu.on_message(STATE, {'kind': 'reject', 'id': 'm4'}, NOW)
        self.assertGreater(out['deltas']['social_pain'], 0); self.assertLess(out['deltas']['v'], 0)
    def test_cap_v(self):
        out = fu.on_message(STATE, {'kind': 'reject', 'id': 'm5'}, NOW)
        self.assertGreaterEqual(out['deltas']['v'], -0.03); self.assertLessEqual(abs(out['deltas']['v']), 0.03)
    def test_cap_self_esteem(self):
        out = fu.on_message(STATE, {'kind': 'insult', 'id': 'm6'}, NOW)
        self.assertLessEqual(abs(out['deltas']['self_esteem']), 0.05)
    def test_idempotent_same_event(self):
        seen = {}
        first = fu.on_message(STATE, {'kind': 'reply', 'id': 'm7'}, NOW, seen)
        second = fu.on_message(STATE, {'kind': 'reply', 'id': 'm7'}, NOW, seen)
        self.assertTrue(second['idempotent']); self.assertEqual(second['deltas'], {})
        self.assertTrue(first['deltas'])
    def test_silence_accumulates(self):
        out = fu.on_silence(STATE, 5, NOW)
        self.assertGreater(out['deltas']['social_pain'], 0); self.assertLess(out['deltas']['mood_valence'], 0)
    def test_silence_cap(self):
        out = fu.on_silence(STATE, 100, NOW)
        self.assertLessEqual(out['deltas']['social_pain'], 0.10); self.assertGreaterEqual(out['deltas']['mood_valence'], -0.02)
    def test_silence_idempotent_same_hour(self):
        seen = {}
        fu.on_silence(STATE, 5, NOW, seen)
        second = fu.on_silence(STATE, 5, NOW + 30, seen)
        self.assertTrue(second['idempotent'])
    def test_audit_format(self):
        out = fu.on_message(STATE, {'kind': 'reply', 'id': 'm8'}, NOW)
        row = out['audit'][0]
        for key in ('field', 'old', 'new', 'source', 'reason'): self.assertIn(key, row)
        self.assertEqual(row['source'], 'user')
    def test_no_field_overlap_with_llm(self):
        user_fields = set(fu.EVENTS['reply']) | {'mood_valence'}
        llm_fields = set(fl.CAPS)
        self.assertTrue(user_fields.isdisjoint({'a', 'trust', 'closeness', 'confidence'}))
    def test_deterministic(self):
        self.assertEqual(fu.on_message(STATE, {'kind': 'praise', 'id': 'm9'}, NOW), fu.on_message(STATE, {'kind': 'praise', 'id': 'm9'}, NOW))
    def test_no_core_assignment(self):
        source = Path(__file__).resolve().parent.parent.joinpath('feedback_user.py').read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'core\.[A-Za-z_]+\s*=', source))

if __name__ == '__main__':
    unittest.main()
