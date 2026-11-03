# -*- coding: utf-8 -*-
"""She may not answer, and she may end a topic.

Not every message deserves a reply. A companion who is tired, tense or
already in conflict may delay the answer, stay silent for a turn, or close
the topic instead of carrying it further. The decision is a bounded
four-way choice:

  respond    answer now
  delay      answer, but not yet (delay_seconds)
  silent     do not answer this turn
  end_topic  answer briefly and close the topic

Inputs are read-only and defensive: state (energy/stress/valence/social),
relationship (closeness/trust/conflict) and topic (intensity or
{'intensity': 0-1, 'kind': ...}). Scores are clamped 0-1 and normalised
into a distribution; without a roll the strongest action wins.

exit_or_silence(state=None, relationship=None, topic=None, flags=None,
                roll=None) returns:

  enabled / action / probability / distribution / delay_seconds /
  reason / roll

Pure functions only: no IO, no clock, no randomness, no host imports, no
LLM calls. A caller that wants sampling passes its own roll in [0, 1).
The module never imports main.py.
"""
from __future__ import annotations

ACTIONS = ("respond", "delay", "silent", "end_topic")
HEAVY_KINDS = ("conflict", "fight", "heavy", "complaint", "sensitive")
DELAY_MIN_S = 30
DELAY_MAX_S = 900

_REASONS = {
    "respond": "还接得住，正常回",
    "delay": "现在没力气，缓一会儿再说",
    "silent": "太累/太堵，这轮先不回",
    "end_topic": "这个话题压得慌，先收住",
}

_TONES = {
    "respond": "",
    "delay": "晚点再回，别急着接",
    "silent": "这轮先不回",
    "end_topic": "收个尾，不展开",
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


def _state(state):
    state = state if isinstance(state, dict) else {}
    return {
        "energy": _clamp(state.get("energy", 0.6)),
        "stress": _clamp(state.get("stress", 0.3)),
        "valence": max(-1.0, min(1.0, _num(state.get("valence"), 0.0))),
        "social": _clamp(state.get("social", state.get("social_battery", 0.6))),
        "closeness": _clamp(state.get("closeness", 0.5)),
        "trust": _clamp(state.get("trust", 0.5)),
        "conflict": _clamp(state.get("conflict", 0.0)),
    }


def _relationship(relationship, state):
    relationship = relationship if isinstance(relationship, dict) else {}
    return {
        "closeness": _clamp(relationship.get(
            "closeness", relationship.get("intimacy", state["closeness"]))),
        "trust": _clamp(relationship.get("trust", state["trust"])),
        "conflict": _clamp(relationship.get("conflict", state["conflict"])),
    }


def _topic(topic):
    if isinstance(topic, dict):
        intensity = topic.get("intensity", topic.get("strength", 0.4))
        kind = str(topic.get("kind") or "").lower()
    elif topic is None:
        intensity = 0.4
        kind = ""
    else:
        intensity = topic
        kind = ""
    burden = _clamp(intensity)
    if kind in HEAVY_KINDS:
        burden = max(burden, 0.75)
    return {"intensity": round(burden, 3), "kind": kind[:12]}


def _scores(state, rel, topic):
    energy = state["energy"]
    stress = state["stress"]
    down = max(0.0, -state["valence"])
    conflict = rel["conflict"]
    closeness = rel["closeness"]
    trust = rel["trust"]
    burden = topic["intensity"]
    respond = (0.50 + 0.18 * closeness + 0.12 * trust
               + 0.15 * energy - 0.30 * down - 0.22 * conflict
               - 0.28 * max(0.0, burden - 0.60) - 0.20 * stress)
    delay = (0.12 + 0.40 * stress + 0.28 * (1.0 - energy)
             + 0.10 * burden + 0.12 * conflict + 0.10 * down)
    silent = (0.04 + 0.50 * (1.0 - energy) + 0.30 * stress
              + 0.30 * down + 0.15 * conflict
              + 0.10 * (1.0 - closeness) - 0.18 * trust)
    end_topic = (0.05 + 0.85 * max(0.0, burden - 0.45)
                 + 0.25 * conflict + 0.20 * down
                 + 0.12 * (1.0 - trust) + 0.08 * stress
                 - 0.08 * closeness)
    return {
        "respond": _clamp(respond),
        "delay": _clamp(delay),
        "silent": _clamp(silent),
        "end_topic": _clamp(end_topic),
    }


def _normalise(scores):
    total = sum(scores.get(action, 0.0) for action in ACTIONS)
    if total <= 0.0:
        return {action: (1.0 if action == "respond" else 0.0)
                for action in ACTIONS}
    dist = {action: scores.get(action, 0.0) / total for action in ACTIONS}
    rounded = {action: round(dist[action], 3) for action in ACTIONS}
    drift = round(1.0 - sum(rounded.values()), 3)
    top = max(ACTIONS, key=lambda action: rounded[action])
    rounded[top] = round(_clamp(rounded[top] + drift), 3)
    return rounded


def _pick(dist, roll):
    if roll is None:
        return max(ACTIONS, key=lambda action: dist[action])
    point = _num(roll, 0.0)
    if point < 0.0:
        point = 0.0
    if point >= 1.0:
        point = 0.999999
    acc = 0.0
    for action in ACTIONS:
        acc += dist[action]
        if point < acc:
            return action
    return ACTIONS[-1]


def _delay_seconds(state, topic):
    value = (60.0 + 240.0 * state["stress"]
             + 180.0 * (1.0 - state["energy"])
             + 120.0 * topic["intensity"])
    return int(max(DELAY_MIN_S, min(DELAY_MAX_S, round(value))))


def _disabled():
    dist = {action: (1.0 if action == "respond" else 0.0)
            for action in ACTIONS}
    return {
        "enabled": False,
        "action": "respond",
        "probability": 1.0,
        "distribution": dist,
        "delay_seconds": 0,
        "reason": "沉默/退出模块关闭，照常回",
        "roll": None,
    }


def exit_or_silence(state=None, relationship=None, topic=None,
                    flags=None, roll=None):
    """Decide whether and how to answer this turn. Plain dict, no IO."""
    flags = flags if isinstance(flags, dict) else {}
    if not bool(flags.get("enabled", True)):
        return _disabled()
    snap = _state(state)
    rel = _relationship(relationship, snap)
    top = _topic(topic)
    scores = _scores(snap, rel, top)
    dist = _normalise(scores)
    action = _pick(dist, roll)
    probability = round(dist[action], 3)
    delay = _delay_seconds(snap, top) if action == "delay" else 0
    return {
        "enabled": True,
        "action": action,
        "probability": probability,
        "distribution": dist,
        "delay_seconds": delay,
        "reason": _REASONS[action],
        "roll": None if roll is None else round(_num(roll, 0.0), 4),
    }


def should_reply(result):
    """False only for the silent action (delay still replies, later)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return True
    return result.get("action") != "silent"


def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"send": True, "delay_seconds": 0, "length_scale": 1.0,
                "tone": "", "action": "respond"}
    action = str(result.get("action") or "respond")
    table = {
        "respond": {"send": True, "length_scale": 1.0},
        "delay": {"send": True, "length_scale": 0.9},
        "silent": {"send": False, "length_scale": 0.0},
        "end_topic": {"send": True, "length_scale": 0.6},
    }
    base = dict(table.get(action, table["respond"]))
    base["delay_seconds"] = int(_num(result.get("delay_seconds"), 0.0))
    base["tone"] = _TONES.get(action, "")
    base["action"] = action
    return base
