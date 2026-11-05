# -*- coding: utf-8 -*-
"""P1 envy and social comparison: noticing the third person.

Envy is not one switch; it escalates in three readable levels:

  * 轻微在意 (mild attention)  - attention is pulled, nothing is at stake yet;
  * 比较 (comparison)          - she starts measuring herself against them;
  * 嫉妒 (envy)                 - the other person is taking something she wants.

Inputs are the relationship stage with the person who mentioned the third
party, how fair the situation feels, the third person (presence and closeness),
and her own self-evaluation.  Output is the level, a 0..1 intensity, one
behaviour tendency (探问 / 收敛 / 挑刺 / 压下) and a one-line reason.

Literature: Festinger 1954 (social comparison), Parrott & Smith 1993 (benign vs
malicious envy), Smith & Kim 2007 (envy and schadenfreude).  Pure functions
only: dict in, dict out.  No IO, no clock, no LLM, no prompt text, and it never
imports main.py.  The module can be switched off.
"""
from __future__ import annotations

KINDS = ("轻微在意", "比较", "嫉妒")
KIND_KEY = {"轻微在意": "mild", "比较": "comparison", "嫉妒": "envy", "": "none"}
BEHAVIORS = ("探问", "收敛", "挑刺", "压下")
STAGE_CLOSENESS = {
    "stranger": 0.05,
    "acquaintance": 0.20,
    "colleague": 0.30,
    "friend": 0.45,
    "close": 0.70,
    "family": 0.80,
    "intimate": 0.90,
    "partner": 0.95,
    "lover": 0.95,
}
TRIGGER_THRESHOLD = 0.20
COMPARE_THRESHOLD = 0.45
ENVY_THRESHOLD = 0.70
SCALE = 1.20
DEFAULT_CONFIG = {"enabled": True, "threshold": TRIGGER_THRESHOLD}
REASONS = {
    "轻微在意": "他提到那个人时，她的注意力被轻轻拽了一下",
    "比较": "她开始拿自己和那个人比",
    "嫉妒": "那个人分走了她在意的东西，她有点嫉妒",
    "": "这次没有触发比较",
    "disabled": "嫉妒模块已关闭",
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


def _config(config):
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(config, bool):
        cfg["enabled"] = config
        return cfg
    if isinstance(config, dict):
        cfg["enabled"] = bool(config.get("enabled", True))
        cfg["threshold"] = _clamp01(
            config.get("threshold", TRIGGER_THRESHOLD), TRIGGER_THRESHOLD)
    return cfg


def _closeness(value):
    """Relationship stage -> 0..1 closeness (strings or a number both work)."""
    if isinstance(value, bool):
        return 0.40
    if isinstance(value, (int, float)):
        return _clamp01(value)
    text = str(value or "").strip().lower()
    if not text:
        return 0.40
    return STAGE_CLOSENESS.get(text, 0.40)


def _third_party(value):
    """Presence x closeness of the mentioned third person, 0..1."""
    if isinstance(value, dict):
        presence = value.get("presence", value.get("mentioned", 1.0))
        closeness = _clamp01(value.get("closeness", 0.5), 0.5)
    elif isinstance(value, bool):
        presence = 1.0 if value else 0.0
        closeness = 0.5
    elif isinstance(value, (int, float)):
        presence = _clamp01(value)
        closeness = 0.5
    else:
        presence = 0.0
        closeness = 0.5
    return _clamp01(_clamp01(presence) * (0.5 + 0.5 * closeness), 0.0)


def _normalize(signals):
    signals = signals if isinstance(signals, dict) else {}
    return {
        "closeness": _closeness(signals.get("relation_stage")),
        "fairness": _clamp01(signals.get("fairness", 0.5), 0.5),
        "third_party": _third_party(signals.get("third_party")),
        "self_evaluation": _clamp01(
            signals.get("self_evaluation", 0.5), 0.5),
    }


def _components(norm):
    """Every signal behind the intensity, each on its own line.

    intensity is kept as a display readout; the components are the evidence,
    so "comparison" and "self-threat" are never fused into one number.
    """
    norm = norm if isinstance(norm, dict) else {}
    closeness = _clamp01(norm.get("closeness", 0.5), 0.5)
    fairness = _clamp01(norm.get("fairness", 0.5), 0.5)
    third = _clamp01(norm.get("third_party", 0.0), 0.0)
    self_eval = _clamp01(norm.get("self_evaluation", 0.5), 0.5)
    return {
        "comparison": round(third, 4),
        "relative_deprivation": round(1.0 - fairness, 4),
        "self_threat": round(1.0 - self_eval, 4),
        "closeness": round(closeness, 4),
        "presence": round(third * (0.5 + 0.5 * closeness), 4),
    }


def intensity_of(signals):
    """0..1 comparison intensity; the single number behind the three levels."""
    norm = _normalize(signals)
    rel = 0.35 + 0.65 * norm["closeness"]
    unfair = 1.0 - norm["fairness"]
    buffer = 1.0 - 0.55 * norm["self_evaluation"]
    core = (norm["third_party"] * rel
            * (0.25 + 0.75 * unfair) * buffer)
    return round(_clamp01(core * SCALE), 4)


def kind_of(intensity, threshold=TRIGGER_THRESHOLD):
    """Map an intensity to the three-level label; '' means not triggered."""
    value = _clamp01(intensity)
    floor = _clamp01(threshold, TRIGGER_THRESHOLD)
    if value < floor:
        return ""
    if value < COMPARE_THRESHOLD:
        return "轻微在意"
    if value < ENVY_THRESHOLD:
        return "比较"
    return "嫉妒"


def behavior_for(kind, closeness, self_evaluation):
    """One behaviour tendency for a level; '' when nothing was triggered."""
    closeness = _clamp01(closeness, 0.40)
    self_evaluation = _clamp01(self_evaluation, 0.5)
    if kind == "嫉妒":
        return "压下" if self_evaluation <= 0.20 else "挑刺"
    if kind == "比较":
        return "探问" if closeness >= 0.50 else "收敛"
    if kind == "轻微在意":
        return "收敛" if closeness < 0.60 else "探问"
    return ""


def assess(signals, config=None):
    """One envy read: level / intensity / behaviour / reason."""
    cfg = _config(config)
    norm = _normalize(signals)
    intensity = intensity_of(signals)
    out = {
        "enabled": bool(cfg["enabled"]),
        "kind": "",
        "kind_key": KIND_KEY[""],
        "intensity": 0.0,
        "behavior": "",
        "reason": REASONS[""],
        "signals": norm,
        "components": _components(norm),
    }
    if not out["enabled"]:
        out["reason"] = REASONS["disabled"]
        return out
    kind = kind_of(intensity, cfg["threshold"])
    if not kind:
        out["intensity"] = intensity
        return out
    out["kind"] = kind
    out["kind_key"] = KIND_KEY[kind]
    out["intensity"] = intensity
    out["behavior"] = behavior_for(
        kind, norm["closeness"], norm["self_evaluation"])
    out["reason"] = REASONS[kind]
    return out


def view(result):
    """Panel-friendly subset of one assess() result (no prompt text)."""
    data = result if isinstance(result, dict) else {}
    return {
        "enabled": bool(data.get("enabled", False)),
        "kind": str(data.get("kind") or ""),
        "kind_key": str(data.get("kind_key") or KIND_KEY[""]),
        "intensity": round(_clamp01(data.get("intensity", 0.0)), 4),
        "behavior": str(data.get("behavior") or ""),
        "reason": str(data.get("reason") or ""),
    }
