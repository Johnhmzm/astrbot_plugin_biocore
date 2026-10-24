# -*- coding: utf-8 -*-
"""Deterministic relationship-state helpers (no AstrBot imports).

Stores a small relationship vector and a bounded trajectory per user. It does
not claim human attachment or consciousness; it is an auditable summary of
interaction history for the biological layer.
"""

from __future__ import annotations

from typing import Any

RELATIONSHIP_SCHEMA_VERSION = 1
MAX_TRAJECTORY = 80


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return (low + high) / 2.0


def relationship_state(
    *,
    trust: Any = 0.5,
    social: Any = 0.5,
    stress: Any = 0.5,
    opponent: Any = 0.0,
    previous: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Build a bounded relationship vector from core state.

    Fields:
        trust: current trust
        closeness: trust + social - stress
        conflict: stress + opponent + low trust
        repair: positive trust change since the last snapshot
        predictability: low absolute trust change
    """
    t = _clamp(trust)
    s = _clamp(social)
    st = _clamp(stress)
    op = _clamp(opponent)
    close = _clamp(0.55 * t + 0.30 * s + 0.15 * (1.0 - st))
    conflict = _clamp(0.40 * st + 0.30 * op + 0.30 * (1.0 - t))
    prev_trust = _clamp(previous.get("trust")) if isinstance(previous, dict) else t
    delta = t - prev_trust
    repair = _clamp(max(0.0, delta) * 2.0)
    predictability = _clamp(1.0 - min(1.0, abs(delta) * 2.0))
    return {
        "trust": round(t, 4),
        "closeness": round(close, 4),
        "conflict": round(conflict, 4),
        "repair": round(repair, 4),
        "predictability": round(predictability, 4),
    }


def append_trajectory(
    trajectory: Any,
    state: dict[str, Any],
    ts: Any,
    *,
    max_len: int = MAX_TRAJECTORY,
) -> list[dict[str, Any]]:
    """Append a bounded trajectory point; keep it small."""
    points: list[dict[str, Any]] = []
    if isinstance(trajectory, list):
        for item in trajectory[-max_len:]:
            if isinstance(item, dict):
                points.append(dict(item))
    try:
        time_value = float(ts)
    except Exception:
        time_value = 0.0
    point = {"ts": time_value}
    for key in ("trust", "closeness", "conflict", "repair", "predictability"):
        point[key] = round(_clamp(state.get(key, 0.5)), 4)
    points.append(point)
    return points[-max_len:]




_STOPWORDS = {
    "这个", "那个", "什么", "怎么", "就是", "不是", "可以", "我们", "你们",
    "他们", "自己", "现在", "然后", "因为", "所以", "但是", "还是", "已经",
    "没有", "一个", "一下", "觉得", "知道", "时候", "真的", "非常", "特别",
    "the", "and", "that", "this", "with", "from", "have", "will", "just",
}


def _tokens(text: str) -> list[str]:
    import re
    raw = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", str(text or ""))
    result = []
    for token in raw:
        t = token.strip().lower()
        if len(t) < 2 or t in _STOPWORDS:
            continue
        result.append(t)
    return result


def build_transactive_map(entries: Any, limit: int = 24) -> dict[str, int]:
    """Crude deterministic 'what this person talks/knows about' map.

    This is a frequency map, not a claim about human knowledge. It is only a
    cheap index for the biological layer; semantic entity extraction stays in
    the interpretation/LLM layer.
    """
    counts: dict[str, int] = {}
    if not isinstance(entries, list):
        return counts
    for entry in entries[-200:]:
        if not isinstance(entry, dict):
            continue
        if entry.get("summarized"):
            continue
        for token in _tokens(str(entry.get("text", ""))):
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:max(1, int(limit))]
    return {k: int(v) for k, v in ranked}


def build_destination_map(entries: Any, limit: int = 24) -> dict[str, dict[str, Any]]:
    """Aggregate who told the agent what (destination/source memory)."""
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(entries, list):
        return result
    for entry in entries[-200:]:
        if not isinstance(entry, dict):
            continue
        destination = entry.get("destination")
        if not isinstance(destination, dict):
            continue
        sender_id = str(destination.get("sender_id") or "").strip()
        sender_name = str(destination.get("sender_name") or "").strip()
        if not sender_id and not sender_name:
            continue
        key = sender_id or sender_name
        item = result.setdefault(key, {
            "sender_id": sender_id,
            "sender_name": sender_name,
            "count": 0,
            "last_ts": 0.0,
            "latest_text": "",
        })
        item["count"] = int(item.get("count", 0) or 0) + 1
        ts = float(entry.get("ts", 0) or 0)
        if ts >= float(item.get("last_ts", 0) or 0):
            item["last_ts"] = ts
            item["latest_text"] = str(entry.get("text", ""))[:160]
    ranked = sorted(result.items(), key=lambda item: (-int(item[1].get("count", 0)), item[0]))[:max(1, int(limit))]
    return {k: v for k, v in ranked}


def update_relationship_record(
    previous: Any,
    *,
    state: dict[str, Any],
    ts: Any,
    transactive_map: Any = None,
    destination_map: Any = None,
) -> dict[str, Any]:
    """Create/update the bounded relationship record stored with the user."""
    prev = previous if isinstance(previous, dict) else {}
    trajectory = append_trajectory(prev.get("trajectory"), state, ts)
    record = {
        "schema_version": RELATIONSHIP_SCHEMA_VERSION,
        "state": {k: round(_clamp(state.get(k, 0.5)), 4) for k in ("trust", "closeness", "conflict", "repair", "predictability")},
        "trajectory": trajectory,
        "transactive_map": transactive_map if isinstance(transactive_map, dict) else prev.get("transactive_map", {}),
        "destination_map": destination_map if isinstance(destination_map, dict) else prev.get("destination_map", {}),
    }
    return record


def summarize_relationship(relationship: Any) -> str:
    """Short deterministic summary for the interpretation layer, if needed."""
    if not isinstance(relationship, dict):
        return ""
    state = relationship.get("state")
    if not isinstance(state, dict):
        return ""
    parts = []
    labels = (("trust", "信任"), ("closeness", "亲近"), ("conflict", "冲突"), ("repair", "修复"), ("predictability", "可预测"))
    for key, label in labels:
        if key in state:
            parts.append(f"{label}={_clamp(state.get(key)):.2f}")
    return " ".join(parts)
