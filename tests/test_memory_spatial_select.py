# -*- coding: utf-8 -*-
"""spatial_select: the candidate stage that runs BEFORE the scorer.

recall used to hand the weighted five-axis ordering the handful of rows it had
already truncated to, so the ordering could only shuffle those rows. The
candidate stage now ranks the WHOLE pool by the same weighted distance first
(Malkov & Yashunin 2018, HNSW: a bounded candidate list before exact scoring;
VLDB 2025 hybrid querying on vectors: the vector stage proposes, the structured
conditions still decide) and only the nearest entries reach the scorer.

Spatial_select is OFF by default: with it off and mode != "spatial", recall
keeps the old path byte for byte. mode="spatial" is the caller's explicit
request and does not need the switch, exactly like recall(spatial=True) for
the ordering stage.
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory import space as sp  # noqa: E402
from biocore_memory.core import config  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.index import cue_score  # noqa: E402
from biocore_memory.recall import recall_entries  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400.0
ANCHOR = NOW - 5 * DAY
QUERY = "海边看日出"
QVER = [1.0, 0.0]


def entry(entry_id, text, ts, vector=None, **extra):
    row = {"id": entry_id, "text": text, "role": "user", "ts": ts,
           "tags": [], "importance": 0.5, "hits": 1, "scope": "default",
           "affect": {"v": 0.0, "a": 0.5}}
    if vector is not None:
        row["vector"] = list(vector)
    row.update(extra)
    return row


def make_engine(entries, flags=None, now=NOW):
    return MemoryEngine(
        store=MemoryStore(doc={"entries": [dict(row) for row in entries]}),
        config={"flags": dict(flags or {})}, now=lambda: now)


def anchoring_case():
    """30 memories with the same text, vector and score.

    Twenty were written "now", ten were written at the question's own moment
    (ANCHOR). Nothing but the time axis separates them, so the fused score is
    identical and the candidate window alone decides which five survive.
    """
    recent = [entry("d%d" % (i + 1), QUERY, NOW, QVER) for i in range(20)]
    anchored = [entry("o%d" % (i + 1), QUERY, ANCHOR, QVER) for i in range(10)]
    return recent + anchored


class SwitchTest(unittest.TestCase):
    """spatial_select defaults to OFF; the caller can say otherwise."""

    def test_select_is_off_by_default(self):
        self.assertFalse(sp.select_enabled({}))
        self.assertFalse(sp.select_enabled({"spatial_select": False}))
        self.assertFalse(sp.select_enabled({}, {"BIOCORE_SPATIAL_SELECT": "off"}))
        self.assertFalse(sp.select_enabled(None))

    def test_switch_reads_flags_nested_env(self):
        self.assertTrue(sp.select_enabled({"spatial_select": True}))
        self.assertTrue(sp.select_enabled({"switches": {"spatial_select": True}}))
        self.assertTrue(sp.select_enabled({}, {"BIOCORE_SPATIAL_SELECT": "1"}))
        # an explicit flag wins over a contradicting environment value
        self.assertFalse(sp.select_enabled({"spatial_select": False},
                                           {"BIOCORE_SPATIAL_SELECT": "1"}))

    def test_engine_defaults_match_the_config(self):
        self.assertFalse(config.FLAGS["spatial_select"])
        self.assertEqual(config.SPATIAL_SELECT_DEPTH, 20)
        self.assertFalse(make_engine([])._flag("spatial_select", False))


class DepthTest(unittest.TestCase):
    """The candidate cap is configuration, never a magic number in the engine."""

    def test_default_depth_comes_from_core_config(self):
        self.assertEqual(sp.depth({}), config.SPATIAL_SELECT_DEPTH)
        self.assertEqual(sp.depth({}, {"BIOCORE_SPATIAL_DEPTH": "7"}), 7)

    def test_engine_honours_the_depth_flag(self):
        engine = make_engine(anchoring_case(),
                             flags={"spatial_select": True, "spatial_depth": 4})
        engine.recall(QUERY, budget=5, vector=QVER, query_ts=ANCHOR)
        self.assertEqual(engine._last_spatial_select["depth"], 4)
        self.assertEqual(engine._last_spatial_select["selected"], 4)

    def test_depth_override_ignores_bad_values(self):
        self.assertEqual(sp.depth({"spatial_depth": 4}), 4)
        self.assertEqual(sp.depth({"switches": {"spatial_depth": 6}}), 6)
        self.assertEqual(sp.depth({"spatial_depth": "not-a-number"}),
                         config.SPATIAL_SELECT_DEPTH)
        self.assertEqual(sp.depth({"spatial_depth": -3}), 1)


class SelectionTest(unittest.TestCase):
    """space.select ranks the whole pool and hands back the nearest ids."""

    def test_select_covers_the_whole_pool(self):
        rows = anchoring_case()
        picked = sp.select(rows, QUERY, query_ts=ANCHOR, limit=len(rows))
        self.assertTrue(picked["ok"])
        self.assertEqual(picked["pool"], 30)
        self.assertEqual(picked["count"], 30)
        self.assertEqual(sorted(picked["ids"]),
                         sorted(row["id"] for row in rows))

    def test_select_limit_caps_the_candidate_list(self):
        picked = sp.select(anchoring_case(), QUERY, query_ts=ANCHOR, limit=3)
        self.assertEqual(picked["count"], 3)
        self.assertEqual(len(picked["ids"]), 3)
        self.assertEqual(picked["depth"], 3)

    def test_select_without_limit_uses_the_configured_depth(self):
        picked = sp.select(anchoring_case(), QUERY, query_ts=ANCHOR)
        self.assertEqual(picked["depth"], config.SPATIAL_SELECT_DEPTH)
        self.assertEqual(picked["count"], config.SPATIAL_SELECT_DEPTH)

    def test_select_is_ordered_by_weighted_distance(self):
        picked = sp.select(anchoring_case(), QUERY, query_ts=ANCHOR, limit=30)
        weighted = [row["weighted"] for row in picked["results"]]
        self.assertEqual(weighted, sorted(weighted))
        # the time-anchored memories come first: they are the near ones
        self.assertEqual(picked["ids"][:10], ["o%d" % (i + 1) for i in range(10)])

    def test_select_scope_filter(self):
        rows = [entry("a", QUERY, ANCHOR, QVER, scope="work"),
                entry("b", QUERY, ANCHOR, QVER, scope="home")]
        self.assertEqual(sp.select(rows, QUERY, query_ts=ANCHOR,
                                   limit=5, scope="work")["ids"], ["a"])
        self.assertEqual(sorted(sp.select(rows, QUERY, query_ts=ANCHOR,
                                          limit=5, scope=None)["ids"]),
                         ["a", "b"])


class RankTest(unittest.TestCase):
    """engine.spatial_rank is the public full-store selection primitive."""

    def test_rank_returns_ids_next_to_the_rows(self):
        engine = make_engine(anchoring_case())
        out = engine.spatial_rank(QUERY, query_ts=ANCHOR, limit=5)
        self.assertTrue(out["ok"])
        self.assertEqual(out["pool"], 30)
        self.assertEqual(out["count"], 5)
        self.assertEqual(out["ids"], ["o%d" % (i + 1) for i in range(5)])
        self.assertEqual([row["id"] for row in out["results"]], out["ids"])

    def test_rank_limit_none_returns_everything(self):
        out = make_engine(anchoring_case()).spatial_rank(QUERY, query_ts=ANCHOR)
        self.assertEqual(out["count"], 30)

    def test_rank_uses_the_query_vector_when_given(self):
        rows = [entry("b", QUERY, ANCHOR, [0.0, 1.0]),
                entry("a", QUERY, ANCHOR, [1.0, 0.0])]
        engine = make_engine(rows)
        blind = engine.spatial_rank(QUERY, query_ts=ANCHOR)
        sighted = engine.spatial_rank(QUERY, query_ts=ANCHOR, vector=QVER)
        self.assertEqual(blind["ids"], ["b", "a"])     # tags only: a tie
        self.assertEqual(sighted["ids"], ["a", "b"])   # 'a' points at the query

    def test_rank_scope_none_spans_every_scope(self):
        rows = [entry("a", QUERY, ANCHOR, QVER, scope="work"),
                entry("b", QUERY, ANCHOR, QVER, scope="home")]
        engine = make_engine(rows)
        self.assertEqual(engine.spatial_rank(QUERY, query_ts=ANCHOR)["ids"], [])
        self.assertEqual(sorted(engine.spatial_rank(QUERY, query_ts=ANCHOR,
                                                    scope=None)["ids"]),
                         ["a", "b"])


class RecallContrastTest(unittest.TestCase):
    """Same query, same anchor: the candidate window changes the top five."""

    def test_remote_memory_reaches_the_window(self):
        old_rows = make_engine(anchoring_case()).recall(
            QUERY, budget=5, vector=QVER, query_ts=ANCHOR)
        engine = make_engine(anchoring_case())
        new_rows = engine.recall(QUERY, budget=5, vector=QVER,
                                 query_ts=ANCHOR, mode="spatial")
        self.assertEqual([row["entry"]["id"] for row in old_rows],
                         ["d%d" % (i + 1) for i in range(5)])
        self.assertEqual([row["entry"]["id"] for row in new_rows],
                         ["o%d" % (i + 1) for i in range(5)])
        self.assertEqual(engine._last_spatial_select["pool"], 30)
        self.assertEqual(engine._last_spatial_select["selected"], 20)

    def test_switch_on_runs_selection_without_a_mode(self):
        engine = make_engine(anchoring_case(), flags={"spatial_select": True})
        rows = engine.recall(QUERY, budget=5, vector=QVER, query_ts=ANCHOR)
        self.assertEqual([row["entry"]["id"] for row in rows],
                         ["o%d" % (i + 1) for i in range(5)])
        self.assertEqual(engine._last_spatial_select["selected"], 20)

    def test_switch_off_keeps_the_old_path(self):
        rows = anchoring_case()
        engine = make_engine(rows)
        got = engine.recall(QUERY, budget=5, vector=QVER)
        self.assertIsNone(engine._last_spatial_select)
        ref = recall_entries(copy.deepcopy(rows), QUERY, budget=5, vector=QVER,
                             embedder=None, three_channel=False, now=NOW,
                             cue_scorer=cue_score)
        self.assertEqual([row["entry"]["id"] for row in got],
                         [row["entry"]["id"] for row in ref])
        self.assertEqual([row["score"] for row in got],
                         [row["score"] for row in ref])

    def test_mode_spatial_needs_no_switch(self):
        engine = make_engine(anchoring_case())
        rows = engine.recall(QUERY, budget=5, vector=QVER, query_ts=ANCHOR,
                             mode="spatial")
        self.assertEqual([row["entry"]["id"] for row in rows],
                         ["o%d" % (i + 1) for i in range(5)])
        self.assertTrue(engine._last_spatial_select["enabled"])

    def test_spatial_true_only_reorders_it_does_not_preselect(self):
        engine = make_engine(anchoring_case())
        rows = engine.recall(QUERY, budget=5, vector=QVER, query_ts=ANCHOR,
                             spatial=True)
        self.assertIsNone(engine._last_spatial_select)
        self.assertEqual([row["entry"]["id"] for row in rows],
                         ["d%d" % (i + 1) for i in range(5)])

    def test_empty_pool_still_recalls(self):
        engine = make_engine([])
        self.assertEqual(engine.recall(QUERY, budget=5, mode="spatial"), [])
        self.assertEqual(engine._last_spatial_select["selected"], 0)


class RememberCoordinatesTest(unittest.TestCase):
    """The engine write path carries the same coordinates as the host pipeline."""

    TEXT = "小夏周五去医院复查"

    def engine(self, flags):
        return MemoryEngine(config={"flags": dict(flags)}, now=lambda: NOW)

    def test_remember_writes_the_five_axes(self):
        engine = self.engine({"spatial_recall": True})
        added = engine.remember({"text": self.TEXT, "role": "user",
                                 "ts": NOW - 120})
        self.assertIsNotNone(added)
        coords = added.get("space")
        self.assertIsInstance(coords, dict)
        self.assertEqual(coords["schema"], sp.SCHEMA)
        self.assertEqual(set(coords), set(sp.AXES) | {"schema", "version",
                                                      "refreshed_at", "drift",
                                                      "event"})
        self.assertEqual(coords["version"], 1)
        self.assertEqual(coords["refreshed_at"], 0.0)
        self.assertEqual(coords["time"]["ts"], round(NOW - 120, 3))
        self.assertEqual(coords["semantic"]["fingerprint"],
                         sp.fingerprint(self.TEXT))
        self.assertTrue(coords["semantic"]["fallback"])   # no vector supplied

    def test_remember_off_writes_no_coordinates(self):
        added = self.engine({}).remember({"text": self.TEXT, "role": "user",
                                          "ts": NOW - 120})
        self.assertIsNotNone(added)
        self.assertNotIn("space", added)
        self.assertEqual(added["text"], self.TEXT)

    def test_written_coordinates_are_selectable(self):
        engine = self.engine({"spatial_recall": True})
        older = engine.remember({"text": "上个月在海边住了一晚", "role": "user",
                                 "ts": NOW - 30 * DAY})
        newer = engine.remember({"text": "今天又去海边了", "role": "user",
                                 "ts": NOW - 60})
        out = engine.spatial_rank("海边", query_ts=NOW, limit=2)
        self.assertEqual(out["ids"], [newer["id"], older["id"]])
        self.assertEqual(out["pool"], 2)

    def test_remember_keeps_the_affect_pair_it_was_given(self):
        engine = self.engine({"spatial_recall": True, "affect_encoding": False})
        added = engine.remember({"text": self.TEXT, "role": "user",
                                 "ts": NOW, "affect": {"v": -0.6, "a": 0.9}})
        self.assertEqual(added["space"]["affect"]["v"], -0.6)
        self.assertAlmostEqual(added["space"]["affect"]["a"], 0.9, places=6)


class HostPathTest(unittest.TestCase):
    """The biocore_runtime host path reaches the same selector."""

    TEXTS = ("today we went to the sea again",
             "last month we stayed one night by the sea",
             "xiaoxia goes to the hospital on friday")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = self._tmp.name
        for text in self.TEXTS:
            pipeline.tool_call("remember", {"text": text, "tags": ["travel"]},
                               self.store, session_id="s1")

    def tearDown(self):
        self._tmp.cleanup()

    def recall(self, **args):
        return pipeline.tool_call("recall", dict(args), self.store,
                                  session_id="s1")

    def test_host_recall_selects_nothing_by_default(self):
        out = self.recall(query="we went to the sea", limit=2)
        self.assertIsNone(out.get("spatial_select"))
        self.assertEqual(len(out["results"]), 2)

    def test_host_recall_mode_spatial_reports_the_selection(self):
        plain = self.recall(query="we went to the sea", limit=2)
        picked = self.recall(query="we went to the sea", limit=2, mode="spatial")
        report = picked["spatial_select"]
        self.assertTrue(report["enabled"])
        self.assertEqual(report["pool"], len(self.TEXTS))
        self.assertEqual(report["depth"], config.SPATIAL_SELECT_DEPTH)
        self.assertEqual([row["id"] for row in picked["results"]],
                         [row["id"] for row in plain["results"]])

    def test_host_recall_reads_the_store_switch(self):
        path = Path(self.store) / "flags.json"
        path.write_text(json.dumps({"spatial_select": True}), encoding="utf-8")
        out = self.recall(query="we went to the sea", limit=2)
        self.assertTrue(out["spatial_select"]["enabled"])


if __name__ == "__main__":
    unittest.main()
