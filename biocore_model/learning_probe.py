# -*- coding: utf-8 -*-
"""P2-1 learning-loop verification helpers (pure).

The point of this module is to *test* that the feedback channel changes
subsequent behaviour, not only numbers:

- repeat the same reward 3x on the same context -> the Q-learning step becomes
  smaller each time (response strength decays / converges) and the preferred
  action becomes stable;
- the Nassar (2010) learning-rate curve shrinks as the prediction error shrinks;
- therefore a repeat of the same stimulus is answered with a measurably
  adjusted (not identical) response.

Pure functions only: no IO, no clock, no main import, no prompt text.
"""
from __future__ import annotations

from . import policy_learning as _pl

try:  # plugin root module (same directory as biocore_model/)
    import memory_meta as _memory_meta
except Exception:  # pragma: no cover
    _memory_meta = None

DEFAULT_REWARDS = (1.0, 1.0, 1.0)
DEFAULT_ALPHA = 0.2
DEFAULT_CTX = "expect|secure|day"
DEFAULT_ACTION = "approach"


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if number != number:
        return float(default)
    return number


def repeat_reward(ctx=DEFAULT_CTX, action=DEFAULT_ACTION, rewards=DEFAULT_REWARDS,
                  alpha=DEFAULT_ALPHA, q_table=None):
    """Apply the same reward repeatedly; returns (table, rows with step deltas)."""
    table = dict(q_table or {}) if isinstance(q_table, dict) else {}
    sequence = rewards if isinstance(rewards, (list, tuple)) else DEFAULT_REWARDS
    sequence = tuple(sequence) or tuple(DEFAULT_REWARDS)
    rows = []
    previous = None
    for index, reward in enumerate(sequence):
        table = _pl.update(table, str(ctx), str(action), _num(reward),
                           alpha=_num(alpha, DEFAULT_ALPHA))
        row = table.get(str(ctx))
        row = row if isinstance(row, dict) else {}
        state = row.get(str(action))
        state = state if isinstance(state, dict) else {}
        q = round(_num(state.get("q")), 6)
        delta = None if previous is None else round(abs(q - previous), 6)
        rows.append({"step": index + 1, "reward": _num(reward), "q": q,
                     "delta": delta})
        previous = q
    return table, rows


def declining_deltas(rows):
    """True when each learning step moves Q less than the previous one."""
    deltas = [row.get("delta") for row in (rows or [])
              if isinstance(row, dict) and row.get("delta") is not None]
    if len(deltas) < 2 or deltas[0] <= 0:
        return False
    return all(deltas[i] < deltas[i - 1] - 1e-9 for i in range(1, len(deltas)))


def response_ratio(rows):
    """Last step size / first step size (1.0 when unavailable)."""
    deltas = [abs(_num(row.get("delta"))) for row in (rows or [])
              if isinstance(row, dict) and row.get("delta") is not None]
    if len(deltas) < 2 or deltas[0] <= 0:
        return 1.0
    return round(deltas[-1] / deltas[0], 4)


def alpha_curve(errors):
    """Nassar alpha per prediction error; shrinking |PE| -> smaller alpha."""
    curve = []
    for error in errors or []:
        alpha = None
        if _memory_meta is not None:
            try:
                alpha = _memory_meta.nassar_alpha(abs(_num(error)))
            except Exception:
                alpha = None
        curve.append({"error": round(abs(_num(error)), 4),
                      "alpha": None if alpha is None else round(float(alpha), 4)})
    return curve


def preferred(table, ctx=DEFAULT_CTX):
    """Greedy preferred action for a context (behaviour, not just numbers)."""
    return _pl.choose(str(ctx), table, epsilon=0.0)


def self_check(rewards=DEFAULT_REWARDS):
    """One-shot verification report used by the tests / a manual run."""
    table, rows = repeat_reward(rewards=rewards)
    curve = alpha_curve([0.5, 0.25, 0.125])
    alphas = [row["alpha"] for row in curve if row["alpha"] is not None]
    alpha_declines = all(alphas[i] <= alphas[i - 1]
                         for i in range(1, len(alphas))) if len(alphas) > 1 else False
    pick = preferred(table)
    report = {"rows": rows, "declining": declining_deltas(rows),
              "ratio": response_ratio(rows), "alpha_curve": curve,
              "alpha_declines": alpha_declines,
              "q_after": rows[-1]["q"] if rows else 0.0,
              "preferred": pick,
              "behaviour_changed": pick.get("action") == DEFAULT_ACTION
              and not pick.get("explored", False)}
    report["ok"] = bool(report["declining"]
                        and report["ratio"] < 1.0
                        and report["behaviour_changed"])
    return report
