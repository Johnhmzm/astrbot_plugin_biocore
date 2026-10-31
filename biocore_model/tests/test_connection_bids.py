# -*- coding: utf-8 -*-
import unittest
from biocore_model import connection_bids as cb

NOW = 1_700_000_000

class BidsTest(unittest.TestCase):
    def test_record_bid(self):
        bids = cb.record_bid([], NOW, 'lonely')
        self.assertEqual(len(bids), 1); self.assertIsNone(bids[0]['turned'])
    def test_turned_toward(self):
        bids = cb.settle_bids(cb.record_bid([], NOW), NOW + 600, responded_ts=NOW + 600)
        self.assertEqual(bids[0]['turned'], 'toward')
    def test_turned_away(self):
        bids = cb.settle_bids(cb.record_bid([], NOW), NOW + 7 * 3600)
        self.assertEqual(bids[0]['turned'], 'away')
    def test_streaks(self):
        bids = [{'turned': 'toward'}, {'turned': 'away'}, {'turned': 'away'}, {'turned': 'away'}]
        self.assertEqual(cb.streaks(bids), (0, 3))
        self.assertEqual(cb.streaks([{'turned': 'away'}, {'turned': 'toward'}, {'turned': 'toward'}, {'turned': 'toward'}]), (3, 0))
    def test_frequency_after_three_away(self):
        bids = [{'turned': 'away'}] * 3
        self.assertAlmostEqual(cb.bid_frequency(bids), 0.7)
    def test_frequency_after_three_toward(self):
        bids = [{'turned': 'toward'}] * 3
        self.assertAlmostEqual(cb.bid_frequency(bids), 1.1)
    def test_frequency_floor(self):
        bids = [{'turned': 'away'}] * 10
        self.assertGreaterEqual(cb.bid_frequency(bids, 0.6), cb.FREQ_MIN)
    def test_frequency_cap(self):
        bids = [{'turned': 'toward'}] * 10
        self.assertLessEqual(cb.bid_frequency(bids, 1.25), cb.FREQ_MAX)
    def test_bid_view(self):
        view = cb.bid_view([{'turned': 'toward'}, {'turned': 'away'}], 1.1)
        self.assertEqual(view['sent'], 2); self.assertEqual(view['toward'], 1); self.assertEqual(view['away'], 1)

class ResponsivenessTest(unittest.TestCase):
    def test_responded_raises(self):
        self.assertGreater(cb.responsiveness_update(0.5, True), 0.5)
    def test_ignored_lowers(self):
        self.assertLess(cb.responsiveness_update(0.5, False), 0.5)
    def test_gate_cost_low(self):
        self.assertEqual(cb.gate_cost_adjust(0.2), 0.05)
    def test_gate_cost_high(self):
        self.assertEqual(cb.gate_cost_adjust(0.9), -0.05)
    def test_disclosure_mult_low(self):
        self.assertEqual(cb.disclosure_mult(0.2), 0.7)
    def test_disclosure_mult_high(self):
        self.assertEqual(cb.disclosure_mult(0.8), 1.0)

class TrustTest(unittest.TestCase):
    def test_three_dimensions(self):
        trust = cb.trust_update(None, regular=True, kept=True, response_rate=0.8)
        for key in ('predictability', 'dependability', 'faith', 'overall'):
            self.assertIn(key, trust)
    def test_dimensions_independent(self):
        trust = cb.trust_update(None, regular=True)
        self.assertGreater(trust['predictability'], 0.5)
        self.assertAlmostEqual(trust['dependability'], 0.5)
    def test_delayed_lowers_dependability(self):
        trust = cb.trust_update(None, delayed=True)
        self.assertLess(trust['dependability'], 0.5)
    def test_overall_weights(self):
        trust = {'predictability': 0.8, 'dependability': 0.6, 'faith': 0.4}
        out = cb.trust_update(trust)
        self.assertAlmostEqual(out['overall'], 0.4 * 0.8 + 0.4 * 0.6 + 0.2 * 0.4)

if __name__ == '__main__':
    unittest.main()
