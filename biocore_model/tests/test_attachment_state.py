# -*- coding: utf-8 -*-
import unittest
from biocore_model import attachment_state as ast

class AttachmentStateTest(unittest.TestCase):
    def test_threat_raises(self):
        self.assertGreater(ast.threat(0.0, 1.0), 0.0)
    def test_modes(self):
        self.assertEqual(ast.mode('anxious', 0.5), 'hyperactivating')
        self.assertEqual(ast.mode('secure', 0.5), 'comfort')
        self.assertEqual(ast.mode('avoidant', 0.5), 'deactivating')
    def test_replied_halves(self):
        self.assertAlmostEqual(ast.decay(0.8, True), 0.4)
    def test_no_reply_decays_hourly(self):
        self.assertAlmostEqual(ast.decay(1.0, False, dt=3), 0.7)
    def test_drive_multipliers(self):
        self.assertEqual(ast.drive_multiplier('anxious'), 1.2)
        self.assertEqual(ast.drive_multiplier('avoidant'), 0.7)
    def test_view_fields(self):
        view = ast.view({'activation': 0.4}, 'secure')
        for key in ('style', 'activation', 'mode', 'drive_mult'): self.assertIn(key, view)
    def test_clamp(self):
        self.assertLessEqual(ast.threat(0.95, 1.0), 1.0)
        self.assertGreaterEqual(ast.decay(0.1, False, dt=100), 0.0)
    def test_unknown_style(self):
        self.assertEqual(ast.mode('bogus', 0.5), 'comfort')

if __name__ == '__main__':
    unittest.main()
