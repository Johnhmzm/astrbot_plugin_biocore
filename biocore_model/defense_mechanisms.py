# -*- coding: utf-8 -*-
"""P1 defense mechanisms: the minimal Vaillant ladder.

When a negative event is too close to hold directly, the self protects itself.
This module keeps the four most useful mechanisms from the Vaillant (1977/1992)
ladder:

  * denial          - refuse to acknowledge the negative event;
  * rationalization - give the behaviour a respectable reason;
  * projection      - put her own feeling onto the other person;
  * displacement    - the anger cannot go to its source, so it lands elsewhere.

Input is one event plus the current core state and her self-concept.  Output is
a single read: which mechanism fired, with 0..1 strength, its 0..1 cost to
functioning, a short reason, and the line she tells herself.

Pure functions only: dicts in, dict out.  No IO, no clock, no LLM, no prompt
text, and it never imports main.py.  The whole module can be switched off.
"""
from __future__ import annotations

MECHANISMS = ("denial", "rationalization", "projection", "displacement")
MECHANISM_ZH = {
    "denial": "否认",
    "rationalization": "合理化",
    "projection": "投射",
    "displacement": "转移",
}
COST_BASE = {
    "denial": 0.65,
    "rationalization": 0.40,
    "projection": 0.55,
    "displacement": 0.35,
}
DEFAULT_CONFIG = {"enabled": True, "threshold": 0.35}
DEFAULT_VALENCE = {
    "failure": -0.60,
    "criticism": -0.50,
    "rejection": -0.60,
    "loss": -0.70,
    "conflict": -0.50,
    "praise": 0.60,
    "success": 0.70,
}
REASONS = {
    "denial": "事件的威胁太近，她选择先不承认它",
    "rationalization": "她需要给自己的行为一个说得通的理由",
    "projection": "她把自己的情绪归到了对方身上",
    "displacement": "源头不能碰，火气落到了别处",
    "none": "这次没有启动防御",
    "disabled": "防御机制已关闭",
}
SELF_TALK = {
    "denial": "这件事没那么严重，先不想它。",
    "rationalization": "我这样做是有道理的，换谁都会这样。",
    "projection": "是他先对我有情绪的，不是我。",
    "displacement": "我不是冲你，是别的事让我烦。",
}


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


def _clamp11(value, default=0.0):
    return max(-1.0, min(1.0, _num(value, default)))


def _config(config):
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(config, bool):
        cfg["enabled"] = config
        return cfg
    if isinstance(config, dict):
        cfg["enabled"] = bool(config.get("enabled", True))
        cfg["threshold"] = _clamp01(config.get("threshold", 0.35), 0.35)
    return cfg


def _event(event):
    return event if isinstance(event, dict) else {}


def _state(state):
    return state if isinstance(state, dict) else {}


def _concept(concept):
    return concept if isinstance(concept, dict) else {}


def _kind(event):
    return str(_event(event).get("kind") or "").strip().lower()


def _valence(event):
    event = _event(event)
    if "valence" in event:
        return _clamp11(event.get("valence"))
    return _clamp11(DEFAULT_VALENCE.get(_kind(event), 0.0))


def _intensity(event):
    return _clamp01(_event(event).get("intensity", 0.5), 0.5)


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _clamp01(value) > 0.0
    return bool(value)


def _self_caused(event):
    event = _event(event)
    if "self_caused" in event:
        return _truthy(event.get("self_caused"))
    return _kind(event) in ("failure", "conflict")


def _other_present(event):
    event = _event(event)
    if "other_present" in event:
        return _truthy(event.get("other_present"))
    target = str(event.get("target") or "").strip().lower()
    if target in ("other", "peer", "friend", "partner"):
        return True
    return _kind(event) in ("conflict", "rejection", "criticism")


def _power_gap(event):
    event = _event(event)
    if "power_gap" in event:
        return _clamp01(event.get("power_gap"))
    target = str(event.get("target") or "").strip().lower()
    return 1.0 if target == "authority" else 0.0


def _state_values(state):
    state = _state(state)
    valence = _clamp11(state.get("v", 0.0))
    arousal = _clamp01(state.get("a", 0.5), 0.5)
    dominance = _clamp01(
        state.get("dominance", state.get("d", 0.5)), 0.5)
    trust = _clamp01(state.get("trust", 0.5), 0.5)
    stress = _clamp01(state.get("stress", 0.5), 0.5)
    if "anger" in state:
        anger = _clamp01(state.get("anger"))
    else:
        anger = _clamp01(max(0.0, -valence) * arousal * max(0.10, dominance))
    if "fear" in state:
        fear = _clamp01(state.get("fear"))
    else:
        fear = _clamp01(max(0.0, -valence) * arousal * max(0.10, 1.0 - dominance))
    return {
        "valence": valence,
        "arousal": arousal,
        "dominance": dominance,
        "trust": trust,
        "stress": stress,
        "anger": anger,
        "fear": fear,
    }


def _concept_values(concept):
    concept = _concept(concept)
    traits = concept.get("traits")
    traits = traits if isinstance(traits, dict) else {}
    clarity = _clamp01(concept.get("clarity", 0.5), 0.5)
    competence = _clamp01(
        concept.get("competence", traits.get("competence", 0.5)), 0.5)
    honesty = _clamp01(
        concept.get("honesty", traits.get("honesty", 0.5)), 0.5)
    esteem = _clamp01(
        concept.get("self_esteem", concept.get("esteem", 0.5)), 0.5)
    return {
        "clarity": clarity,
        "ego": max(competence, honesty),
        "esteem": esteem,
    }


def mechanism_scores(event, state=None, self_concept=None):
    """All four mechanism weights for one event; 0..1 each, deterministic."""
    event = _event(event)
    values = _state_values(state)
    concept = _concept_values(self_concept)
    negative = _clamp01(max(0.0, -_valence(event)))
    threat = negative * _intensity(event)
    clarity = concept["clarity"]
    stress = values["stress"]
    scores = {
        "denial": _clamp01(threat * (0.55 * (1.0 - clarity)
                                     + 0.45 * stress)),
    }
    agency = 1.0 if _self_caused(event) else 0.0
    scores["rationalization"] = _clamp01(
        agency
        * (0.55 + 0.45 * clarity)
        * (0.45 + 0.55 * max(concept["ego"], concept["esteem"]))
        * (0.50 + 0.50 * _intensity(event)))
    other = 1.0 if _other_present(event) else 0.0
    scores["projection"] = _clamp01(
        other
        * max(values["anger"], values["fear"])
        * (0.45 + 0.55 * (1.0 - values["trust"]))
        * (0.60 + 0.40 * negative))
    scores["displacement"] = _clamp01(
        _power_gap(event)
        * values["anger"]
        * (1.0 - values["dominance"])
        * (0.55 + 0.45 * negative))
    return {name: round(value, 4) for name, value in scores.items()}


def assess(event, state=None, self_concept=None, config=None):
    """One defensive read: mechanism / strength / cost / reason / self-talk."""
    cfg = _config(config)
    scores = mechanism_scores(event, state=state, self_concept=self_concept)
    out = {
        "enabled": bool(cfg["enabled"]),
        "mechanism": "",
        "label": "",
        "strength": 0.0,
        "cost": 0.0,
        "reason": "",
        "self_talk": "",
        "scores": scores,
    }
    if not out["enabled"]:
        out["reason"] = REASONS["disabled"]
        return out
    ranked = sorted(MECHANISMS, key=lambda name: (-scores[name],
                                                  MECHANISMS.index(name)))
    best = ranked[0]
    strength = scores[best]
    if strength <= 0.0 or strength < cfg["threshold"]:
        out["reason"] = REASONS["none"]
        return out
    out["mechanism"] = best
    out["label"] = MECHANISM_ZH[best]
    out["strength"] = round(_clamp01(strength), 4)
    out["cost"] = round(_clamp01(COST_BASE[best] * out["strength"]), 4)
    out["reason"] = REASONS[best]
    out["self_talk"] = SELF_TALK[best]
    return out


def view(result):
    """Panel-friendly subset of one assess() result (no prompt text)."""
    data = result if isinstance(result, dict) else {}
    return {
        "enabled": bool(data.get("enabled", False)),
        "mechanism": str(data.get("mechanism") or ""),
        "label": str(data.get("label") or ""),
        "strength": round(_clamp01(data.get("strength", 0.0)), 4),
        "cost": round(_clamp01(data.get("cost", 0.0)), 4),
        "reason": str(data.get("reason") or ""),
        "self_talk": str(data.get("self_talk") or ""),
    }
