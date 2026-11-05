# -*- coding: utf-8 -*-
"""task-AstrBot-migration-1: pure memory scoring math moved out of main.py.

Behavior-preserving extraction of four host helpers:
  memory_importance(core, role)
  score_parts(core, entry, cosine, ...)
  memory_score(core, entry, cosine, ...)
  select_overflow_archive(entries, room, importance_max=0.5)

The host keeps thin wrappers that pass its own switches (salience/fan) and the
ACT_R_DECAY constant, so identical inputs give identical numbers.
"""
from __future__ import annotations

import math
import time

try:  # package context (AstrBot plugin)
    from .. import memory_meta
except Exception:  # pragma: no cover - flat checkout
    import memory_meta  # type: ignore

ACT_R_DECAY_DEFAULT = 0.5
DEFAULT_COSINE = 0.0


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    return number if number == number else default


def memory_importance(core, role):
    """Legacy importance heuristic; core None -> 0.5."""
    if core is None:
        return 0.5
    salience = (0.25 + 0.35 * float(getattr(core, "a", 0.5))
                + 0.25 * abs(float(getattr(core, "v", 0.0))))
    salience += 0.15 * (1.0 - float(getattr(core, "trust", 0.5)))
    if role == "assistant":
        salience *= 0.9
    return max(0.15, min(1.0, salience))


def score_parts(core, entry, cosine, query_text="", hybrid=False,
                sensitive_protect=False, *, salience_boost=False,
                fan_penalty=False, fan_cap=32, fan_floor=0.70, fan_gain=0.10,
                act_r_decay=ACT_R_DECAY_DEFAULT, now=None):
    """Deterministic score plus bounded component factors (same as main.py)."""
    stamp = time.time() if now is None else float(now)
    importance = memory_meta.effective_importance(entry)
    age = max(0.0, stamp - float(entry.get("ts", 0) or 0))
    age_days = age / 86400.0
    retention_model = (getattr(core, "retention_model", "power_law")
                       if core is not None else "power_law")
    if retention_model in ("power_law", "multi_scale"):
        recency = memory_meta.retention_weight(age_days, retention_model)
    else:
        recency = 1.0 / math.pow(1.0 + max(0.0, age_days) * 0.35, 0.55)
    try:
        recall_count = int(entry.get("recall_count", 0) or 0)
    except Exception:
        recall_count = 0
    assoc = memory_meta.decayed_assoc(entry)
    try:
        due = 1.15 if 0 < float(entry.get("next_review_ts", 0) or 0) <= stamp else 1.0
    except Exception:
        due = 1.0
    try:
        stability = max(0.2, float(entry.get("stability_days", 1.0) or 1.0))
    except Exception:
        stability = 1.0
    retention = math.exp(-age_days / stability)
    try:
        _d = act_r_decay
        _b = math.log(max(1e-9, (age_days + 0.05) ** (-_d)))
        base = 1.0 / (1.0 + math.exp(-(_b + 1.0)))
    except Exception:
        base = 0.5
    try:
        schema = memory_meta.effective_schema_congruence(entry)
    except Exception:
        schema = 0.0
    inhibition = memory_meta.retrieval_inhibition(entry)
    regulation = (str(getattr(core, "regulation", "none") or "none")
                  if core is not None else "none")
    regulation_mod = memory_meta.regulation_memory_modifier(entry, regulation)
    lexical_mod = 1.0
    if hybrid and query_text:
        try:
            entry_text = str(entry.get("text") or "")
            variants = memory_meta.expand_query(query_text)
            lexical = max(memory_meta.lexical_overlap(variant, entry_text)
                          for variant in variants) if variants else 0.0
            lexical_mod = 1.0 + 0.12 * lexical
        except Exception:
            lexical_mod = 1.0
    sensitive_mod = 1.0
    if sensitive_protect:
        sensitive_mod = memory_meta.sensitivity_weight(entry)
    source_weight = memory_meta.retrieval_weight(entry)
    score = (cosine * (0.40 + 0.60 * importance) * recency
             * (0.65 + 0.35 * retention)
             * (0.85 + 0.15 * base)
             * (1.0 + 0.10 * math.log1p(max(0, recall_count)))
             * due
             * (1.0 + 0.05 * math.log1p(max(0, assoc)))
             * source_weight
             * (1.0 + 0.10 * schema)
             * (1.0 - 0.15 * inhibition)
             * regulation_mod
             * lexical_mod
             * sensitive_mod)
    sal_factor = 1.0
    if salience_boost:
        try:
            _c = max(0.0, min(1.0, float(cosine)))
            if _c > 0.0:
                sal_factor = 0.90 + 0.20 * _c
                score *= sal_factor
        except Exception:
            sal_factor = 1.0
    if fan_penalty:
        try:
            links = entry.get("links") if isinstance(entry.get("links"), list) else []
            try:
                raw_assoc = sum(int(v) for v in (entry.get("assoc") or {}).values())
            except Exception:
                raw_assoc = 0
            fan = min(int(fan_cap or 32), raw_assoc + len(links))
            penalty = max(float(fan_floor or 0.70),
                          1.0 / (1.0 + float(fan_gain or 0.10)
                                 * math.log1p(max(0, fan))))
            score *= penalty
        except Exception:
            pass
    return {
        "score": float(score),
        "salience": round(sal_factor, 4),
        "cosine": round(float(cosine), 6),
        "importance": round(importance, 4),
        "recency": round(recency, 4),
        "retention": round(0.65 + 0.35 * retention, 4),
        "base": round(0.85 + 0.15 * base, 4),
        "recall_boost": round(1.0 + 0.10 * math.log1p(max(0, recall_count)), 4),
        "assoc_boost": round(1.0 + 0.05 * math.log1p(max(0, assoc)), 4),
        "due": round(due, 4),
        "source_weight": round(float(source_weight), 4),
        "schema": round(schema, 4),
        "inhibition": round(float(inhibition), 4),
        "regulation": round(float(regulation_mod), 4),
        "lexical": round(float(lexical_mod), 4),
        "sensitive": round(float(sensitive_mod), 4),
    }


def memory_score(core, entry, cosine, query_text="", hybrid=False,
                 sensitive_protect=False, *, salience_boost=False,
                 fan_penalty=False, fan_cap=32, fan_floor=0.70, fan_gain=0.10,
                 act_r_decay=ACT_R_DECAY_DEFAULT, now=None):
    parts = score_parts(
        core, entry, cosine, query_text=query_text, hybrid=hybrid,
        sensitive_protect=sensitive_protect, salience_boost=salience_boost,
        fan_penalty=fan_penalty, fan_cap=fan_cap, fan_floor=fan_floor,
        fan_gain=fan_gain, act_r_decay=act_r_decay, now=now)
    score = float(parts.get("score", 0.0))
    try:
        trace = getattr(core, "_last_memory_trace", None) if core is not None else None
        if isinstance(trace, dict):
            entry_id = str(entry.get("id") or "")
            if entry_id and entry_id in [str(x) for x in (trace.get("entry_ids") or [])]:
                valence = max(-1.0, min(1.0, float(trace.get("valence", 0.0) or 0.0)))
                score *= 1.0 + 0.04 * valence
    except Exception:
        pass
    return max(0.0, score)


def select_overflow_archive(entries, room, importance_max=0.5):
    """Deterministic low-importance unpinned overflow selection."""
    rows = [row for row in (entries or []) if isinstance(row, dict)]
    rows.sort(key=lambda row: float(row.get("ts", 0) or 0))
    try:
        keep_n = max(0, int(room or 0))
    except Exception:
        keep_n = 80
    keep = rows[-keep_n:] if keep_n else []
    overflow = []
    for row in rows:
        if row in keep:
            continue
        try:
            importance = float(row.get("importance", 0.5) or 0.5)
        except Exception:
            importance = 0.5
        if importance < float(importance_max) and not memory_meta.is_pinned(row):
            overflow.append(row)
        else:
            keep.append(row)
    keep.sort(key=lambda row: float(row.get("ts", 0) or 0))
    return keep, overflow
