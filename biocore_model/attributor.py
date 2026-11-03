# -*- coding: utf-8 -*-
"""Attribution layer: why did this happen, and who is answerable.

Weiner's attribution model maps three dimensions onto distinct emotions:
locus (me / you / situation), stability (does it keep happening), and
controllability (could it have been helped). The same event attributed
differently produces anger, guilt, helplessness or sympathy, and the
expression layer reacts accordingly.

This module turns appraisal dims into that attribution:

  dims  blame (0-1) / goal (-1..1) / hit (0-1) / involve (0-1)
  event optional {'who': 'me'|'you'|'situation', 'text': ...}

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

LOCI = ("me", "you", "situation")
EMOTIONS = ("anger", "guilt", "helplessness", "sympathy", "neutral")
CONFIDENCE_FLOOR = 0.25

def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:
        return default
    return num

def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))

def _dims(dims):
    dims = dims if isinstance(dims, dict) else {}
    return {
        "blame": _clamp(dims.get("blame", 0.0)),
        "goal": max(-1.0, min(1.0, _num(dims.get("goal"), 0.0))),
        "hit": _clamp(dims.get("hit", 0.0)),
        "involve": _clamp(dims.get("involve", 0.5)),
    }

def cues(dims=None, event=None, relationship=None):
    """Three competing explanations, each scored 0-1."""
    d = _dims(dims)
    event = event if isinstance(event, dict) else {}
    relationship = relationship if isinstance(relationship, dict) else {}
    who = str(event.get("who") or "")
    closeness = _clamp(relationship.get("closeness", 0.5));
    harm = max(0.0, -d["goal"])

    you = (0.60 * d["blame"] + 0.25 * harm
           + (0.15 if who == "you" else 0.0))
    me = ((0.55 if who == "me" else 0.0)
          + 0.30 * d["hit"] * (1.0 - d["blame"])
          + 0.15 * (1.0 - closeness))
    situation = (0.45 * (1.0 - d["involve"])
                 + 0.30 * (1.0 - d["blame"])
                 + (0.25 if who == "situation" else 0.0))
    return {
        "me": round(_clamp(me), 3),
        "you": round(_clamp(you), 3),
        "situation": round(_clamp(situation), 3),
    }

def stability(dims=None, event=None, relationship=None):
    """0 = one-off, 1 = this keeps happening."""
    d = _dims(dims)
    relationship = relationship if isinstance(relationship, dict) else {}
    history = _clamp(relationship.get("conflict", 0.0))
    value = 0.45 * d["blame"] + 0.35 * history + 0.20 * d["involve"]
    return round(_clamp(value), 3)

def controllability(dims=None, event=None, relationship=None):
    """0 = nobody could have helped it, 1 = it was fully avoidable."""
    d = _dims(dims)
    event = event if isinstance(event, dict) else {}
    who = str(event.get("who") or "")
    base = 0.65 * d["blame"] + 0.35 * d["involve"]
    if who == "situation":
        base *= 0.4
    return round(_clamp(base), 3)

def _emotion(locus, control, dims, closeness):
    """Pick the reaction that fits this attribution."""
    if locus == "you":
        return "anger" if control >= 0.45 else "sympathy"
    if locus == "me":
        return "guilt" if control >= 0.45 else "helplessness"
    if dims["hit"] >= 0.6 and dims["blame"] < 0.3:
        return "sympathy" if closeness >= 0.4 else "helplessness"
    return "helplessness" if control < 0.45 else "neutral"

REACTIONS = {
    "anger": "可以顶回去一句，但别翻旧账",
    "guilt": "先认一句，再解释",
    "helplessness": "别硬撑，承认没办法",
    "sympathy": "先接住对方，再问一句",
    "neutral": "正常说",
}

REASONS = {
    "me": "这件事更像是我这边的原因",
    "you": "这件事更像是对方的原因",
    "situation": "这件事不像谁的错，是情况所致",
}

def attribute(dims=None, event=None, relationship=None, flags=None):
    """One attribution for one event. Returns a plain dict."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    scores = cues(dims, event, relationship)
    ordered = sorted(scores.items(), key=lambda row: row[1], reverse=True)
    locus, top = ordered[0] if ordered else ("situation", 0.0)
    second = ordered[1][1] if len(ordered) > 1 else 0.0
    margin = round(max(0.0, top - second), 3)
    if top < CONFIDENCE_FLOOR:
        locus = "situation"
    d = _dims(dims)
    relationship = relationship if isinstance(relationship, dict) else {}
    closeness = _clamp(relationship.get("closeness", 0.5))
    stable = stability(dims, event, relationship)
    control = controllability(dims, event, relationship)
    emotion = _emotion(locus, control, d, closeness)

    if not enabled:
        return {
            "enabled": False, "locus": "situation", "stability": stable,
            "controllability": control, "emotion": "neutral",
            "confidence": margin, "scores": scores,
            "attribution_reason": "归因层关闭", "reaction": REACTIONS["neutral"],
        }

    return {
        "enabled": True,
        "locus": locus,
        "stability": stable,
        "controllability": control,
        "emotion": emotion,
        "confidence": margin,
        "scores": scores,
        "attribution_reason": REASONS.get(locus, ""),
        "reaction": REACTIONS.get(emotion, REACTIONS["neutral"]),
    }

def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"tone": "", "length_scale": 1.0, "emotion": "neutral"}
    emotion = result.get("emotion") or "neutral"
    scale = 0.9 if emotion in ("anger", "guilt") else 1.0
    tone = ""
    if emotion == "anger":
        tone = "语气硬一点，但别解释太多"
    elif emotion == "guilt":
        tone = "先低一点，别急着辩解"
    elif emotion == "helplessness":
        tone = "可以承认没办法"
    elif emotion == "sympathy":
        tone = "先接住对方"
    return {"tone": tone, "length_scale": scale, "emotion": emotion}
