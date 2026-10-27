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
    "ROLE_TYPES",
    "build_social_world",
    "attachment_profile",
    "refusal_protocol",
    "milestone_from_text",
    "merge_milestones",
    "commitment_investment",
    "WE_MEMORY_TYPES",
    "validate_we_memory",
    "merge_we_memory",
    "merge_annotations",
    "apply_relationship_impression",
    "apply_tom_update",
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
ROLE_TYPES = ("家人", "朋友", "同事", "伴侣", "宠物", "其他")
MAX_SOCIAL_WORLD = 20
MAX_MILESTONES = 10
WE_MEMORY_TYPES = ("nickname", "ritual", "anniversary", "inside_joke", "shared_object")
MAX_WE_MEMORY = 20
WE_MEMORY_MIN_CONFIDENCE = 0.55
MAX_ANNOTATIONS = 10
MAX_BELIEF_ITEMS = 3
IMPRESSION_MIN_CONFIDENCE = 0.55
TOM_MIN_CONFIDENCE = 0.50

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
    """EWMA/Brier calibration record per evidence source; record-only, no trust writeback.

    Runtime call site: BioCorePlugin._record_calibration (memory-conflict branch,
    main.py); the record is persisted in the user doc relationship.calibration.
    """
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



_ROLE_HINTS = (
    ("妈妈", "家人"), ("妈", "家人"), ("爸爸", "家人"), ("爸", "家人"),
    ("朋友", "朋友"), ("同事", "同事"), ("伴侣", "伴侣"),
    ("老公", "伴侣"), ("老婆", "伴侣"), ("对象", "伴侣"),
    ("猫", "宠物"), ("狗", "宠物"),
)
_SENSITIVE_SKIP = ("工资", "密码", "身份证", "银行卡", "病历", "病", "手机号")


def build_social_world(entries: Any) -> list[dict[str, Any]]:
    """Deterministic bounded people index from explicit role words; no inference."""
    out = []
    seen = set()
    for entry in (entries if isinstance(entries, list) else [])[-200:]:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "")
        if not text or any(word in text for word in _SENSITIVE_SKIP):
            continue
        for hint, role in _ROLE_HINTS:
            idx = text.find(hint)
            while idx >= 0:
                tail = text[idx + len(hint): idx + len(hint) + 6]
                name = tail[:4].strip("，。！？、,.!? 的")
                if not name or name.startswith(("说", "在", "和", "跟", "是", "很", "又")):
                    name = hint
                key = (role, name)
                if key not in seen:
                    seen.add(key)
                    out.append({"name": name[:20], "role": role,
                                "evidence": [{"ts": _num(entry.get("ts"), 0.0),
                                              "text": text[:40]}]})
                idx = text.find(hint, idx + len(hint))
            if len(out) >= MAX_SOCIAL_WORLD:
                return out[:MAX_SOCIAL_WORLD]
    return out[:MAX_SOCIAL_WORLD]


def attachment_profile(trajectory: Any) -> dict[str, float]:
    """Deterministic 0..1 attachment-style proxies from trajectory; not clinical."""
    points = [x for x in (trajectory if isinstance(trajectory, list) else [])[-80:]
              if isinstance(x, dict)]
    if len(points) < 2:
        return {"safe": 0.5, "anxious": 0.25, "avoidant": 0.25}
    trusts = [_clamp(x.get("trust", 0.5)) for x in points]
    closes = [_clamp(x.get("closeness", 0.5)) for x in points]
    conflicts = [_clamp(x.get("conflict", 0.5)) for x in points]
    repairs = [_clamp(x.get("repair", 0.0)) for x in points]
    mean_trust = sum(trusts) / len(trusts)
    mean_close = sum(closes) / len(closes)
    mean_conf = sum(conflicts) / len(conflicts)
    mean_rep = sum(repairs) / len(repairs)
    mean_trust2 = sum(x * x for x in trusts) / len(trusts)
    variance = max(0.0, mean_trust2 - mean_trust * mean_trust)
    safe = _clamp(0.25 + mean_trust * 0.35 + mean_rep * 0.25 + mean_close * 0.25 - variance * 0.5)
    anxious = _clamp(0.15 + variance * 1.5 + mean_conf * 0.35 + (1.0 - mean_rep) * 0.15)
    avoidant = _clamp(0.15 + (1.0 - mean_close) * 0.35 + max(0.0, mean_conf - 0.3) * 0.25)
    total = safe + anxious + avoidant
    if total <= 0:
        return {"safe": 0.34, "anxious": 0.33, "avoidant": 0.33}
    return {"safe": round(safe / total, 4), "anxious": round(anxious / total, 4),
            "avoidant": round(avoidant / total, 4)}


def refusal_protocol(state: Any) -> dict[str, Any]:
    """Coarse refusal mode from boundary pressure; behavior strategy stays elsewhere.

    Wired (G2/L9, 2026-10-26): BioCorePlugin._deterministic_hint calls this and
    renders a bounded refuse=negotiate|decline token (<=140 chars, no LLM); it
    is a posture token, not a gate that decides whether to reply.
    """
    d = state if isinstance(state, dict) else {}
    pressure = _clamp(d.get("boundary_pressure", 0.0))
    trust = _clamp(d.get("trust", 0.5))
    conflict = _clamp(d.get("conflict", 0.0))
    if pressure >= 0.65 and (trust < 0.55 or conflict >= 0.4):
        return {"mode": "decline", "reason_code": "boundary_pressure_high"}
    if pressure >= 0.35:
        return {"mode": "negotiate", "reason_code": "boundary_pressure"}
    return {"mode": "comply", "reason_code": "normal"}


def milestone_from_text(text: Any) -> dict[str, Any]:
    t = str(text or "")
    if any(x in t for x in ("第一次", "初次")):
        mtype = "first_meet"
    elif any(x in t for x in ("周年", "纪念日", "一年前")):
        mtype = "anniversary"
    elif any(x in t for x in ("答应", "承诺", "说好")) and any(x in t for x in ("做到", "兑现", "守约")):
        mtype = "promise_kept"
    elif any(x in t for x in ("和好", "修复", "道歉", "原谅")):
        mtype = "repair_success"
    else:
        return {}
    key = t.strip()[:80]
    return {"type": mtype, "key": key, "ts": 0.0}


def merge_milestones(existing: Any, additions: Any) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for item in list(existing if isinstance(existing, list) else []) + list(additions if isinstance(additions, list) else []):
        if not isinstance(item, dict):
            continue
        mtype = str(item.get("type") or "")
        key = str(item.get("key") or "")[:80]
        if not mtype or not key or (mtype, key) in seen:
            continue
        seen.add((mtype, key))
        out.append({"type": mtype, "key": key, "ts": _num(item.get("ts"), 0.0)})
    return out[-MAX_MILESTONES:]



def commitment_investment(
    state: Any,
    trajectory: Any,
    interactions: Any = 0,
    repair_success: Any = 0,
    promises_kept: Any = 0,
) -> dict[str, float]:
    """Bounded deterministic commitment/investment proxies (no behavior change)."""
    try:
        n_inter = max(0, int(float(interactions or 0)))
    except Exception:
        n_inter = 0
    traj = [x for x in (trajectory if isinstance(trajectory, list) else [])[-80:]
            if isinstance(x, dict)]
    n_traj = len(traj)
    if n_inter <= 0 and n_traj <= 0:
        return {"commitment": 0.0, "investment": 0.0}
    try:
        n_repair = max(0, min(10, int(float(repair_success or 0))))
    except Exception:
        n_repair = 0
    try:
        n_promise = max(0, min(10, int(float(promises_kept or 0))))
    except Exception:
        n_promise = 0
    traj_term = min(1.0, n_traj / 40.0)
    inter_term = min(1.0, n_inter / 120.0)
    repair_term = min(1.0, n_repair / 3.0)
    promise_term = min(1.0, n_promise / 5.0)
    commitment = _clamp(0.10 + 0.30 * traj_term + 0.25 * inter_term
                        + 0.20 * repair_term + 0.15 * promise_term)
    investment = _clamp(0.08 + 0.35 * traj_term + 0.30 * inter_term
                        + 0.12 * repair_term + 0.15 * promise_term)
    return {"commitment": round(commitment, 4), "investment": round(investment, 4)}


def validate_we_memory(proposal: Any) -> dict[str, Any] | None:
    """Validate one we-memory candidate; evidence-gated and bounded (no LLM)."""
    if not isinstance(proposal, dict):
        return None
    mtype = str(proposal.get("type") or "").strip()
    if mtype not in WE_MEMORY_TYPES:
        return None
    raw_text = " ".join(str(proposal.get("text") or "").split()).strip()
    if not raw_text or len(raw_text) > 40:
        return None
    text = raw_text[:40]
    refs = proposal.get("evidence_refs")
    if not isinstance(refs, list) or not [str(x) for x in refs if str(x)]:
        return None
    try:
        conf = _clamp(_num(proposal.get("confidence"), 0.0))
    except Exception:
        return None
    if conf < WE_MEMORY_MIN_CONFIDENCE:
        return None
    return {
        "type": mtype,
        "text": text,
        "evidence_refs": [str(x)[:80] for x in refs[:5] if str(x)],
        "confidence": round(conf, 3),
    }


def merge_we_memory(existing: Any, proposals: Any) -> list[dict[str, Any]]:
    """Merge validated we-memory items, dedupe by type+text, cap 20."""
    out = []
    seen = set()
    items = list(existing if isinstance(existing, list) else []) + list(proposals if isinstance(proposals, list) else [])
    for item in items:
        valid = validate_we_memory(item)
        if not valid:
            continue
        key = (valid["type"], valid["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(valid)
    return out[-MAX_WE_MEMORY:]




def _bounded_text(value: Any, limit: int = 80) -> str:
    return " ".join(str(value or "").split()).strip()[:max(1, int(limit))]


def merge_annotations(existing: Any, additions: Any, *,
                      limit: int = MAX_ANNOTATIONS) -> list[dict[str, Any]]:
    """Bounded relationship annotations (traits/relation events); no state writes."""
    out: list[dict[str, Any]] = []
    seen = set()
    items = list(existing if isinstance(existing, list) else [])
    items += list(additions if isinstance(additions, list) else [])
    for item in items:
        if isinstance(item, dict):
            text = _bounded_text(item.get("text"), 80)
            kind = _bounded_text(item.get("kind"), 20) or "annotation"
            try:
                confidence = round(_clamp(item.get("confidence", 0.55)), 3)
            except Exception:
                confidence = 0.55
            refs = [str(x)[:80] for x in (item.get("evidence_refs") or []) if str(x)][:6]
            ts = _num(item.get("ts"), 0.0)
        else:
            text = _bounded_text(item, 80)
            kind = "annotation"
            confidence = 0.55
            refs = []
            ts = 0.0
        if not text:
            continue
        key = (kind, text)
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "text": text, "confidence": confidence,
                    "evidence_refs": refs, "ts": round(ts, 3)})
    return out[-max(1, int(limit)):]


def apply_relationship_impression(record: Any, proposal: Any, *,
                                  allowed_refs: Any = None) -> dict[str, Any]:
    """Validate an LLM relationship-impression proposal; returns a record.

    The LLM never writes trust/goals/state here: only bounded annotations and
    evidence-gated we-memory candidates are merged into the relationship record.
    """
    base = dict(record) if isinstance(record, dict) else {}
    if not isinstance(proposal, dict):
        return base
    try:
        confidence = _clamp(proposal.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    if confidence < IMPRESSION_MIN_CONFIDENCE:
        return base
    refs_raw = proposal.get("evidence_refs")
    refs = [str(x)[:80] for x in (refs_raw if isinstance(refs_raw, list) else []) if str(x)][:8]
    if isinstance(allowed_refs, (list, tuple, set)):
        allowed = {str(x) for x in allowed_refs}
        refs = [r for r in refs if r in allowed]
    if not refs:
        return base
    additions: list[dict[str, Any]] = []
    for text in (proposal.get("traits") or [])[:3]:
        item = _bounded_text(text, 60)
        if item:
            additions.append({"kind": "trait", "text": item,
                              "confidence": round(confidence, 3),
                              "evidence_refs": refs[:6], "ts": 0.0})
    for text in (proposal.get("relation_events") or [])[:2]:
        item = _bounded_text(text, 80)
        if item:
            additions.append({"kind": "relation_event", "text": item,
                              "confidence": round(confidence, 3),
                              "evidence_refs": refs[:6], "ts": 0.0})
    base["annotations"] = merge_annotations(base.get("annotations"), additions)
    candidates = []
    for item in (proposal.get("we_memory_candidates") or [])[:2]:
        valid = validate_we_memory({**_valid_candidate(item), "evidence_refs": refs[:3]})
        if valid:
            candidates.append(valid)
    if candidates:
        base["we_memory"] = merge_we_memory(base.get("we_memory"), candidates)
    return base


def _valid_candidate(item: Any) -> dict[str, Any]:
    """Copy only the schema keys a we-memory proposal may set (no evidence here)."""
    data = item if isinstance(item, dict) else {}
    return {"type": str(data.get("type") or "").strip(),
            "text": _bounded_text(data.get("text"), 40),
            "confidence": _num(data.get("confidence"), 0.0),
            "evidence_refs": []}


def apply_tom_update(user_data: Any, proposal: Any, *,
                     allowed_refs: Any = None) -> dict[str, Any]:
    """Validate a bounded ToM proposal and store it in the user record.

    Never touches biological core state or trust; beliefs/desires/intentions are
    capped, evidence-gated annotations used only by the interpretation layer.
    """
    data = dict(user_data) if isinstance(user_data, dict) else {}
    if not isinstance(proposal, dict):
        return data
    try:
        confidence = _clamp(proposal.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    if confidence < TOM_MIN_CONFIDENCE:
        return data
    refs = [str(x)[:80] for x in (proposal.get("evidence_refs") or []) if str(x)][:8]
    if isinstance(allowed_refs, (list, tuple, set)):
        allowed = {str(x) for x in allowed_refs}
        refs = [r for r in refs if r in allowed]
    if not refs:
        return data
    previous = data.get("belief_state") if isinstance(data.get("belief_state"), dict) else {}
    merged = {}
    for key in ("beliefs", "desires", "intentions"):
        old = [str(x)[:60] for x in (previous.get(key) or []) if str(x)][-MAX_BELIEF_ITEMS:]
        new = [_bounded_text(x, 60) for x in (proposal.get(key) or [])[:MAX_BELIEF_ITEMS]]
        values = []
        for item in old + new:
            if item and item not in values:
                values.append(item)
        merged[key] = values[-MAX_BELIEF_ITEMS:]
    data["belief_state"] = {
        "beliefs": merged["beliefs"],
        "desires": merged["desires"],
        "intentions": merged["intentions"],
        "confidence": round(confidence, 3),
        "evidence_refs": refs,
        "ts": _num(proposal.get("ts"), 0.0),
    }
    return data


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
    social_world: Any = None,
    milestones: Any = None,
    we_memory: Any = None,
    interactions: Any = None,
    repair_success: Any = None,
    promises_kept: Any = None,
    annotations: Any = None,
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
    world = social_world if isinstance(social_world, list) else prev.get("social_world", [])
    attachment = attachment_profile(trajectory)
    marks = merge_milestones(prev.get("milestones"), milestones)
    we_items = merge_we_memory(prev.get("we_memory"), we_memory) if isinstance(we_memory, list) else (
        prev.get("we_memory") if isinstance(prev.get("we_memory"), list) else [])
    _inter = interactions if interactions is not None else prev.get("interactions", len(trajectory))
    _repair = repair_success if repair_success is not None else len([x for x in trajectory if float(x.get("repair", 0) or 0) >= 0.05])
    _promises = promises_kept if promises_kept is not None else len([x for x in marks if x.get("type") == "promise_kept"])
    commitment = commitment_investment(state, trajectory, _inter, _repair, _promises)
    notes = (merge_annotations(prev.get("annotations"), annotations)
             if isinstance(annotations, list)
             else merge_annotations(prev.get("annotations"), []))
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
        "social_world": [dict(x) for x in world[:MAX_SOCIAL_WORLD] if isinstance(x, dict)],
        "attachment": attachment,
        "milestones": marks,
        "we_memory": [dict(x) for x in we_items[:MAX_WE_MEMORY] if isinstance(x, dict)],
        "commitment": commitment["commitment"],
        "investment": commitment["investment"],
        "annotations": notes,
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


# ---------------------------------------------------------------------------
# task-55 relationship chain (deterministic, default OFF; caller-gated).
# ---------------------------------------------------------------------------
def attachment_dynamics(trust=0.5, conflict=0.5, closeness=0.5) -> dict:
    """anxiety=.5(1-trust)+.5*conflict; avoid=1-closeness; repair_speed."""
    t = max(0.0, min(1.0, float(trust)))
    c = max(0.0, min(1.0, float(conflict)))
    cl = max(0.0, min(1.0, float(closeness)))
    anxiety = max(0.0, min(1.0, 0.5 * (1.0 - t) + 0.5 * c))
    avoid = max(0.0, min(1.0, 1.0 - cl))
    repair_speed = max(0.5, min(1.0, 1.0 - 0.3 * anxiety - 0.2 * avoid))
    return {"anxiety": round(anxiety, 4), "avoid": round(avoid, 4),
            "repair_speed": round(repair_speed, 4)}


def closeness_step(disclosure=0.0, response=0.0, overreach=0.0,
                   k1=1.0, k3=1.0) -> float:
    """d_closeness = clamp(k1*disclosure*response - k3*overreach, -0.02, 0.03)."""
    try:
        d = float(disclosure) * float(response)
        o = float(overreach)
        k1v = float(k1)
        k3v = float(k3)
    except Exception:
        return 0.0
    return round(max(-0.02, min(0.03, k1v * d - k3v * o)), 4)


GOTTMAN_FOUR_HORSEMEN = {
    "criticism": ("你总是", "你从来不", "你每次都", "你根本就不"),
    "contempt": ("废物", "没用", "可笑", "恶心", "你算什么东西", "不配"),
    "defensiveness": ("不是我的错", "都是你", "你怎么不说", "关我什么事"),
    "stonewalling": ("随便你", "不想说", "无所谓", "别烦我", "沉默"),
}


def gottman_hits(text) -> dict:
    value = str(text or "")
    hits = {}
    for name, words in GOTTMAN_FOUR_HORSEMEN.items():
        found = [w for w in words if w in value]
        if found:
            hits[name] = found[:3]
    return hits


def gottman_conflict_step(text) -> tuple:
    """conflict_step = min(0.15, 0.05*hits) — bounded, never deletes."""
    hits = gottman_hits(text)
    n = sum(len(v) for v in hits.values())
    return hits, round(min(0.15, 0.05 * n), 4)


REPAIR_ACTS = ("对不起", "我错了", "抱歉", "我理解", "你说得对", "我们聊聊",
               "别生气", "我改", "补偿", "重新来")


def repair_step(text, repair_speed=1.0) -> tuple:
    """repair_step = min(0.10, 0.05*acts) * repair_speed (bounded)."""
    value = str(text or "")
    acts = [w for w in REPAIR_ACTS if w in value]
    try:
        speed = max(0.0, min(1.0, float(repair_speed)))
    except Exception:
        speed = 1.0
    return acts, round(min(0.10, 0.05 * len(acts)) * speed, 4)
