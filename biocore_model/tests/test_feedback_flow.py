# -*- coding: utf-8 -*-
"""FB-5 feedback_flow tests: three channels, guard-only writes, idempotency."""
import re
import unittest
from pathlib import Path

from biocore_model import feedback_flow as ff


class FakeCore:
    def __init__(self, state=None):
        self._snapshot = dict(state or {"v": 0.0, "a": 0.4, "stress": 0.1,
                                        "self_esteem": 0.5, "social": 0.5})
        self.loaded = []

    def snapshot(self):
        return dict(self._snapshot)

    def load_state(self, state):
        self.loaded.append(dict(state))
        self._snapshot.update(state)


class StrictCore(FakeCore):
    """Forbids direct affect writes: only the guard-produced load_state path."""

    ALLOWED = {"_snapshot", "loaded", "_state"}

    def __setattr__(self, name, value):
        if name in self.ALLOWED or name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        raise AssertionError("direct core attribute write: " + name)


class Base(unittest.TestCase):
    def setUp(self):
        ff.reset_seen()
        self.core = FakeCore()

    def tearDown(self):
        ff.reset_seen()


class LlmChannelTest(Base):
    def test_struct_and_summary(self):
        out = ff.apply_llm({"v": 0.9, "a": 0.9, "stress": 0.9}, self.core, now=1000.0)
        self.assertIn("v", out["deltas"])
        self.assertIsInstance(out["rejected"], list)
        self.assertIsInstance(out["audit"], list)
        self.assertEqual(set(out["summary"]), set(ff.SUMMARY_FIELDS))
        for field in ff.SUMMARY_FIELDS:
            self.assertEqual(set(out["summary"][field]), {"old", "new", "delta"})
        self.assertGreater(out["summary"]["v"]["new"], out["summary"]["v"]["old"])
        self.assertEqual(self.core.loaded[-1]["v"], out["summary"]["v"]["new"])

    def test_whitelist_rejection(self):
        out = ff.apply_llm({"nope": 1.0}, self.core, now=1001.0)
        self.assertEqual(out["deltas"], {})
        self.assertIn("nope", out["rejected"])

    def test_idempotent_same_payload_now(self):
        first = ff.apply_llm({"v": 0.3}, self.core, now=1002.0)
        snapshot = self.core.snapshot()
        loaded = len(self.core.loaded)
        second = ff.apply_llm({"v": 0.3}, self.core, now=1002.0)
        self.assertTrue(second["idempotent"])
        self.assertEqual(second["deltas"], {})
        self.assertEqual(self.core.snapshot(), snapshot)
        self.assertEqual(len(self.core.loaded), loaded)
        self.assertEqual(second["summary"]["v"]["old"], second["summary"]["v"]["new"])
        self.assertGreater(first["summary"]["v"]["new"], first["summary"]["v"]["old"])

    def test_new_now_applies_again(self):
        ff.apply_llm({"v": 0.3}, self.core, now=1003.0)
        again = ff.apply_llm({"v": 0.3}, self.core, now=1004.0)
        self.assertFalse(again["idempotent"])
        self.assertGreater(again["summary"]["v"]["new"], again["summary"]["v"]["old"])

    def test_caps_come_from_feedback_llm(self):
        out = ff.apply_llm({"v": 1.0}, FakeCore({"v": 0.0}), now=1005.0)
        self.assertLessEqual(out["deltas"].get("v", 0.0), 0.15 + 1e-9)


class UserChannelTest(Base):
    def test_struct_and_summary(self):
        out = ff.apply_user({"kind": "praise", "id": "m1", "ts": 1.0},
                            self.core, now=2000.0)
        self.assertIn("self_esteem", out["deltas"])
        self.assertEqual(set(out["summary"]), set(ff.SUMMARY_FIELDS))
        self.assertGreater(out["summary"]["self_esteem"]["new"],
                           out["summary"]["self_esteem"]["old"])

    def test_invalid_kind_rejected(self):
        out = ff.apply_user({"kind": "not_a_kind"}, self.core, now=2001.0)
        self.assertEqual(out["deltas"], {})
        self.assertIn("not_a_kind", out["rejected"])
        self.assertEqual(self.core.loaded, [])

    def test_idempotent_same_meta_now(self):
        meta = {"kind": "reply", "id": "m2", "ts": 2.0}
        ff.apply_user(meta, self.core, now=2002.0)
        snapshot = self.core.snapshot()
        again = ff.apply_user(meta, self.core, now=2002.0)
        self.assertTrue(again["idempotent"])
        self.assertEqual(again["deltas"], {})
        self.assertEqual(self.core.snapshot(), snapshot)


class MemoryChannelTest(Base):
    def _entries(self):
        return [
            {"id": "old1", "strength": 0.10, "last_decay_ts": 100.0},
            {"id": "old2", "strength": 0.50, "last_decay_ts": 100.0},
            {"id": "e1", "strength": 0.50},
        ]

    def test_decay_and_forgotten(self):
        out = ff.apply_memory(self._entries(), now=100.0 + 48 * 3600, kind="decay")
        strengths = {row["id"]: row["strength"] for row in out["entries"]}
        self.assertLess(strengths["old2"], 0.5)
        self.assertIn("old1", out["forgotten"])
        self.assertEqual(out["kind"], "decay")

    def test_recall_touch_copies(self):
        entries = self._entries()
        out = ff.apply_memory(entries, now=3000.0, kind="recall:e1")
        touched = {row["id"]: row for row in out["entries"]}["e1"]
        self.assertGreater(touched["strength"], 0.5)
        self.assertEqual(entries[2]["strength"], 0.5)  # input not mutated
        self.assertEqual(out["forgotten"], [])

    def test_select_returns_selected(self):
        out = ff.apply_memory(self._entries(), now=3001.0, kind="select:2")
        self.assertEqual(len(out["entries"]), 2)
        self.assertTrue(out["changed"])
        self.assertEqual(out["kind"], "select")

    def test_unknown_kind_noop(self):
        entries = self._entries()
        out = ff.apply_memory(entries, now=3002.0, kind="whatever")
        self.assertEqual(out["kind"], "noop")
        self.assertFalse(out["changed"])
        self.assertEqual([row["id"] for row in out["entries"]],
                         [row["id"] for row in entries])


class GuardOnlyWriteTest(unittest.TestCase):
    def setUp(self):
        ff.reset_seen()

    def test_no_direct_core_attribute_write(self):
        core = StrictCore()
        out = ff.apply_llm({"v": 0.3}, core, now=4000.0)
        self.assertGreater(out["summary"]["v"]["new"], out["summary"]["v"]["old"])
        self.assertEqual(core.loaded[-1]["v"], out["summary"]["v"]["new"])

    def test_dict_core_updates_in_place(self):
        core = {"v": 0.0, "a": 0.4, "stress": 0.1, "self_esteem": 0.5}
        out = ff.apply_llm({"v": 0.2}, core, now=4001.0)
        self.assertGreater(core["v"], 0.0)
        self.assertEqual(core["v"], out["summary"]["v"]["new"])

    def test_source_has_no_main_import_or_core_assignment(self):
        source = Path(ff.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from\s+main|import\s+main)\b",
                                    source, re.MULTILINE))
        self.assertIsNone(re.search(r"\bcore\.[A-Za-z_]+\s*=", source))
        self.assertIn("feedback_guard", source)


class ResetSeenTest(unittest.TestCase):
    def test_reset_allows_reapply(self):
        ff.reset_seen()
        core = FakeCore()
        ff.apply_llm({"v": 0.3}, core, now=5000.0)
        first_snapshot = core.snapshot()
        ff.reset_seen()
        again = ff.apply_llm({"v": 0.3}, core, now=5000.0)
        self.assertFalse(again["idempotent"])
        self.assertNotEqual(core.snapshot(), first_snapshot)


if __name__ == "__main__":
    unittest.main()
