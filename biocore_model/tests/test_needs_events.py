# -*- coding: utf-8 -*-
"""P1-3 need-event hook tests (needs_events.py + main wiring)."""
import ast
import json
import types
import unittest
from pathlib import Path

from biocore_model import needs_events as ne

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"
SOURCE = MAIN.read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))


def _load_helper():
    tree = ast.parse(SOURCE)
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef)
                and item.name == "_apply_needs_events")
    clone = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                            decorator_list=[], returns=node.returns,
                            type_comment=None, lineno=node.lineno,
                            col_offset=node.col_offset,
                            end_lineno=node.end_lineno,
                            end_col_offset=node.end_col_offset)
    log = []
    ns = {"logger": types.SimpleNamespace(
        info=lambda *a, **k: log.append(a),
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None)}
    exec(compile(ast.Module(body=[clone], type_ignores=[]),
                 "<_apply_needs_events>", "exec"), ns)
    return ns[node.name], log


HELPER, LOG = _load_helper()


class FakeCore:
    def __init__(self, needs=None):
        self.needs = dict(needs or ne.DEFAULT_NEEDS)


class FakePlugin:
    def __init__(self, enabled=True):
        self.needs_events_enabled = enabled


class NeedsStateTest(unittest.TestCase):
    def test_defaults_and_clamps(self):
        state = ne.needs_state({"belonging": 5, "control": -2})
        self.assertEqual(state["belonging"], 1.0)
        self.assertEqual(state["control"], 0.0)
        self.assertEqual(state["self_esteem"], ne.BASELINE)
        self.assertEqual(ne.needs_state(None), ne.DEFAULT_NEEDS)


class EventEffectTest(unittest.TestCase):
    def _apply(self, kind, strength=1.0, needs=None):
        needed = dict(needs or ne.DEFAULT_NEEDS)
        return ne.apply(needed, [{"kind": kind, "strength": strength}])

    def test_praised_raises_self_esteem(self):
        after, report = self._apply("praised")
        self.assertGreater(after["self_esteem"], ne.BASELINE)
        self.assertGreater(after["belonging"], ne.BASELINE)
        self.assertGreater(report["deltas"]["self_esteem"], 0)

    def test_rejected_lowers_belonging_and_esteem(self):
        after, report = self._apply("rejected")
        self.assertLess(after["belonging"], ne.BASELINE)
        self.assertLess(after["self_esteem"], ne.BASELINE)
        self.assertLess(report["deltas"]["belonging"], 0)

    def test_ignored_lowers_belonging_and_meaning(self):
        after, _report = self._apply("ignored")
        self.assertLess(after["belonging"], ne.BASELINE)
        self.assertLess(after["meaningful_existence"], ne.BASELINE)

    def test_single_event_is_capped(self):
        after, report = self._apply("rejected", strength=1.0)
        self.assertEqual(report["deltas"]["belonging"], -ne.CAPS["belonging"])
        after2, report2 = ne.apply(ne.DEFAULT_NEEDS,
                                   [{"kind": "rejected", "strength": 1.0}] * 5)
        self.assertEqual(report2["deltas"]["belonging"], -ne.CAPS["belonging"])
        self.assertGreaterEqual(after2["belonging"], 0.0)

    def test_needs_stay_in_range(self):
        low = {key: 0.01 for key in ne.NEED_KEYS}
        after, _report = ne.apply(low, [{"kind": "abandoned",
                                         "strength": 1.0}] * 4)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in after.values()))
        self.assertEqual(after["belonging"], 0.0)

    def test_zero_strength_is_noop(self):
        after, report = ne.apply(ne.DEFAULT_NEEDS,
                                 [{"kind": "praised", "strength": 0.0}])
        self.assertEqual(after, ne.DEFAULT_NEEDS)
        self.assertEqual(report["events"], [])
        str_after, _ = ne.apply(ne.DEFAULT_NEEDS,
                                [{"kind": "praised", "strength": 0}])
        self.assertEqual(str_after, ne.DEFAULT_NEEDS)

    def test_apply_does_not_mutate_input(self):
        source = dict(ne.DEFAULT_NEEDS)
        before = dict(source)
        ne.apply(source, [{"kind": "praised", "strength": 1.0}])
        self.assertEqual(source, before)

    def test_scale_factor(self):
        _after, full = ne.apply(ne.DEFAULT_NEEDS, [{"kind": "praised"}])
        _after2, half = ne.apply(ne.DEFAULT_NEEDS, [{"kind": "praised"}],
                                 scale=0.5)
        self.assertAlmostEqual(half["deltas"]["self_esteem"],
                               full["deltas"]["self_esteem"] / 2.0)

    def test_invalid_events_are_safe(self):
        after, report = ne.apply(None, "nope")
        self.assertEqual(after, ne.DEFAULT_NEEDS)
        self.assertEqual(report["events"], [])
        after2, _ = ne.apply(ne.DEFAULT_NEEDS, [{"kind": "unknown"}])
        self.assertEqual(after2, ne.DEFAULT_NEEDS)


class DimsEventsTest(unittest.TestCase):
    def test_positive_dims(self):
        kinds = {event["kind"]
                 for event in ne.events_from_dims({"goal": 0.8, "involve": 0.7})}
        self.assertIn("achieved", kinds)
        self.assertIn("connected", kinds)

    def test_negative_dims(self):
        kinds = {event["kind"]
                 for event in ne.events_from_dims({"hit": 0.9, "blame": 0.6})}
        self.assertIn("rejected", kinds)

    def test_neutral_dims_no_events(self):
        self.assertEqual(ne.events_from_dims({"goal": 0.0, "hit": 0.0,
                                              "involve": 0.1}), [])
        self.assertEqual(ne.events_from_dims(None), [])


class BehaviorChainTest(unittest.TestCase):
    def test_deficit_biases_contact_and_clarify(self):
        low = dict(ne.DEFAULT_NEEDS, belonging=0.2, control=0.25)
        bias = ne.behavior_bias(low)
        self.assertGreaterEqual(bias["seek_contact"], 0.6)
        self.assertGreater(bias["ask_clarify"], 0.0)

    def test_surplus_biases_sharing(self):
        high = dict(ne.DEFAULT_NEEDS, meaningful_existence=0.95,
                    self_esteem=0.9)
        bias = ne.behavior_bias(high)
        self.assertGreater(bias["share_meaning"], 0.0)
        self.assertGreater(bias["self_assert"], 0.0)

    def test_event_to_needs_to_behavior_chain(self):
        before = ne.behavior_bias(ne.DEFAULT_NEEDS)
        dims = {"hit": 0.9, "blame": 0.7, "involve": 0.0}
        events = ne.events_from_dims(dims)
        after_needs, report = ne.apply(ne.DEFAULT_NEEDS, events)
        after = ne.behavior_bias(after_needs)
        self.assertGreater(after["seek_contact"], before["seek_contact"])
        self.assertLess(after_needs["belonging"],
                        ne.DEFAULT_NEEDS["belonging"])
        self.assertTrue(report["deltas"]["belonging"] < 0)


class WiringTest(unittest.TestCase):
    def test_main_markers(self):
        self.assertIn("def _apply_needs_events(plugin, core, dims)", SOURCE)
        self.assertIn("_apply_needs_events(self, core, _inline.get(\"dims\"))",
                      SOURCE)
        self.assertIn("needs_events as _needs_mod", SOURCE)
        self.assertIn("needs_behavior", SOURCE)
        self.assertIn("[biocore] needs events=", SOURCE)

    def test_schema_default_on(self):
        self.assertIn("needs_events_enabled", SCHEMA)
        self.assertTrue(SCHEMA["needs_events_enabled"]["default"])

    def test_helper_writes_needs_and_bias(self):
        plugin = FakePlugin()
        core = FakeCore()
        LOG.clear()
        report = HELPER(plugin, core, {"hit": 0.9, "blame": 0.7})
        self.assertLess(core.needs["belonging"], ne.BASELINE)
        self.assertIn("seek_contact", core.needs_behavior)
        self.assertTrue(report["events"])
        self.assertTrue(any("needs events" in str(row) for row in LOG))

    def test_helper_disabled_and_neutral_are_noops(self):
        core = FakeCore()
        before = dict(core.needs)
        HELPER(FakePlugin(enabled=False), core, {"hit": 0.9})
        self.assertEqual(core.needs, before)
        HELPER(FakePlugin(), core, {"hit": 0.0})
        self.assertEqual(core.needs, before)
        self.assertFalse(hasattr(core, "needs_behavior"))


if __name__ == "__main__":
    unittest.main()
