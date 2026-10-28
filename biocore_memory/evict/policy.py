# -*- coding: utf-8 -*-
"""Read-only eviction decisions (never deletes, never writes).

eviction_order() keeps the legacy candidate ordering used by the engine.
tick(entries, now) is the M2 read-only decision pass: it partitions entries
into archive / flag / keep for the caller to act on later.

Protection rules (never archived):
- pinned / desktop-anchor style pin;
- self-defining / identity entries;
- explicit promises / open loops / commitments;
- P0/P1 priority entries.

Archive-first signals (deterministic, bounded):
- low salience (importance and event intensity both low);
- redundancy (duplicate text, later copies first);
- old versions (version chain at/over the configured max, or superseded);
- long unused (no access for >= 30 days, when now is supplied);
- otherwise a low eviction score (< ARCHIVE_SCORE).
Between ARCHIVE_SCORE and FLAG_SCORE the entry is only flagged.
"""
from __future__ import annotations

from ..core.config import MAX_VERSIONS
from ..core.util import clamp01
from .score import eviction_score

ARCHIVE_SCORE = 0.30
FLAG_SCORE = 0.50
STALE_SECONDS = 30 * 86400.0
LOW_SALIENCE = 0.35
REDUNDANCY_ARCHIVE = 0.60
# L5 schema-based eviction (default OFF: tick behaves exactly as before).
SCHEMA_EVICTION_ENABLED = False
SCHEMA_ARCHIVE = 0.35
CONSEQUENCE_ARCHIVE = 0.40


def _entry_id(entry):
    return str(entry.get("id") or entry.get("memory_id") or "")


def _event_intensity(entry):
    vector = entry.get("event_vector")
    if hasattr(vector, "as_dict"):
        try:
            vector = vector.as_dict()
        except Exception:
            vector = None
    if isinstance(vector, dict):
        return clamp01(vector.get("intensity"), 0.0)
    return clamp01(entry.get("event_intensity"), 0.0)


def _salience(entry):
    return clamp01(0.6 * clamp01(entry.get("importance"), 0.5)
                   + 0.4 * _event_intensity(entry), 0.5)


def _is_protected(entry):
    if entry.get("pin") or entry.get("pinned"):
        return True
    if entry.get("self_defining") or entry.get("identity"):
        return True
    for key in ("promise", "promises", "commitment", "open_loop", "open_loops"):
        if entry.get(key):
            return True
    priority = str(entry.get("priority") or "").upper()
    if entry.get("p0") or entry.get("p1") or priority in ("P0", "P1"):
        return True
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    return bool(metadata.get("pin") or metadata.get("pinned")
                or metadata.get("self_defining") or metadata.get("promise"))


def _schema_congruence(entry):
    """Read schema congruence from entry or its event_vector (0..1)."""
    vector = entry.get("event_vector")
    if hasattr(vector, "as_dict"):
        try:
            vector = vector.as_dict()
        except Exception:
            vector = None
    if isinstance(vector, dict) and vector.get("schema_conflict") is not None:
        return clamp01(1.0 - clamp01(vector.get("schema_conflict"), 0.0))
    return clamp01(entry.get("schema_congruence"), 1.0)


def _consequence(entry):
    """0..1 consequence of forgetting; missing means neutral/low."""
    return clamp01(entry.get("consequence"), 0.5)


def _is_old_version(entry):
    if entry.get("superseded") or entry.get("old_version"):
        return True
    versions = entry.get("previous_versions")
    if isinstance(versions, (list, tuple)) and len(versions) >= max(1, int(MAX_VERSIONS)):
        return True
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    return bool(metadata.get("superseded") or metadata.get("old_version"))


def _age_seconds(entry, now):
    if not now:
        return 0.0
    last = 0.0
    for key in ("last_recall", "last_access", "ts", "created_ts"):
        try:
            last = max(last, float(entry.get(key) or 0.0))
        except Exception:
            continue
    if last <= 0:
        # No access timestamp at all: unknown age counts as long-unused.
        return float(now)
    try:
        return max(0.0, float(now) - last)
    except Exception:
        return 0.0


def eviction_order(rows):
    """Legacy candidate order: protected/desktop/index-retained first."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        entry = row.get("entry") if isinstance(row.get("entry"), dict) else row
        key = {"id": str(entry.get("id") or ""),
               "score": float(row.get("score", 0.0) or 0.0),
               "pinned": bool(entry.get("pin")),
               "desktop": bool(entry.get("desktop")),
               "index_retained": bool(entry.get("index_retained"))}
        out.append(key)
    out.sort(key=lambda r: (not r["pinned"], not r["desktop"],
                            not r["index_retained"], -r["score"]))
    return out


def tick(entries, now=0.0):
    """Partition entries into {"archive": [ids], "flag": [ids], "keep": [ids]}.

    Read-only: no entry is mutated or removed. Ordering is deterministic:
    archive/flag by (score ascending, id); keep keeps input order.
    """
    items = [e for e in (entries or []) if isinstance(e, dict)]
    total = max(1, len(items))
    seen_text = set()
    scored = []
    for position, entry in enumerate(items):
        entry_id = _entry_id(entry)
        if not entry_id:
            continue
        text = " ".join(str(entry.get("text") or "").split()).lower()
        duplicate = bool(text) and text in seen_text
        if text:
            seen_text.add(text)
        if _is_protected(entry):
            scored.append((entry_id, 1.0, "keep", entry))
            continue
        redundancy = 1.0 if duplicate else (
            1.0 if clamp01(entry.get("redundancy"), 0.0) >= REDUNDANCY_ARCHIVE else 0.0)
        score = eviction_score(entry, now=now,
                               position=position / float(total),
                               redundancy=redundancy)
        stale = _age_seconds(entry, now) >= STALE_SECONDS
        low_salience = _salience(entry) < LOW_SALIENCE
        schema_archive = (SCHEMA_EVICTION_ENABLED
                          and _schema_congruence(entry) < SCHEMA_ARCHIVE
                          and _consequence(entry) < CONSEQUENCE_ARCHIVE)
        must_archive = (duplicate or redundancy >= REDUNDANCY_ARCHIVE
                        or _is_old_version(entry) or stale or low_salience
                        or schema_archive)
        if must_archive or score < ARCHIVE_SCORE:
            decision = "archive"
        elif score < FLAG_SCORE:
            decision = "flag"
        else:
            decision = "keep"
        scored.append((entry_id, score, decision, entry))
    archive = [item for item in scored if item[2] == "archive"]
    flagged = [item for item in scored if item[2] == "flag"]
    keep = [item[0] for item in scored if item[2] == "keep"]
    archive.sort(key=lambda item: (item[1], item[0]))
    flagged.sort(key=lambda item: (item[1], item[0]))
    return {"archive": [item[0] for item in archive],
            "flag": [item[0] for item in flagged],
            "keep": keep}
