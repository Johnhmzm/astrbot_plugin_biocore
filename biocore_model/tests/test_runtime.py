# -*- coding: utf-8 -*-
"""PIPE-2 runtime tests: default pipeline assembly, switches, run_reply, fallback."""
import unittest

from biocore_model import pipeline as pl
from biocore_model import runtime as rt


class FakeEvent:
    def __init__(self, text="", umo="umo-9", sender="u-9"):
        self.message_str = text
        self.unified_msg_origin = umo
        self._sender = sender

    def get_sender_id(self):
        return self._sender


class FakeCore:
    def __init__(self):
        self._snapshot = {"emotion": "calm", "intensity": 0.5, "v": 0.1,
                          "a": 0.2, "stress": 0.1, "self_esteem": 0.7}
        self.observed = []
        self.loaded = []

    def snapshot(self):
        return dict(self._snapshot)

    def observe(self, text, embedding=None):
        self.observed.append(text)

    def load_state(self, state):
        self.loaded.append(dict(state))


class BoomPipeline(pl.Pipeline):
    def run(self, ctx=None, start=None):
        raise RuntimeError("runtime boom")


def request_ctx(text="你好", llm=None, core=None, memory=None):
    meta = {"now": 1000.0}
    if llm is not None:
        meta["llm"] = llm
    return rt.make_request_ctx(plugin=object(), event=FakeEvent(text),
                               core=core or FakeCore(), text=text,
                               memory=memory or [], now=1000.0, meta=meta)


class BuildTest(unittest.TestCase):
    def test_default_pipeline_order(self):
        p = rt.build_default_pipeline()
        self.assertEqual(p.names(),
                         ["perceive", "memory", "bio", "decide", "expr_state",
                          "expr_tone", "expr_intent", "think", "parse",
                          "feedback", "present"])

    def test_default_switches_reflect_in_status(self):
        p = rt.build_default_pipeline()
        rows = {row["name"]: row for row in p.get_status()["stages"]}
        self.assertTrue(rows["memory"]["enabled"])
        self.assertTrue(rows["think"]["enabled"])
        off = rt.build_default_pipeline(switches={"memory": False, "bio": False})
        rows = {row["name"]: row for row in off.get_status()["stages"]}
        self.assertFalse(rows["memory"]["enabled"])
        self.assertFalse(rows["bio"]["enabled"])
        # think is in PIPE-1 REQUIRED_STAGES, so it stays registered; a missing
        # llm already makes it a clean no-op instead of aborting the mainline.
        locked = rt.build_default_pipeline(switches={"think": False})
        rows = {row["name"]: row for row in locked.get_status()["stages"]}
        self.assertTrue(rows["think"]["enabled"])

    def test_singleton_identity_and_reset(self):
        rt.reset_pipeline()
        first = rt.get_pipeline()
        self.assertIs(first, rt.get_pipeline())
        rt.reset_pipeline()
        self.assertIsNot(first, rt.get_pipeline())

    def test_required_stages_cannot_be_disabled(self):
        rt.reset_pipeline()
        for name in rt.REQUIRED_STAGES:
            self.assertRaises(ValueError, rt.set_enabled, name, False)


class RunReplyTest(unittest.TestCase):
    def test_end_to_end_with_llm(self):
        ctx = request_ctx(llm=lambda prompt: "我在。")
        out = rt.run_reply(ctx)
        self.assertEqual(rt.reply_text(out), "我在。")
        self.assertNotIn("pipeline_error", out["meta"])
        names = [row["name"] for row in out["trace"]["stages"]]
        self.assertEqual(names, list(rt.get_pipeline().names()))

    def test_without_llm_has_no_reply_and_no_raise(self):
        out = rt.run_reply(request_ctx())
        self.assertEqual(rt.reply_text(out), "")
        self.assertNotIn("pipeline_error", out["meta"])
        self.assertIn("think", [row["stage"] for row in out["meta"]["skipped"]])

    def test_abort_is_contained(self):
        p = pl.Pipeline()
        p.register(pl.Stage("perceive", lambda c: 1 / 0))
        out = rt.run_reply(request_ctx(), pipeline=p)
        self.assertEqual(out["meta"]["pipeline_error"]["kind"], "abort")
        self.assertEqual(out["meta"]["pipeline_error"]["stage"], "perceive")

    def test_exception_is_contained(self):
        out = rt.run_reply(request_ctx(), pipeline=BoomPipeline())
        self.assertEqual(out["meta"]["pipeline_error"]["kind"], "exception")

    def test_legal_text_has_no_protocol_leak(self):
        fence = chr(96) * 3
        raw = ('好。<bc>{"e":"joy","i":0.6}</bc>' + fence + 'json\n'
               + '{"e":"joy"}\n' + fence)
        out = rt.run_reply(request_ctx(llm=lambda prompt: raw))
        text = rt.reply_text(out)
        self.assertTrue(text)
        self.assertNotIn("<bc>", text)
        self.assertNotIn("json", text)

    def test_disabled_memory_stage_still_valid(self):
        p = rt.build_default_pipeline(switches={"memory": False})
        out = rt.run_reply(request_ctx(llm=lambda prompt: "嗯。"), pipeline=p)
        rows = {row["name"]: row for row in out["trace"]["stages"]}
        self.assertEqual(rows["memory"]["status"], "skipped")
        self.assertEqual(rt.reply_text(out), "嗯。")

    def test_think_error_does_not_abort(self):
        def boom(prompt):
            raise RuntimeError("provider down")
        out = rt.run_reply(request_ctx(llm=boom))
        self.assertNotIn("pipeline_error", out["meta"])
        self.assertEqual(rt.reply_text(out), "")
        self.assertIn("think", [row["stage"] for row in out["meta"]["skipped"]])


class RequestCtxTest(unittest.TestCase):
    def test_fields_and_side_effect_flags(self):
        core = FakeCore()
        ctx = request_ctx(core=core)
        self.assertEqual(ctx["user"], "u-9")
        self.assertEqual(ctx["umo"], "umo-9")
        self.assertEqual(ctx["state"]["emotion"], "calm")
        self.assertTrue(ctx["meta"]["shadow"])
        self.assertFalse(ctx["meta"]["write_core"])
        self.assertFalse(ctx["meta"]["observe"])

    def test_shadow_run_does_not_touch_core(self):
        core = FakeCore()
        out = rt.run_reply(request_ctx(llm=lambda prompt: "ok", core=core))
        self.assertEqual(core.observed, [])
        self.assertEqual(core.loaded, [])
        self.assertEqual(out["core"], core)

    def test_trace_ring_recorded(self):
        out = rt.run_reply(request_ctx(llm=lambda prompt: "hi"))
        self.assertEqual(len(out["trace"]["stages"]), 11)
        self.assertIn("ring", out["trace"])
        self.assertGreaterEqual(len(out["trace"]["ring"]), 11)


class StatusTest(unittest.TestCase):
    def test_get_status_and_set_enabled(self):
        rt.reset_pipeline()
        rt.set_enabled("expr_intent", False)
        rows = {row["name"]: row for row in rt.get_status()["stages"]}
        self.assertFalse(rows["expr_intent"]["enabled"])
        rt.set_enabled("expr_intent", True)
        rows = {row["name"]: row for row in rt.get_status()["stages"]}
        self.assertTrue(rows["expr_intent"]["enabled"])


if __name__ == "__main__":
    unittest.main()
