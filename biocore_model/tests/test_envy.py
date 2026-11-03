# -*- coding: utf-8 -*-
import unittest

from biocore_model import envy as ev


def signals(stage="close", fairness=0.5, third=None, self_eval=0.5):
    return {
        "relation_stage": stage,
        "fairness": fairness,
        "third_party": third,
        "self_evaluation": self_eval,
    }


class EnvyLevelTest(unittest.TestCase):
    def test_mild_attention_level(self):
        out = ev.assess(signals("friend", 0.5,
                                {"presence": 0.9, "closeness": 0.5}, 0.5))
        self.assertEqual(out["kind"], "轻微在意")
        self.assertEqual(out["kind_key"], "mild")

    def test_comparison_level(self):
        out = ev.assess(signals("close", 0.2,
                                {"presence": 0.9, "closeness": 0.6}, 0.4))
        self.assertEqual(out["kind"], "比较")
        self.assertGreaterEqual(out["intensity"], ev.COMPARE_THRESHOLD)
        self.assertLess(out["intensity"], ev.ENVY_THRESHOLD)

    def test_envy_level(self):
        out = ev.assess(signals("intimate", 0.1,
                                {"presence": 1.0, "closeness": 0.8}, 0.3))
        self.assertEqual(out["kind"], "嫉妒")
        self.assertEqual(out["kind_key"], "envy")

    def test_below_trigger_has_no_level(self):
        out = ev.assess(signals("stranger", 0.9, False, 0.9))
        self.assertEqual(out["kind"], "")
        self.assertEqual(out["behavior"], "")
        self.assertLess(out["intensity"], ev.TRIGGER_THRESHOLD)

    def test_thresholds_are_ordered(self):
        self.assertLess(ev.TRIGGER_THRESHOLD, ev.COMPARE_THRESHOLD)
        self.assertLess(ev.COMPARE_THRESHOLD, ev.ENVY_THRESHOLD)

    def test_kind_of_maps_three_levels(self):
        self.assertEqual(ev.kind_of(0.10), "")
        self.assertEqual(ev.kind_of(0.30), "轻微在意")
        self.assertEqual(ev.kind_of(0.55), "比较")
        self.assertEqual(ev.kind_of(0.90), "嫉妒")


class EnvyBehaviorTest(unittest.TestCase):
    def test_close_comparison_asks(self):
        out = ev.assess(signals("close", 0.2,
                                {"presence": 0.9, "closeness": 0.6}, 0.4))
        self.assertEqual(out["behavior"], "探问")

    def test_distant_mild_attention_withdraws(self):
        out = ev.assess(signals("friend", 0.5,
                                {"presence": 0.9, "closeness": 0.5}, 0.5))
        self.assertEqual(out["behavior"], "收敛")

    def test_high_envy_nitpicks(self):
        out = ev.assess(signals("intimate", 0.1,
                                {"presence": 1.0, "closeness": 0.8}, 0.3))
        self.assertEqual(out["behavior"], "挑刺")

    def test_low_self_evaluation_suppresses_envy(self):
        out = ev.assess(signals("intimate", 0.1,
                                {"presence": 1.0, "closeness": 1.0}, 0.1))
        self.assertEqual(out["kind"], "嫉妒")
        self.assertEqual(out["behavior"], "压下")

    def test_behavior_always_known(self):
        for stage in ("stranger", "friend", "close", "intimate"):
            for self_eval in (0.0, 0.5, 1.0):
                out = ev.assess(signals(stage, 0.3,
                                        {"presence": 1.0,
                                         "closeness": 0.8}, self_eval))
                self.assertIn(out["behavior"], ev.BEHAVIORS + ("",))


class EnvyModulationTest(unittest.TestCase):
    def test_relationship_stage_modulates_intensity(self):
        base = {"fairness": 0.4,
                "third_party": {"presence": 0.7, "closeness": 0.5},
                "self_evaluation": 0.5}
        distant = ev.assess(dict(base, relation_stage="stranger"))
        close = ev.assess(dict(base, relation_stage="intimate"))
        self.assertGreater(close["intensity"], distant["intensity"])

    def test_unfairness_raises_intensity(self):
        fair = ev.assess(signals("close", 0.9,
                                 {"presence": 0.8, "closeness": 0.5}, 0.5))
        unfair = ev.assess(signals("close", 0.1,
                                   {"presence": 0.8, "closeness": 0.5}, 0.5))
        self.assertGreater(unfair["intensity"], fair["intensity"])

    def test_third_person_is_required(self):
        silent = ev.assess(signals("intimate", 0.1, False, 0.2))
        mentioned = ev.assess(signals("intimate", 0.1,
                                      {"presence": 1.0, "closeness": 0.8}, 0.2))
        self.assertEqual(silent["intensity"], 0.0)
        self.assertGreater(mentioned["intensity"], 0.0)

    def test_stronger_self_evaluation_buffers(self):
        fragile = ev.assess(signals("intimate", 0.1,
                                    {"presence": 1.0, "closeness": 0.8}, 0.1))
        steady = ev.assess(signals("intimate", 0.1,
                                   {"presence": 1.0, "closeness": 0.8}, 0.9))
        self.assertGreater(fragile["intensity"], steady["intensity"])

    def test_intensity_is_bounded(self):
        for stage in ("stranger", "intimate"):
            for self_eval in (-5, 0, 0.5, 1, 5):
                out = ev.assess(signals(stage, -5,
                                        {"presence": 5, "closeness": 5},
                                        self_eval))
                self.assertGreaterEqual(out["intensity"], 0.0)
                self.assertLessEqual(out["intensity"], 1.0)

    def test_deterministic(self):
        first = ev.assess(signals("close", 0.2,
                                  {"presence": 0.9, "closeness": 0.6}, 0.4))
        second = ev.assess(signals("close", 0.2,
                                   {"presence": 0.9, "closeness": 0.6}, 0.4))
        self.assertEqual(first, second)


class EnvySwitchTest(unittest.TestCase):
    def test_disabled_bool(self):
        out = ev.assess(signals("intimate", 0.1,
                                {"presence": 1.0, "closeness": 0.8}, 0.2),
                        config=False)
        self.assertFalse(out["enabled"])
        self.assertEqual(out["kind"], "")
        self.assertEqual(out["intensity"], 0.0)
        self.assertEqual(out["behavior"], "")
        self.assertTrue(out["reason"])

    def test_disabled_config_dict(self):
        out = ev.assess(signals("intimate", 0.1,
                                {"presence": 1.0, "closeness": 0.8}, 0.2),
                        config={"enabled": False})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["kind"], "")

    def test_threshold_can_be_raised(self):
        out = ev.assess(signals("friend", 0.5,
                                {"presence": 0.9, "closeness": 0.5}, 0.5),
                        config={"threshold": 0.8})
        self.assertEqual(out["kind"], "")

    def test_malformed_inputs_do_not_crash(self):
        for bad in (None, "bad", [], {"relation_stage": None,
                                      "third_party": "??",
                                      "fairness": "x"}):
            out = ev.assess(bad)
            self.assertIn(out["kind"], ev.KINDS + ("",))
            self.assertIn(out["behavior"], ev.BEHAVIORS + ("",))

    def test_view_fields(self):
        out = ev.assess(signals("close", 0.2,
                                {"presence": 0.9, "closeness": 0.6}, 0.4))
        panel = ev.view(out)
        for key in ("enabled", "kind", "kind_key", "intensity", "behavior",
                    "reason"):
            self.assertIn(key, panel)


if __name__ == "__main__":
    unittest.main()
