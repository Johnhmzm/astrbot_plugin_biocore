# -*- coding: utf-8 -*-
"""Emotion probe tests: model-chosen deltas, protections, feedback integration."""
import asyncio
import json
import re
import unittest
from pathlib import Path

from biocore_model import emotion_probe as ep
from biocore_model import feedback_flow as ff

MAIN = Path(__file__).resolve().parents[2] / "main.py"
FENCE = "\x60\x60\x60"


class FakeCore:
    def __init__(self):
        self._snapshot = {"v": 0.1, "a": 0.4, "stress": 0.2,
                          "self_esteem": 0.5, "social": 0.5, "trust": 0.5}

    def snapshot(self):
        return dict(self._snapshot)

    def load_state(self, state):
        self._snapshot.update(state)


def payload(deltas, c=0.8, why="有点被扎到"):
    return json.dumps({"deltas": deltas, "why": why, "c": c})


class ParseTest(unittest.TestCase):
    def setUp(self):
        ep.reset_rate()

    def test_normal_deltas(self):
        out = ep.parse(payload({"v": -0.3, "a": 0.1}), core=object(), now=1000.0)
        self.assertEqual(out["deltas"], {"v": -0.2, "a": 0.1})
        self.assertEqual(out["why"], "有点被扎到")
        self.assertEqual(out["source"], "probe")

    def test_empty_deltas_is_valid_but_no_write(self):
        out = ep.parse(payload({}, c=0.9, why="没影响"), core=object(), now=1000.0)
        self.assertEqual(out["deltas"], {})
        self.assertEqual(ep.to_feedback_payload(out), {})

    def test_unknown_fields_dropped(self):
        out = ep.parse(payload({"mood": 0.5, "v": -0.1}), core=object(), now=1000.0)
        self.assertEqual(out["deltas"], {"v": -0.1})

    def test_per_item_clamp(self):
        out = ep.parse(payload({"v": 0.9, "trust": -0.5}), core=object(), now=1000.0)
        self.assertEqual(out["deltas"], {"v": 0.2, "trust": -0.2})

    def test_rate_limit_same_minute(self):
        core = object()
        first = ep.parse(payload({"v": 0.2, "a": 0.2}), core=core, now=1000.0)
        self.assertEqual(first["deltas"], {"v": 0.2, "a": 0.2})
        second = ep.parse(payload({"v": 0.2}), core=core, now=1001.0)
        self.assertEqual(second["deltas"], {})
        third = ep.parse(payload({"v": 0.2}), core=core, now=1002.0)
        self.assertEqual(third["deltas"], {})

    def test_rate_limit_resets_next_minute(self):
        core = object()
        ep.parse(payload({"v": 0.2, "a": 0.2}), core=core, now=1000.0)
        later = ep.parse(payload({"v": 0.2}), core=core, now=1060.0)
        self.assertEqual(later["deltas"], {"v": 0.2})

    def test_low_confidence_dropped(self):
        self.assertEqual(ep.parse(payload({"v": -0.2}, c=0.39), core=object(),
                                  now=1000.0), {})

    def test_garbage_json(self):
        self.assertEqual(ep.parse("我不是 JSON", core=object(), now=1000.0), {})
        self.assertEqual(ep.parse("", core=object(), now=1000.0), {})

    def test_fenced_json(self):
        raw = "好的\n" + FENCE + "json\n" + payload({"v": -0.1}) + "\n" + FENCE
        out = ep.parse(raw, core=object(), now=1000.0)
        self.assertEqual(out["deltas"], {"v": -0.1})

    def test_why_truncated_to_30(self):
        out = ep.parse(payload({}, why="x" * 80), core=object(), now=1000.0)
        self.assertEqual(len(out["why"]), ep.WHY_MAX_CHARS)


class ProbeAsyncTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ep.reset_rate()

    async def test_success(self):
        async def call(prompt):
            return payload({"v": -0.2, "trust": -0.05}, c=0.9, why="被质疑")
        out = await ep.probe("好。", "你什么意思", call, core=object(), now=2000.0)
        self.assertEqual(out["deltas"], {"v": -0.2, "trust": -0.05})
        self.assertEqual(out["why"], "被质疑")

    async def test_timeout_returns_empty(self):
        async def call(prompt):
            await asyncio.sleep(1.0)
            return payload({"v": -0.2})
        self.assertEqual(await ep.probe("x", "y", call, timeout=0.05,
                                        core=object(), now=2000.0), {})

    async def test_exception_returns_empty(self):
        async def call(prompt):
            raise RuntimeError("boom")
        self.assertEqual(await ep.probe("x", "y", call, core=object(),
                                        now=2000.0), {})

    async def test_prompt_short_and_has_contract(self):
        seen = {}
        async def call(prompt):
            seen["prompt"] = prompt
            return payload({}, c=0.9)
        await ep.probe("回复", "消息", call, core=object(), now=2000.0)
        self.assertLessEqual(len(ep._INSTRUCTION), 120)
        for token in ("deltas", "why", "self_esteem", "无影响", "对方刚说", "回复"):
            self.assertIn(token, seen["prompt"])


class FeedbackIntegrationTest(unittest.TestCase):
    def setUp(self):
        ep.reset_rate()
        ff.reset_seen()

    def tearDown(self):
        ff.reset_seen()

    def test_write_takes_effect(self):
        core = FakeCore()
        out = ep.parse(payload({"v": -0.2, "stress": 0.1, "trust": -0.05},
                               c=1.0), core=object(), now=3000.0)
        meta = ep.to_feedback_payload(out)
        self.assertIn("valence_delta", meta)
        self.assertIn("self_esteem_delta" if False else "stress_delta", meta)
        result = ff.apply_llm(meta, core, now=3000.0)
        self.assertTrue(result["written"])
        self.assertLess(core.snapshot()["v"], 0.1)

    def test_idempotent_same_now(self):
        core = FakeCore()
        meta = ep.to_feedback_payload(ep.parse(payload({"v": -0.2}, c=1.0),
                                               core=object(), now=4000.0))
        first = ff.apply_llm(meta, core, now=4000.0)
        second = ff.apply_llm(meta, core, now=4000.0)
        self.assertTrue(first["written"])
        self.assertEqual(second["deltas"], {})

    def test_empty_deltas_no_write(self):
        core = FakeCore()
        meta = ep.to_feedback_payload(ep.parse(payload({}), core=object(), now=5000.0))
        self.assertEqual(meta, {})
        result = ff.apply_llm(meta, core, now=5000.0)
        self.assertFalse(result["written"])


class RawDiagnosticTest(unittest.TestCase):
    def test_invalid_raw_is_logged(self):
        with self.assertLogs(ep.logger, level="INFO") as captured:
            ep.parse("我不是JSON", core=object(), now=1000.0)
        self.assertTrue(any("emotion probe raw=" in line for line in captured.output))

    def test_low_confidence_raw_is_logged(self):
        with self.assertLogs(ep.logger, level="INFO") as captured:
            ep.parse(payload({"v": -0.2}, c=0.1), core=object(), now=1000.0)
        self.assertTrue(any("emotion probe raw=" in line for line in captured.output))


class WiringStaticTest(unittest.TestCase):
    def test_main_consumes_new_contract(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertIn("emotion_probe_enabled", source)
        self.assertIn("feedback_payload", source)
        self.assertIn("appraisal src=reply dims=%s deltas=%s c=%.2f", source)
        self.assertIn("core=_core, now=time.time()", source)
        self.assertIn("asyncio.create_task(_emotion_probe_task())", source)
        self.assertIn("_probe_raw", source)
        self.assertIn("isinstance(_raw, str)", source)
        self.assertIn("[biocore] emotion probe raw=%r", source)
        self.assertIn("[biocore] emotion probe start", source)
        self.assertIn("emotion probe task failed", source)
        self.assertIn("emotion probe llm returned None", source)
        self.assertIn("exc_info=True", source)


if __name__ == "__main__":
    unittest.main()
