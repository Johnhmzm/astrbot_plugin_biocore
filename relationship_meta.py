# -*- coding: utf-8 -*-
"""Deterministic relationship-state helpers (no AstrBot imports).

Stores a small relationship vector and a bounded trajectory per user. It does
not claim human attachment or consciousness; it is an auditable summary of
interaction history for the biological layer.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "RELATIONSHIP_SCHEMA_VERSION",
    "MAX_TRAJECTORY",
    "REPAIR_PHASES",
    "REPAIR_MAX_EVIDENCE",
    "relationship_state",
    "append_trajectory",
    "build_transactive_map",
    "build_destination_map",
    "update_repair_state",
    "absence_state",
    "calibration_update",
    "update_relationship_record",
    "summarize_relationship",
]

RELATIONSHIP_SCHEMA_VERSION = 2
MAX_TRAJECTORY = 80
REPAIR_PHASES = ("stable", "rupture", "repairing", "repaired")
REPAIR_MAX_EVIDENCE = 20
REPAIR_RUPTURE_CONFLICT = 0.62
REPAIR_REPAIRED_CONFLICT = 0.42
CALIBRATION_MAX_SOURCES = 20

_STOPWORDS = {
    "这个",
    "那个",
    "什么",
    "怎么",
    "就是",
    "不是",
    "可以",
    "我们",
    "你们",
    "他们",
    "自己",
    "现在",
    "然后",
    "因为",
    "所以",
    "但是",
    "还是",
    "已经",
    "没有",
    "一个",
    "一下",
    "觉得",
    "知道",
    "时候",
    "真的",
    "非常",
    "特别",
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "have",
    "will",
    "just",
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}")


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return (low + high) / 2.0



def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return default
        return number
    except Exception:
        return default


def absence_state(last_seen: Any, now: Any) -> dict[str, Any]:
    """Bounded absence/return state; never modifies trust or relationship state."""
    last = _num(last_seen, 0.0)
    current = _num(now, 0.0)
    gap_days = max(0.0, (current - last) / 86400.0) if last > 0 else 0.0
    if gap_days < 1.0:
        bucket = "same_day"
        return_mode = "normal"
    elif gap_days <= 3.0:
        bucket = "short"
        return_mode = "brief"
    elif gap_days <= 14.0:
        bucket = "medium"
        return_mode = "returning"
    else:
        bucket = "long"
        return_mode = "long_absence"
    return {"gap_days": round(gap_days, 3), "bucket": bucket,
            "return_mode": return_mode, "last_seen": round(last, 3),
            "now": round(current, 3)}


def update_repair_state(
    previous_repair: Any,
    state: dict[str, Any],
    previous_state: Any,
    ts: Any,
) -> dict[str, Any]:
    """Deterministic rupture->repair phase transition (state proxy, not clinical)."""
    prev = previous_repair if isinstance(previous_repair, dict) else {}
    prev_phase = str(prev.get("phase") or "stable")
    if prev_phase not in REPAIR_PHASES:
        prev_phase = "stable"
    conflict = _clamp(state.get("conflict", 0.5))
    repair = _clamp(state.get("repair", 0.0))
    prev_conflict = _clamp(previous_state.get("conflict")) if isinstance(previous_state, dict) else conflict
    time_value = _num(ts, 0.0)
    phase = prev_phase
    rupture_ts = _num(prev.get("rupture_ts"), 0.0)
    repair_attempts = int(_num(prev.get("repair_attempts"), 0.0))
    last_repair_ts = _num(prev.get("last_repair_ts"), 0.0)

    if conflict >= REPAIR_RUPTURE_CONFLICT and (
            phase in ("stable", "repaired") or conflict - prev_conflict >= 0.08):
        phase = "rupture"
        rupture_ts = time_value
        repair_attempts = 0
    elif phase == "rupture":
        if conflict <= REPAIR_REPAIRED_CONFLICT and repair >= 0.05:
            phase = "repaired"
            last_repair_ts = time_value
        elif conflict < prev_conflict - 0.02 or repair > 0.05:
            phase = "repairing"
            repair_attempts += 1
            last_repair_ts = time_value
    elif phase == "repairing":
        if conflict <= REPAIR_REPAIRED_CONFLICT and repair >= 0.05:
            phase = "repaired"
            last_repair_ts = time_value
        elif conflict >= REPAIR_RUPTURE_CONFLICT and conflict > prev_conflict:
            phase = "rupture"
            rupture_ts = time_value
            repair_attempts += 1
    elif phase == "repaired" and conflict >= REPAIR_RUPTURE_CONFLICT:
        phase = "rupture"
        rupture_ts = time_value
        repair_attempts = 0

    evidence = []
    if isinstance(prev.get("evidence"), list):
        evidence = [dict(x) for x in prev["evidence"][-REPAIR_MAX_EVIDENCE:] if isinstance(x, dict)]
    evidence.append({"ts": round(time_value, 3), "phase": phase,
                     "conflict": round(conflict, 4), "repair": round(repair, 4)})
    evidence = evidence[-REPAIR_MAX_EVIDENCE:]
    return {"phase": phase, "rupture_ts": round(rupture_ts, 3),
            "repair_attempts": repair_attempts,
            "last_repair_ts": round(last_repair_ts, 3),
            "evidence": evidence}


def calibration_update(state: Any, source: Any, predicted: Any, correct: Any) -> dict[str, Any]:
    """EWMA/Brier calibration record per evidence source; record-only, no trust writeback."""
    prev = state if isinstance(state, dict) else {}
    sources = {}
    raw_sources = prev.get("sources") if isinstance(prev.get("sources"), dict) else {}
    for key, item in raw_sources.items():
        if isinstance(item, dict):
            sources[str(key)] = dict(item)
    name = str(source or "unknown").strip()[:40] or "unknown"
    pred = _clamp(_num(predicted, 0.5))
    target = _clamp(_num(correct, 0.0))
    error = (pred - target) ** 2
    old = sources.get(name, {})
    old_n = int(_num(old.get("n"), 0.0))
    old_sum = _num(old.get("brier_sum"), 0.0)
    old_ewma = _num(old.get("ewma"), error)
    n = old_n + 1
    brier_sum = old_sum + error
    ewma = 0.8 * old_ewma + 0.2 * error
    sources[name] = {
        "n": n,
        "brier_sum": round(brier_sum, 6),
        "brier": round(brier_sum / n, 6),
        "ewma": round(_clamp(ewma), 6),
    }
    if len(sources) > CALIBRATION_MAX_SOURCES:
        ranked = sorted(sources.items(), key=lambda kv: (-int(kv[1].get("n", 0) or 0), kv[0]))
        sources = dict(ranked[:CALIBRATION_MAX_SOURCES])
    return {"sources": sources}


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


def _tokens(text: str) -> list[str]:
    result = []
    for token in _TOKEN_RE.findall(str(text or "")):
        normalized = token.strip().lower()
        if len(normalized) < 2 or normalized in _STOPWORDS:
            continue
        result.append(normalized)
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
        if not isinstance(entry, dict) or entry.get("summarized"):
            continue
        for token in _tokens(str(entry.get("text", ""))):
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {key: int(value) for key, value in ranked[:max(1, int(limit))]}


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
        item = result.setdefault(
            key,
            {
                "sender_id": sender_id,
                "sender_name": sender_name,
                "count": 0,
                "last_ts": 0.0,
                "latest_text": "",
            },
        )
        item["count"] = int(item.get("count", 0) or 0) + 1
        ts = float(entry.get("ts", 0) or 0)
        if ts >= float(item.get("last_ts", 0) or 0):
            item["last_ts"] = ts
            item["latest_text"] = str(entry.get("text", ""))[:160]
    ranked = sorted(result.items(), key=lambda item: (-int(item[1].get("count", 0)), item[0]))
    return {key: value for key, value in ranked[:max(1, int(limit))]}


def update_relationship_record(
    previous: Any,
    *,
    state: dict[str, Any],
    ts: Any,
    transactive_map: Any = None,
    destination_map: Any = None,
    absence: Any = None,
) -> dict[str, Any]:
    """Create/update the bounded relationship record stored with the user."""
    prev = previous if isinstance(previous, dict) else {}
    trajectory = append_trajectory(prev.get("trajectory"), state, ts)
    repair_state = update_repair_state(prev.get("repair_state"), state, prev.get("state"), ts)
    if isinstance(absence, dict):
        absence_state_value = dict(absence)
    elif isinstance(prev.get("absence"), dict):
        absence_state_value = dict(prev["absence"])
    else:
        absence_state_value = absence_state(ts, ts)
    calibration = prev.get("calibration") if isinstance(prev.get("calibration"), dict) else {"sources": {}}
    return {
        "schema_version": RELATIONSHIP_SCHEMA_VERSION,
        "state": {
            key: round(_clamp(state.get(key, 0.5)), 4)
            for key in ("trust", "closeness", "conflict", "repair", "predictability")
        },
        "trajectory": trajectory,
        "transactive_map": transactive_map if isinstance(transactive_map, dict) else prev.get("transactive_map", {}),
        "destination_map": destination_map if isinstance(destination_map, dict) else prev.get("destination_map", {}),
        "repair_state": repair_state,
        "absence": absence_state_value,
        "calibration": calibration,
    }


def summarize_relationship(relationship: Any) -> str:
    """Short deterministic summary for the interpretation layer, if needed."""
    if not isinstance(relationship, dict):
        return ""
    state = relationship.get("state")
    if not isinstance(state, dict):
        return ""
    parts = []
    labels = (
        ("trust", "信任"),
        ("closeness", "亲近"),
        ("conflict", "冲突"),
        ("repair", "修复"),
        ("predictability", "可预测"),
    )
    for key, label in labels:
        if key in state:
            parts.append(f"{label}={_clamp(state.get(key)):.2f}")
    return " ".join(parts)
