# -*- coding: utf-8 -*-
"""Five-axis coordinates for memory entries, and the stages that read them.

A "space" dict carries five axes:

    semantic    the embedding vector (reused when the entry already has one)
                with its provider / model name, plus topic / entity tags and a
                text fingerprint fallback. semantic distance = 1 - cosine
                (Jaccard over tags when either side has no vector)
    time        the entry ts, its own half-life in minutes, its age
    affect      v / a as they stood when the entry was written
    social      scope + trust / closeness at write time
    activation  importance / hits / retrieval_count / last_hit

Boundaries
    Writing coordinates is gated by spatial_recall (default OFF): with it off
    remember() writes exactly the old entry. A coordinate that cannot be built
    returns None and the entry is untouched.

    Reading them has two independent switches:
    - spatial_select (default OFF): a candidate stage. The WHOLE pool is ranked
      by the weighted distance and only the nearest entries reach the ordinary
      scorer; mode="spatial" is the caller's explicit request.
    - spatial_weighted (default ON): how rows that already exist are ordered.
    With both at their defaults, recall keeps its old behaviour byte for byte.

    Two structures ride on the same five axes:
    - displacement (TransE, Bordes 2013): two adjacent memories about one
      (subject, attribute) carry the vector between them; a valence flip with
      time running forward is a revision, anything else an update.
    - index (sign-pattern LSH above the configured threshold): buckets prune
      the exact scan with a per-bucket lower bound, so the bucketed answer is
      the exact answer.

    Distances are reported PER AXIS and stay visible on every row. Ordering:
    - spatial_weighted ON (default): distance = sum(w_axis * d_axis) with
      EQUAL weights, 0.20 per axis -- a neutral engineering default, no axis
      privileged and nothing fitted. A store may override them with
      flags["spatial_weights"] or BIOCORE_SPATIAL_WEIGHTS.
    - spatial_weighted OFF: the old lexicographic order_key, kept as the
      fallback so callers can reproduce the previous behaviour.
    Retrieval is anchored at query_ts (the moment the question was asked,
    Howard & Kahana 2002), not at "now".

Weights / half-lives below are [engineering] (see docs/PAPER-MAP.md).
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from .core.config import (SPATIAL_DEAD_AXIS_STD, SPATIAL_INDEX_PREFIX,
                          SPATIAL_INDEX_THRESHOLD, SPATIAL_SELECT_DEPTH,
                          SPATIAL_STANDARDIZE_MIN_SAMPLE, SPATIAL_WEIGHTS)

# schema 2 added version / refreshed_at / drift to every coordinate dict;
# both are additive, an old entry without them reads as version 1 / drift 0.
SCHEMA = 2
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

# Reconsolidation (Nader 2000): a recalled memory is rewritten by the act of
# recalling it, so a hit re-samples the coordinates with the relationship and
# affect that are current NOW, not the ones that stood at write time. Default
# OFF: recall never mutates the store unless a store asks for it.
RECONSOLIDATE_SWITCH = "spatial_reconsolidate"
RECONSOLIDATE_ENV = "BIOCORE_SPATIAL_RECONSOLIDATE"

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


def zero_drift():
    """Drift of a coordinate that was never rewritten: nothing moved."""
    out = {axis: 0.0 for axis in AXES}
    out["weighted"] = 0.0
    return out


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


def _participants(entry):
    """People (or objects) this memory is about; [] when nobody named them."""
    entry = entry if isinstance(entry, dict) else {}
    raw = entry.get("participants")
    if isinstance(raw, str):
        raw = [raw]
    values = [str(item or "").strip() for item in (raw or [])
              if str(item or "").strip()]
    scope = str(entry.get("social_scope") or "").strip()
    if not values and scope:
        values = [scope]
    out = []
    for value in values:
        if value not in out:
            out.append(value[:32])
    return out[:8]


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


def _affect_values(entry, affect):
    """v / a for the affect axis.

    The host pipeline writes {"v","a"}; an engine entry keeps the same pair as
    {"valence","arousal"}. Read either, then the bare entry fields, then the
    neutral default -- the old {"v","a"} lookup keeps its exact priority.
    """
    def pick(primary, alias, default):
        for source in (affect, entry):
            if not isinstance(source, dict):
                continue
            for name in (primary, alias):
                if name in source:
                    return source[name]
        return default
    return pick("v", "valence", 0.0), pick("a", "arousal", 0.5)


def build(entry, relationship=None, now=None, embed=None, affect=None):
    """Five-axis coordinates for one entry; None when they cannot be built.

    The affect axis is PER ENTRY (Bower 1981; McGaugh 2004; Kensinger 2007):
    the entry's own affect always wins. Only when the entry carries none may a
    caller pass the session state that stood AT THE ENTRY'S ts -- never the
    state as it stands now, which would forge a history the entry never had.
    With neither, the axis is neutral and flagged fallback=True.
    """
    try:
        return _build(entry, relationship, now, embed, affect)
    except Exception:      # a broken entry never breaks the write
        return None


def _build(entry, relationship=None, now=None, embed=None, affect=None):
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
    stored_affect = entry.get("affect") if isinstance(entry.get("affect"), dict) else {}
    state_affect = affect if isinstance(affect, dict) else {}
    if stored_affect:
        affect_v, affect_a = _affect_values(entry, stored_affect)
        affect_fallback = False
    elif state_affect:
        affect_v, affect_a = _affect_values({"affect": state_affect}, state_affect)
        affect_fallback = False
    else:
        affect_v, affect_a = 0.0, 0.5
        affect_fallback = True
    trust = rel.get("trust", entry.get("trust", DEFAULT_TRUST))
    closeness = rel.get("closeness", entry.get("closeness", DEFAULT_CLOSENESS))
    participants = _participants(entry)
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
            "v": round(_clamp(affect_v, -1.0, 1.0), 6),
            "a": round(_clamp(affect_a), 6),
            # true = the entry carried no affect and no state-at-ts was given
            "fallback": affect_fallback,
        },
        "social": {
            "scope": str(entry.get("scope") or entry.get("session_id") or "default")[:64],
            # who the memory is about (Hastie & Kumar 1979): per-entry, never
            # guessed -- an empty list means the axis falls back to the global
            # relationship and says so.
            "participants": participants,
            "fallback": not bool(participants),
            "trust": round(_clamp(trust), 6),
            "closeness": round(_clamp(closeness), 6),
        },
        "activation": {
            "importance": round(_clamp(entry.get("importance", DEFAULT_IMPORTANCE)), 6),
            "hits": int(_num(entry.get("hits"), 1)),
            "retrieval_count": int(_num(entry.get("retrieval_count"), 0)),
            "last_hit_ts": round(_num(entry.get("last_hit_ts"), 0.0), 3),
        },
        # the event segment the entry belongs to (Zacks 2007); coordinates
        # stay per entry, the segment is an extra dimension
        "event": {"id": str(entry.get("event_id") or "")[:24],
                  "index": int(_num(entry.get("event_index"), 0))},
        # written by refresh(); a fresh coordinate is version 1, never rewritten
        "version": 1,
        "refreshed_at": 0.0,
        "drift": zero_drift(),
    }


def affect_at(series, ts):
    """The session state that stood at ts, from a [{ts, v, a}, ...] series.

    The only sanctioned way to give an entry an affect it does not carry
    itself: the point must be at or before the entry's ts. Never call this
    with the state as it stands now -- that would forge a past the entry
    never had.
    """
    moment = _num(ts, 0.0)
    best = None
    for row in series or []:
        if not isinstance(row, dict):
            continue
        stamp = _num(row.get("ts"), 0.0)
        if stamp <= moment and (best is None or stamp > best[0]):
            best = (stamp, row)
    if best is None:
        return None
    row = best[1]
    value_v = row.get("v", row.get("valence"))
    value_a = row.get("a", row.get("arousal"))
    if value_v is None and value_a is None:
        return None
    return {"v": round(_clamp(value_v, -1.0, 1.0), 6),
            "a": round(_clamp(value_a if value_a is not None else 0.5), 6)}


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
    """Who a memory is about first, the relationship inside that group second.

    Hastie & Kumar 1979: people file memories by person/object rather than by
    timestamp, so the participant sets are the primary distance (Jaccard) and
    trust/closeness only separates memories about the same people. Without
    participant information on either side the old scope+relationship formula
    runs unchanged, and the coordinate says fallback=True.
    """
    x = x if isinstance(x, dict) else {}
    y = y if isinstance(y, dict) else {}
    scope = 0.0 if str(x.get("scope") or "") == str(y.get("scope") or "") else 1.0
    spread = (abs(_num(x.get("trust"), DEFAULT_TRUST)
                  - _num(y.get("trust"), DEFAULT_TRUST))
              + abs(_num(x.get("closeness"), DEFAULT_CLOSENESS)
                    - _num(y.get("closeness"), DEFAULT_CLOSENESS))) / 2.0
    px = {str(item) for item in (x.get("participants") or []) if str(item)}
    py = {str(item) for item in (y.get("participants") or []) if str(item)}
    if px and py:
        union = px | py
        jaccard = 0.0 if not union else 1.0 - len(px & py) / float(len(union))
        return round(_clamp(0.75 * jaccard + 0.25 * spread), 6)
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
    """Lexicographic order over the axes; the old implementation, kept as the
    fallback for spatial_weighted=off."""
    row = distances if isinstance(distances, dict) else {}
    return tuple(_num(row.get(axis), 1.0) for axis in DISTANCE_ORDER)


# --------------------------------------------------------- weighted distance
# arXiv 2610.36308 (2026): an older version can outrank the answer even when it
# is inside the recall set, so ordering has to be a weighted trade-off instead
# of a strict axis priority. Howard & Kahana (2002): retrieval is anchored to
# the context of the QUESTION, not to "now" -- hence query_ts.
#
# Equal weights are a NEUTRAL engineering default: no axis is privileged and
# nothing was fitted. Everything configurable lives in core/config.py.
DEFAULT_WEIGHTS = dict(SPATIAL_WEIGHTS)
WEIGHTED_SWITCH = "spatial_weighted"
WEIGHTED_ENV = "BIOCORE_SPATIAL_WEIGHTED"
WEIGHTS_ENV = "BIOCORE_SPATIAL_WEIGHTS"


def weighted_enabled(flags=None, env=None):
    """spatial_weighted: explicit flag > nested switches > env > default ON."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(WEIGHTED_SWITCH), bool):
        return data[WEIGHTED_SWITCH]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(WEIGHTED_SWITCH), bool):
        return switches[WEIGHTED_SWITCH]
    environ = env if hasattr(env, "get") else None
    if environ is not None and WEIGHTED_ENV in environ:
        raw = str(environ.get(WEIGHTED_ENV)).strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return True
        if raw in ("0", "false", "off", "no"):
            return False
    return True


def reconsolidate_enabled(flags=None, env=None):
    """spatial_reconsolidate: flag > nested switches > env > default OFF."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(RECONSOLIDATE_SWITCH), bool):
        return data[RECONSOLIDATE_SWITCH]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(RECONSOLIDATE_SWITCH), bool):
        return switches[RECONSOLIDATE_SWITCH]
    environ = env if hasattr(env, "get") else None
    if environ is not None and RECONSOLIDATE_ENV in environ:
        raw = str(environ.get(RECONSOLIDATE_ENV)).strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return True
        if raw in ("0", "false", "off", "no"):
            return False
    return False


def weights(flags=None, env=None):
    """Axis weights, normalised to sum 1; bad config never breaks ranking."""
    data = flags if isinstance(flags, dict) else {}
    raw = data.get("spatial_weights")
    if not isinstance(raw, dict):
        raw = (data.get("switches") or {}).get("spatial_weights") \
            if isinstance(data.get("switches"), dict) else None
    environ = env if hasattr(env, "get") else None
    if not isinstance(raw, dict) and environ is not None:
        try:
            import json as _json
            raw = _json.loads(str(environ.get(WEIGHTS_ENV) or ""))
        except Exception:
            raw = None
    out = {}
    for axis in AXES:
        out[axis] = max(0.0, _num((raw or {}).get(axis), DEFAULT_WEIGHTS[axis])
                        if isinstance(raw, dict) else DEFAULT_WEIGHTS[axis])
    total = sum(out.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {axis: round(value / total, 6) for axis, value in out.items()}


def weighted_distance(distances, weights=None):
    """distance = sum(w_axis * d_axis); 0 is the query itself."""
    row = distances if isinstance(distances, dict) else {}
    w = weights if isinstance(weights, dict) else DEFAULT_WEIGHTS
    total = 0.0
    for axis in AXES:
        total += _num(w.get(axis), 0.0) * _num(row.get(axis), 1.0)
    return round(total, 6)


def sort_key(distances, query=None, base_weights=None, flags=None,
             env=None):
    """Ranking key for one candidate: weighted sum, or the old lexicographic
    order_key when spatial_weighted is off."""
    if not weighted_enabled(flags, env):
        return order_key(distances)
    base = (base_weights if isinstance(base_weights, dict)
            else weights(flags, env))
    return weighted_distance(distances, base)


# ------------------------------------------------------------------- index
# Above INDEX_THRESHOLD entries the semantic axis gets a sign-pattern LSH
# (Indyk & Motwani 1998): the bucket key is the sign of the first
# INDEX_PREFIX dims. The bucket is only a pruning structure -- the answer is
# still the exact top-k, because every bucket carries a unit centroid and a
# radius, which lower-bounds the cosine distance from the query to any member
# (|x - t| >= |c - t| - |x - c|, and 1 - cos = |x - t|^2 / 2 for unit vectors).
# Buckets whose bound cannot beat the k-th best are skipped; the rest are
# scanned exactly, so the bucketed answer and the full traversal agree.
INDEX_SWITCH = "spatial_index"
INDEX_ENV = "BIOCORE_SPATIAL_INDEX"
THRESHOLD_KEY = "spatial_index_threshold"
THRESHOLD_ENV = "BIOCORE_SPATIAL_INDEX_THRESHOLD"
INDEX_PREFIX = SPATIAL_INDEX_PREFIX
INDEX_THRESHOLD = SPATIAL_INDEX_THRESHOLD


def index_enabled(flags=None, env=None):
    """spatial_index: flag > nested switches > env > default ON."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(INDEX_SWITCH), bool):
        return data[INDEX_SWITCH]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(INDEX_SWITCH), bool):
        return switches[INDEX_SWITCH]
    environ = env if hasattr(env, "get") else None
    if environ is not None and INDEX_ENV in environ:
        raw = str(environ.get(INDEX_ENV)).strip().lower()
        if raw in ("0", "false", "off", "no"):
            return False
        if raw in ("1", "true", "on", "yes"):
            return True
    return True


def index_threshold(flags=None, env=None):
    """Entry count above which bucketing engages (default 5000)."""
    data = flags if isinstance(flags, dict) else {}
    raw = data.get(THRESHOLD_KEY)
    if raw is None and isinstance(data.get("switches"), dict):
        raw = data["switches"].get(THRESHOLD_KEY)
    environ = env if hasattr(env, "get") else None
    if raw is None and environ is not None and THRESHOLD_ENV in environ:
        raw = environ.get(THRESHOLD_ENV)
    try:
        value = int(float(raw))
    except Exception:
        value = int(INDEX_THRESHOLD)
    return max(0, value)


# ------------------------------------------------------- reconsolidation
# Nader 2000: a memory that is recalled is chemically rewritten by the act of
# recalling it, so a hit re-samples the coordinates with the relationship and
# the affect that are current NOW instead of the ones frozen at write time.
# The rewrite is stamped (version+1, refreshed_at) and the displacement it
# caused is recorded as drift, measured with the same per-axis distances the
# ranking uses -- a rewrite that moves nothing records zeros, not a lie.
def refresh(entry, relationship=None, affect=None, now=None, embed=None,
            base_weights=None):
    """Recompute one entry's coordinates; None when they cannot be built."""
    if not isinstance(entry, dict):
        return None
    old = entry.get("space") if isinstance(entry.get("space"), dict) else None
    view = entry
    if isinstance(affect, dict) and affect:
        view = dict(entry)
        view["affect"] = dict(affect)      # today's affect, not the stored one
    fresh = build(view, relationship, now=now, embed=embed)
    if not isinstance(fresh, dict):
        return None
    previous = int(_num((old or {}).get("version"), 1))
    fresh["version"] = (previous + 1) if isinstance(old, dict) else 1
    fresh["refreshed_at"] = round(_num(now, _num(entry.get("ts"), 0.0)), 3)
    if isinstance(old, dict):
        axes = distance(old, fresh)
        # Two coordinates that both carry no semantic information at all are
        # not 1.0 apart -- there is simply nothing to compare, so a rewrite
        # of a bare entry must not look like a semantic jump.
        if not _has_semantics(old) and not _has_semantics(fresh):
            axes["semantic"] = 0.0
        w = base_weights if isinstance(base_weights, dict) else weights()
        fresh["drift"] = dict(axes, weighted=weighted_distance(axes, w))
    else:
        fresh["drift"] = zero_drift()
    return fresh


def _has_semantics(space):
    """True when a semantic block carries a vector or at least one tag."""
    block = (space or {}).get("semantic") if isinstance(space, dict) else None
    block = block if isinstance(block, dict) else {}
    return bool(block.get("vector") or block.get("topics")
                or block.get("entities"))


def _coordinate_stamp(entry):
    """How recent a snapshot is: refreshed_at, then version, then entry ts."""
    entry = entry if isinstance(entry, dict) else {}
    space = entry.get("space") if isinstance(entry.get("space"), dict) else None
    if not isinstance(space, dict):
        return (0.0, 0, _num(entry.get("ts"), 0.0))
    return (_num(space.get("refreshed_at"), 0.0),
            int(_num(space.get("version"), 1)),
            _num(entry.get("ts"), 0.0))


def newer(old_entry, new_entry):
    """The coordinates written last among the two, or None."""
    best, best_key = None, None
    for entry in (old_entry, new_entry):
        if not isinstance(entry, dict):
            continue
        space = entry.get("space")
        if not isinstance(space, dict):
            continue
        key = _coordinate_stamp(entry)
        if best_key is None or key > best_key:
            best, best_key = space, key
    return best


def merge_space(old_entry, new_entry, removed_id=""):
    """Coordinates a merge keeps: the newer snapshot, plus its provenance.

    Nothing is recomputed here: a merge must not invent coordinates, only
    decide which snapshot survives. The ids that were folded into it travel in
    merged_from so a later reader can tell where a coordinate came from.
    """
    picked = newer(old_entry, new_entry)
    if not isinstance(picked, dict):
        return None
    out = json.loads(json.dumps(picked))
    history = []
    for entry in (old_entry, new_entry):
        space = entry.get("space") if isinstance(entry, dict) else None
        for item in (space or {}).get("merged_from") or []:
            text = str(item or "")
            if text and text not in history:
                history.append(text)
    if removed_id and str(removed_id) not in history:
        history.append(str(removed_id))
    if history:
        out["merged_from"] = history[-20:]
    return out


# ------------------------------------------------------------- displacement
# TransE (Bordes 2013): a relation is a translation, h + r ~= t. Two adjacent
# memories that talk about the same (subject, attribute) are a natural pair:
# the later one's coordinates minus the earlier one's are the displacement r.
# A changed mind ("改口") is visible as time running forward while the valence
# flips sign; every other step is an ordinary update.
def displacement(previous, entry, now=None):
    """Displacement between two adjacent memories about one fact, or None."""
    if not isinstance(previous, dict) or not isinstance(entry, dict):
        return None
    prev = (previous.get("space") if isinstance(previous.get("space"), dict)
            else build(previous, now=now))
    cur = (entry.get("space") if isinstance(entry.get("space"), dict)
           else build(entry, now=now))
    if not isinstance(prev, dict) or not isinstance(cur, dict):
        return None
    prev_sem = prev.get("semantic") or {}
    cur_sem = cur.get("semantic") or {}
    prev_vec = _vector({"vector": prev_sem.get("vector")})
    cur_vec = _vector({"vector": cur_sem.get("vector")})
    if prev_vec and cur_vec and len(prev_vec) == len(cur_vec):
        d_semantic = [round(b - a, 6) for a, b in zip(prev_vec, cur_vec)]
    else:
        d_semantic = []          # not comparable: never pretend a direction
    prev_aff = prev.get("affect") or {}
    cur_aff = cur.get("affect") or {}
    prev_v = _num(prev_aff.get("v"), 0.0)
    cur_v = _num(cur_aff.get("v"), 0.0)
    prev_ts = _num((prev.get("time") or {}).get("ts"), _num(previous.get("ts"), 0.0))
    cur_ts = _num((cur.get("time") or {}).get("ts"), _num(entry.get("ts"), 0.0))
    d_time = round(cur_ts - prev_ts, 3)
    flipped = (prev_v != 0.0 and cur_v != 0.0 and (prev_v * cur_v) < 0)
    return {"from_id": str(previous.get("id") or ""),
            "d_semantic": d_semantic,
            "d_time": d_time,
            "d_affect": {"v": round(cur_v - prev_v, 6),
                         "a": round(_num(cur_aff.get("a"), 0.5)
                                    - _num(prev_aff.get("a"), 0.5), 6)},
            "kind": "revision" if (d_time > 0 and flipped) else "update",
            "ts": round(cur_ts, 3)}


def shift_point(space, shift):
    """h + r: the coordinates a displacement predicts (a space-shaped dict)."""
    base = space if isinstance(space, dict) else {}
    row = shift if isinstance(shift, dict) else {}
    out = json.loads(json.dumps(base))
    sem = out.setdefault("semantic", {})
    vector = _vector({"vector": sem.get("vector")})
    d_semantic = row.get("d_semantic") if isinstance(row.get("d_semantic"), list) else []
    if vector and d_semantic and len(vector) == len(d_semantic):
        sem["vector"] = [round(v + d, 6) for v, d in zip(vector, d_semantic)]
        sem["vector_dim"] = len(sem["vector"])
    time_block = out.setdefault("time", {})
    time_block["ts"] = round(_num(time_block.get("ts"), 0.0)
                             + _num(row.get("d_time"), 0.0), 3)
    affect = out.setdefault("affect", {})
    d_affect = row.get("d_affect") if isinstance(row.get("d_affect"), dict) else {}
    affect["v"] = round(_clamp(_num(affect.get("v"), 0.0)
                               + _num(d_affect.get("v"), 0.0), -1.0, 1.0), 6)
    affect["a"] = round(_clamp(_num(affect.get("a"), 0.5)
                               + _num(d_affect.get("a"), 0.0)), 6)
    return out


def displacement_similar(entries, entry_id=None, limit=5, scope=None,
                         flags=None, env=None, base_weights=None):
    """Entries nearest to the point one memory's displacement predicts.

    h + r ~= t: start at the predecessor's coordinates, add the stored
    displacement, and the entries around that target are the ones that "belong
    to the same kind of move". Nothing is written; this is a read.
    """
    rows = [row for row in (entries or []) if isinstance(row, dict)
            and not row.get("deleted") and not row.get("archived")]
    if scope is not None:
        rows = [row for row in rows
                if str(row.get("scope") or "default") == str(scope or "default")]
    want = str(entry_id or "")
    if not want:
        return {"ok": False, "reason": "id_required", "results": []}
    source = next((row for row in rows if str(row.get("id") or "") == want), None)
    if source is None:
        return {"ok": False, "reason": "not_found", "id": want, "results": []}
    coords = source.get("space") if isinstance(source.get("space"), dict) else None
    shift = coords.get("displacement") if isinstance(coords, dict) else None
    if not isinstance(shift, dict):
        return {"ok": False, "reason": "no_displacement", "id": want,
                "results": []}
    from_id = str(shift.get("from_id") or "")
    anchor = next((row for row in rows if str(row.get("id") or "") == from_id), source)
    anchor_space = (anchor.get("space") if isinstance(anchor.get("space"), dict)
                    else build(anchor))
    if not isinstance(anchor_space, dict):
        return {"ok": False, "reason": "no_coordinates", "id": want,
                "results": []}
    target = shift_point(anchor_space, shift)
    base = base_weights if isinstance(base_weights, dict) else weights(flags, env)
    scored = []
    for position, row in enumerate(rows):
        row_id = str(row.get("id") or "")
        if row_id in (want, from_id):
            continue
        space = row.get("space") if isinstance(row.get("space"), dict) else build(row)
        if not isinstance(space, dict):
            continue
        distances = distance(space, target)
        scored.append((weighted_distance(distances, base), position,
                       {"id": row_id,
                        "text": str(row.get("text") or "")[:80],
                        "ts": round(_num(row.get("ts"), 0.0), 3),
                        "distance": distances,
                        "weighted": weighted_distance(distances, base)}))
    scored.sort(key=lambda item: (item[0], item[1]))
    cap = max(0, int(_num(limit, 5)))
    return {"ok": True, "id": want, "from_id": from_id,
            "kind": str(shift.get("kind") or ""), "target_ts":
            round(_num((target.get("time") or {}).get("ts"), 0.0), 3),
            "count": len(scored[:cap]),
            "results": [item[2] for item in scored[:cap]]}




def _unit(vector):
    if not vector:
        return None
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm <= 0:
        return None
    return [float(value) / norm for value in vector]


def _euclid(left, right):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _sign_key(vector, prefix=INDEX_PREFIX):
    """LSH bucket: the sign pattern of the first prefix semantic dims."""
    if not vector:
        return ""
    return "".join("1" if _num(value) >= 0 else "0" for value in vector[:prefix])


def build_buckets(entries, now=None, prefix=INDEX_PREFIX):
    """Semantic sign buckets, each with a unit centroid and a radius."""
    buckets = {}
    for position, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            continue
        space = entry.get("space") if isinstance(entry.get("space"), dict) else build(entry, now=now)
        if not isinstance(space, dict):
            continue
        vector = _vector({"vector": (space.get("semantic") or {}).get("vector")})
        key = _sign_key(vector, prefix)
        row = buckets.setdefault(key, {"rows": [], "units": []})
        row["rows"].append((position, entry, space))
        unit = _unit(vector)
        if unit is not None:
            row["units"].append(unit)
    for row in buckets.values():
        units = row["units"]
        row["centroid"], row["radius"], row["dim"] = None, 2.0, 0
        if units:
            dim = len(units[0])
            mean = [sum(unit[i] for unit in units) / float(len(units))
                    for i in range(dim)]
            centroid = _unit(mean)
            if centroid is not None:
                row["centroid"] = centroid
                row["radius"] = max(_euclid(unit, centroid) for unit in units)
            row["dim"] = dim
    return buckets


def _semantic_bound(bucket, target_unit, semantic_weight):
    """Lower bound on the semantic distance from the query to any member."""
    centroid = bucket.get("centroid")
    if target_unit is None or centroid is None:
        return 0.0
    if int(bucket.get("dim") or 0) != len(target_unit):
        return 0.0
    gap = max(0.0, _euclid(centroid, target_unit) - _num(bucket.get("radius"), 2.0))
    return _num(semantic_weight, 0.0) * 0.5 * gap * gap




# ------------------------------------------------ standardised axis distances
# Mahalanobis 1936: divide each axis distance by the store's own standard
# deviation for that axis, so an axis with a wide spread cannot outvote a
# narrow one just because of its units. Kriegeskorte & Kievit 2013: a dimension
# that does not vary carries no information, so an axis with (almost) no spread
# is dead and its weight goes to zero. Below the sample floor the statistics are
# not trusted and the equal-weight raw sum is used unchanged.
STANDARDIZE_SWITCH = "spatial_standardize"
STANDARDIZE_ENV = "BIOCORE_SPATIAL_STANDARDIZE"
MIN_SAMPLE = SPATIAL_STANDARDIZE_MIN_SAMPLE
DEAD_STD = SPATIAL_DEAD_AXIS_STD
PAIR_LIMIT = 512


def standardize_enabled(flags=None, env=None):
    """spatial_standardize: flag > nested switches > env > default ON."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(STANDARDIZE_SWITCH), bool):
        return data[STANDARDIZE_SWITCH]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(STANDARDIZE_SWITCH), bool):
        return switches[STANDARDIZE_SWITCH]
    environ = env if hasattr(env, "get") else None
    if environ is not None and STANDARDIZE_ENV in environ:
        raw = str(environ.get(STANDARDIZE_ENV)).strip().lower()
        if raw in ("0", "false", "off", "no"):
            return False
        if raw in ("1", "true", "on", "yes"):
            return True
    return True


def sample_pairs(spaces, sample_limit=PAIR_LIMIT):
    """Deterministic pairs with varying lag (not only neighbours).

    An evenly spaced store must not look like a dead time axis merely because
    consecutive gaps happen to match, so the lag grows to seven and wraps.
    """
    rows = [space for space in (spaces or []) if isinstance(space, dict)]
    pairs = []
    total = len(rows)
    for index in range(total):
        lag = 1 + (index % 7)
        other = index + lag
        if other >= total:
            other = index - lag
        if other < 0 or other == index:
            continue
        pairs.append((rows[index], rows[other]))
    if len(pairs) > sample_limit:
        step = max(1, len(pairs) // sample_limit)
        pairs = pairs[::step][:sample_limit]
    return pairs


def stats_of_spaces(spaces, sample_limit=PAIR_LIMIT):
    """Per-axis mean/std over consecutive pairs of the store's own spaces.

    Consecutive pairs keep it O(n), deterministic and independent of the query
    (the same scale is used for every question). None below the sample floor.
    """
    rows = [space for space in (spaces or []) if isinstance(space, dict)]
    if len(rows) < MIN_SAMPLE:
        return None
    pairs = sample_pairs(rows, sample_limit)
    values = {axis: [] for axis in AXES}
    for left, right in pairs:
        distances = distance(left, right)
        for axis in AXES:
            values[axis].append(_num(distances.get(axis), 0.0))
    out = {"sample": len(pairs), "entries": len(rows), "axes": {}}
    for axis, series in values.items():
        mean = sum(series) / float(len(series))
        variance = sum((value - mean) ** 2 for value in series) / float(len(series))
        std = math.sqrt(max(0.0, variance))
        out["axes"][axis] = {"mean": round(mean, 6), "std": round(std, 6),
                             "dead": bool(std < DEAD_STD)}
    return out


def axis_stats(entries, now=None):
    """Store-wide axis statistics for one entry pool (None: small sample)."""
    spaces = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        space = entry.get("space") if isinstance(entry.get("space"), dict) else build(entry, now=now)
        if isinstance(space, dict):
            spaces.append(space)
    return stats_of_spaces(spaces)


def dead_axes(stats):
    """Axes whose distances do not vary: no information, weight zero."""
    axes = (stats or {}).get("axes") or {}
    return [axis for axis in AXES
            if bool((axes.get(axis) or {}).get("dead"))]


def standardized_weights(stats, base=None):
    """w_axis / std_axis, normalised; dead axes get 0."""
    axes = (stats or {}).get("axes") or {}
    base = base if isinstance(base, dict) else weights()
    raw = {}
    for axis in AXES:
        row = axes.get(axis) or {}
        std = _num(row.get("std"), 0.0)
        if row.get("dead") or std <= 0:
            raw[axis] = 0.0
        else:
            raw[axis] = max(0.0, _num(base.get(axis), DEFAULT_WEIGHTS[axis])) / std
    total = sum(raw.values())
    if total <= 0:
        return {axis: 0.0 for axis in AXES}
    return {axis: round(value / total, 6) for axis, value in raw.items()}


def standardized_offset(stats, weights_map):
    """The constant a centred z-score sum carries: sum(w * mean / std)."""
    axes = (stats or {}).get("axes") or {}
    total = 0.0
    for axis in AXES:
        weight = _num((weights_map or {}).get(axis), 0.0)
        if weight <= 0:
            continue
        row = axes.get(axis) or {}
        std = _num(row.get("std"), 0.0)
        if std <= 0:
            continue
        total += weight * _num(row.get("mean"), 0.0) / std
    return round(total, 6)


def standardized_distance(distances, stats, weights_map):
    """sum(w_axis * (d_axis - mean_axis) / std_axis); dead axes contribute 0."""
    axes = (stats or {}).get("axes") or {}
    total = 0.0
    for axis in AXES:
        weight = _num((weights_map or {}).get(axis), 0.0)
        if weight <= 0:
            continue
        row = axes.get(axis) or {}
        std = _num(row.get("std"), 0.0)
        if std <= 0:
            continue
        total += weight * (_num((distances or {}).get(axis), 1.0)
                            - _num(row.get("mean"), 0.0)) / std
    return round(total, 6)


def standardize_report(stats, weights_map=None, flags=None, env=None):
    """What /state and the payloads report about the standardisation."""
    if not stats:
        return {"mode": "raw", "dead_axes": [],
                "reason": ("switch_off" if not standardize_enabled(flags, env)
                           else "small_sample")}
    axes = stats.get("axes") or {}
    return {"mode": "zscore", "sample": int(stats.get("sample") or 0),
            "entries": int(stats.get("entries") or 0),
            "dead_axes": dead_axes(stats),
            "axis_std": {axis: round(_num((axes.get(axis) or {}).get("std"), 0.0), 6)
                         for axis in AXES},
            "weights": dict(weights_map or {})}

def rank_bucketed(entries, query, query_ts=None, now=None, limit=None,
                  base_weights=None, flags=None, env=None, vector=None):
    """Exact top-k over sign buckets; the rows match rank() row for row."""
    anchor = _num(query_ts if query_ts is not None else now, 0.0)
    target = query_space(query, vector=vector, now=anchor)
    base = (base_weights if isinstance(base_weights, dict)
            else weights(flags, env))
    used = base
    buckets = build_buckets(entries, now=anchor)
    # pool order, not bucket order: the consecutive-pair statistics must be
    # the same ones the exact path computes, or the two paths cannot agree
    ordered = sorted((position, space) for bucket in buckets.values()
                     for position, _, space in bucket["rows"])
    spaces = [space for _, space in ordered]
    stats = (stats_of_spaces(spaces) if standardize_enabled(flags, env) else None)
    std_weights = standardized_weights(stats, used) if stats else None
    offset = standardized_offset(stats, std_weights) if stats else 0.0
    axes = (stats or {}).get("axes") or {}
    sem_std = _num((axes.get("semantic") or {}).get("std"), 0.0)
    sem_factor = (_num((std_weights or {}).get("semantic"), 0.0) / sem_std
                  if sem_std > 0 else 0.0)
    target_unit = _unit(_vector({"vector": (target.get("semantic") or {}).get("vector")}))
    plan = []
    for key, bucket in buckets.items():
        lower = _semantic_bound(bucket, target_unit, 1.0)
        bound = ((sem_factor * lower - offset) if stats
                 else _semantic_bound(bucket, target_unit,
                                      used.get("semantic")))
        plan.append((bound, str(key)))
    plan.sort(key=lambda item: (item[0], item[1]))
    keep = []
    scanned = 0
    for bound, key in plan:
        if limit is not None and len(keep) >= limit:
            keep.sort(key=lambda item: (item[0], item[1]))
            if bound > keep[limit - 1][0]:
                break        # every member is strictly farther than this bound
        for position, entry, space in buckets[key]["rows"]:
            distances = distance(space, target)
            raw = weighted_distance(distances, used)
            if stats:
                value = standardized_distance(distances, stats, std_weights)
            else:
                value = raw
            row = {"id": str(entry.get("id") or ""),
                   "text": str(entry.get("text") or "")[:80],
                   "ts": round(_num(entry.get("ts"), 0.0), 3),
                   "distance": distances,
                   "weighted": value,
                   "weighted_raw": raw,
                   "lexicographic": list(order_key(distances))}
            keep.append((value, position, row))
            scanned += 1
    keep.sort(key=lambda item: (item[0], item[1]))
    rows = [item[2] for item in keep]
    if limit is not None:
        rows = rows[:max(0, int(_num(limit, len(rows))))]
    return {"ok": True, "query": str(query or ""),
            "query_ts": round(anchor, 3), "weights": used,
            "mode": "weighted", "count": len(rows), "results": rows,
            "standardize": standardize_report(stats, std_weights, flags, env),
            "index": {"mode": "bucketed", "buckets": len(buckets),
                      "scanned": scanned, "prefix": INDEX_PREFIX,
                      "pool": len([row for row in (entries or [])
                                   if isinstance(row, dict)])}}

def rank(entries, query, query_ts=None, now=None, limit=None,
         base_weights=None, flags=None, env=None, vector=None):
    """Nearest entries to a question asked at query_ts (default: now).

    Rows keep the per-axis distances, the weighted total (raw and
    standardized when the switch is on) and the old lexicographic key, so a
    caller can compare both orders.
    """
    anchor = _num(query_ts if query_ts is not None else now, 0.0)
    target = query_space(query, vector=vector, now=anchor)
    base = (base_weights if isinstance(base_weights, dict)
            else weights(flags, env))
    used = base
    weighted_on = weighted_enabled(flags, env)
    prepared = []
    for entry in [row for row in (entries or []) if isinstance(row, dict)]:
        space = entry.get("space")
        if not isinstance(space, dict):
            space = build(entry, now=anchor)
        if not isinstance(space, dict):
            continue
        prepared.append((entry, space))
    spaces = [space for _, space in prepared]
    stats = (stats_of_spaces(spaces) if standardize_enabled(flags, env) else None)
    std_weights = standardized_weights(stats, used) if stats else None
    rows = []
    for position, (entry, space) in enumerate(prepared):
        distances = distance(space, target)
        raw = weighted_distance(distances, used)
        value = (standardized_distance(distances, stats, std_weights)
                 if stats else raw)
        rows.append((position, {"id": str(entry.get("id") or ""),
                                "text": str(entry.get("text") or "")[:80],
                                "ts": round(_num(entry.get("ts"), 0.0), 3),
                                "distance": distances,
                                "weighted": value,
                                "weighted_raw": raw,
                                "lexicographic": list(order_key(distances))}))
    if weighted_on:
        rows.sort(key=lambda item: (item[1]["weighted"], item[0]))
    else:
        rows.sort(key=lambda item: (item[1]["lexicographic"], item[0]))
    out = [row for _, row in rows]
    if limit is not None:
        out = out[:max(0, int(_num(limit, len(out))))]
    return {"ok": True, "query": str(query or ""), "query_ts": round(anchor, 3),
            "weights": used,
            "mode": ("weighted" if weighted_on else "lexicographic"),
            "standardize": standardize_report(stats, std_weights, flags, env),
            "count": len(out), "results": out,
            "index": {"mode": "exact", "buckets": 0, "scanned": len(out),
                      "prefix": INDEX_PREFIX, "pool": len(spaces)}}


# ------------------------------------------------------- full-store selection
SELECT_SWITCH = "spatial_select"
SELECT_ENV = "BIOCORE_SPATIAL_SELECT"
DEPTH_KEY = "spatial_depth"
DEPTH_ENV = "BIOCORE_SPATIAL_DEPTH"


def select_enabled(flags=None, env=None):
    """spatial_select: explicit flag > nested switches > env > default OFF."""
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(SELECT_SWITCH), bool):
        return data[SELECT_SWITCH]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SELECT_SWITCH), bool):
        return switches[SELECT_SWITCH]
    environ = env if hasattr(env, "get") else None
    if environ is not None and SELECT_ENV in environ:
        raw = str(environ.get(SELECT_ENV)).strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return True
        if raw in ("0", "false", "off", "no"):
            return False
    return False


def depth(flags=None, env=None, default=None):
    """Candidate cap: flags > nested switches > env > core/config.py."""
    data = flags if isinstance(flags, dict) else {}
    raw = data.get(DEPTH_KEY)
    if raw is None and isinstance(data.get("switches"), dict):
        raw = data["switches"].get(DEPTH_KEY)
    environ = env if hasattr(env, "get") else None
    if raw is None and environ is not None and DEPTH_ENV in environ:
        raw = environ.get(DEPTH_ENV)
    base = SPATIAL_SELECT_DEPTH if default is None else default
    try:
        value = int(float(raw))
    except Exception:
        value = int(base)
    return max(1, value)


def select(entries, query, query_ts=None, now=None, limit=None, scope=None,
           flags=None, env=None, vector=None, base_weights=None):
    """Top-N entries over the WHOLE pool by weighted five-axis distance."""
    pool = [row for row in (entries or [])
            if isinstance(row, dict) and not row.get("deleted")
            and not row.get("archived")]
    if scope is not None:
        pool = [row for row in pool
                if str(row.get("scope") or "default") == str(scope or "default")]
    cap = depth(flags, env) if limit is None else max(0, int(_num(limit, 0)))
    if (index_enabled(flags, env) and len(pool) >= index_threshold(flags, env)):
        ranked = rank_bucketed(pool, query, query_ts=query_ts, now=now,
                               limit=cap, base_weights=base_weights,
                               flags=flags, env=env, vector=vector)
    else:
        ranked = rank(pool, query, query_ts=query_ts, now=now, limit=cap,
                      base_weights=base_weights, flags=flags, env=env,
                      vector=vector)
    results = ranked.get("results") or []
    return {"ok": bool(ranked.get("ok")), "query": ranked.get("query", ""),
            "query_ts": ranked.get("query_ts"),
            "pool": len(pool), "depth": cap,
            "ids": [row.get("id") for row in results],
            "count": len(results), "results": results,
            "mode": ranked.get("mode"), "weights": ranked.get("weights"),
            "standardize": ranked.get("standardize")
            or {"mode": "raw", "dead_axes": []},
            "index": ranked.get("index") or {"mode": "exact"}}


def query_space(query, vector=None, now=None, embed=None):
    """Coordinates for a bare query string (same five axes, no id)."""
    return build({"text": query, "vector": vector or [],
                  "ts": _num(now, 0.0), "tags": tokens(query),
                  "importance": DEFAULT_IMPORTANCE}, now=now, embed=embed)


def probe(entries, entry_id=None, query=None, vector=None, limit=5, now=None,
          flags=None, env=None):
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
                        "reason": "" if space is not None else "no_space"}
        return {"ok": False, "reason": "not_found", "id": want}
    if query:
        anchor = _num(now, 0.0)
        target = query_space(query, vector=vector, now=anchor)
        scored = []
        for row in rows:
            stored = row.get("space")
            space = stored if isinstance(stored, dict) else build(row, now=anchor)
            if not isinstance(space, dict):
                continue
            distances = distance(space, target)
            scored.append({"id": str(row.get("id") or ""),
                           "text": str(row.get("text") or "")[:80],
                           "ts": round(_num(row.get("ts"), 0.0), 3),
                           "distance": distances,
                           "weighted": weighted_distance(distances, weights(flags, env)),
                           "from": "entry" if isinstance(stored, dict) else "computed"})
        scored.sort(key=lambda item: sort_key(item["distance"], query,
                                             flags=flags, env=env))
        return {"ok": True, "query": str(query), "count": len(scored),
                "limit": limit, "order": list(DISTANCE_ORDER),
                "mode": ("weighted" if weighted_enabled(flags, env)
                         else "lexicographic"),
                "space": target, "results": scored[:limit]}
    return {"ok": False, "reason": "id_or_query_required"}
