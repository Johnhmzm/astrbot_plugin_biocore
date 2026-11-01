# -*- coding: utf-8 -*-
"""Entity disambiguation for the graph memory (P0-1).

Pure functions only: no filesystem, no clock, no imports from main.py or from
entity_graph. The storage layer (entity_graph) calls match() on every write and
the merge helpers on an explicit merge (dashboard API or a folded duplicate).

Three merge paths, applied in this order:
1. exact normalized name;
2. exact normalized alias (either direction);
3. string similarity >= SIMILARITY_THRESHOLD (default 0.85).

No pronoun/word-list rules on purpose: whether "\u5979" means \u5c0f\u590f is a semantic
decision that the LLM (via the tag's aliases field) or the human (via the
dashboard merge API) has to make; a word list would merge unrelated people.
"""
from __future__ import annotations

import difflib

SIMILARITY_THRESHOLD = 0.85
MAX_MERGE_ALIASES = 12
MAX_MERGE_SOURCES = 8
SCAN_LIMIT = 500

TYPE_DEFAULT = "topic"
ENTITY_TYPES = ("person", "place", "event", "topic")


def normalize(text):
    """Lower-case alphanumeric key used for every comparison."""
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def similarity(left, right):
    """0..1 string similarity; identical normalized keys score 1.0."""
    first = normalize(left)
    second = normalize(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    return round(difflib.SequenceMatcher(None, first, second).ratio(), 4)


def _clean(text):
    return " ".join(str(text or "").split()).strip()


def _aliases_of(entity):
    return [_clean(alias) for alias in (entity.get("aliases") or []) if _clean(alias)]


def _names_of(entity):
    return [_clean(entity.get("name"))] + _aliases_of(entity)


def entity_score(entity, name, aliases=()):
    """Best similarity between the candidate names and one existing entity."""
    if not isinstance(entity, dict):
        return 0.0
    candidates = [_clean(name)] + [_clean(alias) for alias in (aliases or [])]
    prior = [text for text in _names_of(entity) if text]
    best = 0.0
    for candidate in candidates:
        key = normalize(candidate)
        if not key:
            continue
        for other in prior:
            if normalize(other) == key:
                return 1.0
            best = max(best, similarity(candidate, other))
    return round(best, 4)


def _hit(entity, score, via):
    return {"id": str(entity.get("id") or ""),
            "name": _clean(entity.get("name")),
            "score": float(score),
            "via": str(via)}


def match(entities, name, aliases=(), threshold=SIMILARITY_THRESHOLD):
    """Return the existing entity that should absorb *name* (or None).

    *entities* is a list of {"id","name","aliases"} dicts (any order). The
    returned dict carries {"id","name","score","via"} with via in
    {"name","alias","similarity"}.
    """
    key = normalize(name)
    if not key:
        return None
    rows = [row for row in (entities or [])
            if isinstance(row, dict) and normalize(row.get("id"))]
    if not rows:
        return None
    for row in rows:
        if normalize(row.get("name")) == key:
            return _hit(row, 1.0, "name")
    candidate_keys = {key}
    for alias in (aliases or []):
        alias_key = normalize(alias)
        if alias_key:
            candidate_keys.add(alias_key)
    for row in rows:
        prior = {normalize(text) for text in _names_of(row) if normalize(text)}
        if candidate_keys & prior:
            return _hit(row, 1.0, "alias")
    try:
        limit = float(threshold)
    except Exception:
        limit = 0.0
    if limit <= 0:
        return None
    best = None
    for row in rows:
        score = entity_score(row, name, aliases)
        if score + 1e-9 < limit:
            continue
        if best is None or score > best["score"] + 1e-9 or (
                abs(score - best["score"]) <= 1e-9
                and str(row.get("id") or "") < str(best.get("id") or "")):
            best = _hit(row, score, "similarity")
    return best


def bounded_aliases(raw, name="", limit=3, max_chars=20):
    """Bound a model-provided alias list: <=limit names, <=max_chars each."""
    out = []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return out
    name_key = normalize(name)
    for item in raw:
        text = _clean(item)[:max_chars]
        key = normalize(text)
        if not text or not key or key == name_key:
            continue
        if any(normalize(existing) == key for existing in out):
            continue
        out.append(text)
        if len(out) >= max(1, int(limit or 3)):
            break
    return out


def merged_aliases(keep_name, keep_aliases, drop_name, drop_aliases,
                   limit=MAX_MERGE_ALIASES):
    """Aliases of the merged node: keep's aliases, drop's name, drop's aliases."""
    out = []
    keep_key = normalize(keep_name)
    for value in (list(keep_aliases or []) + [drop_name]
                  + list(drop_aliases or [])):
        text = _clean(value)
        key = normalize(text)
        if not text or not key or key == keep_key:
            continue
        if any(normalize(existing) == key for existing in out):
            continue
        out.append(text)
    return out[:max(1, int(limit or MAX_MERGE_ALIASES))]


def merged_sources(left, right, limit=MAX_MERGE_SOURCES):
    """Union of source entry ids, newest last, capped."""
    out = []
    for value in list(left or []) + list(right or []):
        text = str(value or "")
        if text and text not in out:
            out.append(text)
    return out[-max(1, int(limit or MAX_MERGE_SOURCES)):]


def merged_type(keep_type, drop_type):
    """Keep's type unless it is the generic default and drop's is specific."""
    keep = str(keep_type or TYPE_DEFAULT).strip().lower()
    drop = str(drop_type or TYPE_DEFAULT).strip().lower()
    keep = keep if keep in ENTITY_TYPES else TYPE_DEFAULT
    drop = drop if drop in ENTITY_TYPES else TYPE_DEFAULT
    if keep == TYPE_DEFAULT and drop != TYPE_DEFAULT:
        return drop
    return keep


def _positive(value):
    try:
        number = float(value)
    except Exception:
        return 0.0
    return number if number > 0 else 0.0


def merged_span(keep_first, keep_last, drop_first, drop_last):
    """(first_seen, last_seen); zeros are treated as "unknown"."""
    firsts = [stamp for stamp in (_positive(keep_first), _positive(drop_first))
              if stamp > 0]
    lasts = [stamp for stamp in (_positive(keep_last), _positive(drop_last))
             if stamp > 0]
    return (min(firsts) if firsts else 0.0), (max(lasts) if lasts else 0.0)


def rewrite_edges(edges, keep_id, drop_id, make_id=None):
    """Rewire edge endpoints from drop_id to keep_id; returns (edges, stats).

    Edges that become a self-loop only because of the merge are dropped, and
    edges that collapse onto an already-present (src, rel, dst, ts) row are
    folded (max confidence wins).
    """
    keep_id = str(keep_id or "")
    drop_id = str(drop_id or "")
    out = []
    by_key = {}
    rewired = 0
    dropped = 0
    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("src") or "")
        dst = str(edge.get("dst") or "")
        changed = False
        if src == drop_id:
            src, changed = keep_id, True
        if dst == drop_id:
            dst, changed = keep_id, True
        if changed and src == dst:
            dropped += 1
            continue
        row = dict(edge)
        row["src"] = src
        row["dst"] = dst
        if changed:
            rewired += 1
            if make_id is not None:
                row["id"] = make_id(src, str(row.get("rel") or ""), dst,
                                    row.get("ts"))
        key = (src, str(row.get("rel") or ""), dst,
               round(_positive(row.get("ts")), 6))
        if key in by_key:
            existing = by_key[key]
            existing["confidence"] = max(_positive(existing.get("confidence")),
                                         _positive(row.get("confidence")))
            if not str(existing.get("source_entry") or ""):
                existing["source_entry"] = str(row.get("source_entry") or "")
            dropped += 1
            continue
        by_key[key] = row
        out.append(row)
    return out, {"rewired": rewired, "dropped": dropped}


def clean_merge_ids(payload):
    """(keep_id, drop_id) from a dashboard merge payload; blanks when invalid."""
    if not isinstance(payload, dict):
        return "", ""
    keep_id = str(payload.get("keep_id") or payload.get("keep") or "").strip()[:80]
    drop_id = str(payload.get("drop_id") or payload.get("drop") or "").strip()[:80]
    if keep_id and drop_id and keep_id == drop_id:
        return keep_id, ""
    return keep_id, drop_id
