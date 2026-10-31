# -*- coding: utf-8 -*-
"""PIPE-2 stage tests: pure ctx-in/ctx-out wrappers, no main, no files."""
import random
import unittest

from biocore_model import pipeline as pl
from biocore_model import stages as st


class FakeEvent:
    def __init__(self, text="", umo="umo-1", sender="u-1"):
        self.message_str = text
        self.unified_msg_origin = umo
        self._sender = sender

    def get_sender_id(self):
        return self._sender


class FakeCore:
    def __init__(self, snapshot=None):
        self._snapshot = dict(snapshot or {
            "emotion": "sadness", "intensity": 0.6, "self_esteem": 0.4,
            "regulation": "suppress", "v": 0.2, "a": 0.4, "stress": 0.3,
            "social_pain": {"value": 0.1},
        })
        self.observed = []
        self.loaded = []

    def snapshot(self):
        return dict(self._snapshot)

    def observe(self, text, embedding=None):
        self.observed.append((text, embedding))

    def load_state(self, state):
        self.loaded.append(dict(state))
        self._snapshot.update(state)


def ctx(**kw):
    base = {"core": None, "meta": {"now": 1000.0}, "text": ""}
    base.update(kw)
    return base


class PerceiveTest(unittest.TestCase):
    def test_extracts_text_user_umo(self):
        stage = st.perceive()
        out = stage.run(ctx(event=FakeEvent("你好")))
        self.assertEqual(out["text"], "你好")
        self.assertEqual(out["user"], "u-1")
        self.assertEqual(out["umo"], "umo-1")
        self.assertTrue(out["meta"]["perceive"]["has_text"])

    def test_empty_text_marks_skip(self):
        out = st.perceive().run(ctx(event=FakeEvent("")))
        self.assertEqual(out["text"], "")
        self.assertIn({"stage": "perceive", "reason": "empty_text"}, out["meta"]["skipped"])


class MemoryTest(unittest.TestCase):
    def test_selects_by_strength_and_marks_skipped(self):
        entries = [{"id": "a", "strength": 0.9}, {"id": "b", "strength": 0.05},
                   {"id": "c", "strength": 0.7}]
        out = st.memory().run(ctx(memory=entries, meta={"now": 10.0}))
        selected = [row["id"] for row in out["memory_selected"]]
        self.assertNotIn("b", selected)
        self.assertIn("b", out["memory_skipped"])
        self.assertGreaterEqual(len(selected), 1)

    def test_no_entries_skip(self):
        out = st.memory().run(ctx(memory=[]))
        self.assertEqual(out["memory_selected"], [])
        self.assertEqual(out["meta"]["skipped"][0]["reason"], "no_entries")

    def test_touch_does_not_mutate_input(self):
        entries = [{"id": "a", "strength": 0.5}]
        out = st.memory().run(ctx(memory=entries, meta={"now": 10.0, "touch_id": "a"}))
        self.assertEqual(entries[0]["strength"], 0.5)
        self.assertGreater(out["memory_entries"][0]["strength"], 0.5)


class BioTest(unittest.TestCase):
    def test_whitelisted_deltas_go_through_guard(self):
        core = FakeCore()
        out = st.bio().run(ctx(core=core, deltas={"v": 0.05, "stress": 0.05}))
        self.assertAlmostEqual(out["bio_state"]["v"], 0.25, places=3)
        self.assertIn("v", out["bio"]["accepted"])
        self.assertEqual(core.loaded, [])

    def test_non_whitelisted_delta_rejected(self):
        out = st.bio().run(ctx(core=FakeCore(), deltas={"nope": 0.5}))
        self.assertEqual(out["bio"]["accepted"], [])
        self.assertTrue(out["bio"]["rejected"])

    def test_social_pain_event_updates_nested_state(self):
        out = st.bio().run(ctx(core=FakeCore(), meta={"now": 10.0, "social_event": "ignored"}))
        self.assertGreater(out["bio_state"]["social_pain"]["value"], 0.1)

    def test_observe_only_when_enabled(self):
        core = FakeCore()
        st.bio().run(ctx(core=core, text="hi"))
        self.assertEqual(core.observed, [])
        st.bio().run(ctx(core=core, text="hi", meta={"now": 1.0, "observe": True}))
        self.assertEqual(len(core.observed), 1)

    def test_write_core_optional_bridge(self):
        core = FakeCore()
        st.bio().run(ctx(core=core, deltas={"v": 0.05},
                         meta={"now": 1.0, "write_core": True}))
        self.assertEqual(len(core.loaded), 1)


class DecideTest(unittest.TestCase):
    def test_text_needs_reply(self):
        out = st.decide().run(ctx(text="hi"))
        self.assertTrue(out["decision"]["reply"])

    def test_empty_text_skips(self):
        out = st.decide().run(ctx(text=""))
        self.assertFalse(out["decision"]["reply"])
        self.assertEqual(out["meta"]["skipped"][0]["stage"], "decide")


class ExprTest(unittest.TestCase):
    def test_state_block_renders(self):
        core = FakeCore()
        out = st.expr_state().run(ctx(core=core))
        self.assertTrue(out["state_text"])
        self.assertIn("emotion", out["meta"]["expr_state"]["parts"])

    def test_state_missing_is_skip(self):
        out = st.expr_state().run(ctx())
        self.assertEqual(out["state_text"], "")
        self.assertEqual(out["meta"]["skipped"][0]["reason"], "no_state")

    def test_tone_from_emotion(self):
        out = st.expr_tone().run(ctx(core=FakeCore()))
        self.assertEqual(out["tone"]["tendency"], "sadness")
        self.assertLess(out["tone"]["chars_mult"], 1.0)

    def test_tone_unknown_falls_back_to_calm(self):
        out = st.expr_tone().run(ctx(state={"emotion": "??"}))
        self.assertEqual(out["tone"]["tendency"], "calm")

    def test_intent_seeded_is_deterministic(self):
        candidates = [{"kind": "question"}, {"kind": "share_mood"}]
        def pick():
            return st.expr_intent().run(ctx(meta={"now": 5.0, "rng": random.Random(3),
                                                  "intent_candidates": candidates}))
        self.assertEqual(pick()["intent"]["kind"], pick()["intent"]["kind"])

    def test_intent_without_candidates_skips(self):
        out = st.expr_intent().run(ctx())
        self.assertEqual(out["intent"]["kind"], "")
        self.assertEqual(out["meta"]["skipped"][0]["reason"], "no_candidates")


class ThinkParseFeedbackTest(unittest.TestCase):
    def test_think_without_llm_is_noop(self):
        out = st.think().run(ctx())
        self.assertEqual(out["llm_raw"], "")
        self.assertEqual(out["meta"]["skipped"][0]["reason"], "no_llm")

    def test_think_calls_injected_llm(self):
        calls = []
        def llm(prompt):
            calls.append(prompt)
            return "我在。"
        out = st.think().run(ctx(llm=llm))
        self.assertEqual(out["llm_raw"], "我在。")
        self.assertEqual(len(calls), 1)

    def test_think_llm_error_is_contained(self):
        def boom(prompt):
            raise RuntimeError("provider down")
        out = st.think().run(ctx(llm=boom))
        self.assertEqual(out["llm_raw"], "")
        self.assertIn("think", [row["stage"] for row in out["meta"]["skipped"]])

    def test_parse_strips_hidden_tag(self):
        out = st.parse().run(ctx(llm_raw='你好。<bc>{"e":"joy","i":0.6}</bc>'))
        self.assertEqual(out["reply"], "你好。")
        self.assertNotIn("<bc>", out["reply"])

    def test_parse_without_raw_skips(self):
        out = st.parse().run(ctx(llm_raw=""))
        self.assertEqual(out["meta"]["skipped"][0]["reason"], "no_llm_raw")

    def test_feedback_accepts_whitelisted(self):
        out = st.feedback().run(ctx(parsed={"v": 0.05}, state={"v": 0.5}))
        self.assertIn("v", out["feedback"]["accepted"])
        self.assertAlmostEqual(out["bio_state"]["v"], 0.55, places=3)

    def test_feedback_rejects_unknown_field(self):
        out = st.feedback().run(ctx(parsed={"nope": 1.0}, state={"v": 0.5}))
        self.assertEqual(out["feedback"]["accepted"], {})
        self.assertTrue(out["feedback"]["rejected"])


class PresentTest(unittest.TestCase):
    def test_sanitizes_and_splits(self):
        out = st.present().run(ctx(reply='第一句。第二句。<bc>{"e":"joy"}</bc>'))
        self.assertNotIn("<bc>", out["reply"])
        self.assertIsInstance(out["segments"], list)
        self.assertTrue(out["reply"])

    def test_empty_reply_skips(self):
        out = st.present().run(ctx(reply=""))
        self.assertEqual(out["reply"], "")
        self.assertEqual(out["meta"]["skipped"][0]["reason"], "no_reply")


class ContractTest(unittest.TestCase):
    def test_all_stages_follow_contract(self):
        rows = st.build_stages()
        self.assertEqual([row.name for row in rows], list(st.STAGE_NAMES))
        for stage in rows:
            self.assertIsInstance(stage, pl.Stage)
            for attr in ("name", "required", "enabled", "timeout_ms", "on_error", "run"):
                self.assertTrue(hasattr(stage, attr), attr)


if __name__ == "__main__":
    unittest.main()
