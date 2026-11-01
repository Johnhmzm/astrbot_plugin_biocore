# -*- coding: utf-8 -*-
"""P1-1 predictive coding tests (predictor.py + main wiring)."""
import ast
import json
import types
import unittest
from pathlib import Path

from biocore_model import predictor as pr
from biocore_model import policy_learning as pl

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

STATE = {"v": 0.2, "a": 0.5, "d": 0.5, "social": 0.6, "stress": 0.3,
         "energy": 0.6, "trust": 0.6, "emotion": "joy",
         "needs": {"belonging": 0.5, "self_esteem": 0.6, "control": 0.4,
                   "meaningful_existence": 0.7}}


def _load_cycle():
    tree = ast.parse(SOURCE)
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef)
                and item.name == "_predictive_cycle")
    clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                            decorator_list=[], returns=node.returns,
                            type_comment=None, lineno=node.lineno,
                            col_offset=node.col_offset,
                            end_lineno=node.end_lineno,
                            end_col_offset=node.end_col_offset)
    state_node = next(item for item in tree.body
                      if isinstance(item, ast.FunctionDef)
                      and item.name == "_prediction_state")
    state_clone = ast.FunctionDef(name=state_node.name, args=state_node.args,
                                  body=state_node.body, decorator_list=[],
                                  returns=state_node.returns, type_comment=None,
                                  lineno=state_node.lineno,
                                  col_offset=state_node.col_offset,
                                  end_lineno=state_node.end_lineno,
                                  end_col_offset=state_node.end_col_offset)
    log = []
    ns = {"logger": types.SimpleNamespace(
        info=lambda *a, **k: log.append(a),
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None)}
    exec(compile(ast.Module(body=[state_clone, clone], type_ignores=[]),
                 "<_predictive_cycle>", "exec"), ns)
    return ns[node.name], log


CYCLE, LOG = _load_cycle()


class FakeCore:
    def __init__(self, state=None):
        for key, value in (state or STATE).items():
            setattr(self, key, value)
        self.labels = {"emotion": (state or STATE).get("emotion", "joy")}


class FakePlugin:
    def __init__(self, enabled=True):
        self.predictive_enabled = enabled
        self._next_prediction = None
        self._predict_history = []


class VectorTest(unittest.TestCase):
    def test_vector_clamps_and_orders(self):
        vec = pr.vector({"v": 9, "a": -3, "d": "x", "social": 0.4})
        self.assertEqual(list(vec), list(pr.CHANNELS))
        self.assertEqual(vec["v"], 1.0)
        self.assertEqual(vec["a"], 0.0)
        self.assertEqual(vec["d"], 0.0)
        self.assertEqual(vec["social"], 0.4)

    def test_predict_flat_state_is_current(self):
        pred = pr.predict(STATE)
        self.assertEqual(pred["channels"], pr.vector(STATE))
        self.assertEqual(pred["emotion"], "joy")

    def test_predict_follows_damped_trend(self):
        history = [dict(pr.vector(STATE), v=0.0), pr.vector(STATE)]
        pred = pr.predict(STATE, history=history)
        self.assertEqual(pred["channels"]["v"], 0.3)
        rising = [pr.vector({"v": 0.0}), pr.vector({"v": 0.1})]
        pred2 = pr.predict({"v": 0.1}, history=rising)
        self.assertAlmostEqual(pred2["channels"]["v"], 0.15)
        self.assertGreater(pred2["confidence"], pr.predict(STATE)["confidence"])

    def test_slope_is_clamped(self):
        history = [pr.vector({"v": -1.0}), pr.vector({"v": 1.0})]
        pred = pr.predict({"v": 1.0}, history=history)
        self.assertLessEqual(pred["channels"]["v"], 1.0)
        self.assertAlmostEqual(pred["channels"]["v"], 1.0)

    def test_needs_drift_toward_baseline(self):
        pred = pr.predict(STATE)
        self.assertGreater(pred["needs"]["belonging"], 0.5)
        self.assertLess(pred["needs"]["meaningful_existence"], 0.7)


class CompareTest(unittest.TestCase):
    def test_identical_state_has_no_surprise(self):
        pred = pr.predict(STATE)
        report = pr.compare(pred, STATE)
        self.assertEqual(report["error"], 0.0)
        self.assertEqual(report["surprise"], 0.0)
        self.assertTrue(report["emotion_hit"])

    def test_large_change_raises_surprise(self):
        pred = pr.predict(STATE)
        changed = dict(STATE, v=-0.6, a=0.95, stress=0.9, emotion="anger")
        report = pr.compare(pred, changed)
        self.assertGreater(report["error"], 0.1)
        self.assertGreaterEqual(report["surprise"], 0.5)
        self.assertFalse(report["emotion_hit"])
        self.assertEqual(report["actual_emotion"], "anger")
        self.assertEqual(report["channels"]["v"]["error"], 0.8)

    def test_needs_error_reported(self):
        pred = pr.predict(STATE)
        changed = dict(STATE, needs={"belonging": 0.1, "self_esteem": 0.6,
                                     "control": 0.4, "meaningful_existence": 0.7})
        report = pr.compare(pred, changed)
        self.assertGreater(report["needs_error"], 0.0)

    def test_surprise_bounds_and_monotonicity(self):
        values = [pr.surprise(x) for x in (0.0, 0.05, 0.1, 0.25, 1.0)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], 0.0)
        self.assertEqual(values[-1], 1.0)


class EffectScaleTest(unittest.TestCase):
    def test_attention_boost_monotone_bounded(self):
        values = [pr.attention_boost(x) for x in (0.0, 0.2, 0.5, 1.0)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], 0.0)
        self.assertEqual(values[-1], 1.0)

    def test_learning_rate_scale_monotone_bounded(self):
        low = pr.learning_rate_scale(0.0)
        high = pr.learning_rate_scale(1.0)
        self.assertEqual(low, 0.6)
        self.assertEqual(high, 1.8)
        self.assertLess(low, high)
        custom = pr.learning_rate_scale(0.5, low=0.5, high=2.0)
        self.assertAlmostEqual(custom, 1.25)

    def test_scale_feeds_policy_alpha(self):
        # The main wiring multiplies the policy-learning alpha by the scale.
        self.assertIn("_prediction_lr_scale", SOURCE)
        self.assertIn("alpha=_lr", SOURCE)
        slow_table = pl.update({}, "ctx", "approach", 1.0, alpha=0.1)
        fast_table = pl.update({}, "ctx", "approach", 1.0, alpha=0.4)
        slow_q = float(slow_table["ctx"]["approach"]["q"])
        fast_q = float(fast_table["ctx"]["approach"]["q"])
        self.assertLess(slow_q, fast_q)


class HistoryTest(unittest.TestCase):
    def test_append_history_bounded_and_non_mutating(self):
        history = [pr.vector({"v": i / 20.0}) for i in range(6)]
        snapshot = list(history)
        grown = pr.append_history(history, pr.vector({"v": 0.9}))
        self.assertEqual(history, snapshot)
        self.assertEqual(len(grown), pr.MAX_HISTORY)
        self.assertEqual(grown[-1]["v"], 0.9)

    def test_invalid_inputs_are_safe(self):
        self.assertTrue(all(v == 0.0 for v in pr.vector(None).values()))
        self.assertEqual(pr.predict(None)["emotion"], "neutral")
        self.assertEqual(pr.compare(None, None)["surprise"], 0.0)
        self.assertEqual(pr.append_history("x", "y"), [])
        self.assertEqual(pr.summary(None)["surprise"], 0.0)


class WiringTest(unittest.TestCase):
    def test_main_wiring_markers(self):
        self.assertIn("def _predictive_cycle(plugin, core)", SOURCE)
        self.assertIn("_predictive_cycle(self, core)", SOURCE)
        self.assertIn("attention_boost", SOURCE)
        self.assertIn("_retrieval_limit + 1", SOURCE)
        self.assertIn("predictor as _predictor", SOURCE)
        self.assertIn("[biocore] predict surprise=", SOURCE)

    def test_schema_and_config_default(self):
        self.assertIn("predictive_enabled", SCHEMA)
        self.assertTrue(SCHEMA["predictive_enabled"]["default"])
        self.assertIn('self.config.get("predictive_enabled", True)', SOURCE)

    def _run(self, plugin, core):
        return CYCLE(plugin, core)

    def test_cycle_records_error_and_predicts_next(self):
        plugin = FakePlugin()
        core = FakeCore()
        LOG.clear()
        self.assertEqual(self._run(plugin, core), {})
        self.assertIsNotNone(plugin._next_prediction)
        changed = dict(STATE, v=-0.7, stress=0.9, emotion="anger")
        core2 = FakeCore(changed)
        report = self._run(plugin, core2)
        row = pr.summary(report)
        self.assertGreater(report["surprise"], 0.0)
        self.assertEqual(core2.prediction_surprise, row["surprise"])
        self.assertAlmostEqual(core2.learning_rate_scale,
                               row["learning_rate_scale"], places=3)
        self.assertGreaterEqual(core2.attention_boost, 0.0)
        self.assertTrue(any("predict" in str(row) for row in LOG))
        self.assertEqual(plugin._prediction_lr_scale,
                         core2.learning_rate_scale)

    def test_cycle_disabled_is_noop(self):
        plugin = FakePlugin(enabled=False)
        core = FakeCore()
        self.assertEqual(self._run(plugin, core), {})
        self.assertIsNone(plugin._next_prediction)
        self.assertFalse(hasattr(core, "prediction_surprise"))


if __name__ == "__main__":
    unittest.main()
