# -*- coding: utf-8 -*-
"""S4: standardised axis distances and dead-axis removal.

Mahalanobis 1936: divide each axis distance by the store-wide standard
deviation for that axis. Kriegeskorte & Kievit 2013: a dimension that does
not vary carries no information, so an axis with no spread is dead and its
weight goes to zero. Below the sample floor the equal-weight raw sum is used.
"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory import space as sp  # noqa: E402
from biocore_memory.engine import MemoryEngine  # noqa: E402
from biocore_memory.store.json_store import MemoryStore  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400.0
QUERY = "q"
QVEC = [1.0] + [0.0] * 7


def row(index, ts, vec, **extra):
    item = {"id": "e%02d" % index, "text": QUERY + " %d" % index,
            "role": "user", "ts": ts, "tags": [], "importance": 0.5,
            "hits": 1, "scope": "default", "vector": list(vec)}
    item.update(extra)
    return item


def varied(count=40):
    rows = []
    for index in range(count):
        vec = [math.cos(index * 0.3 + dim) for dim in range(8)]
        rows.append(row(index, NOW - (index % 9) * 600.0, vec,
                        affect={"v": math.sin(index * 0.7) * 0.8,
                                "a": 0.3 + (index % 4) * 0.15},
                        importance=0.2 + (index % 5) * 0.15,
                        hits=1 + index % 3,
                        trust=0.2 + (index % 6) * 0.1,
                        closeness=0.3 + (index % 4) * 0.1))
    return rows


def flat_affect(count=40):
    rows = varied(count)
    for item in rows:
        item["affect"] = {"v": 0.0, "a": 0.5}
    return rows


def flip_rows(seed=1, count=40):
    rows = []
    for index in range(count):
        vec = [math.cos(seed + index * 0.7 + dim) for dim in range(8)]
        rows.append(row(index, NOW - (index * (37 + seed % 11)) * 3600.0, vec,
                        affect={"v": math.sin(seed * 1.3 + index * 0.4) * 0.9,
                                "a": 0.5}))
    return rows


def ranked(rows, flags, limit=5):
    return sp.rank(rows, QUERY, query_ts=NOW, limit=limit, vector=QVEC,
                   flags=dict(flags))


class SwitchTest(unittest.TestCase):
    """Default ON; the switch and the sample floor are the two doors."""

    def test_standardize_is_on_by_default(self):
        self.assertTrue(sp.standardize_enabled({}))
        self.assertFalse(sp.standardize_enabled({"spatial_standardize": False}))
        self.assertFalse(sp.standardize_enabled(
            {}, {"BIOCORE_SPATIAL_STANDARDIZE": "off"}))
        self.assertTrue(sp.standardize_enabled(
            {}, {"BIOCORE_SPATIAL_STANDARDIZE": "1"}))

    def test_a_small_store_falls_back_to_the_raw_sum(self):
        out = ranked(varied(20), {})
        self.assertEqual(out["standardize"]["mode"], "raw")
        self.assertEqual(out["standardize"]["reason"], "small_sample")
        top = out["results"][0]
        self.assertEqual(top["weighted"],
                         sp.weighted_distance(top["distance"], out["weights"]))

    def test_a_large_store_standardises(self):
        out = ranked(varied(40), {})
        self.assertEqual(out["standardize"]["mode"], "zscore")
        self.assertGreater(out["standardize"]["sample"], 0)
        self.assertEqual(sorted(out["standardize"]["axis_std"]), sorted(sp.AXES))


class DeadAxisTest(unittest.TestCase):
    """An axis with no spread carries no information."""

    def test_a_constant_axis_is_dead_and_weighted_out(self):
        rows = flat_affect(40)
        stats = sp.axis_stats(rows, now=NOW)
        self.assertIn("affect", sp.dead_axes(stats))
        weights = sp.standardized_weights(stats, sp.weights({}))
        self.assertEqual(weights["affect"], 0.0)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)

    def test_a_varying_axis_stays_alive(self):
        stats = sp.axis_stats(varied(40), now=NOW)
        self.assertNotIn("affect", sp.dead_axes(stats))
        weights = sp.standardized_weights(stats, sp.weights({}))
        self.assertGreater(weights["affect"], 0.0)

    def test_the_dead_axis_does_not_move_the_order(self):
        rows = flat_affect(40)
        out = ranked(rows, {})
        dead = out["standardize"]["dead_axes"]
        self.assertIn("affect", dead)
        self.assertEqual(out["standardize"]["weights"]["affect"], 0.0)


class ScaleTest(unittest.TestCase):
    """Every live axis is expressed in the same unit after standardising."""

    def test_each_axis_z_has_zero_mean_and_unit_std(self):
        rows = varied(40)
        stats = sp.axis_stats(rows, now=NOW)
        spaces = [sp.build(item, now=NOW) for item in rows]
        pairs = sp.sample_pairs(spaces)
        for axis in sp.AXES:
            row = stats["axes"][axis]
            self.assertGreater(row["std"], 0.0, axis)
            mean, std = row["mean"], row["std"]
            values = [sp.distance(left, right)[axis] for left, right in pairs]
            z = [(value - mean) / std for value in values]
            self.assertAlmostEqual(sum(z) / len(z), 0.0, places=4)
            variance = sum(value * value for value in z) / len(z)
            self.assertAlmostEqual(variance, 1.0, places=4)   # rounded std

    def test_the_score_is_the_weighted_z_sum(self):
        rows = varied(40)
        out = ranked(rows, {}, limit=3)
        stats = sp.axis_stats(rows, now=NOW)
        weights = out["standardize"]["weights"]
        for item in out["results"]:
            expected = sp.standardized_distance(item["distance"], stats, weights)
            self.assertAlmostEqual(item["weighted"], expected, places=6)


class OrderingTest(unittest.TestCase):
    """Switch off is the old ordering; standardising re-weights the axes."""

    def test_switching_off_restores_the_raw_sum(self):
        rows = varied(40)
        on = ranked(rows, {"spatial_standardize": False})
        self.assertEqual(on["standardize"]["mode"], "raw")
        self.assertEqual(on["standardize"]["reason"], "switch_off")
        for item in on["results"]:
            self.assertEqual(item["weighted"], item["weighted_raw"])

    def test_standardising_changes_the_order(self):
        rows = flip_rows(1)
        on = ranked(rows, {"spatial_standardize": True})
        off = ranked(rows, {"spatial_standardize": False})
        self.assertEqual(on["standardize"]["mode"], "zscore")
        self.assertNotEqual([r["id"] for r in on["results"]],
                            [r["id"] for r in off["results"]])

    def test_the_bucketed_and_exact_paths_agree_under_zscore(self):
        rows = varied(60)
        bucketed = sp.select(rows, QUERY, query_ts=NOW, limit=5, vector=QVEC,
                             flags={"spatial_index_threshold": 1})
        exact = sp.select(rows, QUERY, query_ts=NOW, limit=5, vector=QVEC,
                          flags={"spatial_index": False})
        self.assertEqual(bucketed["index"]["mode"], "bucketed")
        self.assertEqual(bucketed["standardize"]["mode"], "zscore")
        self.assertEqual(bucketed["ids"], exact["ids"])


class ReportTest(unittest.TestCase):
    """The dead axes are visible where the host looks."""

    def test_the_engine_payload_reports_the_dead_axes(self):
        engine = MemoryEngine(store=MemoryStore(doc={"entries": flat_affect(40)}),
                              now=lambda: NOW)
        out = engine.spatial_rank(QUERY, query_ts=NOW, limit=3, vector=QVEC)
        self.assertIn("affect", out["standardize"]["dead_axes"])

    def test_state_reports_space_stats(self):
        with tempfile.TemporaryDirectory() as store:
            path = Path(store) / "sessions" / "s1" / "memory.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"entries": flat_affect(40)}),
                            encoding="utf-8")
            out = pipeline.dispatch("state", {"session_id": "s1",
                                              "store": store})
            view = out["state"]["space"]
            self.assertEqual(view["mode"], "zscore")
            self.assertIn("affect", view["dead_axes"])
            self.assertIn("axis_std", view)


if __name__ == "__main__":
    unittest.main()
