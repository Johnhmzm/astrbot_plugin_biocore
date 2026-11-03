# -*- coding: utf-8 -*-
"""Possible selves: who she is still trying to become.

A possible self is a small target: a name plus the dimensions it would move.

  {"name": "更会照顾人", "target": {"benevolence": 0.9}, "importance": 0.8}

The gap between the target and where she is now becomes the weight: the
further away and the more it matters, the more it pulls. Output also carries
one short line ("她还想成为…") for logs and panels.

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

DIMENSIONS = ("self_direction", "stimulation", "hedonism", "achievement",
              "power", "security", "conformity", "tradition",
              "benevolence", "universalism")
MAX_SELVES = 6
SENTENCE_LIMIT = 24


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


def _selves(selves):
    out = []
    for raw in selves or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("label") or "").strip()
        if not name:
            continue
        target = raw.get("target") if isinstance(raw.get("target"), dict) else {}
        clean = {dim: round(_clamp(value), 3)
                 for dim, value in target.items() if dim in DIMENSIONS}
        if not clean:
            continue
        out.append({
            "name": name[:30],
            "target": clean,
            "importance": _clamp(raw.get("importance", 0.6)),
        })
    return out


def gap(target, current):
    """Mean distance between a target self and the current profile (0-1)."""
    target = target if isinstance(target, dict) else {}
    current = current if isinstance(current, dict) else {}
    if not target:
        return 0.0
    total = 0.0
    for dim, want in target.items():
        total += abs(_clamp(want) - _clamp(current.get(dim, 0.5)))
    return round(_clamp(total / len(target)), 3)


def rank(selves=None, current=None, flags=None):
    """Weight the possible selves by distance and importance."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    rows = _selves(selves)[:MAX_SELVES]
    current = current if isinstance(current, dict) else {}

    scored = []
    for row in rows:
        distance = gap(row["target"], current)
        weight = round(distance * row["importance"], 4)
        scored.append({"name": row["name"], "gap": distance,
                       "importance": row["importance"], "weight": weight})
    total = sum(item["weight"] for item in scored)
    for item in scored:
        item["share"] = round(item["weight"] / total, 3) if total > 0 else 0.0
    scored.sort(key=lambda item: item["weight"], reverse=True)

    top = scored[0] if scored else None
    sentence = ""
    if enabled and top:
        sentence = ("她还想成为%s" % top["name"])[:SENTENCE_LIMIT]
    return {
        "enabled": enabled,
        "selves": scored if enabled else [],
        "top": top["name"] if (enabled and top) else "",
        "sentence": sentence,
    }


def directives(result):
    """Bounded hint: the leading possible self nudges tone, nothing more."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"tone": "", "pull": 0.0}
    top = result.get("top") or ""
    pull = 0.0
    for item in result.get("selves") or []:
        if item.get("name") == top:
            pull = _clamp(item.get("weight", 0.0))
            break
    return {"tone": ("朝%s一点" % top) if top else "", "pull": round(pull, 3)}
