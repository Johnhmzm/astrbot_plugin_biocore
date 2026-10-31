# -*- coding: utf-8 -*-
import re, unittest
from pathlib import Path
from biocore_model import feedback_llm as fb

STATE = {'v': 0.0, 'a': 0.5, 'stress': 0.2, 'trust': 0.5, 'closeness': 0.5, 'confidence': 0.8,
         'needs': {'belonging': 0.6}}

class FeedbackTest(unittest.TestCase):
    def test_basic_delta(self):
        out = fb.parse_to_deltas({'v': 0.1}, state=STATE)
        self.assertAlmostEqual(out['deltas']['v'], 0.1)
    def test_step_cap_v(self):
        out = fb.parse_to_deltas({'v': 0.9}, state=STATE)
        self.assertAlmostEqual(out['deltas']['v'], 0.15)
    def test_step_cap_stress(self):
        out = fb.parse_to_deltas({'stress': 0.9}, state=STATE)
        self.assertLessEqual(out['deltas']['stress'], 0.10)
    def test_trust_cap(self):
        out = fb.parse_to_deltas({'trust': 0.9}, state=STATE)
        self.assertLessEqual(out['deltas']['trust'], 0.05)
    def test_range_clamp(self):
        state = dict(STATE, v=0.95)
        out = fb.parse_to_deltas({'v': 1.0}, state=state)
        self.assertLessEqual(out['deltas']['v'], 0.05)
    def test_rejected_unknown(self):
        out = fb.parse_to_deltas({'mystery': 1}, state=STATE)
        self.assertIn('mystery', out['rejected'])
    def test_rejected_bad_type(self):
        out = fb.parse_to_deltas({'v': 'high'}, state=STATE)
        self.assertIn('v', out['rejected'])
    def test_idempotent_same_payload_now(self):
        seen = {}
        first = fb.parse_to_deltas({'v': 0.1}, state=STATE, now=100, seen=seen)
        second = fb.parse_to_deltas({'v': 0.1}, state=STATE, now=100, seen=seen)
        self.assertTrue(second['idempotent']); self.assertEqual(second['deltas'], {})
        self.assertTrue(first['deltas'])
    def test_audit_fields(self):
        out = fb.parse_to_deltas({'v': 0.1}, state=STATE)
        row = out['audit'][0]
        for key in ('field', 'old', 'new', 'source', 'reason'):
            self.assertIn(key, row)
        self.assertEqual(row['source'], 'llm')
    def test_needs_delta(self):
        out = fb.parse_to_deltas({'needs': {'belonging': 0.8}}, state=STATE)
        self.assertGreater(out['deltas']['needs']['belonging'], 0)
    def test_unknown_need_rejected(self):
        out = fb.parse_to_deltas({'needs': {'wealth': 1}}, state=STATE)
        self.assertTrue(any('wealth' in item for item in out['rejected']))
    def test_deterministic(self):
        self.assertEqual(fb.parse_to_deltas({'v': 0.1}, state=STATE), fb.parse_to_deltas({'v': 0.1}, state=STATE))
    def test_hash_stable(self):
        self.assertEqual(fb.payload_hash({'a': 1, 'b': 2}), fb.payload_hash({'b': 2, 'a': 1}))
    def test_no_core_assignment(self):
        source = Path(__file__).resolve().parent.parent.joinpath('feedback_llm.py').read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'core\.[A-Za-z_]+\s*=', source))

if __name__ == '__main__':
    unittest.main()
