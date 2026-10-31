# -*- coding: utf-8 -*-
import time, unittest
from biocore_model import autonomy_model as am

NOW = time.mktime((2026, 1, 1, 12, 0, 0, 0, 1, -1))

class SendGateTest(unittest.TestCase):
    def test_fire_when_v_reaches_theta(self):
        out = am.step(0.55, 0.1, sigma=0.0, theta=0.55)
        self.assertTrue(out['fire'])
    def test_cooldown_blocks(self):
        ok, why = am.send_gate({'last_sent_ts': NOW - 10}, now=NOW)
        self.assertFalse(ok); self.assertEqual(why, 'cooldown')
    def test_daily_cap_blocks(self):
        day = time.strftime('%Y-%m-%d', time.localtime(NOW))
        ok, why = am.send_gate({'sent_day': day, 'sent_count': 3}, now=NOW)
        self.assertFalse(ok); self.assertEqual(why, 'daily_cap')
    def test_quiet_hours_blocks(self):
        quiet = time.mktime((2026, 1, 1, 3, 0, 0, 0, 1, -1))
        ok, why = am.send_gate({}, now=quiet)
        self.assertFalse(ok); self.assertEqual(why, 'quiet_hours')
    def test_send_disabled_blocks(self):
        ok, why = am.send_gate({}, send_enabled=False)
        self.assertFalse(ok); self.assertEqual(why, 'send_disabled')
    def test_not_private_blocks(self):
        ok, why = am.send_gate({}, private=False)
        self.assertFalse(ok); self.assertEqual(why, 'not_private')
    def test_allowed(self):
        ok, why = am.send_gate({}, now=NOW)
        self.assertTrue(ok); self.assertEqual(why, 'fired')
    def test_apply_fire_resets(self):
        acc = am.apply_fire({'V': 0.6, 'ticks_since_fire': 5}, now=NOW, text_len=12)
        self.assertEqual(acc['V'], 0.0); self.assertEqual(acc['ticks_since_fire'], 0)
    def test_no_fire_below_theta(self):
        self.assertFalse(am.step(0.4, 0.0, sigma=0.0, theta=0.55)['fire'])

if __name__ == '__main__':
    unittest.main()
