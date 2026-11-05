# -*- coding: utf-8 -*-
"""task-243 step 3.2: per-dimension damping + per-need bias (no single blend).

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_damping_needs_split.py"
"""
import unittest
from unittest import mock

from biocore_model import needs_events as ne
from biocore_runtime import perception as perc


NOW = 1700000000.0


def fake_call(strategy, effect=1.0, deltas=None):
    """A _call seam: pins the appraisal deltas and the chosen strategy."""
    body = deltas if isinstance(deltas, dict) else {"v": -0.10}

    def call(name, fn, *args, **kwargs):
        if name == "appraisal" and fn == "appraise":
            return {"enabled": True, "value": dict(body)}
        if name == "regulation_strategies" and fn == "evaluate":
            return {"enabled": True,
                    "value": {"strategy": strategy, "effect": effect}}
        return {"enabled": False, "value": None}
    return call


def writeback_for(strategy, deltas=None, effect=1.0):
    state = {"core": {"v": -0.2, "a": 0.5, "stress": 0.2, "social": 0.5},
             "relationship": {"trust": 0.5, "closeness": 0.5, "conflict": 0.0},
             "needs": {"belonging": 0.6, "self_esteem": 0.6,
                       "control": 0.6, "meaningful_existence": 0.6}}
    with mock.patch.object(perc, "_call", fake_call(strategy, effect, deltas)):
        return perc.writeback(None, "s1", {"dims": {"goal": 0.5, "control": 0.7}},
                              state=state, now=NOW, enabled_override=True)


class PerDimensionDampingTest(unittest.TestCase):
    """One strategy x dimension table instead of one global keep factor."""

    def test_every_dimension_gets_its_own_share(self):
        shares = {dim: perc.dim_absorb("cognitive_reappraisal", dim, 1.0)
                  for dim in ("v", "a", "stress", "social", "trust")}
        self.assertAlmostEqual(shares["v"], 0.60, places=4)
        self.assertAlmostEqual(shares["a"], 0.48, places=4)
        self.assertAlmostEqual(shares["stress"], 0.60, places=4)
        self.assertAlmostEqual(shares["social"], 0.30, places=4)
        self.assertAlmostEqual(shares["trust"], 0.18, places=4)
        self.assertNotAlmostEqual(shares["v"], shares["a"], places=4)
        self.assertNotAlmostEqual(shares["stress"], shares["trust"], places=4)

    def test_suppression_damps_expression_not_meaning(self):
        arousal = perc.dim_absorb("response_modulation", "a", 1.0)
        valence = perc.dim_absorb("response_modulation", "v", 1.0)
        trust = perc.dim_absorb("response_modulation", "trust", 1.0)
        self.assertGreater(arousal, valence)
        self.assertGreater(arousal, trust)
        self.assertAlmostEqual(valence, 0.09, places=4)   # 0.3 rate x 0.3 gain

    def test_reappraisal_moves_more_than_suppression(self):
        for dim in ("v", "social", "trust"):
            self.assertGreater(perc.dim_absorb("cognitive_reappraisal", dim, 1.0),
                               perc.dim_absorb("response_modulation", dim, 1.0))

    def test_writeback_damps_each_dimension_separately(self):
        out = writeback_for("cognitive_reappraisal",
                            {"v": -0.10, "a": 0.10, "stress": 0.08,
                             "trust": -0.02})
        field = out["applied"]["field"]
        self.assertAlmostEqual(field["v"], -0.04, places=6)      # keep 0.4
        self.assertAlmostEqual(field["a"], 0.052, places=6)      # keep 0.52
        self.assertAlmostEqual(field["stress"], 0.032, places=6)  # keep 0.4
        self.assertAlmostEqual(field["trust"], -0.0164, places=6)  # keep 0.82
        ratios = {name: abs(field[name]) / abs(raw) for name, raw in
                  (("v", 0.10), ("a", 0.10), ("stress", 0.08), ("trust", 0.02))}
        self.assertGreater(len({round(value, 4) for value in ratios.values()}), 2)

    def test_writeback_reports_the_per_dimension_shares(self):
        out = writeback_for("response_modulation",
                            {"v": -0.10, "stress": 0.08})
        per_dim = out["regulation"]["per_dim"]
        self.assertEqual(sorted(per_dim), ["stress", "v"])
        self.assertAlmostEqual(per_dim["v"],
                               perc.dim_absorb("response_modulation", "v", 1.0),
                               places=4)
        self.assertAlmostEqual(per_dim["stress"],
                               perc.dim_absorb("response_modulation",
                                               "stress", 1.0), places=4)
        self.assertNotAlmostEqual(per_dim["v"], per_dim["stress"], places=4)


class PerNeedBiasTest(unittest.TestCase):
    """Each need keeps its own bias; no cross-need averaging."""

    def needs(self, **kw):
        base = {"belonging": 0.6, "self_esteem": 0.6, "control": 0.6,
                "meaningful_existence": 0.6}
        base.update(kw)
        return base

    def test_one_row_per_need(self):
        rows = ne.need_biases(self.needs(belonging=0.3, control=0.9))
        self.assertEqual(sorted(rows), sorted(ne.NEED_KEYS))
        for row in rows.values():
            self.assertEqual(sorted(row),
                             ["bias", "deficit", "surplus", "value"])
        self.assertAlmostEqual(rows["belonging"]["bias"], -0.3, places=4)
        self.assertAlmostEqual(rows["control"]["bias"], 0.3, places=4)
        self.assertAlmostEqual(rows["self_esteem"]["bias"], 0.0, places=4)

    def test_one_need_never_moves_another(self):
        before = ne.need_biases(self.needs())
        after = ne.need_biases(self.needs(belonging=0.1))
        for key in ("self_esteem", "control", "meaningful_existence"):
            self.assertEqual(before[key], after[key])
        self.assertNotEqual(before["belonging"], after["belonging"])

    def test_actions_read_one_need_each(self):
        # a control deficit used to add to self_assert (2.0*self_esteem +
        # 1.5*control); it no longer leaks into that action
        self.assertAlmostEqual(ne.behavior_bias(self.needs(control=0.1))
                               ["self_assert"], 0.0, places=4)
        self.assertGreater(ne.behavior_bias(self.needs(self_esteem=0.9))
                           ["self_assert"], 0.0)
        # and a meaningful_existence deficit no longer inflates ask_clarify
        self.assertAlmostEqual(
            ne.behavior_bias(self.needs(meaningful_existence=0.1))
            ["ask_clarify"], 0.0, places=4)
        self.assertGreater(ne.behavior_bias(self.needs(control=0.3))
                           ["ask_clarify"], 0.0)

    def test_summary_exposes_the_per_need_rows(self):
        row = ne.summary(self.needs(belonging=0.3))
        self.assertIn("bias", row)
        self.assertEqual(sorted(row["bias"]), sorted(ne.NEED_KEYS))
        self.assertAlmostEqual(row["bias"]["belonging"]["deficit"], 0.3, places=4)


if __name__ == "__main__":
    unittest.main()
