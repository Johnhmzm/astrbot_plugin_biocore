# -*- coding: utf-8 -*-
"""HUMAN-2 noise bank tests: reproducibility, channels, bursts."""
import unittest

from biocore_model import noise_bank as nb


class DeterminismTest(unittest.TestCase):
    def test_same_seed_tick_reproducible(self):
        self.assertEqual(nb.value(11, 7, "chat"), nb.value(11, 7, "chat"))

    def test_different_seed_differs(self):
        self.assertNotEqual(nb.value(11, 7), nb.value(12, 7))

    def test_sample_window_shape(self):
        rows = nb.sample_window(3, 10, count=5, name="chat")
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows, nb.sample_window(3, 10, count=5, name="chat"))


class ChannelTest(unittest.TestCase):
    def test_channel_noise_differs(self):
        self.assertNotEqual(nb.channel(5, 9, "chat"), nb.channel(5, 9, "voice"))

    def test_common_is_shared_and_bounded(self):
        value = nb.common(5, 9)
        self.assertLessEqual(abs(value), nb.CLAMP)
        self.assertEqual(value, nb.common(5, 9))

    def test_value_clamped(self):
        for tick in range(200):
            self.assertLessEqual(abs(nb.value(7, tick, "chat")["value"]), nb.CLAMP)


class BurstTest(unittest.TestCase):
    def test_burst_reproducible(self):
        self.assertEqual(nb.burst(9, 4), nb.burst(9, 4))

    def test_burst_disabled_or_forced(self):
        self.assertFalse(nb.burst(9, 4, p=0.0)["hit"])
        self.assertTrue(nb.burst(9, 4, p=1.0)["hit"])

    def test_burst_rare(self):
        hits = sum(1 for tick in range(500) if nb.burst(3, tick)["hit"])
        self.assertLessEqual(hits, 60)

    def test_burst_value_bounds(self):
        row = nb.burst(3, 0, p=1.0)
        self.assertLessEqual(abs(row["value"]), nb.CLAMP)
        self.assertGreaterEqual(row["magnitude"], 0.0)


if __name__ == "__main__":
    unittest.main()
