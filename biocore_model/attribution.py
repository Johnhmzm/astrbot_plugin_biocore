# -*- coding: utf-8 -*-
"""BIO-3: causal attribution (Weiner 1985). Pure functions; no IO."""
from __future__ import annotations

AXES = ("locus", "stability", "controllability")
EXTERNAL = ("他", "她", "对方", "老板", "公司", "环境", "别人", "他们")
INTERNAL = ("我", "自己", "是我", "我的错")
STABLE = ("总是", "每次", "又", "一直", "老是")
UNSTABLE = ("这次", "偶尔", "第一次", "刚好")
CONTROLLABLE = ("能", "可以", "改", "解决", "来得及")
UNCONTROLLABLE = ("没办法", "改不了", "控制不了", "来不及", "注定")


def _contains(text, words):
    return any(word in text for word in words)


def infer(event=None, conversation_hint=None):
    """Rule-based attribution; ambiguous -> neutral (never guess)."""
    text = ""
    if isinstance(event, dict):
        text = str(event.get("text") or event.get("title") or "")
    text += " " + str(conversation_hint or "")
    locus = "external" if _contains(text, EXTERNAL) else ("internal" if _contains(text, INTERNAL) else "neutral")
    stability = "stable" if _contains(text, STABLE) else ("unstable" if _contains(text, UNSTABLE) else "neutral")
    controllability = "uncontrollable" if _contains(text, UNCONTROLLABLE) else (
        "controllable" if _contains(text, CONTROLLABLE) else "neutral")
    return {"locus": locus, "stability": stability, "controllability": controllability,
            "emotion_hint": quadrant(locus, stability, controllability)}


def quadrant(locus, stability, controllability):
    if locus == "internal" and stability == "stable" and controllability == "uncontrollable":
        return "shame"
    if locus == "external" and controllability == "controllable":
        return "anger"
    if locus == "external" and controllability == "uncontrollable":
        return "sadness"
    if locus == "internal" and stability == "unstable" and controllability == "controllable":
        return "guilt"
    return "neutral"


DELTAS = {
    "shame": {"self_blame": 0.10, "valence": -0.06, "confidence": -0.05},
    "anger": {"anger": 0.08, "stress": 0.04, "drive": 0.02},
    "sadness": {"sadness": 0.08, "drive": -0.04, "valence": -0.03},
    "guilt": {"guilt": 0.08, "repair": 0.05, "valence": -0.02},
    "neutral": {},
}


def apply(core_state, attribution, now):
    """Return deltas only; never mutate core. Idempotent per now."""
    state = dict(core_state or {})
    if float(state.get("last_attribution_ts", 0.0) or 0.0) >= float(now):
        return {}
    hint = str((attribution or {}).get("emotion_hint") or "neutral")
    deltas = dict(DELTAS.get(hint, {}))
    if deltas:
        deltas["last_attribution_ts"] = float(now)
        deltas["emotion_hint"] = hint
    return deltas


def view(state, attribution=None):
    data = dict(state or {})
    attribution = attribution if isinstance(attribution, dict) else {}
    locus = attribution.get("locus", data.get("locus", "neutral"))
    stability = attribution.get("stability", data.get("stability", "neutral"))
    controllability = attribution.get("controllability", data.get("controllability", "neutral"))
    return {"locus": locus, "stability": stability, "controllability": controllability,
            "emotion_hint": attribution.get("emotion_hint") or quadrant(locus, stability, controllability)}
