# -*- coding: utf-8 -*-
"""Cross-layer directives: normalize, merge, conservative precedence."""
import unittest

from biocore_model import x_directives as xd


class NormalizeTest(unittest.TestCase):
    def test_defaults(self):
        out = xd.normalize({})
        self.assertEqual(out["length_scale"], 1.0)
        self.assertEqual(out["initiative"], 0.5)
        self.assertEqual(out["tone"], "")
        self.assertFalse(out["allow_correction"])

    def test_clamps_length_and_initiative(self):
        out = xd.normalize({"length_scale": 9, "initiative": -3})
        self.assertEqual(out["length_scale"], xd.LENGTH_MAX)
        self.assertEqual(out["initiative"], 0.0)

    def test_legacy_proactive_maps_to_initiative(self):
        out = xd.normalize({"proactive": 0.8})
        self.assertEqual(out["initiative"], 0.8)

    def test_legacy_allow_fields(self):
        self.assertTrue(xd.normalize({"allow_self_correction": True})["allow_correction"])
        self.assertTrue(xd.normalize({"allow_clarify": True})["allow_correction"])

    def test_note_from_reason(self):
        self.assertEqual(xd.normalize({"reason": "因为累"}).get("note"), "因为累")

    def test_source_recorded(self):
        self.assertEqual(xd.normalize({}, "metacog")["sources"], ["metacog"])

    def test_malformed(self):
        out = xd.normalize("nope")
        self.assertEqual(out["length_scale"], 1.0)


class MergeTest(unittest.TestCase):
    def test_empty(self):
        out = xd.merge([])
        self.assertEqual(out["length_scale"], 1.0)
        self.assertEqual(out["sources"], [])

    def test_takes_min_length(self):
        out = xd.merge([{"length_scale": 1.0}, {"length_scale": 0.8},
                        {"length_scale": 0.9}])
        self.assertEqual(out["length_scale"], 0.8)

    def test_takes_min_initiative(self):
        out = xd.merge([{"proactive": 0.8}, {"initiative": 0.3}])
        self.assertEqual(out["initiative"], 0.3)

    def test_tone_priority(self):
        out = xd.merge_named([("metacog", {"tone": "低置信"}),
                              ("dissonance", {"tone": "认一句"}),
                              ("value_order", {"tone": "按选定的来"})])
        self.assertEqual(out["tone"], "认一句")

    def test_tone_ignores_empty(self):
        out = xd.merge_named([("value_order", {"tone": ""}),
                              ("metacog", {"tone": "少说"})])
        self.assertEqual(out["tone"], "少说")

    def test_correction_is_or(self):
        out = xd.merge([{"allow_self_correction": False},
                        {"allow_correction": True}])
        self.assertTrue(out["allow_correction"])

    def test_notes_joined_and_deduped(self):
        out = xd.merge_named([("metacog", {"reason": "不确定"}),
                              ("attributor", {"reason": "不确定"}),
                              ("narrative", {"note": "故事有点矛盾"})])
        self.assertEqual(out["note"].count("不确定"), 1)
        self.assertIn("故事有点矛盾", out["note"])

    def test_sources_listed(self):
        out = xd.merge_named([("metacog", {}), ("metacog", {}),
                              ("dissonance", {})])
        self.assertEqual(out["sources"], ["metacog", "dissonance"])

    def test_idempotent(self):
        first = xd.merge_named([("metacog", {"tone": "少说"})])
        first["_x_normalized"] = True
        second = xd.merge([first])
        self.assertEqual(second["length_scale"], first["length_scale"])
        self.assertEqual(second["tone"], first["tone"])

    def test_malformed_entries_skipped(self):
        out = xd.merge([None, "x", {"length_scale": 0.7}])
        self.assertEqual(out["length_scale"], 0.7)
        self.assertEqual(len(out["sources"]), 1)

    def test_note_capped(self):
        out = xd.merge([{"note": "字" * 500}])
        self.assertLessEqual(len(out["note"]), xd.NOTE_LIMIT)


if __name__ == "__main__":
    unittest.main()
