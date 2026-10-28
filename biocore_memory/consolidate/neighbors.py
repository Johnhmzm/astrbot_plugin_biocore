# -*- coding: utf-8 -*-
"""A-MEM-style neighbor strengthening proposals (read-only)."""
from __future__ import annotations

NEIGHBORS_ENABLED = False
COSINE_LINK = 0.80
MAX_LINKS = 5


def _tags(entry):
    raw = entry.get("tags")
    if not isinstance(raw, list):
        raw = (entry.get("metadata") or {}).get("tags") if isinstance(entry.get("metadata"), dict) else []
    return {str(x).strip().lower() for x in (raw or []) if str(x).strip()}


def _topic(entry):
    for key in ("topic", "event_key", "event_name"):
        value = str(entry.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def _cosine(a, b):
    try:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        na = sum(float(x) ** 2 for x in a) ** 0.5
        nb = sum(float(y) ** 2 for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def strengthen(entry, neighbors):
    """Suggest bounded links for an entry; returns {entry_id, link_ids, weight}."""
    result = {"entry_id": str((entry or {}).get("id") or "") if isinstance(entry, dict) else "",
              "link_ids": [], "weight": 0.0}
    if not NEIGHBORS_ENABLED or not isinstance(entry, dict):
        return result
    try:
        base_tags, base_topic = _tags(entry), _topic(entry)
        base_vec = entry.get("vector") if isinstance(entry.get("vector"), list) else []
        scored = []
        for other in neighbors or []:
            if not isinstance(other, dict):
                continue
            oid = str(other.get("id") or "")
            if not oid or oid == result["entry_id"]:
                continue
            sim = _cosine(base_vec, other.get("vector") or [])
            if base_tags & _tags(other):
                sim = max(sim, 0.80)
            if base_topic and base_topic == _topic(other):
                sim = max(sim, 0.80)
            if sim >= COSINE_LINK:
                scored.append((sim, oid))
        scored.sort(key=lambda row: (-row[0], row[1]))
        links = [oid for _sim, oid in scored[:MAX_LINKS]]
        weight = round(max(0.0, min(1.0, sum(s for s, _ in scored[:MAX_LINKS])
                                      / max(1, len(links)))), 4) if links else 0.0
        result["link_ids"] = links
        result["weight"] = weight
        return result
    except Exception:
        return result
