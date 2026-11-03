# -*- coding: utf-8 -*-
"""Value ordering: what she would rather keep, when two good things clash.

Base table is Schwartz's ten basic values. Experience nudges the weights
slowly and within bounds, so a single conversation never rewrites her.

Three behavioural corrections are folded in, because a plain weighted sum
orders things like a spreadsheet, not like a person:

1. loss aversion: losing something counts about twice as much as gaining
   the same thing (Kahneman & Tversky);
2. sunk cost: the longer the relationship has run, the more weight the
   existing choice carries when it is threatened;
3. status quo bias: a change only happens when the expected gain clears a
   threshold, so she does not flip on a hair.

Pure functions only: no IO, no host imports, no LLM calls.
"""
from __future__ import annotations

DIMENSIONS = (
    "self_direction", "stimulation", "hedonism", "achievement",
    "power", "security", "conformity", "tradition",
    "benevolence", "universalism",
)
LABELS = {
    "self_direction": "自己做主",
    "stimulation": "新鲜刺激",
    "hedonism": "当下开心",
    "achievement": "被认可",
    "power": "说得上话",
    "security": "安全感",
    "conformity": "不越界",
    "tradition": "守旧",
    "benevolence": "被需要",
    "universalism": "诚实与公平",
}
# The four things the task names, mapped onto Schwartz dimensions.
NECESSITIES = {
    "被需要": ("benevolence",),
    "被尊重": ("achievement", "power"),
    "安全感": ("security",),
    "诚实": ("universalism",),
}

LOSS_MULTIPLIER = 2.0
SUNK_COST_CAP = 0.8
STATUS_QUO_BASE = 0.12
STATUS_QUO_CAP = 0.45
UPDATE_RATE = 0.03
WEIGHT_FLOOR = 0.02
WEIGHT_CEIL = 1.0

DEFAULTS = {
    "self_direction": 0.62, "stimulation": 0.45, "hedonism": 0.40,
    "achievement": 0.55, "power": 0.38, "security": 0.70,
    "conformity": 0.35, "tradition": 0.30, "benevolence": 0.75,
    "universalism": 0.60,
}

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

def defaults():
    """A fresh weight table (copy, so callers cannot mutate ours)."""
    return dict(DEFAULTS)

def normalize(weights):
    """Fill missing dimensions from defaults and clamp every weight."""
    base = defaults()
    if isinstance(weights, dict):
        for dim in DIMENSIONS:
            if dim in weights:
                base[dim] = round(_clamp(weights[dim], WEIGHT_FLOOR, WEIGHT_CEIL), 4)
    return base

def update(weights, events, rate=UPDATE_RATE):
    """Slow, bounded drift: events nudges dimensions, never snaps them."""
    base = normalize(weights)
    rate = max(0.0, min(0.2, _num(rate, UPDATE_RATE)))
    events = events if isinstance(events, dict) else {}
    changed = False
    for dim, delta in events.items():
        if dim not in base:
            continue
        step = max(-0.15, min(0.15, _num(delta)))
        new = base[dim] + rate * step
        base[dim] = round(_clamp(new, WEIGHT_FLOOR, WEIGHT_CEIL), 4)
        changed = changed or abs(base[dim] - weights.get(dim, base[dim])) > 1e-9
    return base

def sunk_cost(duration_days, cap=SUNK_COST_CAP):
    """Existing investment multiplier: grows with how long this has run."""
    days = max(0.0, _num(duration_days))
    # A year together reaches roughly half the cap; it never runs away.
    raw = (days / 365.0) * 0.5
    return round(min(max(0.0, _num(cap, SUNK_COST_CAP)), raw), 3)

def status_quo_threshold(weights, relationship_age_days=0.0, base=STATUS_QUO_BASE):
    """How much better a change must look before she takes it."""
    table = normalize(weights)
    cautious = table.get("security", 0.5) + table.get("tradition", 0.3)
    age = min(1.0, max(0.0, _num(relationship_age_days) / 365.0))
    value = _num(base, STATUS_QUO_BASE) + 0.10 * (cautious - 1.0) + 0.08 * age
    return round(max(0.05, min(STATUS_QUO_CAP, value)), 3)

def _score_option(option, weights, context):
    """Score one option, applying loss aversion and sunk cost."""
    option = option if isinstance(option, dict) else {}
    gains = option.get("gains") if isinstance(option.get("gains"), dict) else {}
    losses = option.get("losses") if isinstance(option.get("losses"), dict) else {}
    table = weights
    score = 0.0
    for dim, amount in gains.items():
        if dim in table:
            score += table[dim] * _clamp(amount)
    for dim, amount in losses.items():
        if dim in table:
            score -= LOSS_MULTIPLIER * table[dim] * _clamp(amount)
    invested = _clamp(context.get("investment", 0.0))
    sunk = sunk_cost(context.get("relationship_age_days", 0.0))
    if option.get("keeps_status_quo"):
        score += sunk * invested
    else:
        score -= sunk * invested * 0.5
    return round(score, 4)

def rank(options, weights=None, context=None, flags=None):
    """Order options by expected value under her current values."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    table = normalize(weights)
    context = context if isinstance(context, dict) else {}
    rows = []
    for index, option in enumerate(options or []):
        item = option if isinstance(option, dict) else {}
        rows.append({
            "index": index,
            "name": str(item.get("name") or item.get("label") or ("选项%d" % (index + 1))),
            "score": round(_score_option(item, table, context), 4),
            "keeps_status_quo": bool(item.get("keeps_status_quo")),
        })
    rows.sort(key=lambda row: row["score"], reverse=True)
    threshold = status_quo_threshold(table, context.get("relationship_age_days", 0.0))
    chosen = None
    if rows:
        best = rows[0]
        baseline = next((row for row in rows if row["keeps_status_quo"]), None)
        if (not enabled or baseline is None or best["keeps_status_quo"]
                or best["score"] - baseline["score"] >= threshold):
            chosen = best["name"]
        else:
            chosen = baseline["name"]
    return {
        "enabled": enabled,
        "ranked": rows,
        "chosen": chosen,
        "threshold": threshold,
        "sunk_cost": sunk_cost(context.get("relationship_age_days", 0.0)),
    }

def necessity_priority(weights=None):
    """Order the four named needs by her current value table."""
    table = normalize(weights)
    rows = []
    for name, dims in NECESSITIES.items():
        value = max((table.get(dim, 0.0) for dim in dims), default=0.0)
        rows.append({"need": name, "value": round(value, 4)})
    rows.sort(key=lambda row: row["value"], reverse=True)
    return rows

def directives(result):
    """Bounded hint for the expression layer (no prompt text)."""
    if not isinstance(result, dict) or not result.get("enabled", True):
        return {"tone": "", "chosen": None}
    chosen = result.get("chosen")
    return {"tone": ("按选定的那个来" if chosen else ""), "chosen": chosen}
