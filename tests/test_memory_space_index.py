# -*- coding: utf-8 -*-
"""Sign-pattern LSH buckets above a threshold (spatial_index, default ON).

The bucket is a pruning structure, not an approximation: every bucket keeps a
unit centroid and a radius, which lower-bounds the cosine distance from the
query to any member, so a bucket can only be skipped when nothing inside could
beat the current k-th row. The bucketed answer must therefore be identical to
the full traversal, row for row -- the tests compare both paths directly.
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory import space as sp  # noqa: E402
from biocore_memory.core import config  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402

NOW = 1_700_000_000.0
QUERY = "周五开会"
QVEC = [1.0] + [0.0] * 7
BUCKET_1 = {"spatial_index_threshold": 1}


def vector(seed, dim=8):
    return [math.cos(seed + index) for index in range(dim)]


def entry(entry_id, ts, vec=None, **extra):
    row = {"id": entry_id, "text": QUERY + " " + entry_id, "role": "user",
           "ts": ts, "tags": [], "importance": 0.5, "hits": 1,
           "scope": "default", "affect": {"v": 0.0, "a": 0.5}}
    if vec is not None:
        row["vector"] = list(vec)
    row.update(extra)
    return row


def varied_rows(count=60):
    return [entry("e%02d" % index, NOW - index * 3600.0, vector(index / 5.0),
                  affect={"v": ((index % 3) - 1) * 0.3, "a": 0.4},
                  importance=0.3 + (index % 4) * 0.1)
            for index in range(count)]


def clustered_rows(per_cluster=20):
    rows = [entry("near%02d" % index, NOW, [1.0] + [0.1] * 7)
            for index in range(per_cluster)]
    rows += [entry("far%02d" % index, NOW, [-1.0] + [0.1] * 7)
             for index in range(per_cluster)]
    return rows


def run(rows, flags, limit=5, query_ts=NOW):
    return sp.select(rows, QUERY, query_ts=query_ts, limit=limit,
                     flags=dict(flags), vector=QVEC)


def ids(payload):
    return [row["id"] for row in payload["results"]]


class SwitchTest(unittest.TestCase):
    """The switch is ON by default; the threshold is configuration."""

    def test_index_is_on_by_default(self):
        self.assertTrue(sp.index_enabled({}))
        self.assertFalse(sp.index_enabled({"spatial_index": False}))
        self.assertFalse(sp.index_enabled({}, {"BIOCORE_SPATIAL_INDEX": "off"}))
        self.assertTrue(sp.index_enabled({}, {"BIOCORE_SPATIAL_INDEX": "1"}))

    def test_the_threshold_defaults_to_the_core_config(self):
        self.assertEqual(config.SPATIAL_INDEX_THRESHOLD, 5000)
        self.assertEqual(sp.index_threshold({}), 5000)
        self.assertEqual(sp.index_threshold({"spatial_index_threshold": 7}), 7)
        self.assertEqual(sp.index_threshold({},
                                            {"BIOCORE_SPATIAL_INDEX_THRESHOLD": "9"}), 9)
        self.assertEqual(sp.index_threshold({"spatial_index_threshold": "bad"}), 5000)


class PathTest(unittest.TestCase):
    """Bucketed and exact traversal must return the same rows."""

    def test_bucketed_and_exact_agree(self):
        rows = varied_rows()
        bucketed = run(rows, BUCKET_1)
        exact = run(rows, {"spatial_index": False})
        self.assertEqual(bucketed["index"]["mode"], "bucketed")
        self.assertEqual(exact["index"]["mode"], "exact")
        self.assertEqual(ids(bucketed), ids(exact))
        self.assertEqual([row["weighted"] for row in bucketed["results"]],
                         [row["weighted"] for row in exact["results"]])
        self.assertEqual([row["distance"] for row in bucketed["results"]],
                         [row["distance"] for row in exact["results"]])

    def test_below_the_threshold_the_exact_path_runs(self):
        out = run(varied_rows(20), {})
        self.assertEqual(out["index"]["mode"], "exact")
        self.assertEqual(out["index"]["buckets"], 0)

    def test_the_switch_off_forces_the_exact_path(self):
        rows = varied_rows()
        out = run(rows, {"spatial_index": False, "spatial_index_threshold": 1})
        self.assertEqual(out["index"]["mode"], "exact")
        self.assertEqual(ids(out), ids(run(rows, {"spatial_index": False})))

    def test_entries_without_vectors_agree_too(self):
        rows = [entry("t%02d" % index, NOW - index, None,
                      tags=["猫" if index % 2 else "工作"])
                for index in range(20)]
        bucketed = run(rows, BUCKET_1)
        exact = run(rows, {"spatial_index": False})
        self.assertEqual(bucketed["index"]["mode"], "bucketed")
        self.assertEqual(ids(bucketed), ids(exact))

    def test_a_far_bucket_is_skipped_and_the_answer_is_unchanged(self):
        rows = clustered_rows()
        bucketed = run(rows, BUCKET_1, limit=3)
        exact = run(rows, {"spatial_index": False}, limit=3)
        self.assertEqual(ids(bucketed), ids(exact))
        self.assertLess(bucketed["index"]["scanned"], bucketed["index"]["pool"])
        self.assertEqual(bucketed["index"]["pool"], len(rows))

    def test_ties_keep_the_same_order(self):
        rows = [entry("tie%02d" % index, NOW, [1.0] + [0.0] * 7)
                for index in range(12)]
        bucketed = run(rows, BUCKET_1, limit=4)
        exact = run(rows, {"spatial_index": False}, limit=4)
        self.assertEqual(ids(bucketed), ids(exact))
        self.assertEqual(ids(bucketed), ["tie00", "tie01", "tie02", "tie03"])


class EngineTest(unittest.TestCase):
    """engine.spatial_rank reaches the same index through the same selector."""

    def engine(self, flags):
        rows = [dict(row) for row in varied_rows()]
        return MemoryEngine(store=MemoryStore(doc={"entries": rows}),
                            config={"flags": dict(flags)}, now=lambda: NOW)

    def test_the_engine_reports_the_bucketed_path(self):
        out = self.engine(BUCKET_1).spatial_rank(QUERY, query_ts=NOW,
                                                 limit=3, vector=QVEC)
        self.assertEqual(out["index"]["mode"], "bucketed")
        self.assertGreater(out["index"]["buckets"], 0)
        off = self.engine({"spatial_index": False}).spatial_rank(
            QUERY, query_ts=NOW, limit=3, vector=QVEC)
        self.assertEqual(out["ids"], off["ids"])

    def test_the_threshold_flag_reaches_the_engine(self):
        out = self.engine({"spatial_index_threshold": 2}).spatial_rank(
            QUERY, query_ts=NOW, limit=3, vector=QVEC)
        self.assertEqual(out["index"]["mode"], "bucketed")


if __name__ == "__main__":
    unittest.main()
