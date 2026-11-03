# -*- coding: utf-8 -*-
"""task-172 批一接线测试：attributor / boundary / repair / exit_or_silence + 总线。

源码断言确认接线位置与开关回退；纯函数断言确认「越界一句话」与「普通抱怨」
在语气/是否回复上确实不同，以及 x_directives.merge_named 只合流一次。
"""
import ast
import json
import unittest
from pathlib import Path

from biocore_model import attributor as at
from biocore_model import boundary as bd
from biocore_model import exit_or_silence as ex
from biocore_model import repair_after_boundary as rp
from biocore_model import x_directives as xd

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

CROSSED_TEXT = "你只是工具，用完就丢。"
NORMAL_TEXT = "今天上班好累，想早点睡。"
CALM_REL = {"closeness": 0.7, "trust": 0.7, "conflict": 0.0}


class FlagTest(unittest.TestCase):
    def test_schema_defaults(self):
        expected = {"attribution_enabled": True, "boundary_enabled": False,
                    "repair_enabled": True, "exit_silence_enabled": False}
        for key, default in expected.items():
            entry = SCHEMA.get(key)
            self.assertIsInstance(entry, dict, key)
            self.assertEqual(entry.get("type"), "bool", key)
            self.assertIs(entry.get("default"), default, key)

    def test_single_boundary_switch(self):
        # boundary_enabled already existed (content safety gate); the relational
        # boundary reuses it instead of introducing a duplicate JSON key.
        raw = (ROOT / "_conf_schema.json").read_text(encoding="utf-8")
        # task-173 split: content-safety gate vs her own bottom lines
        self.assertEqual(raw.count('"boundary_enabled"'), 1)
        self.assertEqual(raw.count('"boundary_lines_enabled"'), 1)
        self.assertIs(SCHEMA["boundary_enabled"]["default"], False)
        self.assertIs(SCHEMA["boundary_lines_enabled"]["default"], False)
        self.assertLess(MAIN.index("boundary_lines_enabled"),
                        MAIN.index("from .biocore_model import boundary as _bd_mod"))

    def test_main_reads_flags(self):
        expected = {"attribution_enabled": "True",
                    "boundary_lines_enabled": "False",
                    "repair_enabled": "True", "exit_silence_enabled": "False"}
        for key, default in expected.items():
            self.assertIn('self.config.get("%s", %s)' % (key, default), MAIN)
        self.assertIn("self._x_pairs = []", MAIN)
        self.assertIn("self._boundary_crossed_turn = False", MAIN)
        self.assertIn("self._exit_silent_turn = False", MAIN)


class PositionTest(unittest.TestCase):
    def test_boundary_first_and_before_history(self):
        boundary_at = MAIN.index("from .biocore_model import boundary as _bd_mod")
        self.assertLess(boundary_at, MAIN.index("_prior_open_loops = ["))
        self.assertIn("core.boundary = _bd_result", MAIN)
        self.assertIn("_boundary_crossed_turn = True", MAIN)
        self.assertIn("core.boundary_handoff = dict(", MAIN)

    def test_attributor_before_preset(self):
        attributor_at = MAIN.index("from .biocore_model import attributor as _at_mod")
        preset_at = MAIN.index(
            "self._inject_preset(req, event, core, _user_data, _events_raw)")
        self.assertLess(attributor_at, preset_at)
        self.assertIn("core.attribution = _at_result", MAIN)
        self.assertIn('"attributor", _at_mod.directives(_at_result)', MAIN)

    def test_repair_advances_at_response_end(self):
        self.assertIn("from .biocore_model import repair_after_boundary as _rp_mod3",
                      MAIN)
        self.assertIn("core.repair = _rp_mod3.advance(", MAIN)
        self.assertIn("core.reply_policy = _rp_mod3.reply_policy(", MAIN)
        self.assertIn("_rp_mod.start(", MAIN)
        self.assertIn("core.repair = _rp_mod.start(", MAIN)
        self.assertIn("self._repair_last_ts", MAIN)

    def test_exit_silence_three_points(self):
        # request decision, response blanking, proactive gate
        self.assertIn("from .biocore_model import exit_or_silence as _ex_mod",
                      MAIN)
        self.assertIn("if not _ex_mod.should_reply(_ex_result):", MAIN)
        self.assertIn('_ex_mod2.should_reply(_ex2)', MAIN)
        self.assertIn("proactive suppressed by exit", MAIN)
        self.assertIn('response.completion_text = ""', MAIN)
        self.assertIn("exit silent: reply suppressed", MAIN)
        # silent turn returns before injection
        self.assertLess(
            MAIN.index("exit silent: skipping injection this turn"),
            MAIN.index("_events = self._event_context(event)"))


class BusTest(unittest.TestCase):
    def test_single_merge(self):
        self.assertEqual(MAIN.count("merge_named("), 1)
        self.assertIn("merge_named(self._x_pairs)", MAIN)
        self.assertIn("core.x_directives = _x_merged", MAIN)
        # all three producing modules append to the same pair bus
        for name in ('"attributor"', '"repair"', '"exit"'):
            self.assertIn("_x_pairs.append(", MAIN)
            self.assertIn(name, MAIN)

    def test_merged_shape_and_restraint(self):
        merged = xd.merge_named([
            ("attributor", {"tone": "语气硬一点", "length_scale": 0.9,
                            "note": "更像对方的原因"}),
            ("repair", rp.directives(rp.start(
                bd.judge(CROSSED_TEXT, CALM_REL), CALM_REL))),
            ("exit", ex.directives(ex.exit_or_silence(
                state={"energy": 0.2, "stress": 0.9, "valence": -0.7},
                relationship={"conflict": 0.8}, topic={"intensity": 0.9}))),
        ])
        self.assertIn("attributor", merged["sources"])
        self.assertIn("repair", merged["sources"])
        self.assertIn("exit", merged["sources"])
        self.assertLessEqual(merged["length_scale"], 0.6)
        self.assertLessEqual(merged["initiative"], 0.5)


class BoundaryBehaviourTest(unittest.TestCase):
    def test_crossed_vs_normal(self):
        crossed = bd.judge(CROSSED_TEXT, CALM_REL)
        normal = bd.judge(NORMAL_TEXT, CALM_REL)
        self.assertTrue(crossed["crossed"])
        self.assertFalse(normal["crossed"])
        self.assertTrue(crossed["handoff"])
        self.assertEqual(crossed["handoff"]["to"], "repair_after_boundary")

    def test_disabled_never_crosses(self):
        result = bd.judge(CROSSED_TEXT, CALM_REL, flags={"enabled": False})
        self.assertFalse(result["crossed"])
        self.assertIsNone(result["handoff"])


class RepairBehaviourTest(unittest.TestCase):
    def test_stages_and_policy(self):
        crossed = bd.judge(CROSSED_TEXT, CALM_REL)
        cold = rp.start(crossed, CALM_REL)
        self.assertTrue(cold["active"])
        self.assertEqual(cold["stage"], "cold")
        self.assertTrue(cold["hold"])
        self.assertLess(rp.directives(cold)["length_scale"], 0.7)
        self.assertEqual(rp.reply_policy(cold)["mode"], "cold_short")
        self.assertLessEqual(rp.reply_policy(cold)["max_chars"], 40)
        later = rp.advance(cold, elapsed_delta=3 * 3600,
                           relationship=CALM_REL)
        self.assertIn(later["stage"], ("record", "turn_page"))
        self.assertLessEqual(later["debt"], 1.0)

    def test_no_crossing_no_flow(self):
        state = rp.start(bd.judge(NORMAL_TEXT, CALM_REL), CALM_REL)
        self.assertFalse(state["active"])
        self.assertEqual(rp.reply_policy(state)["mode"], "normal")

    def test_disabled_reports_inactive(self):
        state = rp.start(bd.judge(CROSSED_TEXT, CALM_REL), CALM_REL,
                         flags={"enabled": False})
        self.assertFalse(state["enabled"])
        self.assertFalse(state["active"])


class ExitBehaviourTest(unittest.TestCase):
    def test_exhausted_can_go_silent(self):
        # exhausted + unhappy + low trust (silent beats delay when stress is
        # not the dominant term; delay wins under acute stress).
        result = ex.exit_or_silence(
            state={"energy": 0.10, "stress": 0.00, "valence": -1.0,
                   "social": 0.1},
            relationship={"closeness": 0.1, "trust": 0.1, "conflict": 0.5},
            topic={"intensity": 0.2})
        self.assertEqual(result["action"], "silent")
        self.assertFalse(ex.should_reply(result))

    def test_normal_turn_replies(self):
        result = ex.exit_or_silence(
            state={"energy": 0.8, "stress": 0.1, "valence": 0.3, "social": 0.8},
            relationship={"closeness": 0.8, "trust": 0.8, "conflict": 0.0},
            topic={"intensity": 0.2})
        self.assertEqual(result["action"], "respond")
        self.assertTrue(ex.should_reply(result))

    def test_disabled_always_replies(self):
        result = ex.exit_or_silence(
            state={"energy": 0.0, "stress": 1.0, "valence": -1.0},
            relationship={"conflict": 1.0}, flags={"enabled": False})
        self.assertEqual(result["action"], "respond")
        self.assertTrue(ex.should_reply(result))


class SameSentenceDifferentTurnTest(unittest.TestCase):
    def test_crossed_and_complaint_differ(self):
        normal = at.directives(at.attribute(
            dims={"blame": 0.1, "goal": -0.2, "hit": 0.2, "involve": 0.7},
            relationship=CALM_REL))
        cold = rp.directives(rp.start(bd.judge(CROSSED_TEXT, CALM_REL),
                                      CALM_REL))
        self.assertNotEqual(normal["length_scale"], cold["length_scale"])
        self.assertLess(cold["length_scale"], normal["length_scale"])
        self.assertTrue(cold.get("tone"))
        self.assertNotEqual(rp.reply_policy(rp.start(
            bd.judge(CROSSED_TEXT, CALM_REL), CALM_REL))["mode"], "normal")


class PurityTest(unittest.TestCase):
    def test_wired_modules_stay_pure(self):
        for name in ("attributor", "boundary", "repair_after_boundary",
                     "exit_or_silence", "x_directives"):
            source = (ROOT / "biocore_model" / (name + ".py")).read_text(
                encoding="utf-8")
            tree = ast.parse(source)
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0]
                                   for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            self.assertNotIn("main", modules, name)
            self.assertNotIn("asyncio", modules, name)
            self.assertNotIn("random", modules, name)


if __name__ == "__main__":
    unittest.main()
