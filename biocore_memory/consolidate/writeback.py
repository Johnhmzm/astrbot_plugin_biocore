"""Write-back bridge for consolidation suggestions (default OFF, idempotent).
Pure/local: operates on an in-memory MemoryStore-like object (entries/add/update).
It never saves to disk by itself; the caller decides when to call store.save().
All failures degrade to skipped entries instead of raising.
"""
from __future__ import annotations
import hashlib
import json
WRITEBACK_ENABLED = False
MAX_RELATED = 8
REFLECTION_SOURCE = "consolidate"
TREE_SOURCE = "ti_mem"
def _digest(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]
def _entries(store):
    try:
        rows = getattr(store, "entries", None)
        if isinstance(rows, list):
            return rows
        if isinstance(store, dict):
            rows = store.get("entries")
            return rows if isinstance(rows, list) else []
        return list(store or [])
    except Exception:
        return []
def _find(store, entry_id):
    try:
        fn = getattr(store, "find", None)
        if callable(fn):
            row = fn(entry_id)
            if isinstance(row, dict):
                return row
    except Exception:
        pass
    for entry in _entries(store):
        if isinstance(entry, dict) and str(entry.get("id") or "") == str(entry_id):
            return entry
    return None
def _add(store, entry):
    try:
        fn = getattr(store, "add", None)
        if callable(fn):
            return fn(entry)
        if isinstance(store, dict):
            store.setdefault("entries", []).append(entry)
            return entry
        store.append(entry)
        return entry
    except Exception:
        return None
def _update(store, entry_id, **fields):
    try:
        fn = getattr(store, "update", None)
        if callable(fn):
            result = fn(entry_id, **fields)
            if result is not None:
                return result
    except Exception:
        pass
    entry = _find(store, entry_id)
    if isinstance(entry, dict):
        entry.update(fields)
        return entry
    return None
def _source_ids(proposal):
    raw = proposal.get("source_ids") if isinstance(proposal, dict) else []
    return sorted({str(x) for x in (raw or []) if str(x)})
def _scope(entry):
    fields = ("session", "scope", "user_id", "agent_id", "app_id", "run_id", "thread")
    return {k: entry.get(k) for k in fields if entry.get(k) is not None}
def _importance(store, ids, default=0.5):
    values = []
    for sid in ids:
        row = _find(store, sid)
        if isinstance(row, dict):
            try:
                values.append(float(row.get("importance", 0.5) or 0.5))
            except Exception:
                continue
    return round(sum(values) / len(values), 4) if values else default
def apply_reflections(store, proposals):
    """Write reflection proposals as system entries; idempotent by source_ids."""
    result = {"written": [], "skipped": []}
    if not WRITEBACK_ENABLED:
        result["skipped"].append({"reason": "disabled"})
        return result
    for idx, proposal in enumerate(proposals or []):
        try:
            text = str((proposal or {}).get("text") or "").strip() if isinstance(proposal, dict) else ""
            ids = _source_ids(proposal)
            if len(text) < 2 or not ids:
                result["skipped"].append({"index": idx, "reason": "invalid"})
                continue
            duplicate = any(
                str(e.get("source") or "") == REFLECTION_SOURCE
                and sorted(str(x) for x in ((e.get("metadata") or {}).get("source_ids") or []))
                == ids
                for e in _entries(store) if isinstance(e, dict))
            if duplicate:
                result["skipped"].append({"index": idx, "reason": "duplicate"})
                continue
            base = {"id": "consolidate_" + _digest(json.dumps([text, ids]))}
            base.update(_scope(_find(store, ids[0]) or {}))
            base.update({"text": text, "role": "system", "source": REFLECTION_SOURCE,
                         "importance": _importance(store, ids),
                         "metadata": {"source_ids": ids, "origin": "reflection"}})
            added = _add(store, base)
            if isinstance(added, dict) and added.get("id"):
                result["written"].append(str(added.get("id")))
            else:
                result["skipped"].append({"index": idx, "reason": "add_failed"})
        except Exception:
            result["skipped"].append({"index": idx, "reason": "error"})
    return result
def _suggestions(suggestions):
    if isinstance(suggestions, dict):
        return [suggestions]
    return [s for s in (suggestions or []) if isinstance(s, dict)]
def apply_neighbors(store, suggestions):
    """Append strengthen() link_ids to related_ids (dedupe, total <=8)."""
    result = {"linked": 0}
    if not WRITEBACK_ENABLED:
        return result
    for suggestion in _suggestions(suggestions):
        try:
            eid = str(suggestion.get("entry_id") or "")
            entry = _find(store, eid)
            if not isinstance(entry, dict):
                continue
            current = entry.get("related_ids")
            current = [str(x) for x in current if str(x)] if isinstance(current, list) else []
            links = [str(x) for x in (suggestion.get("link_ids") or []) if str(x) and str(x) != eid]
            merged = []
            for value in current + links:
                if value not in merged:
                    merged.append(value)
            merged = merged[:MAX_RELATED]
            if merged == current:
                continue
            if _update(store, eid, related_ids=merged):
                result["linked"] += 1
        except Exception:
            continue
    return result
def _day_of(items):
    days = [str((x or {}).get("day") or (x or {}).get("key") or "") for x in (items or [])]
    for value in days:
        if len(value) >= 10 and value[:4].isdigit():
            return value[:10]
    return days[0][:10] if days and days[0] else ""
def write_tree(store, summary):
    """Write one tree summary entry (level/day); idempotent by source+level+day."""
    level = int((summary or {}).get("level") or 1) if isinstance(summary, dict) else 1
    result = {"written": 0, "level": level}
    if not WRITEBACK_ENABLED or not isinstance(summary, dict):
        return result
    try:
        items = list(summary.get("items") or [])
        if not summary.get("generated") or not items:
            return result
        day = _day_of(items)
        duplicate = any(
            str(e.get("source") or "") == TREE_SOURCE
            and int((e.get("metadata") or {}).get("level") or 0) == level
            and str((e.get("metadata") or {}).get("day") or "") == day
            for e in _entries(store) if isinstance(e, dict))
        if duplicate:
            return result
        text = "时间树 L%d %s：%s" % (
            level, day, json.dumps(items[:10], ensure_ascii=False, sort_keys=True)[:1000])
        entry = {"id": TREE_SOURCE + "_" + _digest("%s|%s|%s" % (level, day, text)),
                 "text": text[:1200], "role": "system", "source": TREE_SOURCE,
                 "importance": 0.5,
                 "metadata": {"level": level, "day": day,
                              "source_ids": [str(x.get("key") or "") for x in items[:8]]}}
        added = _add(store, entry)
        if isinstance(added, dict):
            result["written"] = 1
        return result
    except Exception:
        return result
