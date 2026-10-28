# -*- coding: utf-8 -*-
"""Small orchestration helpers used by MemoryEngine (no algorithms)."""
from __future__ import annotations
from .core.util import clamp01


def vector_for(engine, event):
    text = str(getattr(event, "text", "") or "")
    vector = list(getattr(event, "vector", []) or [])
    if not vector and engine.embedder is not None:
        try:
            from .recall import embedding as _embedding
            fn = getattr(_embedding, "embed", None)
            value = fn(text, engine.embedder) if fn else None
            if isinstance(value, (list, tuple)):
                vector = list(value)
        except Exception:
            vector = []
    if vector or engine.embedder is None:
        return vector
    fn = getattr(engine.embedder, "embed_text", None) or getattr(engine.embedder, "embed", None)
    try:
        value = fn(text) if fn else None
        return list(value) if isinstance(value, (list, tuple)) else []
    except Exception:
        return []


def explicit_number(event, key):
    """Return an explicitly supplied 0..1 value, else None.

    Order: dict payload field -> metadata field -> event attribute. For
    "self_relevance" any non-zero attribute counts as explicit; for
    "importance" the dataclass default 0.5 is treated as "not supplied".
    """
    if isinstance(event, dict):
        if event.get(key) is not None:
            try:
                return clamp01(event.get(key), 0.0)
            except Exception:
                return None
        meta = event.get("metadata")
        if isinstance(meta, dict) and meta.get(key) is not None:
            try:
                return clamp01(meta.get(key), 0.0)
            except Exception:
                return None
        return None
    meta = getattr(event, "metadata", None)
    if isinstance(meta, dict) and key in meta and meta.get(key) is not None:
        try:
            return clamp01(meta.get(key), 0.0)
        except Exception:
            return None
    try:
        value = float(getattr(event, key, 0.0))
    except Exception:
        return None
    if key == "importance":
        return clamp01(value, 0.5) if abs(value - 0.5) > 1e-9 else None
    return clamp01(value, 0.0) if value > 0.0 else None


def value_of(event):
    """Memory value: explicit importance wins over the derived formula."""
    explicit = explicit_number(event, "importance")
    if explicit is not None:
        return explicit
    meta = getattr(event, "metadata", None) or {}
    if isinstance(meta, dict) and "importance" in meta:
        return clamp01(meta.get("importance"), 0.5)
    try:
        from .event.vector import value_score
        parts = {"intensity": getattr(event, "intensity", 0.0),
                 "self_relevance": getattr(event, "self_relevance", 0.0),
                 "valence": meta.get("valence", 0.0),
                 "mainline": meta.get("mainline", 0.0),
                 "routine": meta.get("routine", 0.0)}
        return clamp01(value_score(parts), 0.5)
    except Exception:
        return clamp01(getattr(event, "importance", 0.5), 0.5)


def cosine_vectors(a, b):
    """Cosine similarity of two numeric vectors (0.0 when unusable)."""
    try:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        na = sum(float(x) ** 2 for x in a) ** 0.5
        nb = sum(float(y) ** 2 for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def is_protected_entry(entry):
    """True for entries that an automatic eviction must never soft-delete.

    Covers pins, identity anchors/evidence, promises/open loops/commitments and
    P0/P1 priorities (mirrors evict/policy protections plus identity evidence).
    """
    e = entry if isinstance(entry, dict) else {}
    if e.get("pin") or e.get("pinned") or e.get("desktop") or e.get("index_retained"):
        return True
    if e.get("self_defining") or e.get("identity") or e.get("identity_relevant"):
        return True
    for key in ("identity_evidence", "identity_weight", "anchor", "event_anchor"):
        if e.get(key):
            return True
    for key in ("promise", "promises", "commitment", "open_loop", "open_loops",
                "unresolved", "deadline", "due"):
        if e.get(key):
            return True
    priority = str(e.get("priority") or "").upper()
    if e.get("p0") or e.get("p1") or priority in ("P0", "P1"):
        return True
    meta = e.get("metadata")
    if isinstance(meta, dict):
        for key in ("pin", "pinned", "self_defining", "identity",
                    "promise", "commitment", "open_loop"):
            if meta.get(key):
                return True
    return False


def _field(entry, key, default=None):
    """Read a field from the entry or its nested metadata dict."""
    if not isinstance(entry, dict):
        return default
    if key in entry:
        return entry.get(key)
    meta = entry.get("metadata")
    if isinstance(meta, dict) and key in meta:
        return meta.get(key, default)
    return default


def check_after_remember(store, entry, embedder=None):
    """Call store/dedupe.dedupe(entry, entries, embedder); merge/update + version."""
    result = {"dedupe": {"action": "keep", "target_id": None, "reason": "unavailable"},
              "identity": None}
    if not isinstance(entry, dict):
        return result
    try:
        from .store.dedupe import dedupe as _dedupe
        action, target_id, reason = _dedupe(
            entry, store.entries, embedder=embedder)
        result["dedupe"] = {"action": str(action),
                            "target_id": str(target_id) if target_id else None,
                            "reason": str(reason)}
        # Engine-level guard: the L3 "same source within 60s" rule must not
        # collapse unrelated messages. Only an explicit event key may merge.
        if (action in ("merge", "update") and str(reason) == "source_window"
                and not str(entry.get("event_key")
                            or entry.get("event_id")
                            or _field(entry, "event_key") or "")):
            action, target_id = "keep", None
            result["dedupe"] = {"action": "keep", "target_id": None,
                                "reason": "source_window_guard"}
        if action in ("merge", "update") and target_id:
            target = store.find(target_id)
            if target is not None and target is not entry:
                fields = {
                    "hits": int(target.get("hits", 1) or 1) + int(entry.get("hits", 1) or 1),
                    "importance": max(float(target.get("importance", 0.0) or 0.0),
                                      float(entry.get("importance", 0.0) or 0.0)),
                }
                if not target.get("vector") and entry.get("vector"):
                    fields["vector"] = list(entry.get("vector") or [])
                store.update(target_id, **fields)
                store.remove(entry.get("id"), hard=True)
                result["dedupe"]["merged"] = True
    except Exception as exc:
        result["dedupe"] = {"action": "keep", "target_id": None,
                            "reason": "fallback", "error": str(exc)[:80]}
    try:
        from .identity import is_identity
        result["identity"] = {"entry_id": str(entry.get("id") or ""),
                              "is_identity": bool(is_identity(entry))}
    except Exception:
        pass
    return result


def annotate_tiers(rows, high=0.55, mid=0.35):
    """L3: add tier/confidence/usage; HIGH=inject, MID=hint, LOW=drop."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            score = float(row.get("score", 0.0) or 0.0)
        except Exception:
            score = 0.0
        tier = row.get("tier")
        if tier not in ("high", "mid", "medium", "low"):
            tier = "high" if score >= high else "mid" if score >= mid else "low"
        row["tier"] = "mid" if tier == "medium" else tier
        row["confidence"] = round(max(0.0, min(1.0, score)), 4)
        row["usage"] = {"high": "inject", "mid": "hint", "low": "drop"}[row["tier"]]
        out.append(row)
    return out


def provenance_of(entry):
    p = entry.get("provenance") if isinstance(entry, dict) else None
    return p if isinstance(p, dict) else {}


def source_filtered_count(entries, threshold=0.55):
    count = 0
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        p = provenance_of(entry)
        try:
            conf = float(p.get("confidence", entry.get("memory_confidence", 0.7)))
        except Exception:
            conf = 0.7
        if conf < threshold and not entry.get("pin"):
            count += 1
    return count


def slots_ingest(registry, entry, ctx=None):
    """admission -> slot_score -> registry.add_item; switch + evict bridge."""
    if registry is None or not getattr(registry, "enabled", False):
        return {"enabled": False}
    from .slots import admission, pick_evictions, should_switch, slot_score
    ctx = dict(ctx or {})
    entry = dict(entry)
    entry.setdefault("goal_relevance", 0.5)
    entry.setdefault("cue", ctx.get("cue", entry.get("cue", 0.5)))
    score = slot_score(entry, ctx)
    decision = admission(entry, ctx)
    switched, switch_reason = should_switch(ctx)
    trace = {"enabled": True, "score": round(score, 4),
             "decision": decision.get("decision"), "switch": switched,
             "switch_reason": switch_reason, "slot_id": None, "evicted": []}
    if decision.get("decision") != "admit":
        return trace
    text = str(entry.get("text") or entry.get("content") or "")
    item = dict(entry)
    item["slot_score"] = round(score, 4)
    if switched:
        selected = registry.add_dynamic(str(entry.get("topic") or text[:24] or "topic"))
        slot_id = getattr(selected, "slot_id", None) if selected else None
    else:
        if entry.get("self_defining") or entry.get("identity"):
            slot_id = "identity"
        elif entry.get("relationship") or entry.get("trust") is not None:
            slot_id = "relationship"
        elif entry.get("open_loop") or entry.get("promise"):
            slot_id = "promises_open_loops"
        else:
            slot_id = "recent_changes"
    trace["slot_id"] = slot_id
    if slot_id:
        registry.add_item(slot_id, item)
    evicted = pick_evictions(registry)
    for eid in evicted:
        for slot in getattr(registry, "slots", []) or []:
            slot.remove(eid)
    trace["evicted"] = evicted
    return trace
