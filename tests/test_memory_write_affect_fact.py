# -*- coding: utf-8 -*-
"""A: the write path carries what the turn already knows.

affect: the pipeline has the turn's (v, a) in hand; remember takes it as an
optional argument and writes entry.affect = {v, a}. Without it nothing changes:
the old structure, no new field.

attributes: when the caller names no attribute, the text goes through the
extractor dedupe already uses (store/dedupe.extract_fact), so a changed fact
("生日改成...") resolves against the stored value. Text that does not extract
is stored exactly as before, and a broken extractor never blocks the write.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store import dedupe  # noqa: E402
from biocore_memory.store import versioning as v  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400.0
OLD_FACT = "\u6211\u751f\u65e5\u6539\u62104\u67083\u65e5"
NEW_FACT = "\u6211\u751f\u65e5\u6539\u62105\u670830\u65e5"
PLAIN = "\u6211\u521a\u5230\u5bb6"


def make_engine(flags=None, affect=None, now=NOW):
    return MemoryEngine(affect=dict(affect) if isinstance(affect, dict) else affect,
                        config={"flags": dict(flags or {})}, now=lambda: now)


class Store:
    """Temporary per-session store for the host path."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        return self._tmp.name

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


def stored(store, session="s1"):
    # JSON is an export format now: ask the store for it (same bytes as before)
    return pipeline.export_session_json(store, session)["entries"]


class AffectTest(unittest.TestCase):
    """The turn's affect, when there is one."""

    def test_engine_takes_the_caller_affect(self):
        engine = make_engine()
        entry = engine.remember({"text": "\u4eca\u5929\u6709\u70b9\u7d2f", "role": "user", "ts": NOW},
                                affect={"v": -0.4, "a": 0.7})
        self.assertEqual(entry["affect"], {"valence": -0.4, "arousal": 0.7})

    def test_engine_without_affect_keeps_the_old_structure(self):
        engine = make_engine(affect={"v": 0.3, "a": 0.6})
        entry = engine.remember({"text": "\u4eca\u5929\u6709\u70b9\u7d2f", "role": "user", "ts": NOW})
        self.assertEqual(entry["affect"], {"valence": 0.3, "arousal": 0.6})

    def test_engine_affect_is_written_to_the_store(self):
        engine = make_engine()
        entry = engine.remember({"text": "\u4eca\u5929\u6709\u70b9\u7d2f", "role": "user", "ts": NOW},
                                affect={"v": 0.9, "a": 0.1})
        self.assertEqual(engine.store.find(entry["id"])["affect"]["valence"], 0.9)

    def test_host_remember_takes_the_affect(self):
        with Store() as store:
            pipeline.tool_call("remember", {"text": "\u4eca\u5929\u6709\u70b9\u7d2f", "ts": NOW,
                                            "affect": {"v": -0.4, "a": 0.7}},
                               store, session_id="s1")
            rows = stored(store)
            self.assertEqual(rows[0]["affect"], {"v": -0.4, "a": 0.7})

    def test_host_remember_without_affect_writes_no_field(self):
        with Store() as store:
            pipeline.tool_call("remember", {"text": "\u4eca\u5929\u6709\u70b9\u7d2f", "ts": NOW},
                               store, session_id="s1")
            self.assertNotIn("affect", stored(store)[0])

    def test_host_remember_ignores_a_broken_affect(self):
        with Store() as store:
            out = pipeline.tool_call("remember", {"text": "\u4eca\u5929\u6709\u70b9\u7d2f", "ts": NOW,
                                                  "affect": "loud"},
                                     store, session_id="s1")
            self.assertTrue(out["ok"])
            self.assertNotIn("affect", stored(store)[0])

    def test_a_turn_writes_the_affect_it_already_has(self):
        # the entry carries the state the pipeline itself reports for the
        # turn -- whatever the core model made of the value it was handed
        with Store() as store:
            state = {"core": {"v": 0.42, "a": 0.66}}
            started = pipeline.dispatch(
                "turn_start", {"session_id": "s1", "user_text": OLD_FACT,
                               "store": store, "state": state, "now": NOW})
            reported = (started.get("state") or {}).get("core") or {}
            pipeline.dispatch(
                "turn_end", {"session_id": "s1", "user_text": OLD_FACT,
                             "assistant_text": "\u77e5\u9053\u4e86\uff0c\u628a\u65e5\u671f\u8bb0\u4e0b\u6765\u4e86",
                             "store": store, "state": state, "now": NOW})
            rows = stored(store)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["affect"], rows[1]["affect"])
            self.assertAlmostEqual(rows[0]["affect"]["v"], reported["v"], places=6)
            self.assertAlmostEqual(rows[0]["affect"]["a"], reported["a"], places=6)
            self.assertTrue(-1.0 <= rows[0]["affect"]["v"] <= 1.0)
            self.assertTrue(0.0 <= rows[0]["affect"]["a"] <= 1.0)


class FactExtractionTest(unittest.TestCase):
    """The existing extractor turns a fact into a key; nothing else does."""

    def test_explicit_metadata_fills_the_key_slots(self):
        engine = make_engine()
        entry = engine.remember({"text": OLD_FACT, "role": "user", "ts": NOW - DAY,
                                 "metadata": {"subject": "\u6211",
                                              "attribute": "\u751f\u65e5",
                                              "fact_value": "4\u67083\u65e5"}})
        self.assertEqual(entry["subject"], "\u6211")
        self.assertEqual(entry["attribute"], "\u751f\u65e5")
        self.assertEqual(entry["fact_value"], "4\u67083\u65e5")
        self.assertIn("version_key", entry)

    def test_a_text_alone_creates_no_key(self):
        engine = make_engine()
        entry = engine.remember({"text": OLD_FACT, "role": "user", "ts": NOW})
        for key in ("subject", "attribute", "fact_value", "version_key",
                    "status"):
            self.assertNotIn(key, entry)

    def test_a_changed_fact_supersedes_the_stored_one(self):
        engine = make_engine()
        key = {"subject": "\u6211", "attribute": "\u751f\u65e5"}
        first = engine.remember({"text": OLD_FACT, "role": "user",
                                 "ts": NOW - DAY,
                                 "metadata": dict(key, fact_value="4\u67083\u65e5")})
        second = engine.remember({"text": NEW_FACT, "role": "user", "ts": NOW,
                                  "metadata": dict(key,
                                                   fact_value="5\u670830\u65e5")})
        self.assertEqual(first["status"], v.SUPERSEDED)
        self.assertEqual(first["superseded_by"], second["id"])
        self.assertEqual(second["status"], v.ACTIVE)

    def test_a_text_that_does_not_extract_is_left_alone(self):
        engine = make_engine()
        entry = engine.remember({"text": PLAIN, "role": "user", "ts": NOW})
        for key in ("attribute", "fact_value", "subject", "version_key", "status"):
            self.assertNotIn(key, entry)

    def test_an_explicit_annotation_wins(self):
        engine = make_engine()
        entry = engine.remember({"text": OLD_FACT, "role": "user", "ts": NOW,
                                 "attribute": "\u7231\u597d", "fact_value": "\u4e0b\u68cb"})
        self.assertEqual(entry["attribute"], "\u7231\u597d")
        self.assertEqual(entry["fact_value"], "\u4e0b\u68cb")

    def test_a_write_without_metadata_never_fails(self):
        engine = make_engine()
        entry = engine.remember({"text": OLD_FACT, "role": "user", "ts": NOW})
        self.assertIsNotNone(entry)
        self.assertIn("text", entry)
        self.assertNotIn("attribute", entry)

    def test_versioning_off_extracts_nothing(self):
        engine = make_engine({"memory_versioning": False})
        entry = engine.remember({"text": OLD_FACT, "role": "user", "ts": NOW})
        self.assertNotIn("attribute", entry)
        self.assertNotIn("version_key", entry)

    def test_the_host_path_resolves_with_explicit_metadata(self):
        with Store() as store:
            meta = {"subject": "\u6211", "attribute": "\u751f\u65e5"}
            pipeline.tool_call("remember", {"text": OLD_FACT, "ts": NOW - DAY,
                                            "metadata": dict(meta,
                                                             fact_value="4\u67083\u65e5")},
                               store, session_id="s1")
            pipeline.tool_call("remember", {"text": NEW_FACT, "ts": NOW,
                                            "metadata": dict(meta,
                                                             fact_value="5\u670830\u65e5")},
                               store, session_id="s1")
            rows = stored(store)
            self.assertEqual(rows[0]["status"], v.SUPERSEDED)
            self.assertEqual(rows[0]["superseded_by"], rows[1]["id"])
            self.assertEqual(rows[1]["metadata"]["attribute"], "\u751f\u65e5")

    def test_the_host_path_keeps_an_explicit_attribute(self):
        with Store() as store:
            pipeline.tool_call("remember", {"text": OLD_FACT, "ts": NOW,
                                            "attribute": "\u7231\u597d",
                                            "fact_value": "\u4e0b\u68cb"},
                               store, session_id="s1")
            row = stored(store)[0]
            self.assertEqual(row["attribute"], "\u7231\u597d")
            self.assertEqual(row["fact_value"], "\u4e0b\u68cb")


if __name__ == "__main__":
    unittest.main()
