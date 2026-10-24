# -*- coding: utf-8 -*-
"""Deterministic memory provenance, confidence and write-op helpers.

This module is intentionally free of AstrBot imports so it can be used by
scripts/eval_metamemory_policy.py and unit-tested without starting AstrBot.

It does not call an LLM. The LLM/interpretation layer may propose candidates,
but these helpers decide the stored metadata and conservative write operation.
"""

from __future__ import annotations

from typing import Any

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


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def normalize_source(value: Any) -> str:
    """Normalize a source label to one of the known deterministic labels."""
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

    Repeated recall raises confidence slowly; age lowers it slowly. This is not
    a statistical calibrator; it is a conservative default until real
    probability calibration is added.
    """
    src = normalize_source(source)
    base = _BASE_CONFIDENCE.get(src, 0.35)
    evidence = min(0.08, 0.01 * max(0, int(hits))) + min(0.05, 0.01 * max(0, int(review_count)))
    decay = min(0.12, max(0.0, float(age_days)) / 365.0 * 0.06)
    current = base + evidence - decay
    if previous is None:
        return round(_clamp(current), 4)
    blended = 0.6 * _clamp(previous) + 0.4 * _clamp(current)
    return round(_clamp(blended), 4)


def merge_sources(left: Any, right: Any) -> str:
    """Keep the stronger source when duplicate memories merge."""
    a = normalize_source(left)
    b = normalize_source(right)
    return a if SOURCE_RANK.get(a, 0) >= SOURCE_RANK.get(b, 0) else b


def source_precedence(*sources: Any) -> str:
    """Return the strongest source among many."""
    best = "unknown"
    for source in sources:
        candidate = normalize_source(source)
        if SOURCE_RANK.get(candidate, 0) > SOURCE_RANK.get(best, 0):
            best = candidate
    return best


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

    Returns one of ADD, UPDATE, DELETE, NOOP.

    DELETE is only returned when the caller explicitly marks a deletion
    candidate (new_entry is None and old_entry exists with delete flag); this
    helper never deletes on semantic similarity alone.
    """
    if old_entry is None:
        return "ADD"
    if new_entry is None:
        return "DELETE" if bool(old_entry.get("delete_requested")) else "NOOP"
    if conflict:
        return "UPDATE"
    try:
        sim = _clamp(cosine)
    except Exception:
        sim = 0.0
    if sim >= 0.93:
        return "NOOP"
    if sim >= 0.72:
        return "UPDATE"
    return "ADD"


def build_destination(sender_id: Any = "", sender_name: Any = "") -> dict[str, str]:
    """Small destination/source record for who told the agent this memory."""
    return {
        "sender_id": str(sender_id or ""),
        "sender_name": str(sender_name or ""),
    }
