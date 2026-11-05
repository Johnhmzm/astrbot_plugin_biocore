# -*- coding: utf-8 -*-
"""Paper-map alignment: Gross 1998 absorb rates + Deci & Ryan 2000 equal needs.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_paper_alignment.py"
"""
import unittest
from unittest import mock

from biocore_model import self_intent as si
from biocore_runtime import perception as perc


NOW = 1700000000.0


def fake_call(strategy, effect=1.0):
    """A _call seam that pins the appraisal delta and the chosen strategy."""
    def call(name, fn, *args, **kwargs):
        if name == "appraisal" and fn == "appraise":
            return {"enabled": True, "value": {"v": -0.10}}
        if name == "regulation_strategies" and fn == "evaluate":
            return {"enabled": True,
                    "value": {"strategy": strategy, "effect": effect}}
        return {"enabled": False, "value": None}
    return call


def writeback_for(strategy, effect=1.0):
    state = {"core": {"v": -0.2, "a": 0.5, "stress": 0.2, "social": 0.5},
             "relationship": {"trust": 0.5, "closeness": 0.5, "conflict": 0.0},
             "needs": {"belonging": 0.6, "self_esteem": 0.6,
                       "control": 0.6, "meaningful_existence": 0.6}}
    with mock.patch.object(perc, "_call", fake_call(strategy, effect)):
        return perc.writeback(None, "s1", {"dims": {"goal": 0.5, "control": 0.7}},
                              state=state, now=NOW, enabled_override=True)


class AbsorbByStrategyTest(unittest.TestCase):
    """Gross 1998: reappraisal .6 / suppression .3 / everything else .5."""

    def test_reappraisal_absorbs_sixty_percent(self):
        self.assertAlmostEqual(perc.absorb_rate("cognitive_reappraisal"), 0.6)
        self.assertAlmostEqual(perc.absorb_factor("cognitive_reappraisal", 1.0),
                               0.6)

    def test_suppression_absorbs_thirty_percent(self):
        self.assertAlmostEqual(perc.absorb_rate("response_modulation"), 0.3)
        self.assertAlmostEqual(perc.absorb_factor("response_modulation", 1.0),
                               0.3)

    def test_the_other_strategies_keep_the_old_half(self):
        for strategy in ("situation_selection", "situation_modification",
                         "attentional_deployment", "none", "", None):
            self.assertAlmostEqual(perc.absorb_rate(strategy), 0.5)
            self.assertAlmostEqual(perc.absorb_factor(strategy, 1.0), 0.5)

    def test_effect_scales_and_is_bounded(self):
        self.assertAlmostEqual(perc.absorb_factor("cognitive_reappraisal", 0.5),
                               0.3)
        self.assertAlmostEqual(perc.absorb_factor("cognitive_reappraisal", 3.0),
                               0.6)      # effect is clamped to [0, 1]
        self.assertAlmostEqual(perc.absorb_factor("response_modulation", -1.0),
                               0.0)

    def test_writeback_applies_the_strategy_rate(self):
        reappraisal = writeback_for("cognitive_reappraisal")["applied"]["field"]
        suppression = writeback_for("response_modulation")["applied"]["field"]
        other = writeback_for("attentional_deployment")["applied"]["field"]
        # each dimension has its own share now: -0.10 * (1 - dim_absorb)
        self.assertAlmostEqual(reappraisal["v"], -0.04)    # 0.6 on v
        self.assertAlmostEqual(suppression["v"], -0.091)   # 0.6 x 0.3 on v
        self.assertAlmostEqual(other["v"], -0.075)         # 0.6 x 0.5 default
        self.assertEqual(writeback_for("cognitive_reappraisal")["regulation"]
                         ["absorbed"], 0.6)

    def test_positive_deltas_are_not_absorbed(self):
        def call(name, fn, *args, **kwargs):
            if name == "appraisal" and fn == "appraise":
                return {"enabled": True, "value": {"v": 0.10}}
            if name == "regulation_strategies" and fn == "evaluate":
                return {"enabled": True,
                        "value": {"strategy": "cognitive_reappraisal",
                                  "effect": 1.0}}
            return {"enabled": False, "value": None}
        state = {"core": {"v": -0.2}, "relationship": {}, "needs": {}}
        with mock.patch.object(perc, "_call", call):
            out = perc.writeback(None, "s1", {"dims": {"goal": 0.5}},
                                 state=state, now=NOW, enabled_override=True)
        # only the negative pressure is absorbed, a good turn stays as it is
        self.assertAlmostEqual(out["applied"]["field"]["v"], 0.10)


class NeedsEqualWeightTest(unittest.TestCase):
    """Deci & Ryan 2000: the basic needs have equal standing."""

    def test_every_need_weighs_the_same(self):
        self.assertEqual(set(si.NEED_WEIGHTS.values()), {0.25})
        self.assertEqual(set(si.NEED_WEIGHTS), set(si.NEED_KEYS))
        self.assertAlmostEqual(sum(si.NEED_WEIGHTS.values()), 1.0)

    def test_equal_gaps_now_produce_equal_drive(self):
        belonging_low = {"belonging": 0.1, "self_esteem": 0.9,
                         "control": 0.9, "meaningful_existence": 0.9}
        control_low = {"belonging": 0.9, "self_esteem": 0.9,
                       "control": 0.1, "meaningful_existence": 0.9}
        self.assertAlmostEqual(si.drive(belonging_low), si.drive(control_low),
                               places=6)
        self.assertAlmostEqual(si.drive(belonging_low), 0.30, places=6)

    def test_the_old_weights_used_to_favour_belonging(self):
        old = {"belonging": 0.30, "self_esteem": 0.25,
               "control": 0.20, "meaningful_existence": 0.25}
        belonging_low = {"belonging": 0.1, "self_esteem": 0.9,
                         "control": 0.9, "meaningful_existence": 0.9}
        control_low = {"belonging": 0.9, "self_esteem": 0.9,
                       "control": 0.1, "meaningful_existence": 0.9}

        def drive(needs, weights):
            return round(sum(weights[key] * (1.0 - needs[key])
                             for key in si.NEED_KEYS), 4)
        self.assertGreater(drive(belonging_low, old), drive(control_low, old))
        self.assertAlmostEqual(drive(belonging_low, old), 0.34)
        self.assertAlmostEqual(drive(control_low, old), 0.26)
        self.assertAlmostEqual(si.drive(belonging_low), 0.30)
        self.assertAlmostEqual(si.drive(control_low), 0.30)

    def test_weights_still_sum_to_one_inside_an_intent(self):
        result = si.evaluate(snapshot={"v": -0.3, "a": 0.5, "stress": 0.4},
                             relationship={"trust": 0.5, "closeness": 0.5},
                             needs={"belonging": 0.3, "self_esteem": 0.4,
                                    "control": 0.5,
                                    "meaningful_existence": 0.4})
        intents = result.get("intents") or []
        if intents:
            self.assertAlmostEqual(sum(row["weight"] for row in intents), 1.0,
                                   places=3)
