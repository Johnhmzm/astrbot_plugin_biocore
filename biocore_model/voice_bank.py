# -*- coding: utf-8 -*-
"""Voice bank: her own turns of phrase, picked by state and bounded by cooldown.

A voice entry is a small dict:

  {'phrase': '少来。',
   'when': {'v_min': -1.0, 'v_max': 0.2, 'tension_min': 0.0, 'tension_max': 1.0,
            'stages': ['close', 'normal']},
   'weight': 1.0, 'cooldown_s': 3600}

The bank does not generate language; it only selects 0-2 phrases that fit
the current body state and relationship, skip anything used inside its
cooldown, and never repeat a phrase twice in one pick.

Pure functions only: no IO, no host imports, no LLM calls. The caller
passes recent usage in, so persistence stays outside the module.
"""
from __future__ import annotations

import random

MAX_PICKS = 2
DEFAULT_COOLDOWN_S = 6 * 3600.0
STAGES = ("stranger", "normal", "close", "intimate")

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

def normalize_entry(raw):
    """Coerce one loose dict into a valid entry, or return None."""
    if not isinstance(raw, dict):
        return None
    phrase = str(raw.get("phrase") or "").strip()
    if not phrase or len(phrase) > 40:
        return None
    when = raw.get("when") if isinstance(raw.get("when"), dict) else {}
    stages = when.get("stages")
    if isinstance(stages, str):
        stages = [stages]
    if not isinstance(stages, (list, tuple)) or not stages:
        stages = list(STAGES)
    clean_stages = [str(s) for s in stages if str(s) in STAGES] or list(STAGES)
    v_min = _clamp(when.get("v_min", -1.0), -1.0, 1.0)
    v_max = _clamp(when.get("v_max", 1.0), -1.0, 1.0)
    if v_max < v_min:
        v_min, v_max = v_max, v_min
    tension_min = _clamp(when.get("tension_min", 0.0))
    tension_max = _clamp(when.get("tension_max", 1.0))
    if tension_max < tension_min:
        tension_min, tension_max = tension_max, tension_min
    return {
        "phrase": phrase,
        "when": {
            "v_min": round(v_min, 3), "v_max": round(v_max, 3),
            "tension_min": round(tension_min, 3),
            "tension_max": round(tension_max, 3),
            "stages": clean_stages,
        },
        "weight": round(max(0.05, _num(raw.get("weight"), 1.0)), 3),
        "cooldown_s": round(max(0.0, _num(raw.get("cooldown_s"),
                                        DEFAULT_COOLDOWN_S)), 1),
    }

def load(entries):
    """Normalize a list, dropping malformed rows and duplicate phrases."""
    out = []
    seen = set()
    for raw in entries or []:
        row = normalize_entry(raw)
        if not row:
            continue
        key = row["phrase"]
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out

def _recent_map(recent_used):
    """Accept {phrase: ts} or [{phrase, ts}] and return {phrase: ts}."""
    out = {}
    if isinstance(recent_used, dict):
        for key, value in recent_used.items():
            out[str(key)] = _num(value, 0.0)
    elif isinstance(recent_used, (list, tuple)):
        for row in recent_used:
            if isinstance(row, dict) and row.get("phrase"):
                out[str(row["phrase"])] = _num(row.get("ts"), 0.0)
    return out

def matches(entry, state, stage):
    """Does this entry fit the body state and relationship stage?"""
    if not isinstance(entry, dict):
        return False
    when = entry.get("when") or {}
    v = _clamp((state or {}).get("v", 0.0), -1.0, 1.0)
    tension = _clamp((state or {}).get("tension", 0.0))
    if not (_num(when.get("v_min"), -1.0) <= v <= _num(when.get("v_max"), 1.0)):
        return False
    if not (_num(when.get("tension_min"), 0.0) <= tension
            <= _num(when.get("tension_max"), 1.0)):
        return False
    stages = when.get("stages") or list(STAGES)
    return str(stage or "normal") in stages

def available(entries, state, relationship, recent_used, now):
    """Entries that match and are off cooldown."""
    stage = (relationship or {}).get("stage") or "normal"
    recent = _recent_map(recent_used)
    now_ts = _num(now, 0.0)
    out = []
    for entry in load(entries):
        if not matches(entry, state, stage):
            continue
        last = recent.get(entry["phrase"])
        if last is not None and now_ts - last < entry["cooldown_s"]:
            continue
        out.append(entry)
    out.sort(key=lambda row: row["weight"], reverse=True)
    return out

def pick(state, relationship, recent_used, now, entries=None, rng=None):
    """Pick 0-2 phrases.

    entries is the already-loaded bank (the caller reads the data file; this
    module never touches IO). rng=None means deterministic: highest weight
    first. Returns [] when the bank is empty or nothing fits.
    """
    rows = available(entries, state, relationship, recent_used, now)
    if not rows:
        return []
    limit = min(MAX_PICKS, len(rows))
    if rng is not None:
        weights = [row["weight"] for row in rows]
        chosen = []
        pool = list(rows)
        pool_weights = list(weights)
        while pool and len(chosen) < limit:
            total = sum(pool_weights) or 1.0
            mark = rng.random() * total
            upto = 0.0
            index = 0
            for i, weight in enumerate(pool_weights):
                upto += weight
                if mark <= upto:
                    index = i
                    break
            chosen.append(pool.pop(index)["phrase"])
            pool_weights.pop(index)
        return chosen
    return [row["phrase"] for row in rows[:limit]]

def mark_used(recent_used, phrases, now):
    """Return an updated {phrase: ts} map with the picked phrases stamped."""
    out = _recent_map(recent_used)
    stamp = _num(now, 0.0)
    for phrase in phrases or []:
        out[str(phrase)] = stamp
    return out

def stats(entries):
    """Counts for panels: total phrases, by stage coverage."""
    rows = load(entries)
    by_stage = {name: 0 for name in STAGES}
    for row in rows:
        for stage in row["when"]["stages"]:
            by_stage[stage] += 1
    return {"total": len(rows), "by_stage": by_stage}
