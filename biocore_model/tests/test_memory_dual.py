# -*- coding: utf-8 -*-
"""MD-1 memory_dual tests: formulas, testing effect, selection, forgetting."""
import math
import unittest

from biocore_model import memory_dual as md

NOW = 1_700_000_000.0


def entry(**kw):
    base = {"id": "e1", "text": "hello", "storage_s": 0.5, "retrieval_s": 0.5,
            "access_count": 0, "last_access_ts": NOW, "created_ts": NOW,
            "arousal_at_encoding": 0.5, "open_loop": False}
    base.update(kw)
    return base


class DecayTest(unittest.TestCase):
    def test_power_law_1h(self):
        self.assertAlmostEqual(md.decay(1.0, 1.0), math.pow(1 + 1 / 24.0, -0.5), places=12)
        self.assertAlmostEqual(md.decay(1.0, 1.0), 0.979796, places=6)

    def test_power_law_24h(self):
        self.assertAlmostEqual(md.decay(1.0, 24.0), 0.707107, places=6)

    def test_power_law_7d(self):
        self.assertAlmostEqual(md.decay(1.0, 168.0), 0.353553, places=6)

    def test_zero_dt_and_scaling(self):
        self.assertEqual(md.decay(0.42, 0.0), 0.42)
        self.assertAlmostEqual(md.decay(0.8, 24.0), 0.8 * 0.707107, places=6)
        self.assertGreater(md.decay(0.8, 1.0), md.decay(0.8, 24.0))


class EncodeTest(unittest.TestCase):
    def test_defaults(self):
        row = md.encode("海边", NOW)
        self.assertEqual(row["storage_s"], 0.35)
        self.assertEqual(row["retrieval_s"], 0.35)
        self.assertEqual(row["access_count"], 0)
        self.assertEqual(row["last_access_ts"], NOW)
        self.assertFalse(row["open_loop"])
        self.assertFalse(row["hidden"])

    def test_arousal_raises_initial_storage(self):
        low = md.encode("low", NOW, arousal=0.0)
        high = md.encode("high", NOW, arousal=1.0)
        self.assertAlmostEqual(high["storage_s"], 0.70, places=4)
        self.assertGreater(high["storage_s"], low["storage_s"])
        self.assertEqual(high["retrieval_s"], high["storage_s"])

    def test_arousal_clamped(self):
        self.assertAlmostEqual(md.encode("x", NOW, arousal=5.0)["storage_s"], 0.70, places=4)
        self.assertAlmostEqual(md.encode("x", NOW, arousal=-3.0)["storage_s"], 0.35, places=4)

    def test_open_loop_flag(self):
        self.assertTrue(md.encode("todo", NOW, open_loop=True)["open_loop"])


class RecallTest(unittest.TestCase):
    def test_testing_effect_storage_gain(self):
        row = entry(storage_s=0.4, retrieval_s=0.3, access_count=0, last_access_ts=0.0)
        out = md.on_recall(row, NOW)
        self.assertAlmostEqual(out["storage_s"], 0.46, places=4)   # +0.1*(1-0.4)
        self.assertAlmostEqual(out["retrieval_s"], 0.65, places=4)  # +0.35
        self.assertEqual(out["access_count"], 1)
        self.assertEqual(out["last_access_ts"], NOW)

    def test_retrieval_capped_at_one(self):
        out = md.on_recall(entry(retrieval_s=0.9, last_access_ts=0.0), NOW)
        self.assertEqual(out["retrieval_s"], 1.0)

    def test_idempotent_same_now(self):
        row = entry(storage_s=0.4, retrieval_s=0.3, last_access_ts=0.0)
        first = md.on_recall(row, NOW)
        second = md.on_recall(first, NOW)
        self.assertEqual(second["storage_s"], first["storage_s"])
        self.assertEqual(second["retrieval_s"], first["retrieval_s"])
        self.assertEqual(second["access_count"], 1)

    def test_does_not_mutate_input(self):
        row = entry(storage_s=0.4, retrieval_s=0.3, last_access_ts=0.0)
        before = dict(row)
        md.on_recall(row, NOW)
        self.assertEqual(row, before)

    def test_new_now_applies_again(self):
        first = md.on_recall(entry(last_access_ts=0.0), NOW)
        second = md.on_recall(first, NOW + 60)
        self.assertEqual(second["access_count"], 2)
        self.assertGreater(second["storage_s"], first["storage_s"])


class ScoreTest(unittest.TestCase):
    def test_context_weight(self):
        row = entry()
        full = md.score(row, NOW, context_match=1.0)
        half = md.score(row, NOW, context_match=0.25)
        self.assertAlmostEqual(half / full, 0.5, places=6)  # 0.25 ** 0.5

    def test_open_loop_bonus(self):
        closed = md.score(entry(open_loop=False), NOW)
        opened = md.score(entry(open_loop=True), NOW)
        self.assertAlmostEqual(opened / closed, 1.15, places=6)

    def test_frequency_term(self):
        low = md.score(entry(access_count=0), NOW)
        high = md.score(entry(access_count=3), NOW)
        expected = 1.0 + 0.3 * math.log1p(3)
        self.assertAlmostEqual(high / low, expected, places=6)

    def test_decays_over_time(self):
        row = entry(retrieval_s=0.6)
        s0 = md.score(row, NOW)
        s24 = md.score(row, NOW + 24 * 3600)
        s72 = md.score(row, NOW + 72 * 3600)
        self.assertGreater(s0, s24)
        self.assertGreater(s24, s72)

    def test_hidden_scores_zero(self):
        self.assertEqual(md.score(entry(hidden=True), NOW), 0.0)


class SelectTest(unittest.TestCase):
    def _rows(self):
        return [
            entry(id="strong", text="strong", storage_s=0.9, retrieval_s=0.9,
                  last_access_ts=NOW),
            entry(id="recent", text="recent", storage_s=0.6, retrieval_s=0.6,
                  last_access_ts=NOW - 3600),
            entry(id="open", text="open", storage_s=0.5, retrieval_s=0.5,
                  open_loop=True, last_access_ts=NOW - 24 * 3600),
            entry(id="old", text="old", storage_s=0.4, retrieval_s=0.4,
                  last_access_ts=NOW - 30 * 24 * 3600),
            entry(id="hidden", text="hidden", retrieval_s=0.9, hidden=True),
        ]

    def test_sorted_and_limited(self):
        out = md.select(self._rows(), NOW, limit=3)
        ids = [row["id"] for row in out["picked"]]
        self.assertEqual(len(ids), 3)
        self.assertNotIn("hidden", ids)
        scores = [row["score"] for row in out["picked"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(ids[0], "strong")

    def test_min_score_filters(self):
        rows = [entry(id="weak", retrieval_s=0.01, last_access_ts=NOW - 90 * 24 * 3600)]
        out = md.select(rows, NOW, min_score=0.12)
        self.assertEqual(out["picked"], [])
        self.assertEqual(out["skipped"][0]["reason"], "below_min_score")

    def test_skipped_reason_for_limit(self):
        out = md.select(self._rows(), NOW, limit=1)
        reasons = {row["id"]: row["reason"] for row in out["skipped"]}
        self.assertEqual(reasons["hidden"], "hidden")
        self.assertIn("limit", reasons.values())

    def test_context_dict_per_entry(self):
        rows = [entry(id="a", retrieval_s=0.5), entry(id="b", retrieval_s=0.5)]
        out = md.select(rows, NOW, context={"a": 1.0, "b": 0.01})
        self.assertEqual(out["picked"][0]["id"], "a")
        self.assertNotIn("b", [row["id"] for row in out["picked"]])


class ForgetTest(unittest.TestCase):
    def test_marks_hidden_without_deleting(self):
        rows = [entry(id="faint", retrieval_s=0.10),
                entry(id="solid", retrieval_s=0.50)]
        out = md.forget(rows, NOW)
        self.assertEqual(len(out["entries"]), 2)          # nothing deleted
        by_id = {row["id"]: row for row in out["entries"]}
        self.assertTrue(by_id["faint"]["hidden"])
        self.assertFalse(by_id["solid"].get("hidden"))
        self.assertEqual(out["forgotten_ids"], ["faint"])
        self.assertNotIn("hidden", rows[0])               # input untouched

    def test_idempotent_second_call(self):
        rows = [entry(id="faint", retrieval_s=0.10)]
        first = md.forget(rows, NOW)
        second = md.forget(first["entries"], NOW)
        self.assertEqual(first["forgotten_ids"], ["faint"])
        self.assertEqual(second["forgotten_ids"], [])


class TimeEvolutionTest(unittest.TestCase):
    def test_ten_memories_three_horizons(self):
        rows = []
        for index in range(10):
            rows.append(entry(
                id="m%02d" % (index + 1), text="memory-%d" % index,
                storage_s=0.35 + 0.035 * index,
                retrieval_s=0.35 + 0.035 * index,
                last_access_ts=NOW - (index * 6) * 3600,
                open_loop=(index % 3 == 0),
            ))
        early = md.select(rows, NOW, limit=4)
        day = md.select(rows, NOW + 24 * 3600, limit=4)
        three = md.select(rows, NOW + 72 * 3600, limit=4)
        early_scores = {row["id"]: row["score"] for row in early["picked"]}
        day_scores = {row["id"]: row["score"] for row in day["picked"]}
        three_scores = {row["id"]: row["score"] for row in three["picked"]}
        common = set(early_scores) & set(three_scores)
        if common:
            sample = sorted(common)[0]
            self.assertGreater(early_scores[sample], three_scores[sample])
        self.assertNotEqual(early_scores, day_scores)
        self.assertLessEqual(max(three_scores.values()) if three_scores else 1.0,
                             max(early_scores.values()))

    def test_forget_after_long_gap(self):
        rows = [entry(id="m1", retrieval_s=0.30, last_access_ts=NOW)]
        out = md.forget(rows, NOW + 30 * 24 * 3600)
        self.assertIn("m1", out["forgotten_ids"])


if __name__ == "__main__":
    unittest.main()
