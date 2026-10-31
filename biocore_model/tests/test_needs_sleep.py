# -*- coding: utf-8 -*-
import unittest
from biocore_model import needs_sleep as ns, needs_esteem as ne

NOW = 1_700_000_000

class NeedsSleepTest(unittest.TestCase):
    def test_four_needs_include_control_meaning(self):
        data = ns.defaults(NOW)
        for key in ('belonging', 'self_esteem', 'control', 'meaningful_existence'):
            self.assertIn(key, data)
    def test_control_drops_when_stalled(self):
        data = ns.need_step(ns.defaults(NOW), {'silence_hours': 10, 'stalled': True}, dt=10, now=NOW + 1)
        self.assertLess(data['control'], 0.6)
    def test_meaning_drops_after_48h(self):
        long_silence = ns.need_step(ns.defaults(NOW), {'silence_hours': 60}, dt=10, now=NOW + 1)
        short = ns.need_step(ns.defaults(NOW), {'silence_hours': 24}, dt=10, now=NOW + 1)
        self.assertLess(long_silence['meaningful_existence'], short['meaningful_existence'])
    def test_responded_repairs_all(self):
        data = ns.need_step(ns.defaults(NOW), {'responded': True}, dt=0, now=NOW + 1)
        for key in ns.NEED_KEYS: self.assertGreater(data[key], 0.6)
    def test_idempotent_same_now(self):
        first = ns.need_step(ns.defaults(NOW), {'silence_hours': 10}, dt=10, now=NOW)
        second = ns.need_step(first, {'silence_hours': 10}, dt=10, now=NOW)
        self.assertEqual(first['belonging'], second['belonging'])
    def test_sleep_debt_accumulates(self):
        data = ns.sleep_debt_step(0.0, slept_hours=0, dt=8, now=NOW)
        self.assertGreater(data['debt'], 0)
    def test_sleep_repays(self):
        data = ns.sleep_debt_step(4.0, slept_hours=6, dt=6, now=NOW)
        self.assertLess(data['debt'], 4.0)
    def test_sleep_debt_idempotent(self):
        first = ns.sleep_debt_step(2.0, 0, 8, NOW)
        second = ns.sleep_debt_step(first['debt'], 0, 8, NOW, state={'last_debt_ts': NOW})
        self.assertAlmostEqual(second['debt'], first['debt'])
    def test_energy_and_irritability(self):
        self.assertGreater(ns.energy_penalty(12), 0); self.assertGreater(ns.irritability(12), 0)
    def test_view_fields(self):
        view = ns.view(ns.defaults(NOW), 5)
        for key in ('needs', 'dominant', 'sleep_debt', 'energy_penalty', 'irritability'): self.assertIn(key, view)
    def test_needs_esteem_delegates_apply_silence(self):
        old = ne.apply_silence(ne.defaults(), 10)
        new = ns.need_step(ns.defaults(NOW), {'silence_hours': 10}, dt=0, now=NOW + 1)
        self.assertAlmostEqual(old['belonging'], new['belonging'], places=3)
    def test_needs_esteem_delegates_responded(self):
        old = ne.on_responded(ne.defaults())
        self.assertGreater(old['control'], 0.6)
    def test_needs_esteem_delegates_ignored(self):
        old = ne.on_ignored(ne.defaults(), rejected=True)
        new = ns.need_step(ns.defaults(NOW), {'ignored': True}, dt=0, now=NOW + 1)
        self.assertAlmostEqual(old['self_esteem'], new['self_esteem'], places=3)

if __name__ == '__main__':
    unittest.main()
