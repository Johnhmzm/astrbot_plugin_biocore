# -*- coding: utf-8 -*-
"""Emotion regulation strategies (Gross process model), with cost and effect.

The five families of the process model, in the order they can act:

  situation_selection      choose whether to enter the situation at all
  situation_modification   change the situation that is already happening
  attentional_deployment   look away / distract / focus elsewhere
  cognitive_reappraisal    change the meaning of the event
  response_modulation      change the expression after the feeling is there

Each strategy is scored from the state, the event and the relationship, then
the best expected result per unit of cost is chosen. The result reports cost
(how much she spends), effect (how much pressure it is expected to absorb) and
a one-line self-talk (how she talks herself into it). It also carries a
suggested old-style coping tier (problem_focused / emotion_focused /
avoidance) so the existing three tiers keep working: this module advises, it
never replaces them.

evaluate(state=None, event=None, relationship=None, flags=None) returns:

  enabled, strategy, label, cost, effect, reason, self_talk, coping_tier,
  confidence, fit, scores, profiles

flags['enabled'] = False -> strategy 'none', cost/effect 0, old coping wins.

Pure functions only: no IO, no clock, no host imports, no LLM calls. The
module never imports main.py.
"""
from __future__ import annotations

STRATEGIES = (
    "situation_selection",
    "situation_modification",
    "attentional_deployment",
    "cognitive_reappraisal",
    "response_modulation",
)
LABELS = {
    "situation_selection": "情境选择",
    "situation_modification": "情境修正",
    "attentional_deployment": "注意部署",
    "cognitive_reappraisal": "认知重评",
    "response_modulation": "反应调节",
}
REASONS = {
    "situation_selection": "还没进去就能选，代价最低",
    "situation_modification": "事情已经发生，改一改现场",
    "attentional_deployment": "管不住它，先别盯着",
    "cognitive_reappraisal": "换个说法，压得住",
    "response_modulation": "先收着，别露出来",
}
SELF_TALK = {
    "situation_selection": "这次先不去那个场合，没必要硬碰。",
    "situation_modification": "把话题往别处带一点，别让它继续。",
    "attentional_deployment": "先不看这件事，去做点别的。",
    "cognitive_reappraisal": "换个角度想，这不是冲我来的。",
    "response_modulation": "先别表现出来，等这阵过去再说。",
}
COPING_TIERS = ("problem_focused", "emotion_focused", "avoidance")
TIER_OF = {
    "situation_selection": "problem_focused",
    "situation_modification": "problem_focused",
    "attentional_deployment": "avoidance",
    "cognitive_reappraisal": "emotion_focused",
    "response_modulation": "emotion_focused",
}

_UPCOMING = ("before", "upcoming", "future", "planned")


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:  # NaN
        return default
    return num


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))


def _state(state):
    state = state if isinstance(state, dict) else {}
    return {
        "stress": _clamp(state.get("stress", 0.3)),
        "energy": _clamp(state.get("energy", 0.6)),
        "valence": max(-1.0, min(1.0, _num(state.get("valence"), 0.0))),
        "arousal": _clamp(state.get("arousal", 0.5)),
    }


def _event(event):
    event = event if isinstance(event, dict) else {}
    when = str(event.get("when") or "after").lower()
    return {
        "upcoming": when in _UPCOMING,
        "control": _clamp(event.get("controllable", event.get("control", 0.5))),
        "intensity": _clamp(event.get("intensity", 0.5)),
        "public": bool(event.get("public", False)),
        "kind": str(event.get("kind") or "")[:16],
        "when": when[:12],
    }


def _relationship(relationship):
    relationship = relationship if isinstance(relationship, dict) else {}
    return {
        "closeness": _clamp(relationship.get("closeness", relationship.get("intimacy", 0.5))),
        "trust": _clamp(relationship.get("trust", 0.5)),
        "conflict": _clamp(relationship.get("conflict", 0.0)),
    }


def features(state=None, event=None, relationship=None):
    """Bounded features used by every strategy (for panels and tests)."""
    snap = _state(state)
    ev = _event(event)
    rel = _relationship(relationship)
    down = max(0.0, -snap["valence"])
    reflect = _clamp(0.40 * snap["energy"] + 0.30 * rel["trust"]
                     + 0.30 * (1.0 - snap["stress"]))
    return {
        "stress": snap["stress"],
        "energy": snap["energy"],
        "valence": snap["valence"],
        "arousal": snap["arousal"],
        "down": down,
        "upcoming": ev["upcoming"],
        "control": ev["control"],
        "intensity": ev["intensity"],
        "public": ev["public"],
        "when": ev["when"],
        "kind": ev["kind"],
        "closeness": rel["closeness"],
        "trust": rel["trust"],
        "conflict": rel["conflict"],
        "reflect": reflect,
    }


def _fit(strategy, f):
    if strategy == "situation_selection":
        return (0.55 * f["control"] + 0.25 * (1.0 - f["intensity"])
                + 0.20 * (1.0 if f["upcoming"] else 0.0))
    if strategy == "situation_modification":
        return (0.50 * f["control"] + 0.20 * (1.0 - f["intensity"])
                + 0.15 * f["closeness"]
                + 0.15 * (0.5 if f["upcoming"] else 1.0))
    if strategy == "attentional_deployment":
        return (0.45 * f["intensity"] + 0.30 * (1.0 - f["control"])
                + 0.25 * (1.0 - f["energy"]) + 0.15 * f["stress"]
                - 0.10 * f["trust"])
    if strategy == "cognitive_reappraisal":
        return (0.45 * f["reflect"] + 0.25 * (1.0 - f["intensity"])
                + 0.20 * f["trust"]
                + 0.15 * (0.3 if f["upcoming"] else 1.0)
                - 0.15 * f["down"])
    return (0.45 * (1.0 if f["public"] else 0.0)
            + 0.30 * (1.0 - f["closeness"]) + 0.25 * f["conflict"]
            + 0.20 * (1.0 - f["energy"]) + 0.15 * f["stress"]
            - 0.20 * f["trust"])


def _cost(strategy, f):
    if strategy == "situation_selection":
        value = 0.12 + 0.20 * (1.0 - f["control"]) + 0.10 * f["intensity"]
    elif strategy == "situation_modification":
        value = 0.20 + 0.20 * (1.0 - f["control"]) + 0.10 * f["intensity"]
    elif strategy == "attentional_deployment":
        value = (0.20 + 0.20 * f["intensity"] + 0.10 * (1.0 - f["energy"])
                 + 0.10 * f["stress"])
    elif strategy == "cognitive_reappraisal":
        value = (0.30 + 0.25 * f["intensity"] + 0.15 * (1.0 - f["energy"])
                 + 0.10 * (1.0 - f["trust"]))
    else:
        value = (0.45 + 0.25 * f["conflict"] + 0.15 * (1.0 - f["closeness"])
                 + 0.10 * f["stress"])
    return _clamp(value)


def _effect(strategy, f):
    if strategy == "situation_selection":
        value = (0.20 + 0.35 * f["control"] + 0.10 * (1.0 - f["intensity"])
                 + (0.10 if f["upcoming"] else 0.0))
    elif strategy == "situation_modification":
        value = (0.20 + 0.35 * f["control"] + 0.10 * f["closeness"]
                 + 0.10 * (1.0 - f["intensity"]))
    elif strategy == "attentional_deployment":
        value = (0.25 + 0.30 * f["intensity"] + 0.15 * (1.0 - f["control"])
                 + 0.10 * f["stress"])
    elif strategy == "cognitive_reappraisal":
        value = (0.20 + 0.30 * f["reflect"] + 0.20 * f["trust"]
                 + 0.10 * (1.0 - f["intensity"]) - 0.10 * f["down"])
    else:
        value = (0.15 + 0.20 * (1.0 if f["public"] else 0.0)
                 + 0.10 * (1.0 - f["closeness"]) + 0.10 * f["conflict"])
    return _clamp(value)


def profile(strategy, state=None, event=None, relationship=None):
    """One strategy priced against the current moment (no selection)."""
    strategy = str(strategy or "")
    if strategy not in STRATEGIES:
        return {
            "strategy": "none",
            "label": "",
            "fit": 0.0,
            "cost": 0.0,
            "effect": 0.0,
            "score": 0.0,
            "coping_tier": "",
            "reason": "未知策略",
            "self_talk": "",
        }
    f = features(state, event, relationship)
    fit = _clamp(_fit(strategy, f))
    cost = _cost(strategy, f)
    effect = _effect(strategy, f)
    score = _clamp(fit + 0.10 * effect - 0.15 * cost)
    return {
        "strategy": strategy,
        "label": LABELS[strategy],
        "fit": round(fit, 3),
        "cost": round(cost, 3),
        "effect": round(effect, 3),
        "score": round(score, 3),
        # never a ratio: effect and cost keep their own numbers, the score is
        # only the display order the caller sorts by
        "score_parts": {"fit": round(fit, 3), "effect": round(effect, 3),
                        "cost": round(cost, 3)},
        "score_is_display": True,
        "coping_tier": TIER_OF[strategy],
        "reason": REASONS[strategy],
        "self_talk": SELF_TALK[strategy],
    }


def profiles(state=None, event=None, relationship=None):
    """All five strategies, strongest first (ties keep Gross order)."""
    rows = [profile(strategy, state, event, relationship)
            for strategy in STRATEGIES]
    rows.sort(key=lambda row: (-row["score"], STRATEGIES.index(row["strategy"])))
    return rows


def _disabled():
    return {
        "enabled": False,
        "strategy": "none",
        "label": "",
        "cost": 0.0,
        "effect": 0.0,
        "reason": "调节策略库关闭，沿用旧 coping 三档",
        "self_talk": "",
        "coping_tier": "",
        "confidence": 0.0,
        "fit": 0.0,
        "scores": {},
        "profiles": [],
    }


def evaluate(state=None, event=None, relationship=None, flags=None):
    """Pick the best strategy for this moment. Plain dict, no IO."""
    flags = flags if isinstance(flags, dict) else {}
    if not bool(flags.get("enabled", True)):
        return _disabled()
    rows = profiles(state, event, relationship)
    top = rows[0]
    second = rows[1]["score"] if len(rows) > 1 else 0.0
    margin = round(_clamp(top["score"] - second), 3)
    out = dict(top)
    out.update({
        "enabled": True,
        "confidence": margin,
        "scores": {row["strategy"]: row["score"] for row in rows},
        "profiles": rows,
    })
    return out


def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"strategy": "none", "cost": 0.0, "effect": 0.0,
                "coping_tier": "", "tone": ""}
    strategy = str(result.get("strategy") or "none")
    return {
        "strategy": strategy if strategy in STRATEGIES else "none",
        "cost": round(_clamp(result.get("cost", 0.0)), 3),
        "effect": round(_clamp(result.get("effect", 0.0)), 3),
        "coping_tier": (result.get("coping_tier")
                        if result.get("coping_tier") in COPING_TIERS else ""),
        "tone": str(SELF_TALK.get(strategy) or "")[:40],
    }
