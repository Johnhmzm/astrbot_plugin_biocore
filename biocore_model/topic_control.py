# -*- coding: utf-8 -*-
"""Who is steering the conversation, and what she should do with it.

A companion does not only answer; sometimes she keeps the topic going, sometimes
she hands it back, sometimes she starts something new, sometimes she closes it.
This module reads the last few turns of topic control:

  initiate  started a new topic
  switch    changed the topic
  close     closed the topic
  keep      simply continued it

and turns them into:

  holder     me / you / shared
  dominance  0-1, her share of the topic-control moves (recency weighted)
  tendency   让出 / 接住 / 另起 / 收尾  (what she should do next)
  reason     one line for logs and the panel

The choice is a cheap four-way scoring: catching your topic is the default,
yielding happens when she has been steering and you have not, starting a new
one happens when the topic has gone stale and she has energy, closing happens
when a close signal or a late, tired state appears.

topic_control(turns=None, state=None, relationship=None, hour=None,
              flags=None) returns:

  enabled, holder, dominance, tendency, reason, counts, window, last_by, scores

Each turn is {'by': 'me'|'you', 'kind': initiate|switch|close|keep}. A string
'me:initiate' is accepted too. flags: enabled, window (default 6), closing.

Pure functions only: no IO, no clock, no host imports, no LLM calls. The
module never imports main.py.
"""
from __future__ import annotations

HOLDERS = ("me", "you", "shared")
TENDENCIES = ("让出", "接住", "另起", "收尾")
KINDS = ("initiate", "switch", "close", "keep")
CONTROL_KINDS = ("initiate", "switch")
HOLD_ME = 0.62
HOLD_YOU = 0.38
DEFAULT_WINDOW = 6
RECENCY = 0.75
NIGHT_HOURS = (23, 0, 1, 2, 3, 4, 5)

_SPEAKERS = {
    "me": "me", "her": "me", "she": "me", "self": "me", "我": "me",
    "you": "you", "user": "you", "him": "you", "他": "you", "对方": "you",
}
_KINDS = {
    "initiate": "initiate", "initiates": "initiate", "new": "initiate",
    "start": "initiate", "starts": "initiate",
    "switch": "switch", "switches": "switch", "change": "switch",
    "changes": "switch", "shift": "switch",
    "close": "close", "closes": "close", "end": "close", "ends": "close",
    "finish": "close", "wrap": "close",
    "keep": "keep", "continue": "keep", "continues": "keep",
}
REASONS = {
    "让出": "她一直主导，先把话头递回去",
    "接住": "顺着你刚说的往下聊",
    "另起": "这个话题拖太久了，她想换一个",
    "收尾": "话到这儿，她想收住",
}
TONES = {
    "让出": "把话递回去，等他接",
    "接住": "接着聊，不换题",
    "另起": "起个新话头",
    "收尾": "收住，不展开",
}
_INITIATIVE = {"让出": 0.10, "接住": 0.45, "另起": 0.90, "收尾": 0.20}


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


def _turn(turn):
    if isinstance(turn, str) and ":" in turn:
        head, tail = turn.split(":", 1)
        turn = {"by": head, "kind": tail}
    if not isinstance(turn, dict):
        turn = {}
    speaker = str(turn.get("by") or turn.get("speaker") or "you").strip().lower()
    speaker = _SPEAKERS.get(speaker, speaker if speaker in HOLDERS else "you")
    raw_kind = str(turn.get("kind") or turn.get("action")
                   or turn.get("type") or "keep").strip().lower()
    return {"by": speaker, "kind": _KINDS.get(raw_kind, "keep")}


def _rows(turns, window):
    if isinstance(turns, dict):
        turns = turns.get("turns") or []
    rows = []
    for turn in turns if isinstance(turns, (list, tuple)) else []:
        normalized = _turn(turn)
        rows.append(normalized)
    window = max(1, int(_num(window, DEFAULT_WINDOW)))
    return rows[-window:]


def metrics(turns=None, window=DEFAULT_WINDOW):
    """Recency-weighted topic-control facts over the last window turns."""
    rows = _rows(turns, window)
    count = len(rows)
    my_control = 0.0
    your_control = 0.0
    my_weight = 0.0
    total_weight = 0.0
    close_rows = []
    for index, row in enumerate(rows):
        weight = RECENCY ** (count - 1 - index)
        total_weight += weight
        if row["by"] == "me":
            my_weight += weight
        if row["kind"] in CONTROL_KINDS:
            if row["by"] == "me":
                my_control += weight
            else:
                your_control += weight
        if row["kind"] == "close":
            close_rows.append((index, row["by"], weight))
    control_total = my_control + your_control
    dominance = (my_control / control_total) if control_total > 0.0 else 0.5
    if dominance >= HOLD_ME:
        holder = "me"
    elif dominance <= HOLD_YOU:
        holder = "you"
    else:
        holder = "shared"
    closing = bool(close_rows) and close_rows[-1][0] >= max(0, count - 2)
    close_weight = sum(weight for _, by, weight in close_rows if by == "me")
    total_close = sum(weight for _, _, weight in close_rows)
    my_close_share = (close_weight / total_close) if total_close > 0.0 else 0.0
    stale = 0.0
    if rows:
        stale = 1.0
        for row in rows:
            if row["kind"] in CONTROL_KINDS:
                stale = 0.0
                break
    return {
        "count": count,
        "dominance": round(_clamp(dominance), 3),
        "holder": holder,
        "my_control": round(my_control, 3),
        "your_control": round(your_control, 3),
        "engaged": round(_clamp(my_weight / total_weight if total_weight else 0.0), 3),
        "closing": bool(closing),
        "my_close_share": round(_clamp(my_close_share), 3),
        "stale": bool(stale),
        "last_by": rows[-1]["by"] if rows else "you",
    }


def _scores(row, energy, closeness, conflict, night, closing_flag):
    closing = 1.0 if (row["closing"] or closing_flag) else 0.0
    last_by = row["last_by"]
    catch = (0.35 + 0.20 * (1.0 if last_by == "you" else 0.0)
             + 0.15 * row["engaged"] + 0.12 * energy + 0.08 * closeness
             - 0.12 * (1.0 if row["stale"] else 0.0) - 0.10 * closing)
    yield_ = (0.10 + 0.30 * row["dominance"]
              + 0.20 * (1.0 if last_by == "me" else 0.0)
              + 0.12 * closeness + 0.10 * (1.0 - energy)
              + 0.08 * (1.0 if row["your_control"] == 0.0 else 0.0))
    start = (0.10 + 0.15 * (1.0 - row["dominance"]) + 0.20 * energy
             + 0.25 * (1.0 if row["stale"] else 0.0)
             + 0.12 * (1.0 - row["engaged"]) + 0.10 * (1.0 - closeness))
    close = (0.08 + 0.45 * closing + 0.20 * (1.0 - energy)
             + 0.12 * conflict + 0.10 * (1.0 if night else 0.0)
             + 0.08 * row["my_close_share"])
    return {
        "让出": round(_clamp(yield_), 3),
        "接住": round(_clamp(catch), 3),
        "另起": round(_clamp(start), 3),
        "收尾": round(_clamp(close), 3),
    }


def _pick(scores):
    best = TENDENCIES[0]
    best_score = -1.0
    for tendency in TENDENCIES:
        value = scores.get(tendency, 0.0)
        if value > best_score + 1e-12:
            best, best_score = tendency, value
    return best


def _disabled():
    return {
        "enabled": False,
        "holder": "shared",
        "dominance": 0.5,
        "tendency": "接住",
        "reason": "话题主导权关闭，按旧行为",
        "counts": {},
        "window": 0,
        "last_by": "you",
        "scores": {},
    }


def topic_control(turns=None, state=None, relationship=None, hour=None,
                  flags=None):
    """One reading of the topic control. Plain dict, no IO."""
    flags = flags if isinstance(flags, dict) else {}
    if not bool(flags.get("enabled", True)):
        return _disabled()
    window = int(_num(flags.get("window"), DEFAULT_WINDOW))
    row = metrics(turns, window)
    state = state if isinstance(state, dict) else {}
    relationship = relationship if isinstance(relationship, dict) else {}
    energy = _clamp(state.get("energy", 0.6))
    closeness = _clamp(relationship.get(
        "closeness", relationship.get("intimacy", 0.5)))
    conflict = _clamp(relationship.get("conflict", 0.0))
    night = False
    if hour is not None:
        night = int(_num(hour, 12)) % 24 in NIGHT_HOURS
    closing_flag = bool(flags.get("closing", False))
    scores = _scores(row, energy, closeness, conflict, night, closing_flag)
    tendency = _pick(scores)
    return {
        "enabled": True,
        "holder": row["holder"],
        "dominance": row["dominance"],
        "tendency": tendency,
        "reason": REASONS[tendency],
        "counts": {
            "my_control": row["my_control"],
            "your_control": row["your_control"],
            "engaged": row["engaged"],
            "closing": row["closing"],
        },
        "window": row["count"],
        "last_by": row["last_by"],
        "scores": scores,
    }


def directives(result):
    """Bounded hints for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"holder": "shared", "tendency": "接住", "initiative": 0.45,
                "tone": ""}
    tendency = str(result.get("tendency") or "接住")
    if tendency not in TENDENCIES:
        tendency = "接住"
    holder = str(result.get("holder") or "shared")
    return {
        "holder": holder if holder in HOLDERS else "shared",
        "tendency": tendency,
        "initiative": _INITIATIVE[tendency],
        "tone": TONES[tendency],
    }
