# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_model as am

class CapsTest(unittest.TestCase):
    def test_daily3_hourly1(self):
        self.assertEqual(am.derive_hourly_cap(3), 1)
    def test_daily5_hourly2(self):
        self.assertEqual(am.derive_hourly_cap(5), 2)
    def test_daily9_hourly3(self):
        self.assertEqual(am.derive_hourly_cap(9), 3)
    def test_daily20_hourly7(self):
        self.assertEqual(am.derive_hourly_cap(20), 7)
    def test_daily1_hourly1(self):
        self.assertEqual(am.derive_hourly_cap(1), 1)
    def test_clamp_daily(self):
        self.assertEqual(am.daily_cap_value(99), 20); self.assertEqual(am.daily_cap_value(0), 1)
    def test_default(self):
        self.assertEqual(am.daily_cap_value(None), 5)
    def test_effective_caps(self):
        self.assertEqual(am.effective_caps(5), {'daily_cap': 5, 'hourly_cap': 2})
    def test_legacy_hourly_override(self):
        self.assertEqual(am.effective_caps(5, legacy_hourly=4)['hourly_cap'], 4)
    def test_limit_view_has_caps(self):
        view = am.limit_view({}, 2, 1_700_000_000, daily_cap=5)
        self.assertEqual(view['hourly_cap'], 2); self.assertEqual(view['daily_cap'], 5)

if __name__ == '__main__':
    unittest.main()
