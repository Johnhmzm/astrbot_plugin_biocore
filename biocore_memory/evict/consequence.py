# -*- coding: utf-8 -*-
"""Consequence-aware eviction (pure; default OFF)."""
from __future__ import annotations

from ..core.util import clamp01

CONSEQUENCE_ENABLED = False
PROMISE_WORDS = ("答应", "承诺", "保证", "约定", "说好", "一定会", "不再", "永远")
DEADLINE_WORDS = ("明天", "后天", "截止", "ddl", "deadline", "之前", "周", "月", "日", "点")
RISK_WORDS = ("危险", "风险", "生病", "医院", "药", "分手", "绝交", "吵架", "难过", "崩溃",
              "secret", "密码", "隐私", "重要")


def _matches(text, words):
    value = str(text or "").lower()
    return any(str(word).lower() in value for word in words)


def _score(entry):
    e = entry if isinstance(entry, dict) else {}
    text = " ".join(str(e.get(k) or "") for k in ("text", "title", "event", "big_summary"))
    importance = clamp01(e.get("importance"), 0.5)
    promise = 0.30 if _matches(text, PROMISE_WORDS) or e.get("promise") else 0.0
    deadline = 0.25 if _matches(text, DEADLINE_WORDS) or e.get("deadline") else 0.0
    risk = 0.20 if _matches(text, RISK_WORDS) or e.get("risk") else 0.0
    explicit = 0.25 * clamp01(e.get("consequence"), 0.0) if "consequence" in e else 0.0
    return clamp01(0.35 * importance + promise + deadline + risk + explicit, 0.0)


def consequence(entry):
    """0..1 consequence of forgetting an entry (higher = should keep)."""
    if not CONSEQUENCE_ENABLED or not isinstance(entry, dict):
        return 0.0
    try:
        return round(_score(entry), 4)
    except Exception:
        return 0.0


def select_by_consequence(entries, budget):
    """Return ids to evict first: lowest consequence, protected entries skipped."""
    if not CONSEQUENCE_ENABLED:
        return []
    try:
        limit = max(0, int(budget or 0))
    except Exception:
        limit = 0
    if not limit:
        return []
    rows = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("pin") or entry.get("pinned") or entry.get("self_defining") or entry.get("identity"):
            continue
        rows.append((_score(entry), str(entry.get("id") or entry.get("memory_id") or "")))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [eid for _score_value, eid in rows if eid][:limit]
