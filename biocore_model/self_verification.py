# -*- coding: utf-8 -*-
"""P1 self-verification: the urge to correct a false picture of herself.

Self-verification theory (Swann 1983/2012): people want other people to see them
the way they see themselves.  When another person's description misses her
self-concept, the gap opens a corrective motive (想纠正), but its strength is
not a constant.  It is gated by:

  * self-concept clarity (Campbell 1996): clear self-knowledge makes her
    confident that the other person got it wrong;
  * relational stakes: the closer the person is, the more it matters that they
    know the real her.

The module returns a bounded 0..1 tendency for the intent layer; being seen
accurately stays at zero.  Pure functions only: no IO, no clock, no LLM, no
prompt text, and it never imports main.py.
"""
from __future__ import annotations

SELF_KEYS = ("warmth", "competence", "honesty", "autonomy", "playfulness")
CLARITY_FLOOR = 0.30
RELATION_FLOOR = 0.30
DEFAULT_SEVERITY = 0.60
INTENT_THRESHOLD = 0.35
STRONG_URGE = 0.60
DECAY_HALF_LIFE_HOURS = 2.0


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


def _misread_value(misread):
    """bool -> 0/1; a number is already a 0..1 degree of misunderstanding."""
    if isinstance(misread, bool):
        return 1.0 if misread else 0.0
    if isinstance(misread, dict):
        return 0.0
    return _clamp01(misread)


def misread_level(self_image, perceived):
    """0..1 mean gap between her self-concept and the picture others have.

    Only traits present in both dicts are compared, so a partial description
    cannot be counted as a total misunderstanding.
    """
    if not isinstance(self_image, dict) or not isinstance(perceived, dict):
        return 0.0
    keys = [key for key in SELF_KEYS
            if key in self_image and key in perceived]
    if not keys:
        return 0.0
    total = 0.0
    for key in keys:
        total += abs(_clamp01(self_image.get(key)) - _clamp01(perceived.get(key)))
    return round(_clamp01(total / float(len(keys))), 4)


def clarity_factor(clarity):
    """A clear self-concept raises the corrective urge; it never removes it."""
    return round(CLARITY_FLOOR + (1.0 - CLARITY_FLOOR) * _clamp01(clarity), 4)


def relation_factor(relation):
    """Closer relationships raise the stakes of being seen wrongly."""
    return round(RELATION_FLOOR + (1.0 - RELATION_FLOOR) * _clamp01(relation), 4)


def correction_urge(misread, clarity=0.6, relation=0.6,
                    severity=DEFAULT_SEVERITY):
    """0..1 corrective tendency for one episode; accurate description -> 0."""
    level = _misread_value(misread)
    if level <= 0.0:
        return 0.0
    value = (level * clarity_factor(clarity) * relation_factor(relation)
             * _clamp01(severity, DEFAULT_SEVERITY))
    return round(_clamp01(value), 4)


def compare(clarity=0.6, relation=0.6, severity=DEFAULT_SEVERITY):
    """Runnable acceptance check: misunderstood vs accurately described."""
    misunderstood = correction_urge(True, clarity, relation, severity)
    accurate = correction_urge(False, clarity, relation, severity)
    return {
        "misunderstood": misunderstood,
        "accurate": accurate,
        "delta": round(misunderstood - accurate, 4),
    }


def initial(now=0.0):
    return {
        "urge": 0.0,
        "peak": 0.0,
        "misread_count": 0,
        "last_event": "",
        "last_ts": float(now),
    }


def observe(state, misread, clarity=0.6, relation=0.6,
            severity=DEFAULT_SEVERITY, now=0.0, event=""):
    """Apply one episode of being described; one turn is one step."""
    data = dict(state or initial(now))
    last = float(data.get("last_ts", 0.0) or 0.0)
    if data.get("last_event") and float(now) <= last:
        return data
    level = _misread_value(misread)
    urge = correction_urge(level, clarity, relation, severity)
    data["urge"] = urge
    data["peak"] = round(max(_clamp01(data.get("peak", 0.0)), urge), 4)
    data["misread_count"] = int(data.get("misread_count", 0) or 0) + (
        1 if level > 0.0 else 0)
    data["last_event"] = str(
        event or ("misunderstood" if level > 0.0 else "seen_accurately"))
    data["last_ts"] = float(now)
    return data


def decay(state, now, half_life_hours=DECAY_HALF_LIFE_HOURS):
    """The corrective urge fades when the moment passes."""
    data = dict(state or initial(now))
    last = float(data.get("last_ts", 0.0) or 0.0)
    if last > 0.0 and float(now) <= last:
        return data
    if last <= 0.0:
        return data
    hours = max(0.0, (float(now) - last) / 3600.0)
    try:
        half_life = max(0.1, float(half_life_hours))
    except Exception:
        half_life = DECAY_HALF_LIFE_HOURS
    kept = 0.5 ** (hours / half_life)
    data["urge"] = round(_clamp01(float(data.get("urge", 0.0)) * kept), 4)
    data["last_ts"] = float(now)
    return data


def intent(state, threshold=INTENT_THRESHOLD):
    """Output handed to the intent layer: 0..1 correction tendency."""
    data = dict(state or initial())
    urge = _clamp01(data.get("urge", 0.0))
    if urge >= STRONG_URGE:
        strength = "strong"
    elif urge >= _clamp01(threshold, INTENT_THRESHOLD):
        strength = "mild"
    else:
        strength = "none"
    return {
        "correction": round(urge, 4),
        "want_correct": urge >= _clamp01(threshold, INTENT_THRESHOLD),
        "strength": strength,
    }


def view(state):
    """Panel / debug read (no prompt text)."""
    data = dict(state or initial())
    decided = intent(data)
    return {
        "urge": decided["correction"],
        "want_correct": decided["want_correct"],
        "strength": decided["strength"],
        "peak": round(_clamp01(data.get("peak", 0.0)), 4),
        "misread_count": int(data.get("misread_count", 0) or 0),
        "last_event": str(data.get("last_event") or ""),
    }
