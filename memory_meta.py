# -*- coding: utf-8 -*-
"""Deterministic memory provenance, confidence and write-op helpers.

The module is intentionally free of AstrBot imports so it can be used by
scripts/eval_metamemory_policy.py without starting AstrBot.

It does not call an LLM. The LLM/interpretation layer may propose candidates,
but these helpers decide what metadata is stored and which conservative write
operation is allowed.
"""

from __future__ import annotations

import time
from typing import Any

__all__ = [
    "SOURCE_RANK",
    "normalize_source",
    "source_for_input",
    "initial_confidence",
    "update_confidence",
    "merge_sources",
    "source_precedence",
    "retrieval_weight",
    "should_abstain",
    "classify_write_op",
    "memory_tier",
    "detect_conflict",
    "merge_version",
    "select_top",
    "summarize_recall",
    "rollback_entry",
    "build_destination",
]

SOURCE_RANK = {
    "direct": 5,
    "media": 4,
    "told": 3,
    "retrieved": 2,
    "inferred": 1,
    "unknown": 0,
}

_BASE_CONFIDENCE = {
    "direct": 0.82,
    "media": 0.70,
    "told": 0.62,
    "retrieved": 0.55,
    "inferred": 0.45,
    "unknown": 0.35,
}

_SOURCE_WEIGHT = {
    "direct": 1.0,
    "media": 0.97,
    "told": 0.92,
    "retrieved": 0.88,
    "inferred": 0.80,
    "unknown": 0.75,
}

_TIER_WEIGHT = {"hot": 1.03, "warm": 1.0, "cold": 0.97}

_CONFLICT_MARKERS = (
    "改成",
    "改为",
    "其实是",
    "更正",
    "纠正",
    "不是",
    "不再",
    "取消",
    "推迟",
    "换到",
    "变成",
    "update",
    "correction",
    "instead",
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def normalize_source(value: Any) -> str:
    """Normalize a source label to a known deterministic label."""
    text = str(value or "").strip().lower()
    aliases = {
        "user": "direct",
        "self": "direct",
        "direct": "direct",
        "image": "media",
        "voice": "media",
        "audio": "media",
        "media": "media",
        "heard": "told",
        "quoted": "told",
        "told": "told",
        "search": "retrieved",
        "retrieval": "retrieved",
        "retrieved": "retrieved",
        "guess": "inferred",
        "deduced": "inferred",
        "inferred": "inferred",
        "": "unknown",
        "unknown": "unknown",
    }
    return aliases.get(text, "unknown")


def source_for_input(text: str = "", extra: str = "", voice: str = "") -> str:
    """Classify a memory entry's source from deterministic input flags."""
    if str(extra or "").strip() or str(voice or "").strip():
        return "media"
    if str(text or "").strip():
        return "direct"
    return "unknown"


def initial_confidence(source: str = "direct", importance: float = 0.5) -> float:
    """Initial deterministic confidence from source and importance."""
    src = normalize_source(source)
    base = _BASE_CONFIDENCE.get(src, 0.35)
    base += 0.08 * (_clamp(importance, 0.0, 1.0) - 0.5)
    return round(_clamp(base), 4)


def update_confidence(
    previous: float | None,
    source: str = "direct",
    *,
    hits: int = 0,
    review_count: int = 0,
    age_days: float = 0.0,
) -> float:
    """Blend previous confidence with deterministic evidence features.

    Repeated recall raises confidence slowly; age lowers it slowly. This is
    not a statistical calibrator; it is a conservative default until a real
    probability calibrator is added.
    """
    src = normalize_source(source)
    base = _BASE_CONFIDENCE.get(src, 0.35)
    evidence = min(0.08, 0.01 * max(0, int(hits)))
    evidence += min(0.05, 0.01 * max(0, int(review_count)))
    decay = min(0.12, max(0.0, float(age_days)) / 365.0 * 0.06)
    current = base + evidence - decay
    if previous is None:
        return round(_clamp(current), 4)
    blended = 0.6 * _clamp(previous) + 0.4 * _clamp(current)
    return round(_clamp(blended), 4)


def merge_sources(left: Any, right: Any) -> str:
    """Keep the stronger source when duplicate memories merge."""
    left_source = normalize_source(left)
    right_source = normalize_source(right)
    if SOURCE_RANK.get(left_source, 0) >= SOURCE_RANK.get(right_source, 0):
        return left_source
    return right_source


def source_precedence(*sources: Any) -> str:
    """Return the strongest source among many."""
    best = "unknown"
    for source in sources:
        candidate = normalize_source(source)
        if SOURCE_RANK.get(candidate, 0) > SOURCE_RANK.get(best, 0):
            best = candidate
    return best


def retrieval_weight(entry: dict[str, Any] | None) -> float:
    """Small source/confidence/tier weight for memory retrieval scoring.

    Old entries without the new metadata keep a neutral 1.0 weight.
    """
    if not isinstance(entry, dict):
        return 1.0
    if "memory_source" not in entry and "memory_confidence" not in entry:
        return 1.0
    source = normalize_source(entry.get("memory_source"))
    source_weight = _SOURCE_WEIGHT.get(source, 0.80)
    try:
        confidence = _clamp(entry.get("memory_confidence", 0.7))
    except Exception:
        confidence = 0.7
    tier = str(entry.get("memory_tier") or "warm")
    tier_weight = _TIER_WEIGHT.get(tier, 1.0)
    return round((0.85 + 0.15 * confidence) * source_weight * tier_weight, 4)


def should_abstain(
    confidence: float,
    source: str = "unknown",
    *,
    min_confidence: float = 0.38,
    unknown_min_confidence: float = 0.55,
) -> bool:
    """Conservative abstention policy for memory answers."""
    src = normalize_source(source)
    conf = _clamp(confidence)
    if src == "unknown" and conf < unknown_min_confidence:
        return True
    return conf < min_confidence


def classify_write_op(
    old_entry: dict[str, Any] | None,
    new_entry: dict[str, Any] | None,
    cosine: float,
    *,
    conflict: bool = False,
) -> str:
    """Conservative write operation for a new memory candidate.

    Returns one of ADD, UPDATE, DELETE, NOOP. DELETE is only returned when the
    caller explicitly marks a deletion candidate; semantic similarity alone
    never deletes a memory.
    """
    if old_entry is None:
        return "ADD"
    if new_entry is None:
        return "DELETE" if bool(old_entry.get("delete_requested")) else "NOOP"
    if conflict:
        return "UPDATE"
    try:
        similarity = _clamp(cosine)
    except Exception:
        similarity = 0.0
    if similarity >= 0.93:
        return "NOOP"
    if similarity >= 0.72:
        return "UPDATE"
    return "ADD"


def memory_tier(entry: dict[str, Any] | None, now: float | None = None) -> str:
    """Cheap deterministic hot/warm/cold tier for read-budget selection."""
    if not isinstance(entry, dict):
        return "cold"
    try:
        current = float(now if now is not None else time.time())
        ts = float(entry.get("ts", 0) or 0)
        age_days = max(0.0, (current - ts) / 86400.0)
        importance = _clamp(entry.get("importance", 0.5))
        hits = int(entry.get("hits", 0) or 0)
    except Exception:
        age_days, importance, hits = 365.0, 0.5, 0
    if importance >= 0.75 or age_days <= 1.0 or hits >= 3:
        return "hot"
    if importance >= 0.45 or age_days <= 14.0:
        return "warm"
    return "cold"


def detect_conflict(old_text: str, new_text: str) -> bool:
    """Conservative correction/contradiction heuristic for duplicate writes.

    It only fires on explicit correction markers, not on every negation. A
    missed update is safer than a silent rewrite.
    """
    old = str(old_text or "").strip().lower()
    new = str(new_text or "").strip().lower()
    if not old or not new or old == new:
        return False
    has_marker = any(marker in new for marker in _CONFLICT_MARKERS)
    return has_marker and not any(ch.isdigit() for ch in new)


def merge_version(entry: dict[str, Any], old_text: str, *, limit: int = 8) -> None:
    """Keep a bounded previous-version list for UPDATE/rollback."""
    if not isinstance(entry, dict) or not old_text:
        return
    versions = entry.get("previous_versions")
    if not isinstance(versions, list):
        versions = []
    versions.append(str(old_text)[:800])
    entry["previous_versions"] = versions[-max(1, int(limit)):]


def select_top(scored: Any, k: Any, *, cold_budget: int = 2) -> list:
    """Select top memories with a small cold-tier budget.

    Hot/warm entries are preferred; cold entries fill remaining slots up to
    cold_budget. This is a read budget, not an eviction.
    """
    try:
        limit = max(0, int(k))
    except Exception:
        limit = 0
    if limit <= 0 or not isinstance(scored, list):
        return []
    warm_or_better: list = []
    cold: list = []
    for item in scored:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        entry = item[1]
        tier = str(entry.get("memory_tier") or "warm") if isinstance(entry, dict) else "warm"
        if tier == "cold":
            cold.append(item)
        else:
            warm_or_better.append(item)
    selected = warm_or_better[:limit]
    remaining = max(0, limit - len(selected))
    selected.extend(cold[:min(remaining, max(0, int(cold_budget)))])
    if len(selected) < limit:
        used = {id(item[1]) for item in selected}
        for item in cold:
            if id(item[1]) not in used:
                selected.append(item)
                if len(selected) >= limit:
                    break
    return selected[:limit]


def summarize_recall(top: Any, now: float | None = None) -> dict[str, Any]:
    """Build the per-turn memory meta used by the interpretation layer."""
    if not isinstance(top, list):
        return {"count": 0, "confidence": 0.0, "source": "unknown", "abstain": False, "tiers": {}, "destinations": {}}
    rows = []
    destinations: dict[str, int] = {}
    tiers: dict[str, int] = {}
    for _score, entry in top:
        if not isinstance(entry, dict):
            continue
        source = normalize_source(entry.get("memory_source"))
        try:
            confidence = float(entry.get("memory_confidence", 0.6) or 0.6)
        except Exception:
            confidence = 0.6
        tier = str(entry.get("memory_tier") or memory_tier(entry, now))
        rows.append({"source": source, "confidence": confidence, "tier": tier})
        tiers[tier] = int(tiers.get(tier, 0) or 0) + 1
        destination = entry.get("destination")
        if isinstance(destination, dict):
            name = str(destination.get("sender_name") or destination.get("sender_id") or "").strip()
            if name:
                destinations[name] = int(destinations.get(name, 0) or 0) + 1
    if not rows:
        return {"count": 0, "confidence": 0.0, "source": "unknown", "abstain": False, "tiers": {}, "destinations": {}}
    avg_confidence = sum(row["confidence"] for row in rows) / len(rows)
    source = source_precedence(*(row["source"] for row in rows))
    return {
        "count": len(rows),
        "confidence": round(_clamp(avg_confidence), 4),
        "source": source,
        "abstain": should_abstain(avg_confidence, source),
        "tiers": tiers,
        "destinations": dict(sorted(destinations.items(), key=lambda item: -item[1])[:4]),
    }


def rollback_entry(entry: dict[str, Any] | None) -> bool:
    """Restore the last previous version. The vector is cleared for re-embedding."""
    if not isinstance(entry, dict):
        return False
    versions = entry.get("previous_versions")
    if not isinstance(versions, list) or not versions:
        return False
    entry["text"] = str(versions.pop())[:1200]
    entry["vector"] = []
    entry["vec_updated_ts"] = 0.0
    entry["last_write_op"] = "ROLLBACK"
    return True


def build_destination(sender_id: Any = "", sender_name: Any = "") -> dict[str, str]:
    """Small destination record for who told the agent this memory."""
    return {
        "sender_id": str(sender_id or ""),
        "sender_name": str(sender_name or ""),
    }
