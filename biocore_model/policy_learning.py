# -*- coding: utf-8 -*-
"""Contextual-bandit policy learning (pure, no IO, no main import).

References: Thorndike 1911 (law of effect), Rescorla-Wagner 1972 (prediction
error), Sutton & Barto 1998 (contextual bandit), Daw 2011 (model-free choice).
Q-table shape: {ctx_key: {action: {"q": float, "n": int}}}.
"""
from __future__ import annotations

import random

ACTIONS = ("approach", "share", "question", "withdraw", "repair", "rest")
SILENCE_PHASES = ("expect", "protest", "loss", "withdraw")
ATTACHMENTS = ("secure", "anxious", "avoidant")


def hour_bucket(hour):
    try:
        value = float(hour)
    except Exception:
        return "day"
    if 6.0 <= value < 18.0:
        return "day"
    if 18.0 <= value < 23.0:
        return "evening"
    return "night"


def make_context(silence_phase, attachment, hour):
    phase = str(silence_phase or "expect")
    if phase not in SILENCE_PHASES:
        phase = "expect"
    style = str(attachment or "secure")
    if style not in ATTACHMENTS:
        style = "secure"
    return "%s|%s|%s" % (phase, style, hour_bucket(hour))


def _empty_state():
    return {action: {"q": 0.0, "n": 0} for action in ACTIONS}


def _state_for(q_table, ctx_key):
    table = q_table if isinstance(q_table, dict) else {}
    row = table.get(ctx_key)
    if not isinstance(row, dict):
        return _empty_state(), True
    state = {}
    for action in ACTIONS:
        value = row.get(action)
        if isinstance(value, dict):
            try:
                q = float(value.get("q", 0.0) or 0.0)
            except Exception:
                q = 0.0
            try:
                n = int(value.get("n", 0) or 0)
            except Exception:
                n = 0
            state[action] = {"q": q, "n": n}
        elif isinstance(value, (int, float)):
            state[action] = {"q": float(value), "n": 0}
        else:
            state[action] = {"q": 0.0, "n": 0}
    return state, False


def choose(ctx_key, q_table, epsilon=0.1, rng=None):
    rng = rng or random.Random(0)
    state, unseen = _state_for(q_table, str(ctx_key or ""))
    values = [state[action]["q"] for action in ACTIONS]
    if unseen or max(values) == min(values) == 0.0:
        action = ACTIONS[rng.randrange(len(ACTIONS))]
        return {"action": action, "q": round(float(state[action]["q"]), 6), "explored": True}
    try:
        rate = max(0.0, min(1.0, float(epsilon)))
    except Exception:
        rate = 0.1
    if rng.random() < rate:
        action = ACTIONS[rng.randrange(len(ACTIONS))]
        return {"action": action, "q": round(float(state[action]["q"]), 6), "explored": True}
    best = max(values)
    action = next(item for item in ACTIONS if state[item]["q"] == best)
    return {"action": action, "q": round(float(best), 6), "explored": False}


def reward(responded, response_gap_s, delta_discomfort):
    try:
        responded_value = 1.0 if bool(responded) else 0.0
    except Exception:
        responded_value = 0.0
    try:
        gap = max(0.0, float(response_gap_s))
    except Exception:
        gap = 0.0
    try:
        delta = max(-1.0, min(1.0, float(delta_discomfort)))
    except Exception:
        delta = 0.0
    speed = max(0.0, min(1.0, 1.0 - gap / 120.0))
    return round(0.5 * responded_value + 0.3 * delta + 0.2 * speed, 6)


def update(q_table, ctx_key, action, r, alpha=0.2):
    table = dict(q_table or {}) if isinstance(q_table, dict) else {}
    key = str(ctx_key or "")
    state, _ = _state_for(table, key)
    state = {name: dict(value) for name, value in state.items()}
    name = str(action or "")
    if name not in state:
        return table
    try:
        rate = max(0.0, min(1.0, float(alpha)))
    except Exception:
        rate = 0.2
    try:
        target = float(r)
    except Exception:
        target = 0.0
    current = float(state[name]["q"])
    state[name]["q"] = round(current + rate * (target - current), 6)
    state[name]["n"] = int(state[name]["n"]) + 1
    table[key] = state
    return table


def policy_view(q_table, ctx_key):
    state, _ = _state_for(q_table or {}, str(ctx_key or ""))
    rows = [{"action": action, "q": round(float(value["q"]), 6), "n": int(value["n"])}
            for action, value in state.items()]
    rows.sort(key=lambda item: (-item["q"], ACTIONS.index(item["action"])))
    return rows
