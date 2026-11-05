# -*- coding: utf-8 -*-
"""What happens after one of her lines is crossed.

A boundary crossing (boundary.py) is not answered by a rule; it is answered
with a short repair sequence:

  1. cold       she goes quiet: short replies, no warmth, no initiative
  2. state      she says out loud which line was crossed, no detour
  3. record     she keeps the score: normal talk, less warmth
  4. turn_page  she lets it go, either for real or by timeout with debt kept

Progress depends on two things only: elapsed time and apology quality. A good
apology shortens every step; silence never skips the cold stage. If nothing
happens for long enough the flow falls back to turn_page but leaves the debt
on the record (超时回落，不假装原谅).

State is a plain dict owned by the caller: start/from_boundary opens one,
advance moves it forward without mutating the input and without ever moving
the stage backwards. evaluate is the stateless convenience used by tests and
wiring.

Pure functions only: no IO, no clock, no host imports, no LLM calls, and no
prompt text. The module never imports main.py.
"""
from __future__ import annotations

from . import boundary

STAGES = ("cold", "state", "record", "turn_page")
LABELS = {"cold": "冷处理", "state": "明说", "record": "记账",
          "turn_page": "翻页"}

# [engineering] stage durations and the forgive floor are hand-tuned.
COLD_SECONDS = 300.0       # cold -> state
STATE_SECONDS = 1800.0     # state -> record
RECORD_SECONDS = 7200.0    # record -> turn_page
TIMEOUT_SECONDS = 6 * 3600.0
FORGIVE_MIN = 0.6

_DEFAULT_SEVERITY = {"tool": 0.60, "old_score": 0.55, "lie": 0.60,
                     "contempt": 0.60}

_DIRECTIVES = {
    "cold": {"length_scale": 0.45, "warmth": 0.10, "initiative": 0.05,
             "tone": "先冷一冷，不主动"},
    "state": {"length_scale": 0.85, "warmth": 0.30, "initiative": 0.20,
              "tone": "把越界的话说清楚，不绕"},
    "record": {"length_scale": 0.95, "warmth": 0.45, "initiative": 0.30,
               "tone": "正常说话，但别急着翻篇"},
    "turn_page": {"length_scale": 1.05, "warmth": 0.70, "initiative": 0.45,
                  "tone": "可以翻页了"},
}

_REPLY_POLICY = {
    "cold": {"mode": "cold_short", "suppress_affection": True,
             "max_chars": 20, "tone": "只回很短一句，不主动"},
    "state": {"mode": "state", "suppress_affection": True,
              "max_chars": 60, "tone": "把越界的话说清楚"},
    "record": {"mode": "normal", "suppress_affection": False,
               "max_chars": 120, "tone": "正常说话，别急着翻篇"},
    "turn_page": {"mode": "normal", "suppress_affection": False,
                  "max_chars": 200, "tone": "可以翻页"},
}


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


def _relationship(relationship):
    relationship = relationship if isinstance(relationship, dict) else {}
    return {
        "closeness": _clamp(
            relationship.get("closeness", relationship.get("intimacy", 0.5))),
        "trust": _clamp(relationship.get("trust", 0.5)),
        "conflict": _clamp(relationship.get("conflict", 0.0)),
    }


def apology_quality(quality=0.0, count=1):
    """A repeated apology counts less; bounded 0-1."""
    base = _clamp(quality)
    repeats = int(max(0.0, _num(count, 1.0)))
    if repeats <= 1:
        return round(base, 3)
    return round(_clamp(base * (1.0 - 0.15 * min(repeats - 1, 3))), 3)


def thresholds(severity=0.5, quality=0.0, count=1, relationship=None,
               flags=None):
    """Time gates for the four stages, in seconds.

    Bigger hurt, more conflict and less trust stretch the gates; a good
    apology shrinks them. flags['timeout_seconds'] overrides the
    timeout fallback (minimum one minute, for tests and hosts).
    """
    flags = flags if isinstance(flags, dict) else {}
    rel = _relationship(relationship)
    hurt = _clamp(severity)
    q = apology_quality(quality, count)
    scaled = max(0.35, 1.0 + 0.80 * hurt + 0.50 * rel["conflict"]
                 - 0.30 * rel["trust"])
    state_at = COLD_SECONDS * scaled * (1.0 - 0.50 * q)
    record_at = state_at + STATE_SECONDS * scaled * (1.0 - 0.60 * q)
    page_at = record_at + RECORD_SECONDS * scaled * (1.0 - 0.75 * q)
    timeout = max(60.0, _num(flags.get("timeout_seconds"), TIMEOUT_SECONDS))
    return {
        "state": round(state_at, 1),
        "record": round(record_at, 1),
        "page": round(page_at, 1),
        "timeout": round(timeout, 1),
        "scaled": round(scaled, 3),
        "quality": round(q, 3),
    }


def _stage_at(elapsed, gates, severity):
    if elapsed >= gates["timeout"]:
        return "turn_page", True
    if elapsed >= gates["page"]:
        return "turn_page", False
    if elapsed >= gates["record"]:
        return "record", False
    if elapsed >= gates["state"]:
        return "state", False
    return "cold", False


def _forgiveness(elapsed, gates, quality, rel, severity):
    ratio = min(1.0, elapsed / max(1.0, gates["page"]))
    return round(_clamp(0.55 * quality + 0.25 * ratio
                        + 0.12 * rel["trust"] - 0.18 * rel["conflict"]
                        - 0.10 * _clamp(severity)), 3)


def _debt(stage, resolved, fallback, quality, severity):
    hurt = _clamp(severity)
    if stage == "cold":
        return round(_clamp(hurt * 0.75), 3)
    if stage == "state":
        return round(_clamp(hurt * 0.85), 3)
    if stage == "record":
        return round(_clamp(hurt * (1.0 - 0.30 * quality)), 3)
    if resolved:
        return round(_clamp(hurt * 0.15 * (1.0 - 0.50 * quality)), 3)
    if fallback:
        return round(_clamp(hurt * 0.55 * (1.0 - 0.30 * quality)), 3)
    return round(_clamp(hurt * 0.45 * (1.0 - 0.30 * quality)), 3)


def _reason(stage, timeout_hit, resolved, fallback):
    if stage == "cold":
        return "先冷一冷，不急着回应"
    if stage == "state":
        return "把越界的话说清楚"
    if stage == "record":
        return "记下这一次，别马上翻篇"
    if fallback:
        return "等太久了，先翻页，账还记着"
    if resolved:
        return "翻页了，也真的过去了"
    return "翻页了，但还没真的过去"


def _directive(stage, forgiveness):
    base = dict(_DIRECTIVES.get(stage, _DIRECTIVES["turn_page"]))
    if stage in ("record", "turn_page"):
        base["warmth"] = round(_clamp(
            base["warmth"] * (0.5 + 0.5 * _clamp(forgiveness))), 3)
    base["length_scale"] = round(_clamp(base["length_scale"], 0.3, 1.1), 3)
    base["warmth"] = round(_clamp(base["warmth"]), 3)
    base["initiative"] = round(_clamp(base["initiative"]), 3)
    base["tone"] = str(base.get("tone") or "")[:30]
    base["stage"] = stage
    return base


def _severity_of(boundary_result):
    kind = str(boundary_result.get("kind") or "")
    raw = boundary_result.get("severity")
    if raw is None:
        return _DEFAULT_SEVERITY.get(kind, 0.5)
    return _clamp(raw)


def _inactive(reason="没有越界，不需要修复"):
    return {
        "enabled": True,
        "active": False,
        "kind": "",
        "severity": 0.0,
        "stage": "turn_page",
        "label": LABELS["turn_page"],
        "elapsed": 0.0,
        "apology_quality": 0.0,
        "apology_count": 0,
        "forgiveness": 0.0,
        "debt": 0.0,
        "hold": False,
        "resolved": True,
        "fallback": False,
        "directive": _directive("turn_page", 1.0),
        "reason": reason,
    }


def _disabled(kind="", severity=0.0):
    out = _inactive("修复流程关闭，按旧行为处理")
    out.update({"enabled": False, "kind": str(kind or ""),
                "severity": round(_clamp(severity), 3)})
    return out


def _build(stage, timeout_hit, elapsed, kind, severity, quality, count,
           gates, rel):
    q = gates["quality"]
    forgiveness = _forgiveness(elapsed, gates, q, rel, severity)
    resolved = (stage == "turn_page" and not timeout_hit
                and forgiveness >= FORGIVE_MIN)
    fallback = bool(timeout_hit and q < FORGIVE_MIN)
    debt = _debt(stage, resolved, fallback, q, severity)
    return {
        "enabled": True,
        "active": True,
        "kind": str(kind or ""),
        "severity": round(_clamp(severity), 3),
        "stage": stage,
        "label": LABELS[stage],
        "elapsed": round(max(0.0, elapsed), 1),
        "apology_quality": round(q, 3),
        "apology_count": int(max(0, count)),
        "forgiveness": forgiveness,
        "debt": debt,
        "hold": stage in ("cold", "state"),
        "resolved": bool(resolved),
        "fallback": fallback,
        "thresholds": gates,
        "directive": _directive(stage, forgiveness),
        "reason": _reason(stage, timeout_hit, resolved, fallback),
    }


def start(boundary_result=None, relationship=None, flags=None):
    """Open a repair flow from a boundary.judge() result (or a plain dict)."""
    flags = flags if isinstance(flags, dict) else {}
    data = boundary_result if isinstance(boundary_result, dict) else {}
    kind = str(data.get("kind") or "")
    severity = _severity_of(data)
    hit = bool(data.get("crossed")) or bool(data.get("handoff"))
    if not bool(flags.get("enabled", True)):
        return _disabled(kind, severity)
    if not hit:
        return _inactive()
    rel = _relationship(relationship)
    gates = thresholds(severity, 0.0, 0, rel, flags)
    return _build("cold", False, 0.0, kind, severity, 0.0, 0, gates, rel)


def advance(state, elapsed_delta=0.0, apology_quality=None,
            apology_count=None, relationship=None, flags=None):
    """Move an open repair flow forward; never mutates state."""
    flags = flags if isinstance(flags, dict) else {}
    state = state if isinstance(state, dict) else {}
    if not bool(flags.get("enabled", True)):
        return _disabled(state.get("kind"), state.get("severity"))
    if not state.get("active", False):
        return _inactive(str(state.get("reason") or "没有越界，不需要修复"))

    rel = _relationship(relationship if relationship is not None
                        else state.get("relationship"))
    elapsed = max(0.0, _num(state.get("elapsed"), 0.0)
                  + max(0.0, _num(elapsed_delta, 0.0)))
    prev_q = _num(state.get("apology_quality"), 0.0)
    prev_count = int(max(0.0, _num(state.get("apology_count"), 0.0)))
    if apology_quality is not None:
        q = max(prev_q, _clamp(apology_quality))
        count = (prev_count + 1 if apology_count is None
                 else max(prev_count, int(_num(apology_count, prev_count))))
    else:
        q = prev_q
        count = prev_count

    kind = str(state.get("kind") or "")
    severity = _clamp(state.get("severity"), 0.0, 1.0)
    gates = thresholds(severity, q, count, rel, flags)
    stage, timeout_hit = _stage_at(elapsed, gates, severity)
    prev_stage = str(state.get("stage") or "cold")
    if prev_stage in STAGES and STAGES.index(prev_stage) > STAGES.index(stage):
        stage = prev_stage
        timeout_hit = False

    out = _build(stage, timeout_hit, elapsed, kind, severity,
                 q, count, gates, rel)
    out["relationship"] = rel
    return out


def evaluate(boundary_result=None, elapsed_seconds=0.0, apology_quality=None,
             apology_count=None, relationship=None, flags=None):
    """Stateless: start a flow and immediately advance it."""
    flags = flags if isinstance(flags, dict) else {}
    data = boundary_result if isinstance(boundary_result, dict) else {}
    severity = _severity_of(data)
    if not bool(flags.get("enabled", True)):
        return _disabled(data.get("kind"), severity)
    state = start(boundary_result, relationship, flags)
    if not state.get("active", False):
        return state
    return advance(state, elapsed_delta=elapsed_seconds,
                   apology_quality=apology_quality,
                   apology_count=apology_count,
                   relationship=relationship, flags=flags)


def from_boundary(boundary_result, relationship=None, flags=None):
    """Bridge for boundary.py results; alias kept for readable wiring."""
    return start(boundary_result, relationship, flags)


def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True) \
            or not result.get("active", False):
        return {"stage": "turn_page", "length_scale": 1.0, "warmth": 0.5,
                "initiative": 0.4, "tone": ""}
    stage = str(result.get("stage") or "turn_page")
    base = _directive(stage, _num(result.get("forgiveness"), 0.0))
    return base


def reply_policy(result):
    """How to answer while the flow is open; cold still may refuse a turn."""
    if not isinstance(result, dict) or not result.get("enabled", True) \
            or not result.get("active", False):
        return {"mode": "normal", "suppress_affection": False,
                "max_chars": 0, "tone": ""}
    stage = str(result.get("stage") or "cold")
    base = dict(_REPLY_POLICY.get(stage, _REPLY_POLICY["turn_page"]))
    if stage == "turn_page" and result.get("fallback"):
        base["tone"] = "先翻页，账还记着"
    return base
