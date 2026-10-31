# -*- coding: utf-8 -*-
"""HUMAN-3 autonomic oscillation tests: band, period, threshold modulation."""
import unittest

from biocore_model import autonomic as au


class FrequencyTest(unittest.TestCase):
    def test_default_and_none(self):
        self.assertEqual(au.frequency(None), au.DEFAULT_FREQ)
        self.assertEqual(au.frequency(), au.DEFAULT_FREQ)

    def test_clamped_to_band(self):
        self.assertEqual(au.frequency(0.01), au.FREQ_MIN)
        self.assertEqual(au.frequency(5.0), au.FREQ_MAX)

    def test_period(self):
        self.assertAlmostEqual(au.period(0.2), 5.0, places=4)
        self.assertAlmostEqual(au.period(0.1), 10.0, places=4)

    def test_in_band(self):
        self.assertTrue(au.in_band(0.2))
        self.assertFalse(au.in_band(0.05))
        self.assertFalse(au.in_band("x"))


class WaveTest(unittest.TestCase):
    def test_amplitude_bound_and_zero(self):
        self.assertAlmostEqual(au.wave(0.0), 0.0, places=4)
        for now in range(0, 20):
            self.assertLessEqual(abs(au.wave(now * 0.37, amplitude=0.4)), 0.4)

    def test_periodic(self):
        self.assertAlmostEqual(au.wave(1.0, freq=0.2),
                               au.wave(1.0 + au.period(0.2), freq=0.2), places=3)

    def test_phase_shift_equals_time_shift(self):
        self.assertAlmostEqual(au.wave(0.0, phase0=1.0),
                               au.wave(1.0 / (2 * 3.141592653589793 * 0.2)), places=3)


class ThresholdTest(unittest.TestCase):
    def test_threshold_bounds(self):
        for now in range(0, 30):
            value = au.threshold(now=now * 0.4)
            self.assertGreaterEqual(value, au.THRESHOLD_MIN)
            self.assertLessEqual(value, au.THRESHOLD_MAX)

    def test_threshold_oscillates_around_base(self):
        values = [au.threshold(now=index * 0.5) for index in range(20)]
        self.assertLess(min(values), au.BASE_THRESHOLD)
        self.assertGreater(max(values), au.BASE_THRESHOLD)

    def test_zero_amplitude_constant(self):
        self.assertEqual(au.threshold(now=3.0, amplitude=0.0), au.BASE_THRESHOLD)

    def test_modulate_triggered(self):
        low = au.modulate(0.0, now=1.0)
        high = au.modulate(0.99, now=1.0)
        self.assertFalse(low["triggered"])
        self.assertTrue(high["triggered"])
        self.assertGreater(high["ratio"], 1.0)

    def test_sample_length(self):
        self.assertEqual(len(au.sample(0.0, seconds=5.0, step=0.5)), 10)


if __name__ == "__main__":
    unittest.main()
