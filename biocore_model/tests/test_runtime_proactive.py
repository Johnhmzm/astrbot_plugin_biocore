# -*- coding: utf-8 -*-
"""task-205 follow-up: proactive_tick policy lives in the python pipeline.

Covers disabled switches, gap/hourly-cap/cooldown, trust threshold, pending
commitments, text composition and cooldown booking. No Node required.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from biocore_runtime import pipeline as pl

NOW_MS = 1_800_000_000_000
HOUR_MS = 3600 * 1000
LAST_HUMAN_MS = NOW_MS - 4 * HOUR_MS


def switches(**overrides):
    base = {
        "proactiveEnabled": True,
        "proactiveSend": True,
        "proactiveMinGapMinutes": 180,
        "proactivePerHour": 2,
        "proactiveMinTrust": 0.6,
        "proactiveMaxChars": 60,
        "proactiveRequireOpenLoop": True,
        "proactiveIntervalMinutes": 30,
    }
    base.update(overrides)
    return base


def make_store(tmp, session_id="s1", trust=0.8, texts=None, now_ms=NOW_MS):
    root = Path(tmp) / "memory"
    sessions = root / "sessions" / pl.sanitize_session_id(session_id)
    sessions.mkdir(parents=True, exist_ok=True)
    rows = []
    texts = texts if texts is not None else ("明天要去体检，记得问我结果",)
    for index, text in enumerate(texts):
        rows.append({"id": "e%d" % index, "text": text, "role": "user",
                     "ts": now_ms / 1000.0 - index * 60, "deleted": False})
    (sessions / "memory.json").write_text(
        json.dumps({"entries": rows}), encoding="utf-8")
    states = root.parent / "sessions"
    states.mkdir(parents=True, exist_ok=True)
    (states / (pl.sanitize_session_id(session_id) + ".json")).write_text(
        json.dumps({"relationship": {"trust": trust, "closeness": trust}}),
        encoding="utf-8")
    return root


class ShapeTest(unittest.TestCase):
    def test_output_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            out = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(), str(store), now=NOW_MS)
            for key in ("ok", "should_send", "text", "reason", "gap_minutes"):
                self.assertIn(key, out)
            self.assertTrue(out["ok"])
            self.assertTrue(out["should_send"])
            self.assertEqual(out["reason"], "ok")
            self.assertAlmostEqual(out["gap_minutes"], 240.0, places=1)
            self.assertIn("体检", out["text"])

    def test_dispatch_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            out = pl.dispatch("proactive_tick", {
                "session_id": "s1", "last_human_ts": LAST_HUMAN_MS,
                "switches": switches(), "store": str(store), "now": NOW_MS})
            self.assertTrue(out["should_send"])


class SwitchTest(unittest.TestCase):
    def test_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.proactive_tick("s1", LAST_HUMAN_MS,
                                    switches(proactiveEnabled=False),
                                    str(make_store(tmp)), now=NOW_MS)
            self.assertFalse(out["should_send"])
            self.assertEqual(out["reason"], "disabled")

    def test_send_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.proactive_tick("s1", LAST_HUMAN_MS,
                                    switches(proactiveSend=False),
                                    str(make_store(tmp)), now=NOW_MS)
            self.assertFalse(out["should_send"])
            self.assertEqual(out["reason"], "send_off")

    def test_no_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.proactive_tick("", LAST_HUMAN_MS, switches(),
                                    str(make_store(tmp)), now=NOW_MS)
            self.assertFalse(out["should_send"])
            self.assertEqual(out["reason"], "no_session")


class TimingTest(unittest.TestCase):
    def test_too_soon(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.proactive_tick("s1", NOW_MS - 10 * 60 * 1000, switches(),
                                    str(make_store(tmp)), now=NOW_MS)
            self.assertEqual(out["reason"], "too_soon")
            self.assertAlmostEqual(out["gap_minutes"], 10.0, places=1)

    def test_hourly_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "proactive.json").write_text(json.dumps({
                "lastSentAt": NOW_MS - 200 * 60 * 1000,
                "sent": [NOW_MS - 30 * 60 * 1000, NOW_MS - 40 * 60 * 1000],
            }), encoding="utf-8")
            out = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(), str(store),
                                    now=NOW_MS)
            self.assertEqual(out["reason"], "hourly_cap")

    def test_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "proactive.json").write_text(json.dumps({
                "lastSentAt": NOW_MS - 30 * 60 * 1000, "sent": [],
            }), encoding="utf-8")
            out = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(), str(store),
                                    now=NOW_MS)
            self.assertEqual(out["reason"], "cooldown")

    def test_seconds_timestamp_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.proactive_tick("s1", LAST_HUMAN_MS / 1000.0, switches(),
                                    str(make_store(tmp)), now=NOW_MS)
            self.assertTrue(out["should_send"])
            self.assertAlmostEqual(out["gap_minutes"], 240.0, places=1)


class RelationshipTest(unittest.TestCase):
    def test_not_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(),
                                    str(make_store(tmp, trust=0.2)),
                                    now=NOW_MS)
            self.assertEqual(out["reason"], "not_close")
            self.assertAlmostEqual(out["trust"], 0.2, places=3)

    def test_explicit_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp, trust=0.1)
            alt = Path(tmp) / "alt.json"
            alt.write_text(json.dumps({"relationship": {"trust": 0.9}}),
                           encoding="utf-8")
            out = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(), str(store),
                                    now=NOW_MS, state_file=str(alt))
            self.assertTrue(out["should_send"])

    def test_missing_state_uses_default_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "memory"
            (store / "sessions" / "s1").mkdir(parents=True, exist_ok=True)
            (store / "sessions" / "s1" / "memory.json").write_text(
                json.dumps({"entries": [{"text": "明天要体检",
                                         "ts": time.time()}]}), encoding="utf-8")
            out = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(), str(store),
                                    now=NOW_MS)
            self.assertEqual(out["reason"], "not_close")


class CommitmentTest(unittest.TestCase):
    def test_no_commitment(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.proactive_tick(
                "s1", LAST_HUMAN_MS, switches(),
                str(make_store(tmp, texts=("今天天气不错", "晚饭吃了面"))),
                now=NOW_MS)
            self.assertEqual(out["reason"], "no_commitment")

    def test_optional_commitment_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.proactive_tick(
                "s1", LAST_HUMAN_MS,
                switches(proactiveRequireOpenLoop=False),
                str(make_store(tmp, texts=("今天天气不错",))), now=NOW_MS)
            self.assertTrue(out["should_send"])
            self.assertIn("在忙吗", out["text"])

    def test_due_hint_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            texts = ("记得给朋友回消息", "明天要去体检")
            out = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(),
                                    str(make_store(tmp, texts=texts)),
                                    now=NOW_MS)
            self.assertTrue(out["should_send"])
            self.assertIn("明天要去体检", out["text"])

    def test_max_chars_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            long_text = "明天要做的事情" * 10
            out = pl.proactive_tick("s1", LAST_HUMAN_MS,
                                    switches(proactiveMaxChars=24),
                                    str(make_store(tmp, texts=(long_text,))),
                                    now=NOW_MS)
            self.assertTrue(out["should_send"])
            self.assertLessEqual(len(out["text"]), 24)


class BookingTest(unittest.TestCase):
    def test_booking_written_and_second_tick_cooldowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            first = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(),
                                      str(store), now=NOW_MS)
            self.assertTrue(first["should_send"])
            state = json.loads((store / "proactive.json").read_text(encoding="utf-8"))
            self.assertEqual(state["lastSentAt"], float(NOW_MS))
            self.assertTrue(state["lastText"])
            second = pl.proactive_tick("s1", LAST_HUMAN_MS, switches(),
                                       str(store), now=NOW_MS + 60 * 1000)
            self.assertFalse(second["should_send"])
            self.assertEqual(second["reason"], "cooldown")

    def test_no_booking_when_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            pl.proactive_tick("s1", NOW_MS - 60 * 1000, switches(), str(store),
                              now=NOW_MS)
            self.assertFalse((store / "proactive.json").exists())


if __name__ == "__main__":
    unittest.main()
