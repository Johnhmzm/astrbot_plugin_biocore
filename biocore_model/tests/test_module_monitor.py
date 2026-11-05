# -*- coding: utf-8 -*-
"""task-241: per-module monitoring -- own view snapshot, own diff.

Run from the plugin root:

    python -m unittest discover -s biocore_model/tests -p "test_module_monitor.py"
"""
import json
import tempfile
import unittest
from pathlib import Path

from biocore_runtime import batch_registry as reg


NOW = 1700000000.0


def state():
    return {"core": {"v": -0.2, "a": 0.6, "stress": 0.55, "social": 0.45}}


class DriftingBatch(object):
    """A batch whose two modules move independently."""

    def __init__(self, forecast=0.2, confidence=0.4):
        self.forecast = forecast
        self.confidence = confidence

    def apply_turn(self, state, phase, payload):
        return {"enabled": True,
                "modules": {"predictor": True, "memory_dual": True,
                            "graph_recall": True},
                "activity": {"predictor": True, "memory_dual": True,
                             "graph_recall": True},
                "field_deltas": {}, "state_deltas": {}, "skipped": [],
                "reads": {"forecast": {"confidence": self.forecast},
                          "dual": {"picked": [{"score": self.confidence}]},
                          "graph": {"rows": 2}}}


class FlattenTest(unittest.TestCase):
    def test_nested_dicts_become_dotted_channels(self):
        flat = reg.flatten({"forecast": {"channels": {"v": 0.1, "a": 0.5}},
                            "count": 3})
        self.assertEqual(flat, {"forecast.channels.v": 0.1,
                                "forecast.channels.a": 0.5,
                                "count": 3.0})

    def test_bools_and_lists_and_noise(self):
        flat = reg.flatten({"flag": True, "off": False, "rows": [1, 2],
                            "text": "不是数字", "none": None})
        self.assertEqual(flat["flag"], 1.0)
        self.assertEqual(flat["off"], 0.0)
        self.assertEqual(flat["rows[0]"], 1.0)
        self.assertEqual(flat["rows[1]"], 2.0)
        self.assertNotIn("text", flat)
        self.assertNotIn("none", flat)

    def test_view_is_bounded(self):
        flat = reg.flatten({("k%d" % index): index for index in range(80)})
        self.assertLessEqual(len(flat), reg.VIEW_LIMIT)


class ModuleViewTest(unittest.TestCase):
    def test_b_module_owns_its_read_slice(self):
        row = reg.normalize("b", DriftingBatch().apply_turn({}, "turn_start", {}))
        view = reg.module_view("b", "predictor", row)
        self.assertEqual(view, {"forecast.confidence": 0.2})
        self.assertEqual(reg.module_view("b", "memory_dual", row),
                         {"dual.picked[0].score": 0.4})

    def test_module_without_a_slice_has_an_empty_view(self):
        row = reg.normalize("b", DriftingBatch().apply_turn({}, "turn_start", {}))
        self.assertEqual(reg.module_view("b", "migrate_store", row), {})

    def test_c_bundle_field_is_the_module_view(self):
        output = {"ok": True, "fields": ["metacog"],
                  "metacog": {"band": 0.3}, "deltas": {}}
        row = reg.normalize("c", output)
        self.assertEqual(reg.module_view("c", "metacog", row),
                         {"metacog.band": 0.3})


class DiffTest(unittest.TestCase):
    def test_diff_uses_the_1e_6_floor(self):
        self.assertEqual(reg.diff_view({"v": 0.1}, {"v": 0.1 + 5e-7}), {})
        self.assertEqual(reg.diff_view({"v": 0.1}, {"v": 0.2}), {"v": 0.1})

    def test_added_channel_counts_as_a_delta(self):
        self.assertEqual(reg.diff_view({}, {"v": 0.4}), {"v": 0.4})
        self.assertEqual(reg.diff_view({"v": 0.4}, {}), {"v": -0.4})

    def test_effect_is_bounded(self):
        before = {("k%d" % index): 0.0 for index in range(20)}
        after = {("k%d" % index): 0.1 * (index + 1) for index in range(20)}
        effect = reg.diff_view(before, after)
        self.assertEqual(len(effect), reg.EFFECT_LIMIT)
        self.assertIn("k19", effect)


class TickMonitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def tick(self, batch, now=NOW):
        return reg.tick(self.store, "s1", "turn_start", {}, state(), now=now,
                        hooks={"b": batch})

    def test_first_snapshot_is_zero_change(self):
        self.tick(DriftingBatch())
        doc = reg.read_monitor(self.store)
        row = doc["modules"]["b.predictor"]
        self.assertEqual(row["calls"], 1)
        self.assertEqual(row["changed"], 0)
        self.assertEqual(row["zero_change"], 1)
        self.assertEqual(row["last_effect"], {})
        self.assertEqual(row["view"], {"forecast.confidence": 0.2})

    def test_second_tick_reports_the_own_diff(self):
        self.tick(DriftingBatch(forecast=0.2))
        self.tick(DriftingBatch(forecast=0.5), now=NOW + 10)
        row = reg.read_monitor(self.store)["modules"]["b.predictor"]
        self.assertEqual(row["changed"], 1)
        self.assertEqual(row["zero_change"], 1)
        self.assertEqual(row["last_effect"], {"forecast.confidence": 0.3})

    def test_steady_module_stays_zero_change(self):
        self.tick(DriftingBatch())
        self.tick(DriftingBatch(), now=NOW + 10)
        row = reg.read_monitor(self.store)["modules"]["b.memory_dual"]
        self.assertEqual(row["zero_change"], 2)
        self.assertEqual(row["changed"], 0)
        self.assertEqual(row["last_effect"], {})

    def test_modules_in_one_batch_are_independent(self):
        self.tick(DriftingBatch(forecast=0.2, confidence=0.4))
        self.tick(DriftingBatch(forecast=0.9, confidence=0.4), now=NOW + 10)
        doc = reg.read_monitor(self.store)
        self.assertEqual(doc["modules"]["b.predictor"]["changed"], 1)
        self.assertEqual(doc["modules"]["b.memory_dual"]["changed"], 0)
        self.assertEqual(doc["modules"]["b.memory_dual"]["zero_change"], 2)
        # a module whose view never changes stays zero even when a sibling moved
        self.assertEqual(doc["modules"]["b.graph_recall"]["changed"], 0)

    def test_totals_carry_active_zero_change_and_errors(self):
        self.tick(DriftingBatch())
        self.tick(DriftingBatch(forecast=0.7), now=NOW + 10)
        totals = reg.summary(self.store)["totals"]
        self.assertEqual(totals["calls"], 6)
        self.assertEqual(totals["active"], 3)
        self.assertEqual(totals["changed"], 1)
        self.assertEqual(totals["zero_change"], 5)
        self.assertEqual(totals["errored"], 0)

    def test_monitor_doc_is_json_safe_and_persisted(self):
        self.tick(DriftingBatch())
        path = reg.path(self.store)
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("modules", doc)
        self.assertIn("totals", doc)
        row = doc["modules"]["b.predictor"]
        self.assertIsInstance(row["last_effect"], dict)
        json.dumps(doc)  # must not raise


if __name__ == "__main__":
    unittest.main()
