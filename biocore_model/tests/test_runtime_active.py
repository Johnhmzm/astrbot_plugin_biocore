# -*- coding: utf-8 -*-
"""PIPE-2 active-mode tests: run_active payload, fallback, ctx enrichment.

Covers: prompt non-empty / empty-dict fallback / shadow untouched / trace
fields / snapshot+relationship enrichment / motive+silence+intent+tone.
"""
import json
import os
import tempfile
import unittest

from biocore_model import expr_tone as _tone
from biocore_model import pipeline as pl
from biocore_model import runtime as rt


class FakeEvent:
    def __init__(self, text="你好", umo="umo-1", sender="u-1"):
        self.message_str = text
        self.unified_msg_origin = umo
        self._sender = sender

    def get_sender_id(self):
        return self._sender


class FakeCore:
    def __init__(self):
        self._snapshot = {
            "emotion": "calm", "intensity": 0.5, "v": 0.1, "a": 0.2, "d": 0.5,
            "social": 0.5, "stress": 0.1, "energy": 0.6, "trust": 0.5,
            "self_esteem": 0.7,
            "labels": {"emotion": "calm", "need": "talk"},
            "spectrum_probs": [{"name": "calmness", "p": 0.5}],
        }

    def snapshot(self):
        return dict(self._snapshot)


class FakePlugin:
    def __init__(self, data_dir=None, persona_text=""):
        self.data_dir = data_dir
        self.persona_text = persona_text

    def _relationship_of(self, user):
        return {"state": {"closeness": 0.6, "trust": 0.5}}


class BoomPipeline(pl.Pipeline):
    def run(self, ctx=None, start=None):
        raise RuntimeError("active boom")


def make_ctx(text="你好", core=None, plugin=None, now=1000.0, **meta):
    return rt.make_request_ctx(plugin=plugin or FakePlugin(),
                               event=FakeEvent(text), core=core or FakeCore(),
                               text=text, now=now, meta=dict(meta))


class RunActiveTest(unittest.TestCase):
    def setUp(self):
        rt.reset_mode()
        rt.reset_pipeline()

    def test_active_returns_prompt_payload(self):
        out = rt.run_active(make_ctx())
        self.assertIsInstance(out, dict)
        self.assertTrue(out.get("prompt_user") or out.get("prompt_system"))
        self.assertIsInstance(out.get("prompt_system"), str)
        self.assertIsInstance(out.get("prompt_user"), str)
        self.assertIsInstance(out.get("trace"), dict)

    def test_active_trace_fields(self):
        out = rt.run_active(make_ctx())
        trace = out["trace"]
        self.assertIn("stages", trace)
        self.assertIn("ring", trace)
        self.assertEqual(trace["runtime"]["schema"], rt.SCHEMA)
        self.assertEqual(trace["runtime"]["mode"], "active")
        self.assertIn("memory", trace["runtime"]["switches"])
        self.assertEqual([row["name"] for row in trace["stages"]],
                         list(rt.get_pipeline().names()))

    def test_active_failure_returns_empty_dict(self):
        self.assertEqual(rt.run_active(make_ctx(), pipeline=BoomPipeline()), {})

    def test_active_garbage_ctx_never_raises(self):
        self.assertIsInstance(rt.run_active(None), dict)
        self.assertIsInstance(rt.run_active({"meta": "bad"}), dict)

    def test_active_sets_active_meta(self):
        ctx = make_ctx()
        out = rt.run_active(ctx)
        self.assertTrue(out)
        self.assertEqual(ctx["meta"]["pipeline_mode"], "active")
        self.assertFalse(ctx["meta"]["shadow"])


class ShadowUnchangedTest(unittest.TestCase):
    def setUp(self):
        rt.reset_mode()
        rt.reset_pipeline()

    def test_shadow_run_reply_still_returns_ctx(self):
        ctx = make_ctx()
        out = rt.run_reply(ctx)
        self.assertIsInstance(out, dict)
        self.assertTrue(out["meta"]["shadow"])
        self.assertNotIn("prompt_system", out)

    def test_run_active_does_not_change_mode(self):
        rt.run_active(make_ctx())
        self.assertEqual(rt.get_mode(), "shadow")
        out = rt.run_reply(make_ctx(meta_llm=True))
        self.assertIsInstance(out, dict)
        self.assertIn("trace", out)
        self.assertNotIn("prompt_system", out)


class EnrichCtxTest(unittest.TestCase):
    def test_snapshot_and_relationship(self):
        core = FakeCore()
        plugin = FakePlugin()
        ctx = make_ctx(core=core, plugin=plugin)
        ctx["core"] = core
        ctx["plugin"] = plugin
        out = rt.enrich_ctx(ctx)
        self.assertEqual(out["state"]["emotion"], "calm")
        self.assertEqual(out["relationship"]["state"]["closeness"], 0.6)
        self.assertEqual(out["meta"]["relationship"], out["relationship"])

    def test_caller_fields_not_overwritten(self):
        ctx = make_ctx()
        ctx["state"] = {"emotion": "given"}
        ctx["relationship"] = {"state": {"closeness": 0.1}}
        ctx["intent"] = {"kind": "given"}
        out = rt.enrich_ctx(ctx)
        self.assertEqual(out["state"], {"emotion": "given"})
        self.assertEqual(out["relationship"]["state"]["closeness"], 0.1)
        self.assertEqual(out["intent"], {"kind": "given"})

    def test_motive_silence_intent_tone_from_accumulator(self):
        now = 1000000.0
        data = tempfile.mkdtemp(prefix="bc_active_")
        self.addCleanup(lambda: __import__("shutil").rmtree(data, True))
        with open(os.path.join(data, "ui_settings.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "autonomy": {"accumulator": {
                "V": 0.2, "theta": 0.55, "last_user_msg_ts": now - 7200.0,
                "intent": {"kind": "social_gap"}, "tone": {"text": "gentle"}}}}, fh)
        ctx = make_ctx(plugin=FakePlugin(data), now=now)
        out = rt.enrich_ctx(ctx)
        self.assertIsInstance(out.get("motive"), dict)
        self.assertIn("motive", out["motive"])
        self.assertIn("drift", out["motive"])
        self.assertEqual(out["silence"]["hours"], 2.0)
        self.assertEqual(out["intent"], {"kind": "social_gap"})
        self.assertEqual(out["tone"], {"text": "gentle"})


class LongPromptTest(unittest.TestCase):
    PERSONA = ("你是小灰，一只灰色羽毛的拟人小生物，喜欢安静地陪着对方，说话短、语气轻。" * 120)[:2636]

    def setUp(self):
        rt.reset_mode()
        rt.reset_pipeline()

    def _plugin(self, now=1000000.0):
        data = tempfile.mkdtemp(prefix="bc_active_long_")
        self.addCleanup(lambda: __import__("shutil").rmtree(data, True))
        with open(os.path.join(data, "ui_settings.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "autonomy": {"accumulator": {
                "V": 0.3, "theta": 0.55, "last_user_msg_ts": now - 7200.0,
                "intent": {"kind": "social_gap", "text_hint": "想接住情绪"},
                "tone": {"text": "先接住情绪，再谈事情"}}}}, fh)
        return FakePlugin(data, persona_text=self.PERSONA)

    def test_active_prompt_has_persona_state_gap_intent_tone_protocol(self):
        out = rt.run_active(make_ctx(plugin=self._plugin(), now=1000000.0))
        system = out.get("prompt_system", "")
        user = out.get("prompt_user", "")
        prompt = (system + "\n" + user).strip()
        self.assertGreater(len(prompt), 1200)
        self.assertIn(self.PERSONA[:40], system)
        self.assertIn("【输出格式 · 必须遵守】", system)
        self.assertNotIn("【输出格式", user)
        self.assertIn("情绪", user)        # state_block
        self.assertIn("关系", user)        # relationship
        self.assertIn("间隔", user)        # gap
        self.assertTrue("social_gap" in user or "想接住情绪" in user)  # intent
        tone_text = str(_tone.tone_block("calm", emotion="calm", intensity=0.5,
                                          self_esteem=0.7, regulation=None).get("text") or "")
        self.assertTrue(tone_text[:6] in user)  # tone

    def test_run_prompt_enriches_for_main_path(self):
        # main.py calls run_prompt directly; it must self-enrich too.
        out = rt.run_prompt(make_ctx(plugin=self._plugin(), now=1000000.0))
        self.assertIsInstance(out, dict)
        self.assertIn(self.PERSONA[:40], out.get("prompt_system", ""))
        self.assertGreater(len(out.get("prompt_system", "")) + len(out.get("prompt_user", "")), 1200)


if __name__ == "__main__":
    unittest.main()
