# -*- coding: utf-8 -*-
"""Deterministic memory provenance, confidence and write-op helpers.

The module is intentionally free of AstrBot imports so it can be used by
scripts/eval_metamemory_policy.py without starting AstrBot.

It does not call an LLM. The LLM/interpretation layer may propose candidates,
but these helpers decide what metadata is stored and which conservative write
operation is allowed.
"""

from __future__ import annotations

import hashlib
import math
import re
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
    "ANSWER_GATE_FORCE",
    "ANSWER_GATE_SEMI",
    "answer_confidence",
    "abstention_gate",
    "apply_abstention_gate",
    "answer_gate",
    "text_similarity",
    "schema_congruence",
    "is_self_defining",
    "retrieval_inhibition",
    "apply_retrieval_inhibition",
    "regulation_memory_modifier",
    "detect_delete_request",
    "is_delete_confirmation",
    "deletion_candidates",
    "soft_delete_entry",
    "restore_entry",
    "detect_restore_request",
    "detect_rollback_request",
    "rollback_candidate",
    "restore_candidate",
    "append_write_log",
    "handle_delete_command",
    "detect_open_loops",
    "resolve_open_loops",
    "CANDIDATE_MAX",
    "CANDIDATE_MAX_CONFIDENCE",
    "apply_memory_candidate",
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

_STRONG_CORRECTION_MARKERS = (
    "改成",
    "改为",
    "其实是",
    "更正",
    "纠正",
    "换到",
    "变成",
    "update",
    "correction",
    "instead",
)

_WEAK_NEGATION_MARKERS = ("不是", "不再", "取消", "推迟")


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
    if any(marker in new for marker in _STRONG_CORRECTION_MARKERS):
        return True
    has_weak = any(marker in new for marker in _WEAK_NEGATION_MARKERS)
    return has_weak and not any(ch.isdigit() for ch in new)


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
    """Build the per-turn memory meta used by the interpretation layer.

    The meta now also carries a deterministic answer_confidence and an
    abstention gate: force (withhold uncertain memory content), semi (keep the
    content but mark it uncertain) or none.
    """
    empty = {
        "count": 0, "confidence": 0.0, "source": "unknown", "abstain": False,
        "tiers": {}, "destinations": {}, "answer_confidence": 0.0,
        "gate": "none", "conflicts": 0,
    }
    if not isinstance(top, list):
        return empty
    rows = []
    destinations: dict[str, int] = {}
    tiers: dict[str, int] = {}
    conflicts = 0
    oldest_ts = 0.0
    for _score, entry in top:
        if not isinstance(entry, dict):
            continue
        # Legacy entries without the new metadata were written from direct
        # user/model input; keep them neutral rather than "unknown" so old
        # data does not trigger forced abstention after an upgrade.
        if "memory_source" in entry or "memory_confidence" in entry:
            source = normalize_source(entry.get("memory_source"))
            try:
                confidence = float(entry.get("memory_confidence", 0.6) or 0.6)
            except Exception:
                confidence = 0.6
        else:
            source = "direct"
            confidence = 0.7
        tier = str(entry.get("memory_tier") or memory_tier(entry, now))
        rows.append({"source": source, "confidence": confidence, "tier": tier})
        tiers[tier] = int(tiers.get(tier, 0) or 0) + 1
        # A conflict resolved by an explicit user correction is still
        # versioned for rollback but must not force abstention afterwards.
        if entry.get("conflict") and not entry.get("conflict_resolved"):
            conflicts += 1
        try:
            ts = float(entry.get("ts", 0) or 0)
            if ts > 0 and (oldest_ts <= 0 or ts < oldest_ts):
                oldest_ts = ts
        except Exception:
            pass
        destination = entry.get("destination")
        if isinstance(destination, dict):
            name = str(destination.get("sender_name") or destination.get("sender_id") or "").strip()
            if name:
                destinations[name] = int(destinations.get(name, 0) or 0) + 1
    if not rows:
        return empty
    avg_confidence = sum(row["confidence"] for row in rows) / len(rows)
    source = source_precedence(*(row["source"] for row in rows))
    stale_days = 0.0
    try:
        current = float(now if now is not None else time.time())
        if oldest_ts > 0:
            stale_days = max(0.0, (current - oldest_ts) / 86400.0)
    except Exception:
        stale_days = 0.0
    meta = {
        "count": len(rows),
        "confidence": round(_clamp(avg_confidence), 4),
        "source": source,
        "abstain": should_abstain(avg_confidence, source),
        "tiers": tiers,
        "destinations": dict(sorted(destinations.items(), key=lambda item: -item[1])[:4]),
        "conflicts": conflicts,
    }
    meta["answer_confidence"] = answer_confidence(meta, conflict=conflicts > 0, stale_days=stale_days)
    meta["gate"] = abstention_gate(meta["answer_confidence"], source)
    meta["abstain"] = bool(meta["abstain"] or meta["gate"] != "none")
    return meta


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
    entry["needs_reindex"] = True
    entry["last_write_op"] = "ROLLBACK"
    return True


def build_destination(sender_id: Any = "", sender_name: Any = "") -> dict[str, str]:
    """Small destination record for who told the agent this memory."""
    return {
        "sender_id": str(sender_id or ""),
        "sender_name": str(sender_name or ""),
    }


# ---------------------------------------------------------------------------
# Answer confidence / abstention gate (metamemory policy)
# ---------------------------------------------------------------------------
ANSWER_GATE_FORCE = 0.34
ANSWER_GATE_SEMI = 0.55
ANSWER_SOURCE_FORCE = 0.48
ANSWER_CONFLICT_PENALTY = 0.16
ANSWER_STALE_PENALTY_MAX = 0.12
ANSWER_STALE_DAYS = 45.0


def answer_confidence(aggregate: Any, *, conflict: bool = False,
                      stale_days: float = 0.0) -> float:
    """Deterministic confidence that recalled memory may be asserted as fact.

    Conservative policy value, not a calibrated probability: source rank,
    coverage, cold-tier share, conflicts and staleness all pull it down.
    """
    if not isinstance(aggregate, dict):
        return 0.0
    try:
        count = int(aggregate.get("count", 0) or 0)
    except Exception:
        count = 0
    if count <= 0:
        return 0.0
    confidence = _clamp(aggregate.get("confidence", 0.0))
    source = normalize_source(aggregate.get("source"))
    source_factor = 0.72 + 0.06 * SOURCE_RANK.get(source, 0)
    coverage_factor = 0.82 + 0.06 * min(3, count)
    tiers = aggregate.get("tiers") if isinstance(aggregate.get("tiers"), dict) else {}
    try:
        cold = int(tiers.get("cold", 0) or 0)
    except Exception:
        cold = 0
    tier_factor = 1.0 - 0.10 * (cold / float(max(1, count)))
    value = confidence * min(1.0, source_factor) * min(1.0, coverage_factor) * tier_factor
    if conflict or bool(aggregate.get("conflict")) or bool(aggregate.get("conflicts")):
        value -= ANSWER_CONFLICT_PENALTY
    try:
        age_days = max(0.0, float(stale_days or 0.0))
    except Exception:
        age_days = 0.0
    if age_days > 0.0:
        value -= min(ANSWER_STALE_PENALTY_MAX, age_days / ANSWER_STALE_DAYS * 0.05)
    return round(_clamp(value), 4)


def abstention_gate(confidence: Any, source: Any = "unknown", *,
                    force: float = ANSWER_GATE_FORCE,
                    semi: float = ANSWER_GATE_SEMI) -> str:
    """Map answer confidence to a deterministic abstention gate level.

    force: withhold uncertain memory content; semi: keep content but mark
    it uncertain; none: normal.
    """
    conf = _clamp(confidence)
    src = normalize_source(source)
    if src in ("unknown", "inferred"):
        force = max(float(force), ANSWER_SOURCE_FORCE)
    if conf <= 0.0:
        return "force"
    if conf < float(force):
        return "force"
    if conf < float(semi):
        return "semi"
    return "none"


def apply_abstention_gate(memory_text: Any, gate: Any) -> str:
    """Return the memory content the interpretation layer may receive.

    force withholds the memory lines entirely so an uncertain memory cannot
    be asserted as fact; semi/none keep the content (the interpretation
    layer owns the uncertainty note).
    """
    text = str(memory_text or "")
    if str(gate or "none") == "force":
        return ""
    return text


def answer_gate(aggregate: Any, memory_text: Any = "", *,
                conflict: bool = False, stale_days: float = 0.0) -> dict[str, Any]:
    """Compute answer confidence, gate level and filtered memory text."""
    conf = answer_confidence(aggregate, conflict=conflict, stale_days=stale_days)
    source = aggregate.get("source") if isinstance(aggregate, dict) else "unknown"
    count = 0
    if isinstance(aggregate, dict):
        try:
            count = int(aggregate.get("count", 0) or 0)
        except Exception:
            count = 0
    gate = abstention_gate(conf, source) if count > 0 else "none"
    abstain = bool(gate != "none")
    if isinstance(aggregate, dict) and aggregate.get("abstain"):
        abstain = True
    return {"answer_confidence": conf, "gate": gate, "abstain": abstain,
            "memory_text": apply_abstention_gate(memory_text, gate)}


# ---------------------------------------------------------------------------
# Deterministic text / self-schema helpers (schema-congruent memory)
# ---------------------------------------------------------------------------


def _bigrams(text: Any) -> set[str]:
    try:
        value = "".join(str(text or "").split())
    except Exception:
        return set()
    if len(value) < 2:
        return {value} if value else set()
    return {value[i:i + 2] for i in range(len(value) - 1)}


def text_similarity(a: Any, b: Any) -> float:
    """Deterministic char-bigram Dice similarity in [0, 1]."""
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    return round(len(ga & gb) / float(len(ga | gb)), 4)


SCHEMA_SELF_DEFINING_THRESHOLD = 0.45


def schema_congruence(text: Any, schema_texts: Any) -> float:
    """How much a memory matches the current self-schema (Conway, 2005).

    Deterministic character-bigram containment against bounded schema texts
    (self-model, narrative self, autobiographical titles). It only decides
    storage metadata; it never rewrites the memory.
    """
    grams = _bigrams(text)
    if not grams or not isinstance(schema_texts, (list, tuple)):
        return 0.0
    best = 0.0
    for schema in list(schema_texts)[-24:]:
        schema_grams = _bigrams(schema)
        if not schema_grams:
            continue
        overlap = len(grams & schema_grams)
        containment = overlap / float(len(grams))
        dice = overlap / float(len(grams | schema_grams))
        best = max(best, 0.75 * containment + 0.25 * dice)
    return round(max(0.0, min(1.0, best)), 4)


def is_self_defining(entry: Any, congruence: Any = None, *,
                     threshold: float = SCHEMA_SELF_DEFINING_THRESHOLD,
                     importance_min: float = 0.62) -> bool:
    """Self-defining memory flag: schema-congruent, important, rehearsed."""
    if not isinstance(entry, dict):
        return False
    if congruence is None:
        congruence = entry.get("schema_congruence", 0.0)
    congruence = _clamp(congruence)
    importance = _clamp(entry.get("importance", 0.5))
    def _count(key: str) -> int:
        try:
            return int(entry.get(key, 0) or 0)
        except Exception:
            return 0

    hits = _count("hits")
    reviews = _count("review_count")
    recalls = _count("recall_count")
    rehearsal = min(1.0, (hits + reviews + recalls) / 4.0)
    score = 0.55 * congruence + 0.30 * importance + 0.15 * rehearsal
    return bool(congruence >= float(threshold)
                and importance >= float(importance_min)
                and score >= 0.55
                and (hits + reviews + recalls) >= 1)


# ---------------------------------------------------------------------------
# Retrieval-induced forgetting (active inhibition)
# ---------------------------------------------------------------------------
INHIBITION_GAIN = 0.28
INHIBITION_DECAY_DAYS = 7.0
INHIBITION_THRESHOLD_COSINE = 0.45


def retrieval_inhibition(entry: Any, now: float | None = None) -> float:
    """Effective retrieval-induced forgetting for one entry (decays with age)."""
    if not isinstance(entry, dict):
        return 0.0
    base = _clamp(entry.get("inhibition", 0.0))
    if base <= 0.0:
        return 0.0
    try:
        current = float(now if now is not None else time.time())
        stamped = float(entry.get("inhibition_ts", 0) or 0)
        age_days = max(0.0, (current - stamped) / 86400.0) if stamped > 0 else 0.0
    except Exception:
        age_days = 0.0
    return round(base * math.exp(-age_days / INHIBITION_DECAY_DAYS), 4)


def apply_retrieval_inhibition(candidates: Any, recalled_ids: Any,
                               now: float | None = None) -> int:
    """Inhibit similar memories that lost the retrieval competition.

    Retrieval-induced forgetting: after a successful recall, competing
    similar traces are suppressed. They are not deleted and the suppression
    decays over days.
    """
    if not isinstance(candidates, (list, tuple)):
        return 0
    recalled = {str(x) for x in (recalled_ids or []) if str(x)}
    current = float(now if now is not None else time.time())
    changed = 0
    for item in candidates:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        entry, cosine = item[0], item[1]
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        if entry_id and entry_id in recalled:
            continue
        try:
            similarity = float(cosine)
        except Exception:
            similarity = 0.0
        if similarity < INHIBITION_THRESHOLD_COSINE:
            continue
        new_value = _clamp(_clamp(entry.get("inhibition", 0.0))
                           + INHIBITION_GAIN * _clamp(similarity))
        entry["inhibition"] = round(new_value, 4)
        entry["inhibition_ts"] = current
        try:
            entry["suppression_count"] = int(entry.get("suppression_count", 0) or 0) + 1
        except Exception:
            entry["suppression_count"] = 1
        changed += 1
    return changed


# ---------------------------------------------------------------------------
# Emotion regulation x memory (Gross process model modulation)
# ---------------------------------------------------------------------------


def regulation_memory_modifier(entry: Any, regulation: Any, emotion: Any = "") -> float:
    """Deterministic regulation x memory retrieval multiplier.

    Suppression narrows retrieval of high-arousal negative memories;
    reappraisal favours memories that carry meaning/reflection; comfort and
    avoidance bias toward negative material; distraction discounts all.
    """
    if not isinstance(entry, dict):
        return 1.0
    reg = str(regulation or "none").strip().lower()
    try:
        valence = float(entry.get("encoding_valence", 0.0) or 0.0)
    except Exception:
        valence = 0.0
    arousal = _clamp(entry.get("encoding_arousal", 0.5))
    if reg == "suppress":
        return round(max(0.80, 0.94 - 0.10 * _clamp(-valence) * arousal), 4)
    if reg == "reappraise":
        meaning = str(entry.get("meaning") or entry.get("reflection") or "").strip()
        encoding = str(entry.get("encoding_regulation") or "")
        bonus = 0.04 if (meaning or encoding == "reappraise") else 0.0
        return round(min(1.10, 1.04 + bonus), 4)
    if reg == "seek_comfort":
        return 1.05 if valence < -0.1 else 1.0
    if reg == "distraction":
        return 0.96
    if reg == "avoid":
        return 0.97 if valence < -0.1 else 1.0
    return 1.0


# ---------------------------------------------------------------------------
# Explicit write commands: DELETE / RESTORE / ROLLBACK over a memory doc
# ---------------------------------------------------------------------------
DELETE_MATCH_THRESHOLD = 0.55
DELETE_STRONG_MATCH = 0.80
DELETE_CONFIRM_WINDOW_SECONDS = 300.0
PENDING_DELETE_MAX_CANDIDATES = 3

_DELETE_MARKERS = (
    "确认删除", "删除记忆", "删掉记忆", "删除这条记忆", "清除记忆", "清除这条记忆",
    "别再记得", "不要再记得", "忘掉", "忘记", "删掉", "删除",
    "delete memory", "forget about", "forget that",
)
_RESTORE_MARKERS = ("恢复记忆", "撤销删除", "取消删除", "恢复那条记忆",
                    "恢复刚才删的", "undelete", "restore memory")
_ROLLBACK_MARKERS = (
    "回滚记忆", "回滚刚才", "回滚这次", "回滚到上一版", "回滚",
    "撤销修改", "撤回修改", "撤销刚才", "撤销这次", "撤销记忆修改",
    "恢复上一版", "恢复记忆修改", "还原记忆", "rollback memory",
)
_GENERIC_DELETE_TARGETS = {"", "那个", "这个", "那些", "这些", "它", "这件事",
                          "那件事", "刚才", "前面", "所有", "全部", "记忆", "内容"}
_CONFIRM_TOKENS = {"确认", "确定", "是的", "是", "对", "对的", "没错", "嗯", "嗯嗯",
                   "删", "删吧", "可以", "可以删", "确认删除", "确认删除记忆",
                   "好的", "好", "yes", "y", "ok", "confirm"}
_CLEAN_STRIP = "：:，,。.！!？?、；; \t\n\"'“”「」‘’（）()[]【】"


def _normalize_for_match(text: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").lower())


def _clean_delete_target(text: Any) -> str:
    value = str(text or "").strip().strip(_CLEAN_STRIP)
    for _ in range(6):
        before = value
        for particle in ("关于", "有关", "这条", "那条", "这个", "那个", "记住的",
                         "请", "帮我", "把"):
            if value.startswith(particle):
                value = value[len(particle):].strip().strip(_CLEAN_STRIP)
        for particle in ("的记忆", "的事情", "相关记忆", "相关", "吧", "这条", "那条", "内容", "记忆"):
            if value.endswith(particle):
                value = value[: -len(particle)].strip().strip(_CLEAN_STRIP)
        if value == before:
            break
    return value.strip()


def _contains_confirmation(text: Any) -> bool:
    normalized = str(text or "").strip()
    return any(token in normalized for token in ("确认", "确定", "是的", "没错"))


def detect_delete_request(text: Any) -> dict[str, Any] | None:
    """Detect an explicit natural-language delete instruction (not inference)."""
    raw = str(text or "").strip()
    if not raw or len(raw) > 240:
        return None
    if (("?" in raw or "？" in raw or raw.endswith(("吗", "呢"))) and "确认" not in raw):
        return None
    lowered = raw.lower()
    for marker in _DELETE_MARKERS:
        index = lowered.find(marker)
        if index < 0:
            continue
        prefix = lowered[max(0, index - 3):index]
        if marker != "确认删除" and ("不" in prefix or "别" in prefix or "没" in prefix):
            continue
        rest = raw[index + len(marker):]
        target = _clean_delete_target(rest)
        if not target and index > 0:
            before = raw[:index]
            for lead in ("请你", "请", "帮我", "麻烦", "你"):
                if before.startswith(lead):
                    before = before[len(lead):]
                    break
            if before.startswith("把"):
                before = before[1:]
            target = _clean_delete_target(before)
        if not target and "确认" not in raw:
            # Marker present but no concrete target: explicit request, vague target.
            return {
                "explicit": True,
                "marker": marker,
                "target": "",
                "vague": True,
                "confirmed": _contains_confirmation(raw),
            }
        return {
            "explicit": True,
            "marker": marker,
            "target": target,
            "vague": target in _GENERIC_DELETE_TARGETS or len(target) < 2,
            "confirmed": _contains_confirmation(raw),
        }
    return None


def is_delete_confirmation(text: Any) -> bool:
    """True only for a short explicit confirmation answer."""
    normalized = re.sub(r"[\s。.!！?？,，、；;:：]+", "", str(text or ""))
    return 0 < len(normalized) <= 12 and normalized.lower() in _CONFIRM_TOKENS


def _delete_match_score(target: Any, entry_text: Any) -> float:
    target_norm = _normalize_for_match(target)
    entry_norm = _normalize_for_match(entry_text)
    if not target_norm or not entry_norm:
        return 0.0
    if target_norm in entry_norm:
        return 1.0
    target_grams = _bigrams(target_norm)
    entry_grams = _bigrams(entry_norm)
    if not target_grams or not entry_grams:
        return 0.0
    overlap = len(target_grams & entry_grams)
    containment = overlap / float(len(target_grams))
    dice = overlap / float(len(target_grams | entry_grams))
    return round(0.7 * containment + 0.3 * dice, 4)


def deletion_candidates(entries: Any, target: Any, *,
                        threshold: float = DELETE_MATCH_THRESHOLD) -> list:
    """Rank live entries matched by an explicit delete target.

    Summaries and already-deleted entries are never candidates, so a
    consolidated original cannot be removed by a natural-language command.
    """
    if not isinstance(entries, list):
        return []
    target_norm = _normalize_for_match(target)
    if len(target_norm) < 2:
        return []
    scored = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("deleted") or entry.get("summarized") or str(entry.get("role") or "") == "summary":
            continue
        score = _delete_match_score(target_norm, str(entry.get("text") or ""))
        if score >= threshold:
            scored.append((round(score, 4), entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def soft_delete_entry(entry: Any, now: float | None = None, reason: str = "user_request") -> bool:
    """Soft delete: hide from recall, keep text/versions for audit + restore."""
    if not isinstance(entry, dict) or entry.get("deleted"):
        return False
    entry["deleted"] = True
    entry["deleted_ts"] = round(float(now if now is not None else time.time()), 3)
    entry["delete_reason"] = str(reason or "user_request")[:120]
    entry["last_write_op"] = "DELETE"
    entry["vector"] = []
    entry["vec_updated_ts"] = 0.0
    entry["needs_reindex"] = True
    return True


def restore_entry(entry: Any, now: float | None = None) -> bool:
    """Undo a soft delete; the caller re-embeds because the vector was cleared."""
    if not isinstance(entry, dict) or not entry.get("deleted"):
        return False
    entry["deleted"] = False
    entry["restored_ts"] = round(float(now if now is not None else time.time()), 3)
    entry["last_write_op"] = "RESTORE"
    entry["needs_reindex"] = True
    return True


def append_write_log(doc: Any, *, op: str, entry_id: Any = "", reason: Any = "",
                     ts: float | None = None) -> list:
    """Bounded write-op audit log stored with the memory doc."""
    if not isinstance(doc, dict):
        return []
    log = doc.get("write_log") if isinstance(doc.get("write_log"), list) else []
    try:
        stamp = round(float(ts if ts is not None else time.time()), 3)
    except Exception:
        stamp = round(time.time(), 3)
    log.append({"ts": stamp, "op": str(op or "")[:16],
                "id": str(entry_id or "")[:32], "reason": str(reason or "")[:120]})
    doc["write_log"] = log[-80:]
    return doc["write_log"]


def detect_restore_request(text: Any) -> bool:
    raw = str(text or "").lower()
    return any(marker in raw for marker in _RESTORE_MARKERS)


def detect_rollback_request(text: Any) -> bool:
    raw = str(text or "").lower()
    return any(marker in raw for marker in _ROLLBACK_MARKERS)


def restore_candidate(entries: Any) -> dict | None:
    """Most recently soft-deleted entry (newest deleted_ts wins)."""
    if not isinstance(entries, list):
        return None
    best = None
    best_ts = -1.0
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("deleted"):
            continue
        try:
            ts = float(entry.get("deleted_ts", 0) or 0)
        except Exception:
            ts = 0.0
        if ts >= best_ts:
            best = entry
            best_ts = ts
    return best


def rollback_candidate(entries: Any) -> dict | None:
    """Most recently changed entry that still has a version to roll back to."""
    if not isinstance(entries, list):
        return None
    best = None
    best_ts = -1.0
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("deleted"):
            continue
        versions = entry.get("previous_versions")
        if not isinstance(versions, list) or not versions:
            continue
        try:
            ts = max(float(entry.get("vec_updated_ts", 0) or 0),
                     float(entry.get("last_write_ts", 0) or 0),
                     float(entry.get("ts", 0) or 0))
        except Exception:
            ts = 0.0
        if ts >= best_ts:
            best = entry
            best_ts = ts
    return best




# ---------------------------------------------------------------------------
# LLM-proposed memory candidates (Mem0-style: propose, never write)
# ---------------------------------------------------------------------------
CANDIDATE_MAX = 3
CANDIDATE_MAX_CONFIDENCE = 0.70


def _candidate_id(text: str, stamp: float) -> str:
    raw = (str(text) + "|" + str(stamp)).encode("utf-8")
    return "cand_" + hashlib.sha1(raw).hexdigest()[:10]


def apply_memory_candidate(entries: Any, candidate: Any, *, match: Any = None,
                           cosine: Any = 0.0, vector: Any = None,
                           now: float | None = None,
                           provenance: Any = None) -> dict[str, Any]:
    """Route one LLM-proposed candidate through the deterministic policy.

    The model only proposes text/source/confidence/kind; this helper decides
    ADD/UPDATE/NOOP. A candidate can never DELETE a memory, even if it asks
    to, and its confidence is capped below direct-user confidence.
    """
    if not isinstance(entries, list) or not isinstance(candidate, dict):
        return {"op": "NOOP", "entry": None, "reason": "invalid_candidate"}
    kind = str(candidate.get("kind") or "add").strip().lower()
    if kind == "delete":
        return {"op": "NOOP", "entry": None, "reason": "llm_delete_not_allowed"}
    text = str(candidate.get("text") or "").strip()[:300]
    if len(text) < 4:
        return {"op": "NOOP", "entry": None, "reason": "candidate_too_short"}
    source = normalize_source(candidate.get("source"))
    if source not in ("told", "inferred"):
        source = "inferred"
    try:
        confidence = min(CANDIDATE_MAX_CONFIDENCE,
                         max(0.20, float(candidate.get("confidence", 0.5) or 0.5)))
    except Exception:
        confidence = 0.50
    stamp = float(now if now is not None else time.time())
    try:
        similarity = _clamp(cosine)
    except Exception:
        similarity = 0.0
    target = match if isinstance(match, dict) and not match.get("deleted") else None
    conflict = bool(target and detect_conflict(str(target.get("text") or ""), text))
    op = classify_write_op(target, {"text": text}, similarity,
                           conflict=conflict or kind == "update")
    if op == "DELETE":
        op = "NOOP"
    if op == "ADD":
        entry = {
            "id": _candidate_id(text, stamp),
            "text": text,
            "role": "user",
            "vector": list(vector) if isinstance(vector, (list, tuple)) else [],
            "ts": stamp,
            "hits": 1,
            "importance": round(_clamp(0.40 + 0.40 * confidence), 3),
            "memory_source": source,
            "memory_confidence": round(confidence, 4),
            "memory_tier": "warm",
            "conflict": False,
            "candidate_origin": "llm",
            "last_write_op": "ADD",
            "last_write_ts": stamp,
            "write_ops": {"ADD": 1},
            "schema_congruence": 0.0,
            "self_defining": False,
            "inhibition": 0.0,
            "suppression_count": 0,
            "last_used": stamp,
            "next_review_ts": stamp + 86400,
            "review_count": 0,
        }
        if isinstance(provenance, dict):
            entry["provenance"] = dict(provenance)
        entries.append(entry)
        return {"op": "ADD", "entry": entry, "reason": "candidate_add"}
    if op == "UPDATE" and target is not None:
        old_text = str(target.get("text") or "")
        merge_version(target, old_text)
        if text != old_text:
            target["text"] = text
            if isinstance(vector, (list, tuple)):
                target["vector"] = list(vector)
            target["vec_updated_ts"] = stamp
        previous = target.get("memory_confidence")
        try:
            previous_value = float(previous) if previous is not None else confidence
        except Exception:
            previous_value = confidence
        target["memory_confidence"] = round(
            min(CANDIDATE_MAX_CONFIDENCE,
                max(0.20, 0.5 * previous_value + 0.5 * confidence)), 4)
        target["memory_source"] = merge_sources(target.get("memory_source"), source)
        target["conflict"] = bool(conflict)
        target["candidate_origin"] = "llm"
        target["last_write_op"] = "UPDATE"
        target["last_write_ts"] = stamp
        ops = target.get("write_ops") if isinstance(target.get("write_ops"), dict) else {}
        ops["UPDATE"] = int(ops.get("UPDATE", 0) or 0) + 1
        target["write_ops"] = ops
        return {"op": "UPDATE", "entry": target, "reason": "candidate_update"}
    if target is not None:
        target["last_used"] = stamp
        target["hits"] = int(target.get("hits", 0) or 0) + 1
        return {"op": "NOOP", "entry": target, "reason": "candidate_duplicate"}
    return {"op": "NOOP", "entry": None, "reason": "candidate_noop"}


def handle_delete_command(doc: Any, text: Any, now: float | None = None) -> dict[str, Any]:
    """Deterministic runtime state machine for explicit memory commands.

    Only explicit delete/restore/rollback instructions are recognised;
    semantic similarity alone never deletes a memory. A delete request is
    staged as pending and only executes after an explicit confirmation turn
    (or when the same message already carries a confirmation marker). The
    command text itself is never stored as a new memory.
    """
    if not isinstance(doc, dict):
        return {"handled": False}
    try:
        current = float(now if now is not None else time.time())
    except Exception:
        current = time.time()
    entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
    pending = doc.get("pending_delete") if isinstance(doc.get("pending_delete"), dict) else None
    if pending:
        try:
            pending_age = current - float(pending.get("created_ts", 0) or 0)
        except Exception:
            pending_age = DELETE_CONFIRM_WINDOW_SECONDS + 1.0
        if pending_age > DELETE_CONFIRM_WINDOW_SECONDS:
            doc.pop("pending_delete", None)
            pending = None
        elif is_delete_confirmation(text):
            ids = [str(x) for x in (pending.get("ids") or []) if str(x)]
            target = None
            if len(ids) == 1:
                target = next((e for e in entries if isinstance(e, dict)
                               and str(e.get("id") or "") == ids[0]
                               and not e.get("deleted")), None)
            doc.pop("pending_delete", None)
            if target is not None and soft_delete_entry(target, current, reason="user_confirm"):
                append_write_log(doc, op="DELETE", entry_id=ids[0],
                                 reason="user_confirm", ts=current)
                return {"handled": True, "op": "DELETE", "entry": target,
                        "reason": "confirmed", "target": str(pending.get("target") or "")}
            return {"handled": True, "op": "NOOP", "reason": "pending_target_missing",
                    "target": str(pending.get("target") or "")}
        else:
            # Any unrelated turn cancels a pending confirmation: no stale deletes.
            doc.pop("pending_delete", None)
    if detect_restore_request(text):
        target = restore_candidate(entries)
        if target is not None and restore_entry(target, current):
            append_write_log(doc, op="RESTORE",
                             entry_id=str(target.get("id") or ""),
                             reason="user_request", ts=current)
            return {"handled": True, "op": "RESTORE", "entry": target}
        return {"handled": True, "op": "NOOP", "reason": "no_restore_target"}
    if detect_rollback_request(text):
        target = rollback_candidate(entries)
        if target is not None and rollback_entry(target):
            target["rollback_ts"] = current
            append_write_log(doc, op="ROLLBACK",
                             entry_id=str(target.get("id") or ""),
                             reason="user_request", ts=current)
            return {"handled": True, "op": "ROLLBACK", "entry": target}
        return {"handled": True, "op": "NOOP", "reason": "no_rollback_target"}
    request = detect_delete_request(text)
    if request is None:
        return {"handled": False}
    target_text = str(request.get("target") or "")
    if request.get("vague"):
        return {"handled": True, "op": "NOOP", "reason": "vague_target"}
    matches = deletion_candidates(entries, target_text)
    if not matches:
        return {"handled": True, "op": "NOOP", "reason": "no_match",
                "target": target_text}
    strong = [item for item in matches if item[0] >= DELETE_STRONG_MATCH]
    if len(strong) == 1:
        chosen_ids = [str(strong[0][1].get("id") or "")]
    elif len(matches) == 1:
        chosen_ids = [str(matches[0][1].get("id") or "")]
    else:
        return {"handled": True, "op": "NOOP", "reason": "ambiguous",
                "target": target_text,
                "candidates": [str(item[1].get("id") or "")
                               for item in matches[:PENDING_DELETE_MAX_CANDIDATES]]}
    chosen_ids = [x for x in chosen_ids if x]
    if not chosen_ids:
        return {"handled": True, "op": "NOOP", "reason": "no_match",
                "target": target_text}
    if request.get("confirmed"):
        target = next((e for e in entries if isinstance(e, dict)
                       and str(e.get("id") or "") == chosen_ids[0]
                       and not e.get("deleted")), None)
        if target is not None and soft_delete_entry(target, current, reason="explicit_confirm"):
            append_write_log(doc, op="DELETE", entry_id=chosen_ids[0],
                             reason="explicit_confirm", ts=current)
            return {"handled": True, "op": "DELETE", "entry": target,
                    "reason": "explicit_confirm", "target": target_text}
        return {"handled": True, "op": "NOOP", "reason": "pending_target_missing"}
    doc["pending_delete"] = {"target": target_text, "ids": chosen_ids,
                             "created_ts": current, "source": "natural_language"}
    return {"handled": True, "op": "PENDING", "target": target_text,
            "ids": chosen_ids}


# ---------------------------------------------------------------------------
# Prospective memory / open loops (deterministic extraction + resolution)
# ---------------------------------------------------------------------------
OPEN_LOOP_MAX = 20
OPEN_LOOP_MERGE_SIMILARITY = 0.6
_OPEN_LOOP_DIRECT_CUES = ("记得", "答应", "别忘了", "到时候", "一定要", "帮我", "还没")
_OPEN_LOOP_FUTURE_CUES = ("明天", "后天", "下周", "待会", "晚点", "等会", "回头", "下次")
_OPEN_LOOP_VERBS = ("要", "得", "去", "交", "做", "给", "见", "开", "来", "陪", "还")
_OPEN_LOOP_NOISE = ("不要记得", "不用记得", "别记得", "不记得", "没记得",
                     "不用了", "取消了", "不去了", "算了")
_COMPLETION_CUES = ("做完了", "完成了", "搞定了", "弄好了", "交了", "解决了",
                    "处理完了", "结束了", "已经做了", "已经完成", "办好了")
_CANCEL_CUES = ("不用了", "取消了", "不去了", "算了", "不用去", "取消")
_OPEN_LOOP_DUE_HINTS = (
    ("soon", ("现在", "马上", "待会", "晚点", "等会", "今天")),
    ("tomorrow", ("明天",)),
    ("later", ("后天", "下周", "下次", "之后", "回头", "周末")),
)


def _has_open_loop_cue(text: str) -> bool:
    if any(cue in text for cue in _OPEN_LOOP_DIRECT_CUES):
        return True
    for marker in _OPEN_LOOP_FUTURE_CUES:
        index = text.find(marker)
        while index >= 0:
            tail = text[index + len(marker):index + len(marker) + 6]
            if any(verb in tail for verb in _OPEN_LOOP_VERBS):
                return True
            index = text.find(marker, index + 1)
    return False


def _open_loop_segment(text: str) -> str:
    for part in re.split(r"[。！？!?；;\n]+", str(text or "")):
        segment = part.strip()
        if segment and _has_open_loop_cue(segment):
            return segment[:120]
    return ""


def _open_loop_due(text: str) -> str:
    for hint, markers in _OPEN_LOOP_DUE_HINTS:
        if any(marker in text for marker in markers):
            return hint
    return "none"


def _hash10(value: str) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:10]


def detect_open_loops(text: Any, now: float | None = None) -> list[dict[str, Any]]:
    """Extract at most one prospective-memory loop from one user message.

    Deterministic cue words only (remember/agree/remind/next-time + future
    marker with an action verb); no LLM rewriting. Questions and negated
    reminders are ignored.
    """
    raw = str(text or "").strip()
    if len(raw) < 4 or len(raw) > 240:
        return []
    if any(noise in raw for noise in _OPEN_LOOP_NOISE):
        return []
    if ("?" in raw or "？" in raw) and "记得" not in raw:
        return []
    if not _has_open_loop_cue(raw):
        return []
    segment = _open_loop_segment(raw)
    if not segment:
        return []
    try:
        stamp = round(float(now if now is not None else time.time()), 3)
    except Exception:
        stamp = round(time.time(), 3)
    return [{
        "id": "loop_" + _hash10(segment),
        "text": segment,
        "due_hint": _open_loop_due(raw),
        "status": "open",
        "created_ts": stamp,
        "last_mentioned_ts": stamp,
        "mentioned": 1,
    }]


def resolve_open_loops(loops: Any, text: Any, now: float | None = None) -> int:
    """Resolve/expire open loops from later conversation (bounded policy)."""
    if not isinstance(loops, list):
        return 0
    raw = str(text or "")
    try:
        current = float(now if now is not None else time.time())
    except Exception:
        current = time.time()
    changed = 0
    for loop in loops:
        if not isinstance(loop, dict) or str(loop.get("status") or "open") != "open":
            continue
        loop_text = str(loop.get("text") or "")
        shared = _bigrams(loop_text) & _bigrams(raw)
        matched = bool(loop_text and loop_text in raw) or len(shared) >= 1
        if matched and any(cue in raw for cue in _COMPLETION_CUES):
            loop["status"] = "fulfilled"
            loop["resolved_ts"] = round(current, 3)
            changed += 1
            continue
        if matched and any(cue in raw for cue in _CANCEL_CUES):
            loop["status"] = "canceled"
            loop["resolved_ts"] = round(current, 3)
            changed += 1
            continue
        created = loop.get("created_ts")
        try:
            created_ts = float(created) if created is not None else current
        except Exception:
            created_ts = current
        age_days = max(0.0, (current - created_ts) / 86400.0)
        window = {"soon": 1.0, "tomorrow": 2.0}.get(str(loop.get("due_hint") or ""), 7.0)
        if age_days > window:
            loop["status"] = "expired"
            loop["resolved_ts"] = round(current, 3)
            changed += 1
    return changed
