# -*- coding: utf-8 -*-
"""Deterministic remember-side dedupe (L0 exact / L1 near / L2 fact / L3 structural).

Host-neutral: stdlib + core + index/entities only; no astrbot, no prompt, no LLM.
Public API:
    normalize(text) -> str                       # punctuation/space/case-insensitive hash
    dedupe(entry, entries, embedder=None) -> (action, target_id|None, reason)
where action is one of "merge" / "flag" / "update" / "keep".
Failure of any optional layer degrades to ("keep", None, "fallback").
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata

from ..core.util import clamp01
from ..index.entities import cues

L1_MERGE = 0.90
L1_FLAG = 0.75
L3_WINDOW_SECONDS = 60.0

_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)
_PREDICATES = ("生日", "住在", "工作", "上学", "喜欢", "讨厌", "爱吃", "害怕",
               "养了", "叫", "是", "有", "去", "在", "买了", "看了")


def normalize(text) -> str:
    """Normalize text and return a short stable hash (L0 exact key)."""
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    value = _PUNCT.sub("", value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def cosine(a, b) -> float:
    """Cosine similarity for two numeric vectors (0.0 when unusable)."""
    try:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        na = math.sqrt(sum(float(x) ** 2 for x in a))
        nb = math.sqrt(sum(float(y) ** 2 for y in b))
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def _meta(entry):
    return entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}


def _field(entry, key, default=None):
    if key in entry:
        return entry.get(key)
    return _meta(entry).get(key, default)


def _entry_vector(entry, embedder):
    """Entry vector first; otherwise ask the optional embedder (sync only)."""
    try:
        vec = entry.get("vector")
        if isinstance(vec, (list, tuple)) and vec:
            return list(vec)
        if embedder is None:
            return None
        fn = getattr(embedder, "embed_text", None) or getattr(embedder, "embed", None)
        if not fn:
            return None
        value = fn(str(entry.get("text") or ""))
        if hasattr(value, "__await__"):
            return None  # sync dedupe never drives async embedders
        return list(value) if isinstance(value, (list, tuple)) and value else None
    except Exception:
        return None


def extract_fact(text):
    """Extract (main_entity, predicate, value) slots from text; None if unclear.

    Uses the deterministic index/entities cue rules for the subject and a fixed
    predicate list for the relation. Values are punctuation-normalized.
    """
    try:
        raw = str(text or "")
        c = cues(raw)
        entities = [e for e in (c.get("entities") or []) if len(e) >= 1]
        if not entities:
            return None
        main_entity = entities[0]
        predicate, value = "", ""
        for p in _PREDICATES:
            pos = raw.find(p)
            if pos < 0:
                continue
            tail = raw[pos + len(p):].strip(" 了过是在的，。,.!?！？；;：:、")
            tail = re.sub(r"[\s\W_]+", "", tail, flags=re.UNICODE)[:24]
            if tail:
                predicate, value = p, tail
                break
        if not predicate or not value:
            return None
        return (main_entity[:32], predicate, value)
    except Exception:
        return None


def _structural_key(entry):
    event_key = str(_field(entry, "event_key") or "").strip()
    source = str(_field(entry, "source") or _field(entry, "memory_source")
                 or _field(entry, "module") or "").strip()
    try:
        ts = float(entry.get("ts", 0) or 0.0)
    except Exception:
        ts = 0.0
    return event_key, source, ts


def dedupe(entry, entries, embedder=None):
    """Unified remember-side dedupe.

    Returns (action, target_id|None, reason). Never raises.
    """
    try:
        if not isinstance(entry, dict):
            return "keep", None, "invalid_entry"
        text = str(entry.get("text") or "").strip()
        if len(text) < 2:
            return "keep", None, "empty_text"
        candidates = [e for e in (entries or [])
                      if isinstance(e, dict) and not e.get("deleted")
                      and str(e.get("id") or "") != str(entry.get("id") or "")]
        if not candidates:
            return "keep", None, "no_candidates"

        # L0 exact normalized hash.
        h = normalize(text)
        for old in candidates:
            if normalize(old.get("text")) == h:
                return "merge", str(old.get("id") or ""), "exact_hash"

        # L1 near-duplicate (optional embedder). Higher score wins.
        best_id, best_score = None, 0.0
        if embedder is not None:
            new_vec = _entry_vector(entry, embedder)
            if new_vec:
                for old in candidates:
                    vec = _entry_vector(old, embedder)
                    if not vec:
                        continue
                    score = cosine(new_vec, vec)
                    if score > best_score:
                        best_id, best_score = str(old.get("id") or ""), score
        if best_id and best_score >= L1_MERGE:
            return "merge", best_id, "near_dup:%.3f" % best_score
        if best_id and L1_FLAG <= best_score < L1_MERGE:
            return "flag", best_id, "near_review:%.3f" % best_score

        # L2 fact-level: same subject + predicate + value -> update.
        fact = extract_fact(text)
        if fact:
            for old in candidates:
                if extract_fact(old.get("text")) == fact:
                    return "update", str(old.get("id") or ""), "fact_duplicate"

        # L3 structural: same event_key, or same source within 60s.
        event_key, source, ts = _structural_key(entry)
        for old in candidates:
            old_key, old_source, old_ts = _structural_key(old)
            if event_key and old_key and event_key == old_key:
                return "merge", str(old.get("id") or ""), "event_key"
            if (source and old_source and source == old_source
                    and abs(ts - old_ts) <= L3_WINDOW_SECONDS):
                return "merge", str(old.get("id") or ""), "source_window"
        return "keep", None, "no_duplicate"
    except Exception:
        return "keep", None, "fallback"
