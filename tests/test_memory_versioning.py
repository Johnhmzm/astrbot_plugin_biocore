# -*- coding: utf-8 -*-
"""arXiv 2610.36308: version resolution for attributed facts.

An entry gets a (subject, attribute) key from an explicit metadata block, an
"attribute" field, or -- when the caller named nothing -- the deterministic
extractor dedupe already uses (store/dedupe.extract_fact). Text that does not
extract gets no key, so nothing is resolved against anything.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_memory.store import versioning as v  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400.0


def make_engine(flags=None, now=NOW):
    return MemoryEngine(store=MemoryStore(),
                        config={"flags": dict(flags or {})},
                        now=lambda: now)


def fact(engine, text, attribute=None, fact_value=None, ts=NOW,
         subject=None, scope=None, meta=None):
    event = {"text": text, "role": "user", "ts": ts}
    if attribute is not None:
        event["attribute"] = attribute
    if fact_value is not None:
        event["fact_value"] = fact_value
    if subject is not None:
        event["subject"] = subject
    if scope is not None:
        event["scope"] = scope
    if meta is not None:
        event["metadata"] = meta
    return engine.remember(event)


class KeyTest(unittest.TestCase):
    """Explicit annotations only; no text guessing."""

    def test_metadata_block_is_a_key(self):
        key = v.key_of({"text": "随便一句话",
                        "metadata": {"subject": "user", "attribute": "city",
                                     "fact_value": "上海"}})
        self.assertEqual(key, {"subject": "user", "attribute": "city",
                               "value": "上海"})

    def test_entry_level_attribute_is_a_key(self):
        key = v.key_of({"text": "随便一句话", "attribute": "city",
                        "fact_value": "上海"})
        self.assertEqual(key["attribute"], "city")
        self.assertEqual(key["value"], "上海")

    def test_subject_defaults_to_the_role(self):
        self.assertEqual(v.key_of({"text": "x", "attribute": "city",
                                   "fact_value": "上海"})["subject"], "user")
        self.assertEqual(v.key_of({"text": "x", "role": "assistant",
                                   "attribute": "city",
                                   "fact_value": "上海"})["subject"],
                         "assistant")

    def test_text_alone_gives_no_key(self):
        # every one of these LOOKS like a fact; none carries an annotation.
        for text in ("我的生日是3月5日", "我住在上海", "我搬到北京了",
                     "我的职业是医生", "约定周五见面"):
            self.assertIsNone(v.key_of({"text": text, "role": "user"}), text)

    def test_value_is_normalised_but_not_interpreted(self):
        self.assertEqual(v.key_of({"attribute": "x",
                                   "fact_value": "  上海　"})["value"], "上海")


class SupersedeTest(unittest.TestCase):
    """New value wins; the old one stays as history."""

    def test_new_value_supersedes_old(self):
        engine = make_engine()
        old = fact(engine, "住在哪个城市不重要", "city", "上海", ts=NOW - 10 * DAY)
        new = fact(engine, "又提了一次城市", "city", "北京", ts=NOW)
        self.assertEqual(old["status"], v.SUPERSEDED)
        self.assertEqual(old["superseded_by"], new["id"])
        self.assertEqual(old["superseded_at"], round(NOW, 3))
        self.assertEqual(new["status"], v.ACTIVE)

    def test_old_value_is_kept_not_deleted(self):
        engine = make_engine()
        old = fact(engine, "住在哪个城市不重要", "city", "上海", ts=NOW - 10 * DAY)
        fact(engine, "又提了一次城市", "city", "北京", ts=NOW)
        self.assertEqual(len(engine.store.entries), 2)
        self.assertIn(old, engine.store.entries)
        self.assertEqual(old["text"], "住在哪个城市不重要")   # text untouched
        self.assertFalse(old.get("deleted"))

    def test_recall_hides_superseded_by_default(self):
        engine = make_engine()
        old = fact(engine, "城市 A", "city", "上海", ts=NOW - 10 * DAY)
        new = fact(engine, "城市 B", "city", "北京", ts=NOW)
        ids = [row["entry"]["id"] for row in engine.recall("城市", budget=5)]
        self.assertIn(new["id"], ids)
        self.assertNotIn(old["id"], ids)

    def test_history_question_can_see_the_old_value(self):
        engine = make_engine()
        old = fact(engine, "城市 A", "city", "上海", ts=NOW - 10 * DAY)
        new = fact(engine, "城市 B", "city", "北京", ts=NOW)
        ids = [row["entry"]["id"] for row in engine.recall(
            "她以前说过城市吗", budget=5, include_superseded=True)]
        self.assertEqual(sorted(ids), sorted([old["id"], new["id"]]))

    def test_out_of_order_write_is_superseded_by_the_stored_value(self):
        engine = make_engine()
        new = fact(engine, "城市 B", "city", "北京", ts=NOW)
        old = fact(engine, "城市 A", "city", "上海", ts=NOW - 5 * DAY)
        self.assertEqual(old["status"], v.SUPERSEDED)
        self.assertEqual(old["superseded_by"], new["id"])
        self.assertEqual(new["status"], v.ACTIVE)

    def test_same_value_twice_is_not_a_version(self):
        engine = make_engine()
        first = fact(engine, "城市 A", "city", "上海", ts=NOW - DAY)
        second = fact(engine, "城市 A 再说一次", "city", "上海", ts=NOW)
        self.assertEqual(first.get("status"), v.ACTIVE)
        self.assertEqual(second.get("status"), v.ACTIVE)

    def test_different_attributes_do_not_collide(self):
        engine = make_engine()
        city = fact(engine, "城市", "city", "上海", ts=NOW - DAY)
        job = fact(engine, "工作", "job", "医生", ts=NOW)
        self.assertEqual(city.get("status"), v.ACTIVE)
        self.assertEqual(job.get("status"), v.ACTIVE)
        self.assertEqual(len(engine.recall("城市 工作", budget=5)), 2)

    def test_scopes_are_resolved_separately(self):
        engine = make_engine()
        first = fact(engine, "城市", "city", "上海", ts=NOW - DAY, scope="a")
        second = fact(engine, "城市", "city", "北京", ts=NOW, scope="b")
        self.assertEqual(first.get("status"), v.ACTIVE)
        self.assertEqual(second.get("status"), v.ACTIVE)


class NoAnnotationTest(unittest.TestCase):
    """A text that does not extract is never resolved, marked or filtered."""

    def test_unannotated_entries_are_never_resolved(self):
        engine = make_engine()
        first = fact(engine, "我刚到家", ts=NOW - 10 * DAY)
        second = fact(engine, "今天天气不错", ts=NOW)
        self.assertNotIn("status", first)
        self.assertNotIn("version_key", first)
        self.assertNotIn("attribute", first)
        self.assertNotIn("superseded_by", first)
        self.assertNotIn("status", second)
        self.assertNotIn("attribute", second)

    def test_unannotated_entries_are_all_recalled(self):
        engine = make_engine()
        first = fact(engine, "我刚到家", ts=NOW - 10 * DAY)
        second = fact(engine, "今天天气不错", ts=NOW)
        ids = [row["entry"]["id"] for row in engine.recall("到家 天气", budget=5)]
        self.assertEqual(sorted(ids), sorted([first["id"], second["id"]]))

    def test_summary_has_no_version_rows(self):
        engine = make_engine()
        fact(engine, "我刚到家", ts=NOW - 10 * DAY)
        fact(engine, "今天天气不错", ts=NOW)
        summary = engine.memory_versions()
        self.assertEqual(summary["active"], 2)
        self.assertEqual(summary["superseded"], 0)
        self.assertEqual(summary["recent"], [])
        self.assertEqual(engine.memory_conflicts(), [])


class DisputeTest(unittest.TestCase):
    """Two values for one key in ONE turn cannot be ordered."""

    def test_same_turn_values_are_disputed(self):
        engine = make_engine()
        first = fact(engine, "城市 A", "city", "上海", ts=NOW)
        second = fact(engine, "城市 B", "city", "北京", ts=NOW)
        self.assertEqual(first["status"], v.DISPUTED)
        self.assertEqual(second["status"], v.DISPUTED)
        self.assertNotIn("superseded_by", first)

    def test_disputed_entries_stay_visible_in_recall(self):
        engine = make_engine()
        fact(engine, "城市 A", "city", "上海", ts=NOW)
        fact(engine, "城市 B", "city", "北京", ts=NOW)
        ids = [row["entry"]["id"] for row in engine.recall("城市", budget=5)]
        self.assertEqual(len(ids), 2)

    def test_conflict_is_reported(self):
        engine = make_engine()
        fact(engine, "城市 A", "city", "上海", ts=NOW)
        fact(engine, "城市 B", "city", "北京", ts=NOW)
        rows = engine.memory_conflicts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attribute"], "city")
        self.assertEqual(sorted(rows[0]["values"]), ["上海", "北京"])
        self.assertEqual(len(rows[0]["ids"]), 2)

    def test_state_summary_counts_and_recent(self):
        engine = make_engine()
        old = fact(engine, "城市 A", "city", "上海", ts=NOW - DAY)
        fact(engine, "城市 B", "city", "北京", ts=NOW)
        summary = engine.memory_versions()
        self.assertEqual(summary["active"], 1)
        self.assertEqual(summary["superseded"], 1)
        self.assertEqual(summary["disputed"], 0)
        self.assertLessEqual(len(summary["recent"]), 5)
        self.assertEqual(summary["recent"][0]["id"], old["id"])
        self.assertEqual(summary["recent"][0]["attribute"], "city")


class SwitchOffTest(unittest.TestCase):
    """memory_versioning OFF: nothing marked and nothing filtered."""

    def test_switch_off_marks_nothing(self):
        engine = make_engine(flags={"memory_versioning": False})
        old = fact(engine, "城市 A", "city", "上海", ts=NOW - DAY)
        new = fact(engine, "城市 B", "city", "北京", ts=NOW)
        self.assertNotIn("status", old)
        self.assertNotIn("version_key", old)
        self.assertNotIn("status", new)

    def test_switch_off_filters_nothing(self):
        engine = make_engine(flags={"memory_versioning": False})
        old = fact(engine, "城市 A", "city", "上海", ts=NOW - DAY)
        new = fact(engine, "城市 B", "city", "北京", ts=NOW)
        ids = [row["entry"]["id"] for row in engine.recall("城市", budget=5)]
        self.assertEqual(sorted(ids), sorted([old["id"], new["id"]]))

    def test_flag_defaults_on(self):
        engine = make_engine()
        self.assertTrue(engine._flag("memory_versioning", True))
        self.assertTrue(v.enabled({}, {}))
        self.assertFalse(v.enabled({"memory_versioning": False}, {}))


class PipelineStateTest(unittest.TestCase):
    """/state.memory_versions + /state.memory_conflicts from the live store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self.store.mkdir(parents=True, exist_ok=True)
        self._home = os.environ.get("BIOCORE_HOME")
        os.environ["BIOCORE_HOME"] = str(Path(self.tmp.name) / "home")

    def tearDown(self):
        self.tmp.cleanup()
        if self._home is None:
            os.environ.pop("BIOCORE_HOME", None)
        else:
            os.environ["BIOCORE_HOME"] = self._home

    def remember(self, text, ts=NOW, **extra):
        args = {"text": text, "ts": ts}
        args.update(extra)
        return pipeline.tool_call("remember", args, str(self.store),
                                  session_id="s1")

    def test_pipeline_remember_marks_and_recall_hides(self):
        old = self.remember("城市 A", attribute="city", fact_value="上海",
                            ts=NOW - DAY)["entry"]
        new = self.remember("城市 B", attribute="city", fact_value="北京",
                            ts=NOW)["entry"]
        self.assertNotEqual(old["id"], new["id"])
        out = pipeline.tool_call("recall", {"query": "城市", "limit": 5},
                                 str(self.store), session_id="s1")
        ids = [row["id"] for row in out["results"]]
        self.assertIn(new["id"], ids)
        self.assertNotIn(old["id"], ids)

    def test_pipeline_without_attribute_does_not_resolve(self):
        first = self.remember("我住在上海", ts=NOW - DAY)["entry"]
        second = self.remember("我搬到北京了", ts=NOW)["entry"]
        out = pipeline.tool_call("recall", {"query": "上海 北京", "limit": 5},
                                 str(self.store), session_id="s1")
        ids = [row["id"] for row in out["results"]]
        self.assertIn(first["id"], ids)
        self.assertIn(second["id"], ids)

    def test_pipeline_history_query_sees_old_value(self):
        old = self.remember("城市 A", attribute="city", fact_value="上海",
                            ts=NOW - DAY)["entry"]
        self.remember("城市 B", attribute="city", fact_value="北京", ts=NOW)
        out = pipeline.tool_call(
            "recall", {"query": "城市", "limit": 5, "include_superseded": True},
            str(self.store), session_id="s1")
        rows = {row["id"]: row for row in out["results"]}
        self.assertIn(old["id"], rows)
        self.assertEqual(rows[old["id"]]["status"], v.SUPERSEDED)

    def test_state_exposes_memory_versions_and_conflicts(self):
        self.remember("城市 A", attribute="city", fact_value="上海", ts=NOW - DAY)
        self.remember("城市 B", attribute="city", fact_value="北京", ts=NOW)
        self.remember("城市 C", attribute="city", fact_value="广州", ts=NOW + 10)
        self.remember("城市 D", attribute="city", fact_value="深圳", ts=NOW + 10)
        state = pipeline.dispatch("state", {"session_id": "s1",
                                            "store": str(self.store)})["state"]
        versions = state["memory_versions"]
        self.assertGreaterEqual(versions["superseded"], 1)
        self.assertGreaterEqual(versions["disputed"], 2)
        self.assertLessEqual(len(versions["recent"]), 5)
        conflicts = state["memory_conflicts"]
        self.assertTrue(conflicts)
        self.assertTrue(any(row["attribute"] == "city" for row in conflicts))

    def test_state_is_json_safe(self):
        self.remember("城市 A", attribute="city", fact_value="上海", ts=NOW)
        state = pipeline.dispatch("state", {"session_id": "s1",
                                            "store": str(self.store)})["state"]
        json.dumps(state["memory_versions"], ensure_ascii=False)
        json.dumps(state["memory_conflicts"], ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
