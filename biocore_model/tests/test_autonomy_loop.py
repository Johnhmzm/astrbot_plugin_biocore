# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_loop as loop

NOW = 1_700_000_000

class LoopTest(unittest.TestCase):
    def test_record_attempt(self):
        acc = loop.record_attempt({}, NOW, 'lonely', 0.4, 12)
        self.assertEqual(acc['sent_count'], 1); self.assertEqual(acc['last_attempt']['code'], 'lonely')
    def test_quick_reply_counts(self):
        acc = loop.record_attempt({}, NOW, 'lonely', 0.4, 10)
        acc = loop.on_user_reply(acc, NOW + 600)
        self.assertEqual(acc['responded_count'], 1); self.assertAlmostEqual(acc['last_response_latency_s'], 600.0)
    def test_late_reply_not_counted(self):
        acc = loop.record_attempt({}, NOW)
        acc = loop.on_user_reply(acc, NOW + 7 * 3600)
        self.assertEqual(acc.get('responded_count', 0), 0)
    def test_settle_ignored(self):
        acc = loop.record_attempt({}, NOW)
        acc = loop.settle(acc, NOW + 7 * 3600)
        self.assertEqual(acc['ignored_count'], 1); self.assertTrue(acc['last_attempt']['closed'])
    def test_settle_recent_not_ignored(self):
        acc = loop.record_attempt({}, NOW)
        acc = loop.settle(acc, NOW + 60)
        self.assertEqual(acc.get('ignored_count', 0), 0)
    def test_response_rate(self):
        self.assertAlmostEqual(loop.response_rate({'responded_count': 5, 'ignored_count': 7}), round(5/12, 4))
    def test_rate_empty(self):
        self.assertEqual(loop.response_rate({}), 0.0)
    def test_per_code_ewma_up(self):
        learning = loop.per_code_stats({}, 'lonely', True)
        self.assertGreater(learning['per_code']['lonely']['rate'], 0.5)
    def test_per_code_ewma_down(self):
        learning = loop.per_code_stats({}, 'lonely', False)
        self.assertLess(learning['per_code']['lonely']['rate'], 0.5)
    def test_tune_every_ten(self):
        learning = {'per_code': {'social_gap': {'sent': 10, 'rate': 0.8}}, 'last_tune_ts': NOW - 10}
        weights = {'social_gap': 0.5, 'lonely': 0.5}
        new, learning2 = loop.tune_weights(learning, weights, NOW, total_sent=10)
        self.assertNotEqual(new['social_gap'], 0.5)
        self.assertAlmostEqual(sum(new.values()), 1.0, places=6)
        self.assertLessEqual(abs(new['social_gap'] - 0.5), 0.05 + 1e-9)
    def test_tune_step_cap(self):
        learning = {'per_code': {'social_gap': {'sent': 10, 'rate': 1.0}}, 'last_tune_ts': NOW - 10}
        old = {'social_gap': 0.5, 'lonely': 0.5}
        new, _ = loop.tune_weights(learning, old, NOW, total_sent=10)
        self.assertGreater(new['social_gap'], 0.5); self.assertLessEqual(new['social_gap'], 0.55)
    def test_tune_not_due(self):
        learning = {'per_code': {'x': {'sent': 1, 'rate': 0.9}}, 'last_tune_ts': NOW - 10}
        weights = {'x': 1.0}
        new, _ = loop.tune_weights(learning, weights, NOW, total_sent=3)
        self.assertEqual(new, weights)
    def test_loop_view_fields(self):
        view = loop.loop_view({'sent_count': 12, 'responded_count': 5, 'ignored_count': 7, 'last_attempt': {'code': 'lonely', 'ts': NOW}}, {'per_code': {'lonely': {'sent': 3, 'rate': 0.4}}})
        for key in ('sent', 'responded', 'ignored', 'response_rate', 'avg_latency_s', 'last_attempt', 'per_code'):
            self.assertIn(key, view)
    def test_stall_detection(self):
        self.assertTrue(loop.tick_stalled({'last_tick_ts': NOW - 700}, NOW, 300))
        self.assertFalse(loop.tick_stalled({'last_tick_ts': NOW - 100}, NOW, 300))
        self.assertFalse(loop.tick_stalled({}, NOW))

if __name__ == '__main__':
    unittest.main()
