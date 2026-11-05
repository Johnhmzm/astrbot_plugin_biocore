# -*- coding: utf-8 -*-
"""task-244 step 1: shadow coordinates for memory entries (write-only).

Every entry gets a read-only "space" dict with five axes:

    semantic    the embedding vector (reused when the entry already has one)
                with its provider / model name, plus topic / entity tags and a
                text fingerprint fallback. semantic distance = 1 - cosine
                (Jaccard over tags when either side has no vector)
    time        the entry ts, its own half-life in minutes, its age
    affect      v / a as they stood when the entry was written
    social      scope + trust / closeness at write time
    activation  importance / hits / retrieval_count / last_hit

Boundaries
    Step 1 only adds coordinates. recall(), ranking and the memory score never
    read this module, and recall keeps its old behaviour byte for byte.
    The switch spatial_recall is OFF by default; with it off nothing is written.
    A coordinate that cannot be built returns None and the entry is untouched.

    Distances are reported PER AXIS. They are never added into one number; the
    nearest list is ordered lexicographically (semantic, affect, time,
    activation, social), which keeps every axis visible in the ranking.

Weights / half-lives below are [engineering] (see docs/PAPER-MAP.md).
"""
from __future__ import annotations

import hashlib
import math
import re

SCHEMA = 1
SWITCH_KEY = "spatial_recall"
ENV_KEY = "BIOCORE_SPATIAL_RECALL"
AXES = ("semantic", "time", "affect", "social", "activation")
DISTANCE_ORDER = ("semantic", "affect", "time", "activation", "social")

VECTOR_LIMIT = 768
TOPIC_LIMIT = 8
ENTITY_LIMIT = 8
FINGERPRINT_CHARS = 12

BASE_HALF_LIFE_MINUTES = 180.0      # [engineering]
HALF_LIFE_BY_KIND = {"direct": 180.0, "recall": 120.0,
                     "summary": 240.0, "reflection": 360.0}   # [engineering]
IMPORTANCE_SPAN = 0.5               # half-life scales 0.5x .. 1.5x
HITS_CEILING = 20.0                 # [engineering] log scale for the hits axis
DEFAULT_IMPORTANCE = 0.5
DEFAULT_TRUST = 0.5
DEFAULT_CLOSENESS = 0.5

_TOKEN = re.compile(r"[a-z0-9_]+")       # latin words
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")   # CJK runs, split into bigrams below
_WS = re.compile(r"\s+")


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return number


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))


def enabled(flags=None, env=None):
    """spatial_recall: explicit flag > nested switches > env > default OFF."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and ENV_KEY in environ:
        raw = str(environ.get(ENV_KEY)).strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return True
        if raw in ("0", "false", "off", "no"):
            return False
    return False


def tokens(text):
    """Deterministic bag: latin words + CJK bigrams + single characters.

    Bigrams are what the governance concept extractor produces, so a query and
    an entry's topics line up when no embedding is available.
    """
    body = _WS.sub(" ", str(text or "")).lower()
    out = _TOKEN.findall(body)
    for run in _CJK_RUN.findall(body):
        if len(run) == 1:
            out.append(run)
            continue
        out.extend(run[index:index + 2] for index in range(len(run) - 1))
        out.extend(run)
    seen = []
    for item in out:
        if item not in seen:
            seen.append(item)
    return seen


def fingerprint(text):
    body = _WS.sub(" ", str(text or "")).strip().lower()
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def half_life_minutes(entry):
    """Per-entry half-life: the kind's base, scaled by importance."""
    entry = entry if isinstance(entry, dict) else {}
    kind = str(entry.get("kind") or entry.get("memory_kind") or "direct")
    base = HALF_LIFE_BY_KIND.get(kind, BASE_HALF_LIFE_MINUTES)
    importance = _clamp(entry.get("importance", DEFAULT_IMPORTANCE))
    return round(base * (1.0 - IMPORTANCE_SPAN + 2.0 * IMPORTANCE_SPAN * importance),
                 3)


def _vector(entry):
    raw = entry.get("vector") if isinstance(entry, dict) else None
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for value in raw[:VECTOR_LIMIT]:
        try:
            number = float(value)
        except Exception:
            continue
        if math.isfinite(number):
            out.append(round(number, 6))
    return out


def _tags(values, limit):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    out = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text[:32])
    return out[:limit]   # tags first, then concepts: order is meaningful


def _embed_names(entry, embed=None):
    """Provider / model of the embedding, so mismatches are visible at a glance."""
    entry = entry if isinstance(entry, dict) else {}
    info = embed if isinstance(embed, dict) else {}
    provider = str(info.get("provider")
                   or entry.get("embedding_provider")
                   or entry.get("vector_provider")
                   or entry.get("embed_provider") or "")[:64]
    model = str(info.get("model")
                or entry.get("embedding_model")
                or entry.get("vector_model")
                or entry.get("embed_model") or "")[:64]
    return provider, model


def build(entry, relationship=None, now=None, embed=None):
    """Five-axis coordinates for one entry; None when they cannot be built."""
    try:
        return _build(entry, relationship, now, embed)
    except Exception:      # a broken entry never breaks the write
        return None


def _build(entry, relationship=None, now=None, embed=None):
    if not isinstance(entry, dict):
        return None      # nothing to put coordinates on
    rel = relationship if isinstance(relationship, dict) else {}
    embed_provider, embed_model = _embed_names(entry, embed)
    stamp = _num(now, _num(entry.get("ts"), 0.0))
    ts = round(_num(entry.get("ts"), stamp), 3)
    vector = _vector(entry)
    topics = _tags(list(entry.get("tags") or []) + list(entry.get("concepts") or []),
                   TOPIC_LIMIT)
    entities = _tags(entry.get("entities") or entry.get("entity"), ENTITY_LIMIT)
    affect = entry.get("affect") if isinstance(entry.get("affect"), dict) else {}
    trust = rel.get("trust", entry.get("trust", DEFAULT_TRUST))
    closeness = rel.get("closeness", entry.get("closeness", DEFAULT_CLOSENESS))
    return {
        "schema": SCHEMA,
        "semantic": {
            "vector": vector,
            "vector_dim": len(vector),
            # true = tags only; never pretend a vector exists
            "fallback": not bool(vector),
            "provider": embed_provider,
            "model": embed_model,
            "topics": topics,
            "entities": entities,
            "fingerprint": fingerprint(entry.get("text")),
        },
        "time": {
            "ts": ts,
            "half_life_minutes": half_life_minutes(entry),
            "age_minutes": round(max(0.0, stamp - ts) / 60.0, 3),
            "last_hit_ts": round(_num(entry.get("last_hit_ts"), 0.0), 3),
        },
        "affect": {
            "v": round(_clamp(affect.get("v", entry.get("v", 0.0)), -1.0, 1.0), 6),
            "a": round(_clamp(affect.get("a", entry.get("a", 0.5))), 6),
        },
        "social": {
            "scope": str(entry.get("scope") or entry.get("session_id") or "default")[:64],
            "trust": round(_clamp(trust), 6),
            "closeness": round(_clamp(closeness), 6),
        },
        "activation": {
            "importance": round(_clamp(entry.get("importance", DEFAULT_IMPORTANCE)), 6),
            "hits": int(_num(entry.get("hits"), 1)),
            "retrieval_count": int(_num(entry.get("retrieval_count"), 0)),
            "last_hit_ts": round(_num(entry.get("last_hit_ts"), 0.0), 3),
        },
    }


# ------------------------------------------------------------------ distance
def _cosine_distance(x, y):
    dot = sum(a * b for a, b in zip(x, y))
    norm_x = math.sqrt(sum(a * a for a in x))
    norm_y = math.sqrt(sum(b * b for b in y))
    if norm_x <= 0 or norm_y <= 0:
        return 1.0
    return _clamp(1.0 - dot / (norm_x * norm_y), 0.0, 2.0)


def _semantic_distance(x, y):
    x = x if isinstance(x, dict) else {}
    y = y if isinstance(y, dict) else {}
    vx = _vector({"vector": x.get("vector")})
    vy = _vector({"vector": y.get("vector")})
    if vx and vy and len(vx) == len(vy):
        # 1 - cosine: 0 for the same direction, 2 for the opposite one
        return round(_clamp(_cosine_distance(vx, vy), 0.0, 2.0), 6)
    tx, ty = set(x.get("topics") or []), set(y.get("topics") or [])
    ex, ey = set(x.get("entities") or []), set(y.get("entities") or [])
    union = tx | ty | ex | ey
    if not union:
        return 1.0
    shared = (tx & ty) | (ex & ey)
    return round(1.0 - len(shared) / len(union), 6)


def _time_distance(x, y):
    x = x if isinstance(x, dict) else {}
    y = y if isinstance(y, dict) else {}
    gap = abs(_num(x.get("ts"), 0.0) - _num(y.get("ts"), 0.0))
    scale = max(1.0, _num(x.get("half_life_minutes"), BASE_HALF_LIFE_MINUTES),
                _num(y.get("half_life_minutes"), BASE_HALF_LIFE_MINUTES)) * 60.0
    return round(_clamp(gap / scale), 6)


def _affect_distance(x, y):
    x = x if isinstance(x, dict) else {}
    y = y if isinstance(y, dict) else {}
    dv = _num(x.get("v"), 0.0) - _num(y.get("v"), 0.0)
    da = _num(x.get("a"), 0.5) - _num(y.get("a"), 0.5)
    return round(_clamp(math.sqrt((dv * dv + da * da) / 2.0)), 6)


def _social_distance(x, y):
    x = x if isinstance(x, dict) else {}
    y = y if isinstance(y, dict) else {}
    scope = 0.0 if str(x.get("scope") or "") == str(y.get("scope") or "") else 1.0
    spread = (abs(_num(x.get("trust"), DEFAULT_TRUST)
                  - _num(y.get("trust"), DEFAULT_TRUST))
              + abs(_num(x.get("closeness"), DEFAULT_CLOSENESS)
                    - _num(y.get("closeness"), DEFAULT_CLOSENESS))) / 2.0
    return round(_clamp(0.5 * scope + 0.5 * spread), 6)


def _activation_distance(x, y):
    x = x if isinstance(x, dict) else {}
    y = y if isinstance(y, dict) else {}
    importance = abs(_num(x.get("importance"), DEFAULT_IMPORTANCE)
                     - _num(y.get("importance"), DEFAULT_IMPORTANCE))
    ceiling = math.log1p(HITS_CEILING)
    hits = abs(math.log1p(max(0.0, _num(x.get("hits"), 0.0)))
               - math.log1p(max(0.0, _num(y.get("hits"), 0.0)))) / ceiling
    return round(_clamp(0.6 * importance + 0.4 * hits), 6)


def distance(space_a, space_b):
    """Per-axis distance; there is no total, on purpose."""
    a = space_a if isinstance(space_a, dict) else {}
    b = space_b if isinstance(space_b, dict) else {}
    return {
        "semantic": _semantic_distance(a.get("semantic"), b.get("semantic")),
        "time": _time_distance(a.get("time"), b.get("time")),
        "affect": _affect_distance(a.get("affect"), b.get("affect")),
        "social": _social_distance(a.get("social"), b.get("social")),
        "activation": _activation_distance(a.get("activation"),
                                           b.get("activation")),
    }


def order_key(distances):
    """Lexicographic order over the axes; nothing is summed."""
    row = distances if isinstance(distances, dict) else {}
    return tuple(_num(row.get(axis), 1.0) for axis in DISTANCE_ORDER)


# --------------------------------------------------------------------- probe
def query_space(query, vector=None, now=None, embed=None):
    """Coordinates for a bare query string (same five axes, no id)."""
    return build({"text": query, "vector": vector or [],
                  "ts": _num(now, 0.0), "tags": tokens(query),
                  "importance": DEFAULT_IMPORTANCE}, now=now, embed=embed)


def probe(entries, entry_id=None, query=None, vector=None, limit=5, now=None):
    """Debug read: one entry's five axes, or the nearest entries to a query."""
    rows = [row for row in (entries or []) if isinstance(row, dict)]
    limit = max(1, min(20, int(_num(limit, 5))))
    if entry_id:
        want = str(entry_id)
        for row in rows:
            if str(row.get("id") or "") == want:
                stored = row.get("space")
                space = stored if isinstance(stored, dict) else build(row, now=now)
                return {"ok": space is not None, "id": want,
                        "source": "entry" if isinstance(stored, dict) else "computed",
                        "space": space,
                        "reason": "" if space is not None else "build_failed"}
        return {"ok": False, "reason": "not_found", "id": want}
    if query:
        target = query_space(query, vector=vector, now=now)
        scored = []
        for row in rows:
            stored = row.get("space")
            space = stored if isinstance(stored, dict) else build(row, now=now)
            if not isinstance(space, dict):
                continue
            distances = distance(space, target)
            scored.append({"id": str(row.get("id") or ""),
                           "text": str(row.get("text") or "")[:80],
                           "ts": round(_num(row.get("ts"), 0.0), 3),
                           "distance": distances,
                           "from": "entry" if isinstance(stored, dict) else "computed"})
        scored.sort(key=lambda item: order_key(item["distance"]))
        return {"ok": True, "query": str(query), "count": len(scored),
                "limit": limit, "order": list(DISTANCE_ORDER),
                "space": target, "results": scored[:limit]}
    return {"ok": False, "reason": "id_or_query_required"}
