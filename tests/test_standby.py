# -*- coding: utf-8 -*-
"""task-215: standby initiative -- outbox only, default off."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from biocore_runtime import pipeline, standby


def noon(offset_minutes=0):
    local = time.localtime()
    stamp = time.mktime((local.tm_year, local.tm_mon, local.tm_mday,
                         12, 0, 0, 0, 0, -1))
    return stamp + offset_minutes * 60


def ok_transport(captured=None):
    def call(url, payload, timeout, headers):
        if captured is not None:
            captured.append(payload)
        body = json.dumps({"choices": [{"message": {"content": "最近还好吗？"}}]})
        return 200, body.encode("utf-8")
    return call


def fail_transport(url, payload, timeout, headers):
    raise OSError("network down")


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.store = self.data_dir / "memory"
        (self.store / "sessions" / "s1").mkdir(parents=True)
        self.cfg = {
            "standby_enabled": True,
            "standby_store": str(self.store),
            "standby_session_id": "s1",
            "standby_model_base_url": "http://127.0.0.1:9",
            "standby_model": "test-model",
            "standby_active_hours": "09:00-23:00",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def outbox(self):
        path = self.store / "proactive" / "outbox.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def seed_state(self, **values):
        path = self.store / "proactive" / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values), encoding="utf-8")

    def session_state(self, **values):
        pipeline._save_session_state(str(self.store), "s1", values)


class GatesTest(Case):
    def test_default_off(self):
        result = standby.tick(now=noon(), config={"standby_store": str(self.store)})
        self.assertEqual(result["reason"], "disabled")
        self.assertEqual(self.outbox(), [])

    def test_outside_active_hours(self):
        early = noon(-12 * 60)  # 00:00
        result = standby.tick(now=early, config=self.cfg,
                              transport=ok_transport())
        self.assertEqual(result["reason"], "outside_active_hours")
        self.assertEqual(self.outbox(), [])

    def test_daily_cap(self):
        now = noon()
        self.seed_state(sent=[now - 60, now - 120, now - 180],
                        last_attempt_ts=0.0, last_sent_ts=0.0)
        result = standby.tick(now=now, config=self.cfg,
                              transport=ok_transport())
        self.assertEqual(result["reason"], "daily_cap")

    def test_cooldown_blocks(self):
        now = noon()
        self.seed_state(last_attempt_ts=now - 10 * 60)
        result = standby.tick(now=now, config=self.cfg,
                              transport=ok_transport())
        self.assertEqual(result["reason"], "cooldown")

    def test_no_reply_streak_stops(self):
        now = noon()
        self.seed_state(awaiting_reply=True, no_reply_streak=1,
                        last_sent_ts=now - 3 * 3600)
        self.session_state(last_human_ts=now - 5 * 3600)
        result = standby.tick(now=now, config=self.cfg,
                              transport=ok_transport())
        self.assertEqual(result["reason"], "no_reply_streak")
        self.assertEqual(self.outbox(), [])

    def test_reply_resets_streak(self):
        now = noon()
        self.seed_state(awaiting_reply=True, no_reply_streak=1,
                        last_sent_ts=now - 3 * 3600,
                        last_attempt_ts=now - 3 * 3600)
        self.session_state(last_human_ts=now - 3600)
        result = standby.tick(now=now, config=self.cfg,
                              transport=ok_transport())
        self.assertEqual(result["reason"], "ok")
        self.assertEqual(len(self.outbox()), 1)


class OutputTest(Case):
    def test_outbox_row_shape(self):
        now = noon()
        result = standby.tick(now=now, config=self.cfg,
                              transport=ok_transport())
        self.assertEqual(result["reason"], "ok")
        row = self.outbox()[0]
        for key in ("ts", "text", "reason", "state_snapshot", "prompt",
                    "fallback"):
            self.assertIn(key, row)
        self.assertEqual(row["text"], "最近还好吗？")
        self.assertFalse(row["fallback"])

    def test_prompt_has_full_persona_memories_digest(self):
        long_persona = "你是安吉拉。" + "必须保持礼貌、精确、克制。" * 40
        (self.store / "persona_profile.json").write_text(
            json.dumps({"persona_text": long_persona}), encoding="utf-8")
        (self.store / "sessions" / "s1" / "memory.json").write_text(
            json.dumps({"entries": [
                {"id": "a", "text": "苹果很甜", "ts": 3},
                {"id": "b", "text": "明天体检", "ts": 2},
                {"id": "c", "text": "咖啡少糖", "ts": 1}]}), encoding="utf-8")
        self.session_state(last_user_text="今天有点累", last_human_ts=noon() - 3600)
        prompt = standby.build_prompt({}, ["苹果很甜", "明天体检", "咖啡少糖"],
                                      long_persona, digest="今天有点累")
        self.assertIn(long_persona, prompt)
        self.assertIn("最近记得：", prompt)
        self.assertIn("苹果很甜", prompt)
        self.assertIn("上次对话：今天有点累", prompt)
        captured = []
        standby.tick(now=noon(), config=self.cfg,
                     transport=ok_transport(captured))
        tick_prompt = captured[0]["messages"][0]["content"]
        self.assertIn("最近记得：", tick_prompt)
        self.assertIn("上次对话：今天有点累", tick_prompt)

    def test_missing_model_uses_template(self):
        cfg = dict(self.cfg)
        cfg["standby_model"] = ""
        result = standby.tick(now=noon(), config=cfg)
        self.assertEqual(result["reason"], "template_fallback")
        self.assertTrue(result["fallback"])
        self.assertTrue(self.outbox()[0]["text"])

    def test_transport_failure_uses_template(self):
        result = standby.tick(now=noon(), config=self.cfg,
                              transport=fail_transport)
        self.assertEqual(result["reason"], "template_fallback")
        self.assertTrue(self.outbox()[0]["fallback"])

    def test_second_tick_is_cooldown(self):
        now = noon()
        standby.tick(now=now, config=self.cfg, transport=ok_transport())
        second = standby.tick(now=now + 60, config=self.cfg,
                              transport=ok_transport())
        self.assertEqual(second["reason"], "cooldown")
        self.assertEqual(len(self.outbox()), 1)


class StateTest(Case):
    def test_summary_and_state_fields(self):
        now = noon()
        standby.tick(now=now, config=self.cfg, transport=ok_transport())
        summary = standby.summary(str(self.store), now=now + 60, enabled=True)
        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["sent_today"], 1)
        self.assertGreater(summary["next_at"], 0)
        self.assertEqual(summary["last_reason"], "ok")
        body = pipeline.dispatch("state", {
            "store": str(self.store), "session_id": "s1",
            "persona_profile": str(Path(self.tmp.name) / "missing.json")})["state"]
        self.assertIn("standby", body)
        for key in ("enabled", "next_at", "pending", "sent_today",
                    "last_reason"):
            self.assertIn(key, body["standby"])

    def test_action_is_gated_by_flag(self):
        out = pipeline.dispatch("standby_tick", {
            "store": str(self.store), "session_id": "s1", "now": noon()})
        self.assertEqual(out["reason"], "disabled")


if __name__ == "__main__":
    unittest.main()
