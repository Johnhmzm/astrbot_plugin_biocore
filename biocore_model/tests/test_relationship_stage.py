# -*- coding: utf-8 -*-
import random, unittest
from biocore_model import relationship_stage as rs

NOW = 1_700_000_000

class StageTest(unittest.TestCase):
    def test_stranger(self):
        self.assertEqual(rs.stage_for(5), 'stranger')
    def test_acquaintance(self):
        self.assertEqual(rs.stage_for(10), 'acquaintance')
    def test_friend(self):
        self.assertEqual(rs.stage_for(55), 'friend')
    def test_close(self):
        self.assertEqual(rs.stage_for(91), 'close')
    def test_boundary_50(self):
        self.assertEqual(rs.stage_for(50), 'friend')
    def test_boundary_90(self):
        self.assertEqual(rs.stage_for(90), 'close')
    def test_friend_config(self):
        cfg = rs.stage_config(55)
        self.assertEqual(cfg['tau_hours'], 24); self.assertEqual(cfg['daily_cap'], 5)
    def test_stranger_config(self):
        cfg = rs.stage_config(0)
        self.assertEqual(cfg['tau_hours'], 8); self.assertEqual(cfg['daily_cap'], 1)
    def test_min_interval(self):
        cfg = rs.stage_config(55)
        self.assertAlmostEqual(cfg['min_interval_hours'], round(24 / (5 * 0.6), 2))

class HabituationTest(unittest.TestCase):
    def test_novelty_decay(self):
        self.assertAlmostEqual(rs.novelty(0), 1.0)
        self.assertAlmostEqual(rs.novelty(2), round(0.85 ** 2, 4))
    def test_disabled_below_threshold(self):
        usage = {'t1': {'count': 8, 'last_ts': NOW - 60}}
        info = rs.template_weight('t1', usage, NOW)
        self.assertTrue(info['disabled']); self.assertLess(info['weight'], 0.3)
    def test_not_disabled_after_24h(self):
        usage = {'t1': {'count': 8, 'last_ts': NOW - 25 * 3600}}
        self.assertFalse(rs.template_weight('t1', usage, NOW)['disabled'])
    def test_window_reset(self):
        usage = {'t1': {'count': 8, 'last_ts': NOW - 8 * 86400}}
        info = rs.template_weight('t1', usage, NOW)
        self.assertEqual(info['count'], 0)
    def test_record_template(self):
        usage = rs.record_template({}, 't1', NOW)
        self.assertEqual(usage['t1']['count'], 1)
    def test_templates_view(self):
        usage = {'t1': {'count': 9, 'last_ts': NOW - 10}, 't2': {'count': 1, 'last_ts': NOW - 10}}
        view = rs.templates_view(usage, NOW)
        self.assertIn('t1', view['disabled']); self.assertEqual(view['top_used'][0]['template_id'], 't1')
    def test_pick_weighted_skips_disabled(self):
        usage = {'t1': {'count': 9, 'last_ts': NOW - 10}}
        self.assertEqual(rs.pick_weighted(['t1'], usage, NOW, random.Random(0)), None)
    def test_pick_weighted_returns_candidate(self):
        self.assertEqual(rs.pick_weighted(['t1', 't2'], {}, NOW, random.Random(0)) in ('t1', 't2'), True)

if __name__ == '__main__':
    unittest.main()
