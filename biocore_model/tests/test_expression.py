# -*- coding: utf-8 -*-
"""task-243 段2: expression policy -- 表层扮演 / 抑制 / 展示规则.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_expression.py"
"""
import copy
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import dimensions as dim
from biocore_runtime import expression as exp
from biocore_runtime import pipeline as pl


NOW = 1700000000.0
MASK_LINE = exp.LINES["mask"]
LEAK_LINE = exp.LINES["leak"]
SUPPRESS_LINE = exp.LINES["suppress"]


def conflicted(now=NOW):
    """One axis written both ways: explicit says up, implicit went down."""
    return dim.absorb(dim.initial(now), explicit={"v": 0.5},
                      implicit={"v": -0.4}, now=now)


class PolicyTest(unittest.TestCase):
    """The four modes, driven only by thresholds and priority."""

    def test_no_conflict_is_authentic(self):
        row = exp.policy(dim.initial(NOW), {"trust": 0.2, "closeness": 0.3})
        self.assertEqual(row["mode"], "authentic")
        self.assertEqual(row["reason"], "no_conflict")
        self.assertEqual(row["hints"], exp.HINTS["authentic"])
        self.assertEqual(exp.render(row), [])      # nothing to constrain

    def test_conflict_with_thin_trust_masks(self):
        row = exp.policy(conflicted(), {"trust": 0.2, "closeness": 0.3})
        self.assertEqual(row["mode"], "mask")
        self.assertEqual(row["reason"], "surface_acting")
        self.assertFalse(row["hints"]["explain"])
        self.assertFalse(row["hints"]["soften"])

    def test_conflict_in_a_close_relationship_leaks(self):
        row = exp.policy(conflicted(), {"trust": 0.7, "closeness": 0.8})
        self.assertEqual(row["mode"], "leak")
        self.assertEqual(row["reason"], "leak_through")
        self.assertTrue(row["hints"]["soften"])
        self.assertEqual(row["hints"]["sentence"], "short")

    def test_high_stress_suppresses_before_anything_else(self):
        model = dim.absorb(conflicted(), explicit={"stress": 0.9}, now=NOW)
        row = exp.policy(model, {"trust": 0.7, "closeness": 0.8})
        self.assertEqual(row["mode"], "suppress")   # display rule wins
        self.assertEqual(row["reason"], "display_rule")
        self.assertFalse(row["hints"]["explain"])
        self.assertFalse(row["hints"]["soften"])

    def test_a_formal_intent_suppresses(self):
        row = exp.policy(conflicted(), {"trust": 0.7, "closeness": 0.8},
                         intent="formal")
        self.assertEqual(row["mode"], "suppress")

    def test_relationship_stage_decides_mask_or_leak(self):
        model = conflicted()
        thin = exp.policy(model, {"trust": 0.2, "closeness": 0.3})
        close = exp.policy(model, {"trust": 0.7, "closeness": 0.8})
        self.assertEqual((thin["mode"], close["mode"]), ("mask", "leak"))
        self.assertNotEqual(thin["hints"], close["hints"])

    def test_hints_are_a_tendency_only(self):
        for mode in exp.MODES:
            hints = exp.HINTS[mode]
            self.assertEqual(sorted(hints), ["explain", "modifier",
                                             "sentence", "soften"])
            self.assertIn(hints["sentence"], ("short", "medium", "long"))
            self.assertIn(hints["modifier"], ("sparse", "normal", "dense"))
            self.assertIsInstance(hints["explain"], bool)
            self.assertIsInstance(hints["soften"], bool)

    def test_render_is_short_and_carries_no_numbers(self):
        for mode in exp.MODES:
            lines = exp.render({"enabled": True, "mode": mode,
                                "hints": exp.HINTS[mode]})
            self.assertLessEqual(len(lines), 2)
            blob = "".join(lines)
            self.assertIsNone(re.search(r"\d", blob))     # no value leaks out
            for axis in dim.DIMS:
                self.assertNotIn(axis, blob)

    def test_policy_never_mutates_the_model(self):
        model = conflicted()
        before = copy.deepcopy(model)
        exp.policy(model, {"trust": 0.2, "closeness": 0.3})
        exp.render(exp.policy(model, {"trust": 0.2, "closeness": 0.3}))
        self.assertEqual(model, before)


class MergeExtraTest(unittest.TestCase):
    """The expression rows go through batch_d's prompt_extra, not a new seam."""

    def base(self):
        return {"schema": 1, "enabled": True, "tone": {"tendency": "reply"},
                "length": {"target": 12, "max_chars": 40}, "initiative": 0.5,
                "avoid": ["说教"], "sources": ["expr_tone"],
                "hints": [{"source": "expr_tone", "text": "先接住情绪",
                           "chars": 6}],
                "budget_chars": exp.MERGE_BUDGET_CHARS}

    def test_merge_keeps_the_base_and_appends_the_policy_rows(self):
        row = exp.policy(conflicted(), {"trust": 0.2, "closeness": 0.3})
        merged = exp.merge_extra(self.base(), row)
        self.assertEqual(merged["tone"], {"tendency": "reply"})
        self.assertEqual(merged["length"]["target"], 12)
        self.assertEqual(merged["avoid"], ["说教"])
        self.assertIn("expr_tone", merged["sources"])
        self.assertIn("expression_policy", merged["sources"])
        self.assertEqual(merged["hints"][0]["source"], "expr_tone")
        rows = [item for item in merged["hints"]
                if item["source"] == "expression_policy"]
        self.assertEqual([item["text"] for item in rows],
                         exp.render(row))
        self.assertEqual(merged["expression_policy"]["mode"], "mask")

    def test_merge_is_idempotent_and_bounded(self):
        row = exp.policy(conflicted(), {"trust": 0.2, "closeness": 0.3})
        once = exp.merge_extra(self.base(), row)
        twice = exp.merge_extra(once, row)
        self.assertEqual(len(once["hints"]), len(twice["hints"]))
        full = self.base()
        full["hints"] = [{"source": "filler", "text": "x" * 40, "chars": 40}
                         for _ in range(exp.MERGE_HINT_LIMIT)]
        merged = exp.merge_extra(full, row)
        self.assertEqual(len(merged["hints"]), exp.MERGE_HINT_LIMIT)
        self.assertLessEqual(sum(item["chars"] for item in merged["hints"]),
                             exp.MERGE_BUDGET_CHARS)

    def test_authentic_policy_adds_no_row(self):
        row = exp.policy(dim.initial(NOW), {"trust": 0.2, "closeness": 0.3})
        merged = exp.merge_extra(self.base(), row)
        self.assertEqual([item["text"] for item in merged["hints"]],
                         ["先接住情绪"])


class ExpressionPipelineTest(unittest.TestCase):
    """prompt_extra seam + /state.expression_policy + the off switch."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self.store.mkdir(parents=True, exist_ok=True)
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")
        self._saved = {key: os.environ.pop(key, None)
                       for key in ("BIOCORE_EXPRESSION_POLICY",)}

    def tearDown(self):
        self.tmp.cleanup()
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def relationship(self, trust, closeness):
        (self.store / "relationship.json").write_text(
            json.dumps({"relationship": {"trust": trust,
                                         "closeness": closeness,
                                         "conflict": 0.0}}), encoding="utf-8")

    def turn(self, deltas=None, **extra):
        payload = {"session_id": "s1", "store": str(self.store),
                   "user_text": "在吗"}
        payload.update(extra)
        start = pl.dispatch("turn_start", payload)
        if deltas is not None:
            end_payload = {"session_id": "s1", "store": str(self.store),
                           "assistant_text": "嗯。",
                           "dimension_deltas": deltas}
            end_payload.update({key: value for key, value in extra.items()
                                if key in ("expression_policy",)})
            pl.dispatch("turn_end", end_payload)
            start = pl.dispatch("turn_start", payload)
        return start

    def policy_line(self, caption):
        return [line for line in str(caption).splitlines()
                if line.strip() in ("- " + MASK_LINE, "- " + LEAK_LINE,
                                    "- " + SUPPRESS_LINE)]

    CONFLICT = {"explicit": {"v": 0.5}, "implicit": {"v": -0.4}}

    def test_state_exposes_mode_hints_sources(self):
        self.relationship(0.2, 0.3)
        self.turn(deltas=self.CONFLICT)
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store)})["state"]
        row = shown["expression_policy"]
        self.assertEqual(row["mode"], "mask")
        self.assertEqual(sorted(row["hints"]), ["explain", "modifier",
                                                "sentence", "soften"])
        self.assertIn("relationship", row["sources"])
        self.assertTrue(row["enabled"])

    def test_prompt_block_carries_one_short_policy_line(self):
        self.relationship(0.2, 0.3)
        out = self.turn(deltas=self.CONFLICT)
        caption = out["prompt_block"]
        self.assertEqual(self.policy_line(caption), ["- " + MASK_LINE])
        self.assertNotIn("0.4", caption)          # the readout stays inside
        self.assertNotIn("0.5", caption)
        state = json.loads((self.store / "sessions" / "s1" / "state.json")
                           .read_text(encoding="utf-8"))
        block = pl.prompt_block({"state": state, "switches": {},
                                 "store": str(self.store)})
        self.assertEqual(block["sections"]["expression_policy"]["mode"], "mask")
        self.assertIn("- " + MASK_LINE, block["text"])

    def test_close_relationship_leaks_into_the_same_seam(self):
        self.relationship(0.7, 0.8)
        out = self.turn(deltas=self.CONFLICT)
        self.assertEqual(self.policy_line(out["prompt_block"]),
                         ["- " + LEAK_LINE])

    def test_authentic_adds_nothing_to_the_prompt(self):
        self.relationship(0.2, 0.3)
        out = self.turn()
        self.assertEqual(self.policy_line(out["prompt_block"]), [])
        policy = (pl.prompt_block({"state": {}, "switches": {}})
                  ["sections"].get("expression_policy") or {})
        self.assertEqual(policy.get("mode"), "authentic")

    def test_switch_off_returns_the_old_prompt(self):
        self.relationship(0.2, 0.3)
        (self.store / "flags.json").write_text(
            json.dumps({"expression_policy": False}), encoding="utf-8")
        out = self.turn(deltas=self.CONFLICT)
        self.assertEqual(self.policy_line(out["prompt_block"]), [])
        shown = pl.dispatch("state", {"session_id": "s1",
                                      "store": str(self.store)})["state"]
        self.assertNotIn("expression_policy", shown)

    def test_payload_flag_wins_over_the_default(self):
        self.relationship(0.2, 0.3)
        out = self.turn(deltas=self.CONFLICT, expression_policy=False)
        self.assertEqual(self.policy_line(out["prompt_block"]), [])
