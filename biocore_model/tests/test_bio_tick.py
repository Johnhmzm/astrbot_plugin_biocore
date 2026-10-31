# -*- coding: utf-8 -*-
"""Life-maintenance tick tests: decay, intero, needs, threshold, idempotency."""
import os
import time
import unittest
from pathlib import Path
from unittest import mock

from biocore_model import bio_tick as bt
from biocore_model import sleep_circadian as sleep


class FakeCore:
    def __init__(self, **kw):
        self.v = 0.0
        self.a = 0.5
        self.d = 0.55
        self.social = 0.5
        self.stress = 0.2
        self.energy = 0.6
        self.trust = 0.5
        self.labels = {"emotion": "neutral"}
        self.emotion_decay_factors = {"neutral": 1.0}
        self.valence_decay_minutes = 120.0
        self.arousal_decay_minutes = 30.0
        self.social_decay_minutes = 180.0
        self.circadian_alertness = 0.5
        self.allostatic_load = 0.0
        self.needs = None
        self.sleep_debt = 0.0
        self.last_debt_ts = 0.0
        self.last_bio_tick_ts = 0.0
        self._bio_tick_count = 0
        self.relationship_context = {"state": {"conflict": 0.0, "closeness": 0.5}}
        self.pending_intent = None
        self.intero = None
        self._metabolic_energy_offset = 0.0
        for key, value in kw.items():
            setattr(self, key, value)

    def snapshot(self):
        return {"v": self.v, "a": self.a, "d": self.d, "social": self.social,
                "stress": self.stress, "energy": self.energy,
                "trust": self.trust, "labels": dict(self.labels),
                "sleep_debt": self.sleep_debt,
                "allostatic_load": self.allostatic_load}


def _now(hour=12):
    return time.mktime((2026, 1, 1, hour, 0, 0, 0, 0, -1))


class DecayTest(unittest.TestCase):
    def test_valence_decays_to_zero(self):
        core = FakeCore(v=-0.5)
        out = bt.bio_tick(core, now=1000.0, dt_hours=1.0)
        self.assertAlmostEqual(core.v, -0.5 * 0.5 ** 0.5, places=4)
        self.assertTrue(out["changed"])

    def test_arousal_regresses_to_baseline(self):
        core = FakeCore(a=0.8)
        bt.bio_tick(core, now=1000.0, dt_hours=1.0)
        self.assertAlmostEqual(core.a, 0.50, places=4)

    def test_social_regresses_to_baseline(self):
        core = FakeCore(social=0.2)
        bt.bio_tick(core, now=1000.0, dt_hours=1.0)
        expected = 0.55 + (0.2 - 0.55) * (0.5 ** (60.0 / 180.0))
        self.assertAlmostEqual(core.social, expected, places=4)

    def test_stress_re_derived_from_affect(self):
        core = FakeCore(v=-0.4, a=0.7, d=0.6, social=0.5)
        bt.bio_tick(core, now=1000.0, dt_hours=1.0)
        expected = (0.45 * max(0.0, -core.v) * core.a + 0.35 * (1.0 - core.d)
                    + 0.20 * (1.0 - core.social))
        self.assertAlmostEqual(core.stress, expected, places=2)

    def test_dt_cap_at_six_hours(self):
        core = FakeCore(v=-1.0)
        out = bt.bio_tick(core, now=1000.0, dt_hours=100.0)
        self.assertEqual(out["dt_hours"], 6.0)
        self.assertAlmostEqual(core.v, -1.0 * 0.5 ** (360.0 / 120.0), places=4)


class InteroNeedsTest(unittest.TestCase):
    def test_intero_updated_and_ts_set(self):
        core = FakeCore(stress=0.6, a=0.7)
        out = bt.bio_tick(core, now=1234.0, dt_hours=1.0)
        self.assertEqual(out["intero"]["ts"], 1234.0)
        self.assertIs(core.intero, out["intero"])
        for dim in ("tension", "warmth", "heaviness", "clarity"):
            self.assertGreaterEqual(out["intero"][dim], 0.0)
            self.assertLessEqual(out["intero"][dim], 1.0)

    def test_needs_step_runs(self):
        core = FakeCore()
        out = bt.bio_tick(core, now=5000.0, dt_hours=1.0)
        self.assertEqual(core.needs["last_tick_ts"], 5000.0)
        bt.bio_tick(core, now=8600.0, dt_hours=1.0)  # second tick applies the silence delta
        self.assertLess(core.needs["belonging"], 0.6)
        self.assertIn("needs", out["log"])

    def test_sleep_debt_accumulates(self):
        core = FakeCore()
        bt.bio_tick(core, now=5000.0, dt_hours=2.0)
        self.assertAlmostEqual(core.sleep_debt, 1.0, places=3)
        self.assertEqual(core.last_debt_ts, 5000.0)

    def test_circadian_alertness_set_from_now(self):
        core = FakeCore()
        now = _now(3)
        bt.bio_tick(core, now=now, dt_hours=1.0)
        self.assertAlmostEqual(core.circadian_alertness,
                               sleep.circadian(time.localtime(now).tm_hour), places=4)

    def test_allostatic_load_grows_under_stress(self):
        core = FakeCore(stress=0.9)
        bt.bio_tick(core, now=1000.0, dt_hours=0.0)  # no affect decay: keep stress high
        self.assertGreater(core.allostatic_load, 0.0)


class IdempotencyTest(unittest.TestCase):
    def test_same_now_only_applies_once(self):
        core = FakeCore(v=-0.6, a=0.8)
        first = bt.bio_tick(core, now=2000.0, dt_hours=1.0)
        v1, a1, count1 = core.v, core.a, core._bio_tick_count
        second = bt.bio_tick(core, now=2000.0, dt_hours=1.0)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertFalse(second["changed"])
        self.assertEqual((core.v, core.a, core._bio_tick_count), (v1, a1, count1))

    def test_log_throttled_every_ten_ticks(self):
        core = FakeCore()
        emits = []
        for index in range(10):
            out = bt.bio_tick(core, now=1000.0 + index * 3600.0, dt_hours=1.0)
            emits.append(out["log"]["emit"])
        self.assertTrue(emits[0])  # first tick always emits (first-run visibility)
        self.assertEqual(emits[1:9], [False] * 8)
        self.assertTrue(emits[9])
        self.assertEqual(out["log"]["count"], 10)

    def test_env_forces_every_tick(self):
        core = FakeCore()
        with mock.patch.dict(os.environ, {"BIOCORE_BIO_TICK_LOG": "1"}):
            emits = [bt.bio_tick(core, now=5000.0 + index * 3600.0,
                                 dt_hours=1.0)["log"]["emit"] for index in range(5)]
        self.assertEqual(emits, [True] * 5)


class PendingIntentTest(unittest.TestCase):
    def test_high_discomfort_triggers_intent(self):
        core = FakeCore(stress=0.9, a=0.8, sleep_debt=0.8, v=-0.6, social=0.3,
                        trust=0.3, d=0.4, energy=0.2, allostatic_load=0.5,
                        labels={"emotion": "sadness"})
        core.relationship_context = {"state": {"conflict": 0.6, "closeness": 0.2}}
        core.intero = {"tension": 0.90, "warmth": 0.10, "heaviness": 0.90,
                      "clarity": 0.20, "ts": 0.0}
        out = bt.bio_tick(core, now=3000.0, dt_hours=0.1)
        self.assertGreater(out["discomfort"], bt.DISCOMFORT_TRIGGER)
        intent = out["pending_intent"]
        self.assertIsInstance(intent, dict)
        self.assertIn(intent["action"], ("approach", "share", "question",
                                         "withdraw", "repair", "rest"))
        self.assertEqual(intent["source"], "bio_tick")
        self.assertTrue(intent["reason"])

    def test_calm_state_keeps_pending_intent_empty(self):
        core = FakeCore()
        out = bt.bio_tick(core, now=3000.0, dt_hours=1.0)
        self.assertLessEqual(out["discomfort"], bt.DISCOMFORT_TRIGGER)
        self.assertIsNone(out["pending_intent"])
        self.assertIsNone(out["action"])


class PurityTest(unittest.TestCase):
    def test_source_has_no_llm_or_main_import(self):
        source = Path(bt.__file__).read_text(encoding="utf-8").lower()
        self.assertNotIn("llm", source)
        self.assertNotIn("import main", source)
        self.assertNotIn("from main", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("httpx", source)

    def test_memory_maintenance_throttle_and_forget(self):
        core = FakeCore()
        core.memory_entries = [
            {"id": "a", "retrieval_s": 0.8},
            {"id": "b", "retrieval_s": 0.01},
        ]
        first = bt.memory_maintenance(core, now=1000.0, dt_hours=1.0)
        self.assertFalse(first["skipped"])
        self.assertEqual(first["decayed"], 2)
        self.assertGreaterEqual(first["forgotten"], 1)
        second = bt.memory_maintenance(core, now=1200.0, dt_hours=1.0)
        self.assertTrue(second["skipped"])
        self.assertEqual(second["reason"], "throttled")


if __name__ == "__main__":
    unittest.main()
