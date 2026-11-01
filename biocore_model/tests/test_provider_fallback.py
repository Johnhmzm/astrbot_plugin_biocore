# -*- coding: utf-8 -*-
"""task-127: fallback ordering/cooldown tests."""
import unittest
from pathlib import Path

from biocore_model import provider_fallback as pf

REPO = Path(__file__).resolve().parents[2]


class CandidatesTest(unittest.TestCase):
    def test_primary_only_when_fallback_empty(self):
        self.assertEqual(pf.candidates("main", [], {}, 1000.0), ["main"])
        self.assertEqual(pf.candidates("main", None, {}, 1000.0), ["main"])

    def test_order_primary_then_fallbacks(self):
        out = pf.candidates("main", ["backup1", "backup2"], {}, 1000.0)
        self.assertEqual(out, ["main", "backup1", "backup2"])

    def test_dedupes_and_cleans_ids(self):
        out = pf.candidates(" main ", ["main", "backup1", " ", None, "backup1"],
                            {}, 1000.0)
        self.assertEqual(out, ["main", "backup1"])

    def test_primary_none_uses_fallbacks(self):
        self.assertEqual(pf.candidates(None, ["backup1"], {}, 1000.0),
                         ["backup1"])

    def test_cooling_provider_skipped(self):
        state = {"main": 995.0}
        self.assertEqual(pf.candidates("main", ["backup1"], state, 1000.0),
                         ["backup1"])

    def test_cooldown_expires(self):
        state = {"main": 900.0}
        self.assertEqual(pf.candidates("main", ["backup1"], state, 1000.0),
                         ["main", "backup1"])

    def test_all_cooling_returns_empty(self):
        state = {"main": 999.0, "backup1": 998.0}
        self.assertEqual(pf.candidates("main", ["backup1"], state, 1000.0), [],
                         msg="every candidate cooling")

    def test_custom_cooldown(self):
        state = {"main": 800.0}
        self.assertEqual(pf.candidates("main", [], state, 1000.0, cooldown=300),
                         [])
        self.assertEqual(pf.candidates("main", [], state, 1000.0, cooldown=60),
                         ["main"])


class StateTest(unittest.TestCase):
    def test_mark_failure_copies_state(self):
        state = {}
        out = pf.mark_failure(state, "backup1", 123.0)
        self.assertEqual(out["backup1"], 123.0)
        self.assertEqual(state, {})

    def test_mark_success_records_current_and_clears_cooldown(self):
        state = {"main": 100.0, "backup1": 101.0}
        out = pf.mark_success(state, "backup1", 200.0)
        self.assertNotIn("backup1", out)
        self.assertEqual(pf.current(out), "backup1")
        self.assertEqual(out["main"], 100.0)
        self.assertEqual(state["backup1"], 101.0)

    def test_reserved_keys_never_become_candidates(self):
        state = pf.mark_success({}, "backup1", 10.0)
        self.assertEqual(pf.candidates("main", ["current"], state, 20.0),
                         ["main"])
        self.assertFalse(pf.is_cooling(state, "current", 20.0))

    def test_describe(self):
        state = {"main": 100.0}
        self.assertEqual(pf.describe(state), "failed=main")
        state = pf.mark_success(state, "backup1", 200.0)
        self.assertIn("current=backup1", pf.describe(state))


class WiringStaticTest(unittest.TestCase):
    def test_main_has_fallback_wiring(self):
        source = (REPO / "main.py").read_text(encoding="utf-8")
        self.assertIn("provider_fallback_order", source)
        self.assertIn("[biocore] provider fallback from=%s to=%s reason=%s", source)
        self.assertIn("provider_fallback as _pf", source)


if __name__ == "__main__":
    unittest.main()
