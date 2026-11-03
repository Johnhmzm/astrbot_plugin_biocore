# -*- coding: utf-8 -*-
"""Compatibility: every module's directive-like output through x_directives.

Three kinds of producers are covered (31 total, 24+ required):

- 13 modules with a dedicated directives(result) -> canonical directive dict;
- 2 payload() projections (boundary, self_intent) -> dashboard projection;
- 16 view() projections (attachment_state, envy, ...) -> panel read-only dict.

For each producer: build a typical output, normalize it, and assert the
canonical shape is complete, in range, idempotent, and merges cleanly. Then
exercise merge() on pairs, on five, and on all, plus tone priority, note
dedupe, clamping, aliases and malformed inputs.

diag_trace.view() is deliberately excluded: it returns a list of panel rows,
not a dict, so it is a display read rather than a producer.

Observed incompatibilities are RECORDED here, never fixed in the
producers (this file is the only write target; see
incompatibility_report()):

- payload()/view() projections carry no length/initiative/tone/allow_correction
  field, so normalize() returns the canonical defaults for those fields
  (structural compat via merge, semantic gap: they are panel projections,
  not hints). A "reason" field still lands in note via the alias.
- Some directives() fields have no canonical home and are dropped by
  normalize(): exit_or_silence {send, delay_seconds, action},
  dissonance {relief}, metacog {confidence}, attributor {emotion},
  compassion_fatigue {empathy}, narrative {allow_clarify is consumed only
  when True}, possible_selves {pull}, relation_stage {stage},
  repair_after_boundary {stage, warmth}, self_intent {kind, weight},
  value_order {chosen}, regulation_strategies {strategy, cost, effect,
  coping_tier}.
- narrative.directives() for a calm story returns tone="" and
  allow_clarify=False, i.e. it contributes no signal; callers must treat
  that as "no hint", not as "neutral override".
- merge() re-labels rows that were not marked "_x_normalized": passing
  normalize() output straight into merge() replaces the source name with
  "itemN", so tone priority can be lost. Use merge_named() or set
  "_x_normalized" before merging; test_normalize_output_is_relabelled_by_merge
  pins the current behaviour.

Nothing in the producing modules is changed.
"""
import unittest

from biocore_model import x_directives as xd

from biocore_model import (
    affective_labor, attachment_behavior, attachment_regulation,
    attachment_state, attribution, attributor, boundary, compassion_fatigue,
    defense_mechanisms, dissonance, envy, exit_or_silence,
    frustration_curve, granularity, intero_core, metacog, narrative,
    needs_esteem, needs_sleep, possible_selves, regulation_strategies,
    relation_stage, repair_after_boundary, secrecy, self_esteem, self_intent,
    self_verification, social_pain, social_repair, value_order,
)

# Canonical shape is whatever the contract module says it is.
CANONICAL_KEYS = frozenset(xd.normalize({}))
# Legacy spellings that normalize() already maps onto canonical fields.
ALIAS_KEYS = {
    "length": "length_scale",
    "proactive": "initiative",
    "allow_self_correction": "allow_correction",
    "allow_clarify": "allow_correction",
    "reason": "note",
}
# Keys that make an output "directive-shaped" rather than a panel projection.
DIRECTIVE_FIELDS = frozenset((
    "length_scale", "length", "initiative", "proactive", "tone",
    "allow_correction", "allow_self_correction", "allow_clarify",
))
# Directives producers that legitimately contribute nothing for a calm
# input; every other directives() output must carry at least one signal.
KNOWN_NO_SIGNAL_DIRECTIVES = frozenset(("narrative",))


# ---------------------------------------------------------------------------
# Typical inputs: one factory per producer (same output a caller would get).
# ---------------------------------------------------------------------------
def _attach():
    return attachment_behavior.directives(attachment_behavior.evaluate(
        "anxious", {"closeness": 0.7, "stress": 0.5, "ignored": True}))


def _attributor():
    return attributor.directives(attributor.attribute(
        {"blame": 0.8, "goal": -0.6, "hit": 0.6, "involve": 0.7},
        {"who": "you"}))


def _compassion():
    return compassion_fatigue.directives(compassion_fatigue.fatigue(8, 0.9, 0.0))


def _dissonance():
    return dissonance.directives(dissonance.strength(
        [{"text": "不熬夜", "weight": 0.8, "age_days": 1}],
        {"kind": "熬夜", "contradicts": ["不熬夜"]}))


def _exit():
    return exit_or_silence.directives(exit_or_silence.exit_or_silence(
        {"energy": 0.2, "stress": 0.8, "v": -0.4}, {"closeness": 0.4}))


def _metacog():
    return metacog.directives(metacog.evaluate(confidence=0.2, guard_hits=2))


def _narrative():
    events = [{"kind": "rupture", "text": "吵了一架", "valence": -0.6,
               "ts": 100.0, "importance": 0.8},
              {"kind": "repair", "text": "和好", "valence": 0.5,
               "ts": 200.0, "importance": 0.7}]
    return narrative.directives(narrative.summarize(events))


def _selves():
    return possible_selves.directives(possible_selves.rank(
        [{"name": "更会照顾人", "target": {"benevolence": 0.95},
          "importance": 0.9}],
        {"benevolence": 0.4}))


def _stage():
    return relation_stage.directives(relation_stage.evaluate(
        {"interactions": 20, "disclosures": 6, "repairs": 1,
         "days_known": 60, "conflict": 0.1}))


def _repair():
    return repair_after_boundary.directives(repair_after_boundary.start(
        {"kind": "insult", "severity": 0.7, "crossed": True},
        {"closeness": 0.6, "trust": 0.5}))


def _regulation():
    result = regulation_strategies.evaluate(
        {"v": -0.4, "a": 0.6, "stress": 0.8, "energy": 0.3,
         "social": 0.4, "control": 0.2},
        {"kind": "conflict", "text": "被指责", "valence": -0.6,
         "public": True},
        {"closeness": 0.6, "trust": 0.5})
    return regulation_strategies.directives(result)


def _self_intent_state():
    return self_intent.evaluate(
        {"v": -0.2, "stress": 0.6, "energy": 0.4},
        {"closeness": 0.6, "trust": 0.6},
        {"belonging": 0.3, "self_esteem": 0.5, "control": 0.4,
         "meaningful_existence": 0.5})


def _self_intent():
    return self_intent.directives(_self_intent_state())


def _self_intent_payload():
    return self_intent.payload(
        _self_intent_state(),
        pending_prompts=["问她周五体检结果"],
        voice_phrases=["少来。"],
        metacog={"band": "low", "confidence": 0.3,
                 "allow_self_correction": True, "low_streak": 2})


def _value_order():
    return value_order.directives(value_order.rank(
        [{"name": "保持现状", "keeps_status_quo": True},
         {"name": "改变", "gains": {"security": 0.9}}],
        value_order.defaults(), {"investment": 0.5,
                                 "relationship_age_days": 200}))


def _labor():
    return affective_labor.view(affective_labor.initial(0.0))


def _attach_state():
    return attachment_state.view({"activation": 0.6}, "anxious")


def _attribution():
    return attribution.view({"locus": "他", "stability": "总是",
                             "controllability": "能"},
                            {"locus": "他", "stability": "总是",
                             "controllability": "能"})


def _defense():
    return defense_mechanisms.view({"enabled": True, "mechanism": "rationalization",
                                    "label": "合理化", "strength": 0.5,
                                    "cost": 0.2, "reason": "给自己一个理由"})


def _envy():
    return envy.view({"enabled": True, "kind": "比较", "kind_key": "compare",
                      "intensity": 0.5, "tendency": "收敛",
                      "reason": "她开始拿自己比"})


def _granularity():
    state = {"v": 0.1, "a": 0.3, "d": 0.5, "social": 0.5,
             "trust": 0.5, "stress": 0.4}
    return granularity.view(granularity.from_state(state))


def _intero():
    return intero_core.view({"tension": 0.6, "warmth": 0.3,
                             "heaviness": 0.5, "clarity": 0.4})


def _secrecy():
    return secrecy.view(secrecy.initial(0.0))


def _self_esteem():
    return self_esteem.view(self_esteem.initial(0.0))


def _verification():
    return self_verification.view(self_verification.initial(0.0))


def _social_pain():
    return social_pain.view(social_pain.initial(0.0))


def _sleep():
    return needs_sleep.view(needs_sleep.defaults(0.0), 1.5)


def _esteem_need():
    return needs_esteem.view(needs_esteem.defaults(), 0.5)


def _social_repair():
    return social_repair.view(0.4, {"boundary": 0.3}, {"empathy": 0.4},
                              {"repair": 0.2}, {"gap_hours": 2.0})


def _boundary_payload():
    return boundary.payload(boundary.judge("滚", {"trust": 0.4,
                                                  "closeness": 0.5}))


def _attachment_regulation():
    return attachment_regulation.view(
        "anxious", 0.6, "hyperactivating", "reappraisal", 0.4, True,
        {"valence": -0.2})


def _frustration():
    return frustration_curve.view(5)


# name, factory, kind; kind is "directives", "payload" or "view".
PRODUCERS = (
    ("attachment_behavior", _attach, "directives"),
    ("attributor", _attributor, "directives"),
    ("compassion_fatigue", _compassion, "directives"),
    ("dissonance", _dissonance, "directives"),
    ("exit_or_silence", _exit, "directives"),
    ("metacog", _metacog, "directives"),
    ("narrative", _narrative, "directives"),
    ("possible_selves", _selves, "directives"),
    ("regulation_strategies", _regulation, "directives"),
    ("relation_stage", _stage, "directives"),
    ("repair_after_boundary", _repair, "directives"),
    ("self_intent", _self_intent, "directives"),
    ("value_order", _value_order, "directives"),
    ("boundary", _boundary_payload, "payload"),
    ("self_intent_payload", _self_intent_payload, "payload"),
    ("affective_labor", _labor, "view"),
    ("attachment_state", _attach_state, "view"),
    ("attribution", _attribution, "view"),
    ("defense_mechanisms", _defense, "view"),
    ("envy", _envy, "view"),
    ("granularity", _granularity, "view"),
    ("intero_core", _intero, "view"),
    ("secrecy", _secrecy, "view"),
    ("self_esteem", _self_esteem, "view"),
    ("self_verification", _verification, "view"),
    ("social_pain", _social_pain, "view"),
    ("needs_sleep", _sleep, "view"),
    ("needs_esteem", _esteem_need, "view"),
    ("social_repair", _social_repair, "view"),
    ("attachment_regulation", _attachment_regulation, "view"),
    ("frustration_curve", _frustration, "view"),
)

PRODUCER_NAMES = tuple(name for name, _, _ in PRODUCERS)
DIRECTIVE_PRODUCERS = tuple(name for name, _, kind in PRODUCERS
                            if kind == "directives")
PAYLOAD_PRODUCERS = tuple(name for name, _, kind in PRODUCERS
                          if kind == "payload")
PROJECTION_PRODUCERS = tuple(name for name, _, kind in PRODUCERS
                             if kind in ("payload", "view"))


def _produce(name):
    for label, factory, _kind in PRODUCERS:
        if label == name:
            return factory()
    raise KeyError(name)


def _normalized(name):
    return xd.normalize(_produce(name), name)


def _merge_ready(name, raw=None):
    """A normalized row that merge() will not relabel (contract flag)."""
    row = _normalized(name) if raw is None else xd.normalize(raw, name)
    row["_x_normalized"] = True
    return row


def _directive_signal(out):
    """True when the row actually asks for a different expression."""
    return bool(out["tone"]
                or out["allow_correction"]
                or out["length_scale"] != xd.DEFAULT_LENGTH
                or out["initiative"] != xd.DEFAULT_INITIATIVE)


def incompatibility_report():
    """What each producer gives, and what normalize() cannot carry over."""
    report = {}
    for name, factory, kind in PRODUCERS:
        raw = factory()
        declared = set(raw) if isinstance(raw, dict) else set()
        out = xd.normalize(raw)
        report[name] = {
            "kind": kind,
            "declared": sorted(declared),
            "unmapped": sorted(declared - CANONICAL_KEYS - set(ALIAS_KEYS)),
            "has_directive_fields": bool(declared & DIRECTIVE_FIELDS),
            "has_directive_signal": _directive_signal(out),
        }
    return report


def report_summary(report=None):
    report = incompatibility_report() if report is None else report
    return {
        "total": len(report),
        "directive_producers": sum(1 for row in report.values()
                                   if row["kind"] == "directives"),
        "payload_producers": sum(1 for row in report.values()
                                 if row["kind"] == "payload"),
        "view_producers": sum(1 for row in report.values()
                              if row["kind"] == "view"),
        "with_directive_fields": sum(1 for row in report.values()
                                     if row["has_directive_fields"]),
        "with_directive_signal": sum(1 for row in report.values()
                                     if row["has_directive_signal"]),
        "with_unmapped_fields": sum(1 for row in report.values()
                                    if row["unmapped"]),
    }


# ---------------------------------------------------------------------------
# One generated test per producer.
# ---------------------------------------------------------------------------
class PerModuleTest(unittest.TestCase):
    """Fixture holder; tests are generated below."""


def _make_per_module(name, factory):
    def test(self):
        raw = factory()
        self.assertIsInstance(raw, dict, name)
        out = xd.normalize(raw, name)
        self.assertEqual(set(out), set(CANONICAL_KEYS), name)
        self.assertGreaterEqual(out["length_scale"], xd.LENGTH_MIN, name)
        self.assertLessEqual(out["length_scale"], xd.LENGTH_MAX, name)
        self.assertGreaterEqual(out["initiative"], 0.0, name)
        self.assertLessEqual(out["initiative"], 1.0, name)
        self.assertIsInstance(out["tone"], str, name)
        self.assertIsInstance(out["note"], str, name)
        self.assertLessEqual(len(out["note"]), xd.NOTE_LIMIT, name)
        self.assertIsInstance(out["allow_correction"], bool, name)
        self.assertEqual(out["sources"], [name], name)
        # Idempotent: normalizing an already-normalized directive changes
        # nothing except the caller-supplied source label.
        again = xd.normalize(out, name)
        for key in CANONICAL_KEYS - {"sources"}:
            self.assertEqual(again[key], out[key], name + "." + key)
        # A single raw producer output merges to itself through the named
        # path, keeping its source label.
        merged = xd.merge_named([(name, raw)])
        self.assertEqual(merged["length_scale"], out["length_scale"], name)
        self.assertEqual(merged["initiative"], out["initiative"], name)
        self.assertEqual(merged["tone"], out["tone"], name)
        self.assertEqual(merged["allow_correction"],
                         out["allow_correction"], name)
        self.assertEqual(merged["sources"], [name], name)
    return test


for _name, _factory, _kind in PRODUCERS:
    setattr(PerModuleTest, "test_" + _name, _make_per_module(_name, _factory))


# ---------------------------------------------------------------------------
# merge(): conservative combination of many hints.
# ---------------------------------------------------------------------------
class MergeTest(unittest.TestCase):
    def setUp(self):
        self.rows = {name: _merge_ready(name) for name in PRODUCER_NAMES}

    def test_pairwise_merge(self):
        for left, right in zip(PRODUCER_NAMES, PRODUCER_NAMES[1:]):
            a, b = self.rows[left], self.rows[right]
            out = xd.merge([a, b])
            self.assertEqual(out["length_scale"],
                             min(a["length_scale"], b["length_scale"]))
            self.assertEqual(out["initiative"],
                             min(a["initiative"], b["initiative"]))
            self.assertEqual(out["sources"], [left, right])
            self.assertIsInstance(out["allow_correction"], bool)

    def test_five_merge(self):
        chosen = ["metacog", "attributor", "dissonance", "narrative",
                  "value_order"]
        rows = [self.rows[name] for name in chosen]
        out = xd.merge(rows)
        self.assertAlmostEqual(out["length_scale"],
                               min(row["length_scale"] for row in rows))
        self.assertAlmostEqual(out["initiative"],
                               min(row["initiative"] for row in rows))
        self.assertEqual(out["sources"], chosen)

    def test_all_merge(self):
        rows = list(self.rows.values())
        out = xd.merge(rows)
        self.assertEqual(len(out["sources"]), len(PRODUCERS))
        self.assertEqual(len(set(out["sources"])), len(PRODUCERS))
        self.assertEqual(out["sources"], list(PRODUCER_NAMES))
        self.assertGreaterEqual(out["length_scale"], xd.LENGTH_MIN)
        self.assertLessEqual(out["length_scale"], xd.LENGTH_MAX)
        self.assertGreaterEqual(out["initiative"], 0.0)
        self.assertLessEqual(out["initiative"], 1.0)
        self.assertLessEqual(len(out["note"]), xd.NOTE_LIMIT)

    def test_merge_is_stable(self):
        first = xd.merge([self.rows[name] for name in PRODUCER_NAMES[:5]])
        # merge() does not return the "_x_normalized" marker, so a second
        # merge must be told; values must still round-trip unchanged.
        self.assertNotIn("_x_normalized", first)
        first["_x_normalized"] = True
        second = xd.merge([first])
        self.assertEqual(first["length_scale"], second["length_scale"])
        self.assertEqual(first["initiative"], second["initiative"])
        self.assertEqual(first["tone"], second["tone"])
        self.assertEqual(first["note"], second["note"])
        self.assertEqual(first["sources"], second["sources"])

    def test_merge_named(self):
        pairs = [("metacog", {"length_scale": 0.8, "tone": "甲"}),
                 ("attributor", {"length_scale": 1.2, "tone": "乙"})]
        out = xd.merge_named(pairs)
        self.assertEqual(out["length_scale"], 0.8)
        self.assertEqual(out["tone"], "甲")  # metacog outranks attributor
        self.assertEqual(out["sources"], ["metacog", "attributor"])

    def test_merge_uses_source_label_from_raw_rows(self):
        out = xd.merge([{"tone": "甲", "_source": "metacog"},
                        {"tone": "乙", "_source": "attributor"}])
        self.assertEqual(out["sources"], ["metacog", "attributor"])
        self.assertEqual(out["tone"], "甲")

    def test_tone_priority_is_order_independent(self):
        rows = [_merge_ready("possible_selves", {"tone": "低优先"}),
                _merge_ready("metacog", {"tone": "高优先"}),
                _merge_ready("not_a_layer", {"tone": "未知来源"})]
        for order in (rows, list(reversed(rows)),
                      [rows[1], rows[2], rows[0]]):
            out = xd.merge(order)
            self.assertEqual(out["tone"], "高优先")

    def test_unknown_source_ranks_last(self):
        known = _merge_ready("possible_selves", {"tone": "已知"})
        unknown = _merge_ready("not_a_layer", {"tone": "未知"})
        self.assertEqual(xd.merge([unknown, known])["tone"], "已知")
        self.assertEqual(xd.merge([unknown])["tone"], "未知")

    def test_notes_are_joined_and_deduped(self):
        rows = [_merge_ready("metacog", {"note": "同一个理由"}),
                _merge_ready("attributor", {"note": "同一个理由"}),
                _merge_ready("value_order", {"note": "另一个理由"})]
        out = xd.merge(rows)
        self.assertEqual(out["note"].count("同一个理由"), 1)
        self.assertIn("另一个理由", out["note"])

    def test_allow_correction_is_or(self):
        rows = [_merge_ready("metacog", {"allow_correction": False}),
                _merge_ready("narrative", {"allow_clarify": True})]
        self.assertTrue(xd.merge(rows)["allow_correction"])

    def test_empty_merge(self):
        out = xd.merge([])
        self.assertEqual(out["length_scale"], xd.DEFAULT_LENGTH)
        self.assertEqual(out["initiative"], xd.DEFAULT_INITIATIVE)
        self.assertEqual(out["tone"], "")
        self.assertEqual(out["sources"], [])
        self.assertEqual(xd.merge(None), out)

    def test_non_dict_items_are_skipped(self):
        rows = [None, "x", 3, [], self.rows["metacog"]]
        out = xd.merge(rows)
        self.assertEqual(out["sources"], ["metacog"])

    def test_merge_does_not_mutate_raw_rows(self):
        raw = {"length_scale": 0.7, "tone": "短"}
        xd.merge([raw])
        self.assertEqual(raw, {"length_scale": 0.7, "tone": "短"})
        self.assertNotIn("_x_normalized", raw)


# ---------------------------------------------------------------------------
# Legacy spellings and malformed inputs.
# ---------------------------------------------------------------------------
class LegacyShapeTest(unittest.TestCase):
    def test_each_alias_maps(self):
        cases = (
            ("length", "length_scale", 0.7),
            ("proactive", "initiative", 0.9),
            ("allow_self_correction", "allow_correction", True),
            ("allow_clarify", "allow_correction", True),
            ("reason", "note", "低置信"),
        )
        for legacy, canonical, value in cases:
            out = xd.normalize({legacy: value})
            self.assertEqual(out[canonical], value, legacy)
            self.assertNotIn(legacy, out, legacy)

    def test_all_legacy_fields_merge(self):
        legacy = [{"length_scale": 0.8, "tone": "短一点", "proactive": 0.7},
                  {"length": 1.2, "allow_self_correction": True,
                   "reason": "低置信"},
                  {"allow_clarify": True, "note": "矛盾"},
                  {"initiative": 0.2}]
        out = xd.merge([xd.normalize(row, "legacy%d" % i)
                        for i, row in enumerate(legacy)])
        self.assertEqual(out["length_scale"], 0.8)
        self.assertEqual(out["initiative"], 0.2)
        self.assertTrue(out["allow_correction"])
        self.assertIn("低置信", out["note"])
        self.assertIn("矛盾", out["note"])

    def test_malformed_inputs_survive(self):
        for bad in (None, "x", [], 3, {"length_scale": "y"},
                    {"initiative": float("nan")}, {"tone": 7}):
            out = xd.normalize(bad, "bad")
            self.assertEqual(set(out), set(CANONICAL_KEYS))
            self.assertGreaterEqual(out["length_scale"], xd.LENGTH_MIN)
            self.assertLessEqual(out["length_scale"], xd.LENGTH_MAX)
            self.assertEqual(out["sources"], ["bad"])

    def test_values_are_clamped_and_text_truncated(self):
        out = xd.normalize({"length_scale": 9, "initiative": -1,
                            "tone": "长" * 100, "note": "注" * 200})
        self.assertEqual(out["length_scale"], xd.LENGTH_MAX)
        self.assertEqual(out["initiative"], 0.0)
        self.assertEqual(len(out["tone"]), 60)
        self.assertEqual(len(out["note"]), xd.NOTE_LIMIT)


# ---------------------------------------------------------------------------
# Contract constants.
# ---------------------------------------------------------------------------
class ContractTest(unittest.TestCase):
    def test_bounds_and_defaults(self):
        self.assertLess(xd.LENGTH_MIN, xd.LENGTH_MAX)
        self.assertGreaterEqual(xd.DEFAULT_LENGTH, xd.LENGTH_MIN)
        self.assertLessEqual(xd.DEFAULT_LENGTH, xd.LENGTH_MAX)
        self.assertGreaterEqual(xd.DEFAULT_INITIATIVE, 0.0)
        self.assertLessEqual(xd.DEFAULT_INITIATIVE, 1.0)
        self.assertGreater(xd.NOTE_LIMIT, 0)

    def test_source_priority_is_unique_and_ranked(self):
        self.assertEqual(len(xd.SOURCE_PRIORITY), len(set(xd.SOURCE_PRIORITY)))
        for index, name in enumerate(xd.SOURCE_PRIORITY):
            self.assertEqual(xd.PRIORITY_INDEX[name], index)
        self.assertEqual(set(xd.normalize({})), set(CANONICAL_KEYS))


# ---------------------------------------------------------------------------
# Compatibility report: what is compatible, what is silently lost.
# ---------------------------------------------------------------------------
class IncompatibilityReportTest(unittest.TestCase):
    def test_report_covers_every_producer(self):
        report = incompatibility_report()
        self.assertEqual(set(report), set(PRODUCER_NAMES))
        self.assertEqual(len(report), len(PRODUCERS))

    def test_summary_counts_are_consistent(self):
        summary = report_summary()
        self.assertEqual(summary["total"], len(PRODUCERS))
        self.assertEqual(summary["directive_producers"],
                         len(DIRECTIVE_PRODUCERS))
        self.assertEqual(summary["payload_producers"],
                         len(PAYLOAD_PRODUCERS))
        self.assertEqual(summary["view_producers"],
                         len(PRODUCERS) - len(DIRECTIVE_PRODUCERS)
                         - len(PAYLOAD_PRODUCERS))
        self.assertLessEqual(summary["with_directive_fields"],
                             summary["total"])
        self.assertLessEqual(summary["with_directive_signal"],
                             summary["total"])

    def test_directives_producers_are_directive_shaped(self):
        report = incompatibility_report()
        for name in DIRECTIVE_PRODUCERS:
            row = report[name]
            self.assertEqual(row["kind"], "directives", name)
            self.assertTrue(row["has_directive_fields"], name)

    def test_directives_producers_carry_a_signal(self):
        # Every directives() output but the documented calm-narrative case
        # actually asks for a different expression.
        report = incompatibility_report()
        for name in DIRECTIVE_PRODUCERS:
            if name in KNOWN_NO_SIGNAL_DIRECTIVES:
                self.assertFalse(report[name]["has_directive_signal"], name)
            else:
                self.assertTrue(report[name]["has_directive_signal"], name)

    def test_projection_producers_have_no_directive_signal(self):
        # Structural compat (dicts, merge safely), but no length/initiative/
        # tone/allow_correction: they are panel projections, not hints.
        report = incompatibility_report()
        for name in PROJECTION_PRODUCERS:
            self.assertFalse(report[name]["has_directive_signal"], name)

    def test_unmapped_fields_are_recorded_not_silently_dropped(self):
        report = incompatibility_report()
        for name, row in report.items():
            for key in row["declared"]:
                if key in CANONICAL_KEYS or key in ALIAS_KEYS:
                    continue
                self.assertIn(key, row["unmapped"], name)

    def test_normalize_output_is_relabelled_by_merge(self):
        # Known merge() wart, recorded not fixed: normalize() does not set
        # "_x_normalized", so passing its output straight into merge() makes
        # merge() relabel the row "itemN" and source-name tone priority is
        # lost. Use merge_named() / _merge_ready() on the hot path.
        row = xd.normalize({"tone": "甲"}, "metacog")
        out = xd.merge([row])
        self.assertEqual(out["sources"], ["item0"])
        self.assertEqual(out["tone"], "甲")

    def test_merge_of_projection_only_hints_is_harmless(self):
        # Projections merge to "no hint" instead of leaking panel fields.
        rows = [_merge_ready(name) for name in PROJECTION_PRODUCERS]
        out = xd.merge(rows)
        self.assertEqual(out["length_scale"], xd.DEFAULT_LENGTH)
        self.assertEqual(out["initiative"], xd.DEFAULT_INITIATIVE)
        self.assertEqual(out["tone"], "")
        self.assertFalse(out["allow_correction"])
        self.assertEqual(out["sources"], list(PROJECTION_PRODUCERS))


# ---------------------------------------------------------------------------
# Coverage: the 24-module requirement.
# ---------------------------------------------------------------------------
class CoverageTest(unittest.TestCase):
    # Modules that expose directives(result); new ones must be added here.
    EXPECTED_DIRECTIVE_MODULES = frozenset((
        "attachment_behavior", "attributor", "compassion_fatigue",
        "dissonance", "exit_or_silence", "metacog", "narrative",
        "possible_selves", "regulation_strategies", "relation_stage",
        "repair_after_boundary", "self_intent", "value_order",
    ))

    def test_expected_directive_modules_are_covered(self):
        self.assertEqual(set(DIRECTIVE_PRODUCERS),
                         set(self.EXPECTED_DIRECTIVE_MODULES))

    def test_at_least_24_producers(self):
        self.assertGreaterEqual(len(PRODUCERS), 24)

    def test_producer_names_are_unique(self):
        self.assertEqual(len(PRODUCER_NAMES), len(set(PRODUCER_NAMES)))

    def test_every_producer_is_dict(self):
        for name, factory, _kind in PRODUCERS:
            self.assertIsInstance(factory(), dict, name)


if __name__ == "__main__":
    unittest.main()
