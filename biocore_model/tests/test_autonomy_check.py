# -*- coding: utf-8 -*-
import time, unittest
from biocore_model import autonomy_check as ac

BASE = {"enabled": True, "ready": True, "impulse": 0.9, "threshold": 0.6,
        "last_sent_ts": 0, "sent_count": 0, "sent_day": "", "cooldown_seconds": 3600, "daily_cap": 3}

class AutonomyCheckTest(unittest.TestCase):
    def test_ready(self):
        self.assertEqual(ac.reason(dict(BASE), True, True, now=time.mktime((2026, 1, 1, 12, 0, 0, 0, 1, -1))), "ready")

    def test_not_private(self):
        self.assertEqual(ac.reason(dict(BASE), False, True), "not_private")

    def test_no_session(self):
        self.assertEqual(ac.reason(dict(BASE), True, False), "no_session")

    def test_not_ready(self):
        self.assertEqual(ac.reason(dict(BASE, ready=False)), "not_ready")
        self.assertEqual(ac.reason(dict(BASE, impulse=0.1)), "not_ready")

    def test_cooldown(self):
        now = time.mktime((2026, 1, 1, 12, 0, 0, 0, 1, -1))
        self.assertEqual(ac.reason(dict(BASE, last_sent_ts=now - 10), True, True, now=now), "cooldown")

    def test_daily_cap(self):
        now = time.mktime((2026, 1, 1, 12, 0, 0, 0, 1, -1))
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        self.assertEqual(ac.reason(dict(BASE, sent_day=day, sent_count=3), True, True, now=now), "daily_cap")

    def test_snapshot_fields(self):
        snap = ac.snapshot(dict(BASE, impulse_ema=0.5, max_chars=120, last_sent_ts=1.0))
        self.assertIn("impulse", snap); self.assertIn("max_chars", snap)

    def test_chinese_mapping(self):
        for code in ("ready", "not_ready", "cooldown", "daily_cap", "quiet_hours", "no_session", "not_private"):
            self.assertTrue(ac.reason_text(code))

if __name__ == "__main__":
    unittest.main()
