# -*- coding: utf-8 -*-
"""P1 emotion granularity: refine the six prototypes into second-level labels.

The six prototypes are the ones already used by biocore_model.emotion_geometry
(joy / sadness / anger / fear / loneliness / trust).  This module only *reads*
their scores plus optional appraisal cues and refines the winning prototype into
the finer words used by the internal readout and the panel
(委屈 / 失望 / 被忽视 / 被冒犯 / 不安 / 疲惫).

It never writes the biological state, never builds prompt text, never calls an
LLM and never imports main.py.

Contract::

    refine(scores, context, config, rules) -> {
        "enabled": bool,
        "primary": "sadness",              # one of SIX_PROTOTYPES, or ""
        "primary_zh": "难过",
        "secondary": [{"key": "aggrieved", "label": "委屈", "score": 0.66}],
        "labels": ["委屈"],
        "display": "委屈",                  # first secondary label, else primary
        "fallback": False,                 # True == fell back to the six prototypes
    }

The input scores is a mapping prototype -> 0..1, normally the probs dict
returned by emotion_geometry.classify(state).  The context carries optional
appraisal cues (offense / fatigue) that the six prototypes cannot express; a
rule only reads a cue when it declares context_requires.

The config is either a bool (the enabled switch) or a dict such as
{"enabled": False, "max_labels": 1}.  The rules argument replaces the whole
mapping table, which keeps the table configurable; a disabled module or a score
set with no matching rule falls back to the plain six-prototype label.
"""
from __future__ import annotations

SIX_PROTOTYPES = ("joy", "sadness", "anger", "fear", "loneliness", "trust")
PROTOTYPE_ZH = {
    "joy": "开心",
    "sadness": "难过",
    "anger": "生气",
    "fear": "害怕",
    "loneliness": "孤独",
    "trust": "信任",
}

DEFAULT_CONFIG = {"enabled": True, "max_labels": 2}

# Second-level mapping table.  Every rule is a soft score over prototype
# strengths with hard preconditions, so a weak adjacent prototype can never
# invent a finer label on its own.  Order is only a tie-breaker; scores decide.
DEFAULT_RULES = (
    {
        "key": "aggrieved",
        "label": "委屈",
        "primary": "sadness",
        "requires": {"anger": 0.15},
        "weights": {"sadness": 1.0, "anger": 0.5},
        "threshold": 0.55,
    },
    {
        "key": "disappointed",
        "label": "失望",
        "primary": "sadness",
        "requires": {"trust": 0.15},
        "forbids": {"anger": 0.15},
        "weights": {"sadness": 1.0, "trust": 0.35},
        "threshold": 0.55,
    },
    {
        "key": "ignored",
        "label": "被忽视",
        "primary": "loneliness",
        "requires": {"sadness": 0.10},
        "weights": {"loneliness": 1.0, "sadness": 0.4},
        "threshold": 0.50,
    },
    {
        "key": "offended",
        "label": "被冒犯",
        "primary": "anger",
        "context_requires": {"offense": 0.40},
        "weights": {"anger": 1.0},
        "threshold": 0.45,
    },
    {
        "key": "uneasy",
        "label": "不安",
        "primary": "fear",
        "requires": {"loneliness": 0.10},
        "weights": {"fear": 1.0, "loneliness": 0.3},
        "threshold": 0.50,
    },
    {
        "key": "worn_out",
        "label": "疲惫",
        "primary": "sadness",
        "context_requires": {"fatigue": 0.40},
        "weights": {"sadness": 1.0},
        "threshold": 0.45,
    },
)

_EPS = 1e-12


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return float(default)
    if num != num or num in (float("inf"), float("-inf")):
        return float(default)
    return num


def _clamp01(value, default=0.0):
    return max(0.0, min(1.0, _num(value, default)))


def _config(config):
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(config, bool):
        cfg["enabled"] = config
        return cfg
    if isinstance(config, dict):
        cfg["enabled"] = bool(config.get("enabled", True))
        try:
            cfg["max_labels"] = max(0, int(config.get("max_labels", 2)))
        except Exception:
            cfg["max_labels"] = 2
    return cfg


def _scores(scores):
    return scores if isinstance(scores, dict) else {}


def _context(context):
    return context if isinstance(context, dict) else {}


def primary(scores):
    """Top prototype, with the tuple order breaking exact ties."""
    scores = _scores(scores)
    best = ""
    best_value = 0.0
    for key in SIX_PROTOTYPES:
        value = _clamp01(scores.get(key, 0.0))
        if value > best_value + _EPS:
            best, best_value = key, value
    return best


def _requirement_met(scores, required):
    scores = _scores(scores)
    for key, need in (required or {}).items():
        if key not in scores:
            return False
        if _clamp01(scores.get(key)) < _num(need, 1.0):
            return False
    return True


def _context_met(context, required):
    context = _context(context)
    for key, need in (required or {}).items():
        if key not in context:
            return False
        if _clamp01(context.get(key)) < _num(need, 1.0):
            return False
    return True


def _forbidden_hit(scores, forbidden):
    scores = _scores(scores)
    for key, limit in (forbidden or {}).items():
        if key in scores and _clamp01(scores.get(key)) >= _num(limit, 0.0):
            return True
    return False


def _rule_value(rule, scores):
    scores = _scores(scores)
    total = 0.0
    for key, weight in (rule.get("weights") or {}).items():
        total += _num(weight, 0.0) * _clamp01(scores.get(key, 0.0))
    return total


def match_rules(scores, context=None, rules=None):
    """All matching rules for the winning prototype, best first (deterministic)."""
    scores = _scores(scores)
    context = _context(context)
    top = primary(scores)
    table = rules if isinstance(rules, (list, tuple)) else DEFAULT_RULES
    rows = []
    if not top:
        return rows
    for index, rule in enumerate(table or ()):
        if not isinstance(rule, dict):
            continue
        if str(rule.get("primary") or "") != top:
            continue
        try:
            if not _requirement_met(scores, rule.get("requires")):
                continue
            if not _context_met(context, rule.get("context_requires")):
                continue
            if _forbidden_hit(scores, rule.get("forbids")):
                continue
            value = _rule_value(rule, scores)
            threshold = _num(rule.get("threshold", 0.0), 0.0)
        except Exception:
            continue
        if value + _EPS < threshold:
            continue
        rows.append((value, index, {
            "key": str(rule.get("key") or rule.get("label") or ""),
            "label": str(rule.get("label") or ""),
            "score": round(max(0.0, min(1.0, value)), 4),
        }))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in rows]


def refine(scores, context=None, config=None, rules=None):
    """Refine prototype scores into {primary, secondary, display} for one read."""
    cfg = _config(config)
    top = primary(scores)
    out = {
        "enabled": bool(cfg["enabled"]),
        "primary": top,
        "primary_zh": PROTOTYPE_ZH.get(top, ""),
        "secondary": [],
        "labels": [],
        "display": PROTOTYPE_ZH.get(top, ""),
        "fallback": True,
    }
    if not out["enabled"] or not top:
        return out
    matched = match_rules(scores, context=context, rules=rules)[:cfg["max_labels"]]
    if matched:
        out["secondary"] = matched
        out["labels"] = [row["label"] for row in matched]
        out["display"] = out["labels"][0]
        out["fallback"] = False
    return out


def view(scores, context=None, config=None, rules=None):
    """Panel-friendly read: coarse label plus second-level line."""
    refined = refine(scores, context=context, config=config, rules=rules)
    if refined["secondary"]:
        line = "{}（{}）".format(refined["display"], refined["primary_zh"])
    else:
        line = refined["primary_zh"]
    return {
        "enabled": refined["enabled"],
        "primary": refined["primary"],
        "primary_zh": refined["primary_zh"],
        "secondary": [{"key": row["key"], "label": row["label"]}
                      for row in refined["secondary"]],
        "display": refined["display"],
        "line": line,
        "fallback": refined["fallback"],
    }


def _prototype_probs(state):
    try:
        try:
            from .emotion_geometry import classify
        except Exception:  # pragma: no cover - direct script import
            from emotion_geometry import classify
        return (classify(state or {}) or {}).get("probs") or {}
    except Exception:
        return {}


def from_state(state, context=None, config=None, rules=None):
    """End-to-end pure read: core state -> six prototypes -> refined labels."""
    return refine(_prototype_probs(state), context=context, config=config, rules=rules)
