# -*- coding: utf-8 -*-
"""task-238 (batch D): the twenty-nine motivation / expression modules.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_batch_d.py"
"""
import copy
import json
import os
import unittest

from biocore_runtime import batch_d as bd
from biocore_model import expr_intent


NOW = 1700000000.0
TAG = ('{"dims":{"goal":-0.2,"blame":0.5,"hit":0.4,"involve":0.7},'
       '"situation":{"challenge":0.1,"praise":0.0,"hurt":0.6},'
       '"why":"被冷落","c":0.8}')


def state():
    return {"core": {"v": -0.2, "a": 0.6, "stress": 0.55, "social": 0.45,
                     "energy": 0.5},
            "relationship": {"trust": 0.55, "closeness": 0.6, "conflict": 0.1,
                             "attachment_style": "secure"},
            "needs": {"belonging": 0.5, "self_esteem": 0.55, "control": 0.6,
                      "meaningful_existence": 0.55}}


def payload(**extra):
    data = {"user_text": "在吗？",
            "assistant_text": "嗯，我在。今天有点累，先说一句。",
            "emotion": "neutral", "intensity": 0.5, "now": NOW,
            "length_target": 12, "length_max": 40,
            "silence_hours": 3.0,
            "llm_feedback": {"valence_delta": 0.05, "confidence": 0.8},
            "user_meta": {"responded": True, "response_gap_s": 120},
            "schedule_items": [{"id": "s1", "due_ts": NOW + 60,
                                "entity": "小林"}],
            "voice_entries": [], "recent_voice": [],
            "recent_turns": [{"role": "user", "text": "在吗", "ts": NOW - 60}]}
    data.update(extra)
    return data


def turn(phase, **extra):
    return bd.apply_turn(state(), phase, payload(**extra))


class SwitchTest(unittest.TestCase):
    def test_default_is_on(self):
        self.assertTrue(bd.enabled())
        self.assertTrue(bd.enabled({}, env={}))

    def test_payload_and_env_can_turn_it_off(self):
        self.assertFalse(bd.enabled({"batch_d": False}))
        self.assertFalse(bd.enabled({"switches": {"batch_d": False}}))
        self.assertFalse(bd.enabled({}, env={"BIOCORE_BATCH_D": "0"}))

    def test_bad_phase_is_refused(self):
        out = bd.apply_turn(state(), "recall", payload())
        self.assertFalse(out["enabled"])
        self.assertEqual(out["reason"], "bad_phase")

    def test_twenty_nine_modules_declared_and_available(self):
        self.assertEqual(len(bd.MODULES), 29)
        out = turn("turn_start")
        self.assertEqual(out["counts"]["modules"], 29)
        self.assertEqual(out["counts"]["available"], 29)
        self.assertEqual(set(out["modules"]), set(bd.MODULES))

    def test_proactive_sending_stays_off_by_default(self):
        self.assertFalse(turn("turn_start")["proactive_allowed"])
        asked = bd.apply_turn(state(), "turn_start",
                              payload(proactive_allowed=True))
        self.assertFalse(asked["proactive_allowed"])  # still needs the send gate
        both = bd.apply_turn(state(), "turn_start",
                             payload(proactive_allowed=True,
                                     proactive_send=True))
        self.assertTrue(both["proactive_allowed"])


class StartTest(unittest.TestCase):
    def test_autonomy_read_has_drive_and_theta(self):
        autonomy = turn("turn_start")["reads"]["autonomy"]
        self.assertIn("parts", autonomy)
        self.assertIn("drive", autonomy)
        self.assertGreaterEqual(autonomy["theta"], 0.0)
        self.assertIn(autonomy["mode"], ("drive", "hold", "repair", "quiet"))

    def test_expression_intent_comes_from_expr_intent(self):
        expression = turn("turn_start")["reads"]["expression"]
        self.assertIn(expression["intent"], list(expr_intent.BASE))
        self.assertTrue(expression["tone"])

    def test_silence_decision_is_carried(self):
        quiet = bd.apply_turn(state(), "turn_start",
                              payload(intensity=1.0, emotion="sad"))
        expression = quiet["reads"]["expression"]
        self.assertIn("exit", expression)
        self.assertTrue(expression["should_reply"])

    def test_granularity_reads_a_primary_label(self):
        granularity = turn("turn_start")["reads"]["expression"]["granularity"]
        self.assertTrue(granularity)
        self.assertIn("primary", granularity)

    def test_scheduler_and_voice_bank_read(self):
        schedule = turn("turn_start")["reads"]["schedule"]
        self.assertEqual(schedule["due"], 1)
        self.assertEqual(schedule["voice_available"], 0)
        self.assertEqual(schedule["pick"]["id"], "s1")

    def test_char_limits_are_carried(self):
        limits = turn("turn_start")["reads"]["expression"]["limits"]
        self.assertEqual(limits["target"], 12)
        self.assertEqual(limits["max_chars"], 40)

    def test_start_state_deltas_carry_autonomy_and_expression(self):
        out = turn("turn_start")
        self.assertIn("autonomy", out["state_deltas"])
        self.assertIn("expression", out["state_deltas"])
        self.assertIn("should_reply", out["state_deltas"]["expression"])


class EndTest(unittest.TestCase):
    def test_state_tag_is_parsed_and_stripped(self):
        out = turn("turn_end", assistant_text="嗯，我在。\n" + TAG)
        tag = out["state_deltas"]["state_tag"]
        self.assertAlmostEqual(tag["dims"]["hit"], 0.4, places=4)
        self.assertEqual(tag["confidence"], 0.8)
        self.assertEqual(out["state_deltas"]["reply"]["chars"], len("嗯，我在。"))

    def test_guard_and_split_are_reported(self):
        out = turn("turn_end")
        reply = out["state_deltas"]["reply"]
        self.assertEqual(reply["segments"], 1)
        self.assertIsInstance(reply["guard_hits"], list)
        many = bd.apply_turn(state(), "turn_end",
                             payload(assistant_text="嗯。我在。\n先说一句。"))
        self.assertGreaterEqual(many["state_deltas"]["reply"]["segments"], 1)

    def test_llm_feedback_becomes_bounded_field_deltas(self):
        out = turn("turn_end")
        self.assertGreater(out["field_deltas"].get("v", 0.0), 0.0)
        for name, value in out["field_deltas"].items():
            self.assertLessEqual(abs(value), bd.CAPS[name] + 1e-9)

    def test_user_feedback_is_recorded(self):
        feedback = turn("turn_end")["state_deltas"]["feedback"]
        self.assertIn("user", feedback)
        self.assertAlmostEqual(feedback["user"]["deltas"]["v"], 0.02, places=4)

    def test_autonomy_accumulator_is_written_once_per_tick(self):
        first = turn("turn_end")
        acc = first["state_deltas"]["autonomy_acc"]
        self.assertIn("last_apply_ts", acc)
        again = bd.apply_turn(dict(state(), autonomy_acc=acc), "turn_end",
                              payload())
        self.assertEqual(again["state_deltas"]["autonomy_acc"]["last_apply_ts"],
                         acc["last_apply_ts"])

    def test_template_render_and_topic_control(self):
        out = bd.apply_turn(state(), "turn_end",
                            payload(reply_template="你好 {{name}}",
                                    template_vars={"name": "小林"}))
        self.assertGreater(out["state_deltas"]["reply"]["template_chars"], 0)
        self.assertIn("topic_control", out["state_deltas"])

    def test_reply_limit_tokens_are_read(self):
        out = bd.apply_turn(state(), "turn_end",
                            payload(reply_limit={"max_tokens": 800}))
        self.assertEqual(out["reads"]["expression"]["limits"]["max_tokens"], 800)


class PromptExtraTest(unittest.TestCase):
    def test_extra_is_bounded_and_prompt_free(self):
        extra = bd.prompt_extra(state(), payload(gap_seconds=3600))
        self.assertTrue(extra["enabled"])
        self.assertLessEqual(len(extra["hints"]), bd.HINT_LIMIT)
        self.assertLessEqual(sum(row["chars"] for row in extra["hints"]),
                             bd.BUDGET_CHARS)
        blob = json.dumps(extra, ensure_ascii=False).lower()
        # hints are a list of small rows, never one assembled prompt
        self.assertNotIn("prompt_block", blob)
        self.assertIsInstance(extra["hints"], list)
        self.assertNotIn("joined", extra)

    def test_extra_carries_tone_length_initiative(self):
        extra = bd.prompt_extra(state(), payload(gap_seconds=7200))
        self.assertIn("tendency", extra["tone"])
        self.assertEqual(extra["length"]["target"], 12)
        self.assertGreaterEqual(extra["initiative"], 0.0)
        self.assertLessEqual(extra["initiative"], 1.0)
        self.assertIn("expr_tone", extra["sources"])

    def test_gap_hint_uses_hours(self):
        extra = bd.prompt_extra(state(), payload(gap_seconds=3600))
        gap = [row for row in extra["hints"] if row["source"] == "proactive_context"]
        self.assertTrue(gap)
        self.assertIn("1 小时", gap[0]["text"])

    def test_extra_off_switch(self):
        extra = bd.prompt_extra(state(), payload(batch_d=False))
        self.assertFalse(extra["enabled"])
        self.assertEqual(extra["hints"], [])


class ContractTest(unittest.TestCase):
    def test_state_is_never_mutated(self):
        before = state()
        snapshot = copy.deepcopy(before)
        bd.apply_turn(before, "turn_start", payload())
        bd.apply_turn(before, "turn_end", payload())
        bd.prompt_extra(before, payload())
        self.assertEqual(json.dumps(before, sort_keys=True),
                         json.dumps(snapshot, sort_keys=True))

    def test_deterministic_numbers(self):
        first = turn("turn_end")
        second = turn("turn_end")
        for out in (first, second):
            out.pop("ts", None)
        self.assertEqual(json.dumps(first, sort_keys=True, ensure_ascii=False),
                         json.dumps(second, sort_keys=True, ensure_ascii=False))

    def test_json_safe_and_no_prompt(self):
        for phase in ("turn_start", "turn_end"):
            out = turn(phase)
            json.dumps(out, ensure_ascii=False)
            self.assertNotIn("prompt_block", out)

    def test_missing_payload_degrades_quietly(self):
        out = bd.apply_turn(state(), "turn_start", {})
        self.assertTrue(out["enabled"])
        self.assertIn("autonomy", out["reads"])
        extra = bd.prompt_extra(state(), {})
        self.assertTrue(extra["enabled"])


if __name__ == "__main__":
    unittest.main()
