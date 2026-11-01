# -*- coding: utf-8 -*-
"""Three-layer memory projection for the reply prompt (no LLM, no IO).

Layers:
  resident  - durable facts about the user (nickname / preferences / profile),
              injected on every turn regardless of the query;
  retrieval - event memories, injected on demand and capped by
              retrieval_limit (default 2, configurable);
  archive   - the raw store; only counted here, never injected.

Classification is keyword based and ordering is deterministic, so the same
store yields the same prompt block across days; nothing is parsed back.
"""
from __future__ import annotations

import difflib

RESIDENT_LIMIT = 5
RETRIEVAL_LIMIT = 2
HARD_RESIDENT_LIMIT = 8
HARD_RETRIEVAL_LIMIT = 5
MAX_CHARS = 420
FACT_TRIM = 60
EVENT_TRIM = 50

# item-1: no keyword tables. Resident = explicit tag / kind / pin only; facts
# about the user come from the probe's optional "fact" field.
RESIDENT_TAGS = {"resident", "fact", "profile"}
RESIDENT_KINDS = {"resident", "fact", "profile"}
ARCHIVE_ROLES = ("summary",)
FACT_MAX_CHARS = 20
FACT_MIN_CONFIDENCE = 0.5
FACT_DUP_RATIO = 0.85


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _clamp_limit(value, default, hard_max):
    try:
        number = int(value)
    except Exception:
        number = int(default)
    if number < 0:
        return 0
    return min(number, int(hard_max))


def _text_of(entry):
    if not isinstance(entry, dict):
        return ""
    for key in ("text", "content", "memory"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _norm(text):
    return "".join(ch for ch in str(text or "").lower() if not ch.isspace()
                   and ch not in "，,。.！!？?、;；:：~")


def _entry_tags(entry):
    tags = entry.get("tags") if isinstance(entry, dict) else None
    if isinstance(tags, str):
        return {tags.strip().lower()} - {""}
    if isinstance(tags, (list, tuple, set)):
        return {str(tag).strip().lower() for tag in tags if str(tag).strip()}
    return set()


def _entry_kind(entry):
    for key in ("memory_layer", "layer", "kind", "type", "category"):
        value = entry.get(key) if isinstance(entry, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _is_valid(entry):
    if not isinstance(entry, dict):
        return False
    if entry.get("deleted") or entry.get("summarized"):
        return False
    role = str(entry.get("role") or "").strip().lower()
    if role in ARCHIVE_ROLES:
        return False
    return bool(_text_of(entry))


def classify(entry):
    """Return "resident", "retrieval", or "" for an unusable entry."""
    if not _is_valid(entry):
        return ""
    kind = _entry_kind(entry)
    if kind in RESIDENT_KINDS or _entry_tags(entry) & RESIDENT_TAGS:
        return "resident"
    if entry.get("pin") or entry.get("pinned"):
        return "resident"
    return "retrieval"


def _row(entry):
    return {"id": str(entry.get("id") or ""),
            "text": _text_of(entry),
            "ts": _num(entry.get("ts")),
            "importance": _num(entry.get("importance", 0.5), 0.5),
            "pin": bool(entry.get("pin") or entry.get("pinned"))}


def _resident_key(row):
    return (1 if row["pin"] else 0, row["importance"], row["ts"])


def _retrieval_key(row):
    return (row["importance"], row["ts"])


def select(entries, recalled_ids=None, resident_limit=RESIDENT_LIMIT,
           retrieval_limit=RETRIEVAL_LIMIT, now=None):
    """Split usable entries into resident / retrieval rows with hard caps.

    Returns a dict with ``resident``, ``retrieval``, ``archive_count`` and the
    clamped limits. ``now`` is accepted for signature stability; layer
    selection never decays resident facts. ``recalled_ids`` fixes the
    retrieval order (best first) and wins over the deterministic fallback.
    """
    del now  # resident/retrieval selection is deliberately time-independent
    resident_cap = _clamp_limit(resident_limit, RESIDENT_LIMIT, HARD_RESIDENT_LIMIT)
    retrieval_cap = _clamp_limit(retrieval_limit, RETRIEVAL_LIMIT, HARD_RETRIEVAL_LIMIT)
    rows = []
    if isinstance(entries, (list, tuple)):
        for entry in list(entries):
            if not _is_valid(entry):
                continue
            rows.append((classify(entry), _row(entry)))
    archive_count = len(rows)
    resident_rows = [row for layer, row in rows if layer == "resident"]
    resident_rows.sort(key=_resident_key, reverse=True)
    resident_out = []
    seen_texts = set()
    seen_ids = set()
    for row in resident_rows:
        norm = _norm(row["text"])
        if not norm or norm in seen_texts:
            continue
        seen_texts.add(norm)
        if row["id"]:
            seen_ids.add(row["id"])
        resident_out.append(row)
        if len(resident_out) >= resident_cap:
            break
    retrieval_rows = [row for layer, row in rows if layer == "retrieval"]
    by_id = {row["id"]: row for _layer, row in rows if row["id"]}
    ordered = []
    ordered_ids = set()
    if isinstance(recalled_ids, (list, tuple)):
        for rid in list(recalled_ids):
            rid = str(rid or "")
            row = by_id.get(rid)
            if row is None or rid in ordered_ids:
                continue
            if rid in seen_ids or _norm(row["text"]) in seen_texts:
                continue
            ordered_ids.add(rid)
            ordered.append(row)
    fallback = [row for row in retrieval_rows
                if not row["id"] or row["id"] not in ordered_ids]
    fallback.sort(key=_retrieval_key, reverse=True)
    for row in fallback:
        if len(ordered) >= retrieval_cap:
            break
        norm = _norm(row["text"])
        if not norm or norm in seen_texts:
            continue
        seen_texts.add(norm)
        ordered.append(row)
    return {"resident": resident_out,
            "retrieval": ordered[:retrieval_cap],
            "archive_count": archive_count,
            "resident_limit": resident_cap,
            "retrieval_limit": retrieval_cap}


def _trim(text, limit):
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def _age_label(ts, now):
    try:
        now_ts = float(now)
        ts = float(ts)
    except Exception:
        return ""
    if now_ts <= 0 or ts <= 0:
        return ""
    days = max(0.0, (now_ts - ts) / 86400.0)
    if days < 1.0:
        return "今天："
    if days < 2.0:
        return "昨天："
    return "%.0f 天前：" % days


def render(entries, recalled_ids=None, resident_limit=RESIDENT_LIMIT,
           retrieval_limit=RETRIEVAL_LIMIT, now=None) -> str:
    """Render the layered memory prompt block, or "" when nothing is usable.

    Resident lines come first and are emitted on every turn; the retrieval
    section holds at most ``retrieval_limit`` events (0 disables it). The
    archive layer is never injected, it is only counted in select().
    """
    picked = select(entries, recalled_ids=recalled_ids,
                    resident_limit=resident_limit,
                    retrieval_limit=retrieval_limit, now=now)
    lines = []
    if picked["resident"]:
        lines.append("[分层记忆]")
        lines.append("常驻事实：")
        for row in picked["resident"]:
            lines.append("- " + _trim(row["text"], FACT_TRIM))
    if picked["retrieval"]:
        if not lines:
            lines.append("[分层记忆]")
        lines.append("相关事件：")
        for row in picked["retrieval"]:
            lines.append("- " + _age_label(row["ts"], now)
                         + _trim(row["text"], EVENT_TRIM))
    text = "\n".join(lines).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip()
    return text


def _fact_norm(text):
    return _norm(text)


def _similarity(left, right):
    left, right = _fact_norm(left), _fact_norm(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) >= 4 and len(right) >= 4 and (left in right or right in left):
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def fact_entry(fact, confidence=1.0):
    """Probe "fact" -> resident memory payload, or None when unusable."""
    text = " ".join(str(fact or "").split()).strip()
    if not text:
        return None
    try:
        if float(confidence) < FACT_MIN_CONFIDENCE:
            return None
    except Exception:
        return None
    if len(text) > FACT_MAX_CHARS:
        text = text[:FACT_MAX_CHARS]
    return {"text": text, "tags": ["resident"],
            "memory_source": "probe_fact", "importance": 0.7}


def duplicate_resident(text, entries, threshold=FACT_DUP_RATIO):
    """True when *text* is >= threshold similar to an existing resident entry."""
    if not str(text or "").strip():
        return False
    rows = entries if isinstance(entries, (list, tuple)) else []
    for entry in rows:
        if classify(entry) != "resident":
            continue
        if _similarity(text, _text_of(entry)) >= float(threshold):
            return True
    return False


def should_write_fact(fact, confidence, entries=None, written_keys=None,
                      message_key=""):
    """Gate a probe fact: valid, once per message, not a resident duplicate."""
    candidate = fact_entry(fact, confidence)
    if candidate is None:
        return False
    key = str(message_key or "")
    if key and isinstance(written_keys, dict) and key in written_keys:
        return False
    return not duplicate_resident(candidate["text"], entries)

