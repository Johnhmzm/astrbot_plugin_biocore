# -*- coding: utf-8 -*-
"""PIPE-4 mode tests: shadow/active switching, prompt output, fallback, safety."""
import json
import tempfile
import unittest
from pathlib import Path

from biocore_model import pipeline as pl
from biocore_model import pipeline_api as pa
from biocore_model import runtime as rt


class FakePlugin:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)


class FakeEvent:
    def __init__(self, text="", umo="umo-7", sender="u-7"):
        self.message_str = text
        self.unified_msg_origin = umo
        self._sender = sender

    def get_sender_id(self):
        return self._sender


class FakeCore:
    def __init__(self):
        self._snapshot = {"emotion": "sadness", "intensity": 0.6, "self_esteem": 0.4,
                          "regulation": "suppress", "v": 0.1, "a": 0.4, "stress": 0.3}
        self.observed = []
        self.loaded = []

    def snapshot(self):
        return dict(self._snapshot)

    def observe(self, text, embedding=None):
        self.observed.append(text)

    def load_state(self, state):
        self.loaded.append(dict(state))


def make_ctx(text="今天好累", core=None, meta=None):
    return rt.make_request_ctx(plugin=None, event=FakeEvent(text),
                               core=core if core is not None else FakeCore(),
                               text=text, memory=[], now=1000.0, meta=meta or {})


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.plugin = FakePlugin(self.tmp)
        rt.reset_mode()
        rt.apply_switches({})
        rt.reset_pipeline()
        pa.reset_boot()

    def tearDown(self):
        rt.reset_mode()
        rt.apply_switches({})
        rt.reset_pipeline()
        pa.reset_boot()
        self._tmp.cleanup()


class ModeTest(Base):
    def test_default_mode_is_shadow(self):
        self.assertEqual(rt.MODE_DEFAULT, "shadow")
        self.assertEqual(rt.get_mode(), "shadow")

    def test_apply_mode_switches_without_restart(self):
        before = rt.get_pipeline()
        self.assertEqual(rt.apply_mode("active"), "active")
        self.assertEqual(rt.get_mode(), "active")
        self.assertIs(rt.get_pipeline(), before)
        self.assertEqual(rt.apply_mode("shadow"), "shadow")

    def test_apply_mode_invalid_rejected(self):
        with self.assertRaises(ValueError):
            rt.apply_mode("turbo")
        self.assertEqual(rt.get_mode(), "shadow")

    def test_save_mode_persists_to_ui_settings(self):
        saved = pa.save_mode(self.plugin, "active")
        self.assertTrue(saved["ok"])
        data = json.loads((self.tmp / "ui_settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["autonomy"]["pipeline_mode"], "active")
        self.assertEqual(rt.get_mode(), "active")

    def test_load_mode_default_and_roundtrip(self):
        self.assertEqual(pa.load_mode(self.plugin), "shadow")
        pa.save_mode(self.plugin, "active")
        self.assertEqual(pa.load_mode(self.plugin), "active")

    def test_boot_applies_persisted_active_mode(self):
        pa.save_mode(self.plugin, "active")
        rt.reset_mode()
        pa.reset_boot()
        other = FakePlugin(self.tmp)
        self.assertTrue(pa.boot(other))
        self.assertEqual(rt.get_mode(), "active")

    def test_payload_mode_get_and_set(self):
        self.assertEqual(pa.payload_mode(self.plugin)["mode"], "shadow")
        result = pa.payload_mode(self.plugin, "active")
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "active")
        self.assertEqual(pa.payload_mode(self.plugin)["mode"], "active")

    def test_payload_mode_invalid(self):
        result = pa.payload_mode(self.plugin, "loud")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "invalid_mode")


class PromptTest(Base):
    def test_shadow_run_reply_has_no_prompt_keys(self):
        out = rt.run_reply(make_ctx())
        self.assertNotIn("prompt_system", out)
        self.assertNotIn("prompt_user", out)
        self.assertIn("trace", out)

    def test_active_run_prompt_structure(self):
        rt.apply_mode("active")
        out = rt.run_prompt(make_ctx())
        self.assertIsNotNone(out)
        for key in ("prompt_system", "prompt_user", "trace", "order"):
            self.assertIn(key, out)
        self.assertTrue(out["prompt_user"])
        self.assertEqual(len(out["trace"]["stages"]), 11)

    def test_active_prompt_contains_state_and_protocol(self):
        rt.apply_mode("active")
        out = rt.run_prompt(make_ctx())
        self.assertIn("sadness", out["prompt_user"])
        self.assertIn("【输出格式 · 必须遵守】", out["prompt_system"])
        self.assertNotIn("【输出格式", out["prompt_user"])

    def test_active_prompt_uses_persona_opts(self):
        rt.apply_mode("active")
        out = rt.run_prompt(make_ctx(meta={"template_opts": {
            "persona": "你是小助手", "speak_style": "口语"}}))
        self.assertIn("小助手", out["prompt_system"])
        self.assertIn("口语", out["prompt_system"])

    def test_active_failure_returns_none(self):
        rt.apply_mode("active")
        bad = pl.Pipeline()
        bad.register(pl.Stage("perceive", lambda ctx: 1 / 0))
        self.assertIsNone(rt.run_prompt(make_ctx(), pipeline=bad))

    def test_active_empty_ctx_returns_none(self):
        rt.apply_mode("active")
        self.assertIsNone(rt.run_prompt(rt.make_request_ctx()))

    def test_mode_switch_routes_behavior_in_one_process(self):
        shadow = rt.run_reply(make_ctx())
        self.assertNotIn("prompt_user", shadow)
        rt.apply_mode("active")
        active = rt.run_prompt(make_ctx())
        self.assertTrue(active and active["prompt_user"])
        rt.apply_mode("shadow")
        again = rt.run_reply(make_ctx())
        self.assertNotIn("prompt_user", again)


    def test_active_run_reply_returns_prompt_payload(self):
        rt.apply_mode("active")
        out = rt.run_reply(make_ctx())
        for key in ("prompt_system", "prompt_user", "trace"):
            self.assertIn(key, out)
        self.assertTrue(out["prompt_user"])

    def test_active_run_reply_failure_returns_empty_dict(self):
        rt.apply_mode("active")
        bad = pl.Pipeline()
        bad.register(pl.Stage("perceive", lambda ctx: 1 / 0))
        self.assertEqual(rt.run_reply(make_ctx(), pipeline=bad), {})


class SafetyTest(Base):
    def test_shadow_does_not_write_core(self):
        core = FakeCore()
        rt.run_reply(make_ctx(core=core, meta={"observe_core": True}))
        self.assertEqual(core.observed, [])
        self.assertEqual(core.loaded, [])

    def test_active_observe_core_default_false(self):
        rt.apply_mode("active")
        core = FakeCore()
        out = rt.run_prompt(make_ctx(core=core))
        self.assertIsNotNone(out)
        self.assertEqual(core.observed, [])
        self.assertEqual(core.loaded, [])

    def test_active_observe_core_true_calls_observe(self):
        rt.apply_mode("active")
        core = FakeCore()
        out = rt.run_prompt(make_ctx(core=core, meta={"observe_core": True}))
        self.assertIsNotNone(out)
        self.assertEqual(core.observed, ["今天好累"])
        self.assertEqual(core.loaded, [])

    def test_trace_has_stage_ms(self):
        rt.apply_mode("active")
        out = rt.run_prompt(make_ctx())
        stages = out["trace"]["stages"]
        self.assertEqual([row["name"] for row in stages],
                         ["perceive", "memory", "bio", "decide", "expr_state",
                          "expr_tone", "expr_intent", "think", "parse",
                          "feedback", "present"])
        for row in stages:
            self.assertIsInstance(row["ms"], float)
            self.assertGreaterEqual(row["ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
