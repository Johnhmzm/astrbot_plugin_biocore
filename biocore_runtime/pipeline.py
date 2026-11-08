# -*- coding: utf-8 -*-
"""BioCore runtime pipeline: capture / inject / gate / tools policy in Python.

CONTRACT
--------
This module is the single policy owner. Node (DSH) only forwards JSON and
executes the returned action. It never imports astrbot and never renders a full
prompt by itself.

CLI (one JSON line in stdin, one JSON line out):

    python biocore_runtime/pipeline.py <action>
      inject        in {phase, session_id, user_text, state, switches}
                    out {ok, text, phase, chars, sections}
      gate          in {reply, user_text, switches}
                    out {ok, blocked, action: pass|replace, text, rule, label}
      capture       in {session_id, role, text, switches, store?}
                    out {ok, captured, reason, entry_id?}
      tool          in {name, args, session_id, switches, store?}
                    out {ok, result}   (result 不含 ok，内层 ok 拍平到外层)
      memory_inject in {session_id, store?, max_chars?, top_k?}
                    out {ok, text, chars, ids}
      trace         in {session_id, store?, limit?}
                    out {ok, rows}  (read-only; rows are trace JSONL entries)

turn_end writes one diagnostic row to <store>/traces/<session_id>.jsonl,
keeping the newest 50; diagnostics never change gate/capture behaviour.
      proactive_tick in {session_id, last_human_ts, switches, store?, now?}
                    out {ok, should_send, text, reason, gap_minutes}

Four switch keys, all default false in every environment:
  safety_enabled / boundary_enabled / crisis_safety_enabled / proactive_send
proactive_autonomy is accepted only as a read-side alias for proactive_send.

Relationship is user-level, not session-level (relationship_shared defaults true):
<store>/relationship.json holds trust/closeness/conflict/attachment_style/bids/
days_known; turn_start merges it into the session state and turn_end folds the
bounded per-turn change back (trust/closeness/conflict <= 0.02 per turn, versioned
+ lock file; relationship_shared=false keeps the old per-session behaviour).
Session state stays <store>/sessions/<session_id>/state.json for mood/stress/etc.

Storage layout: <store>/sessions/<session_id>/memory.json and
<store>/sessions/<session_id>/capture_state.json. Default store root comes from
payload.store, then env BIOCORE_MEMORY_STORE, then <plugin>/data/memory.

Python functions (import path: biocore_runtime.pipeline):
  capture_decision(session_id, role, text, state) -> {capture, reason, ...}
  capture(session_id, role, text, store, config=None) -> {ok, decision, entry}
  inject_block(session_id, store, max_chars=420, top_k=5) -> {text, chars, ids}
  gate_reply(reply_text, flags) -> {hit, blocked, action, rule, text}
  prompt_block(payload) -> {ok, phase, text, chars, sections}
  tool_call(name, args, store) -> remember / recall / forget result
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

# Running as a script: make the plugin root importable for biocore_model.
_PLUGIN_ROOT = str(Path(__file__).resolve().parents[1])
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

MAX_CHARS = 420           # [engineering] default budget when the caller says nothing
INJECT_MAX_CHARS = 12000  # [engineering] ceiling for an explicit caller request
EVENT_CAP_MODE = os.environ.get("BIOCORE_EVENT_CAP_MODE") or "flat"
# [engineering] how many turns an event may render:
#   flat = always 5, no event is ever skipped (default)
#   hint = the claim-density hint decides (off by default: P01 measured 78/88
#          with the hint vs 79/88 flat, a difference inside the noise band, and
#          the guard row below already keeps the best-matching turn)
#   min3 = at least 3, so a dense-note event still shows its best turn
EVENT_CAP_STATS = {"events": 0, "skipped": 0, "rows": 0}
ADAPTIVE_WINDOW = int(os.environ.get("BIOCORE_ADAPTIVE_WINDOW") or 200)
# [engineering] the drift threshold is learned from the *recent* distribution:
# scanning the whole session on every recall grew with the store and never
# mattered (old turns cannot change the current boundary)
_THR_MEMO = {"stamp": None, "thr": None}
SENT_POOL = int(os.environ.get("BIOCORE_SENT_POOL") or 0)
# [engineering] 0 = every row of the event competes for the cap; N = only the
# N best rows by cosine do, so a long noisy event cannot flood the block
# [engineering] every knob that decides segmentation reads an env override:
# a value that decides behaviour is configuration, not a constant to recompile.
EVENT_SIM_CLOSE = float(os.environ.get("BIOCORE_EVENT_SIM_CLOSE") or 0.30)
# below EVENT_SIM_CLOSE a turn starts a new event
EVENT_MAX_TURNS = int(os.environ.get("BIOCORE_EVENT_MAX_TURNS") or 8)
# 0 = no hard cap; else split at N turns
EVENT_MAX_CHARS = int(os.environ.get("BIOCORE_EVENT_MAX_CHARS") or 900)  # safety net
EVENT_GAP_S = float(os.environ.get("BIOCORE_EVENT_GAP_S") or 86400.0)
# a day of silence also splits an event
TOP_K = 5                 # [engineering]
INJECT_MAX_K = 10          # inject_block may ask for more when rerank prunes
INJECT_MODES = ("query", "recent")
HOURLY_CAP = 20           # [engineering] product rate limit, not a memory theory
MIN_CHARS = 8             # [engineering]
MAX_TEXT_CHARS = 2000     # [engineering]
MAX_STATE_CHARS = 200     # [engineering]
MAX_ENTRIES = 500         # [engineering]
SESSION_MAX_LEN = 80
_HOUR = 3600.0
_WS = re.compile(r"\s+")
_SESSION_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_LATIN = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")

try:
    from biocore_model import boundary_gate as _boundary_gate
except Exception:  # pragma: no cover - only when the plugin root is absent
    _boundary_gate = None

try:
    from biocore_model import intero_core as _intero_core
except Exception:  # pragma: no cover
    _intero_core = None

try:
    from biocore_runtime import rerank as _rerank_mod
except Exception:  # pragma: no cover
    _rerank_mod = None

try:  # task-221: one global core state shared by every session
    from . import core_state as _core_state
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import core_state as _core_state
    except Exception:
        _core_state = None

try:  # task-223: memory governance + relationship accumulation
    from . import governance as _governance
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import governance as _governance
    except Exception:
        _governance = None
try:
    from . import relationship_state as _relationship_state
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import relationship_state as _relationship_state
    except Exception:
        _relationship_state = None
try:  # task-62: normalized channels / chunks / shards / prediction
    from . import retrieval_plus as _retrieval_plus
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import retrieval_plus as _retrieval_plus
    except Exception:
        _retrieval_plus = None
try:  # contract migration 1: cache stats in the core
    from . import cache_stats as _cache_stats
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import cache_stats as _cache_stats
    except Exception:
        _cache_stats = None
try:  # task-36 + task-78: tier hysteresis / reconsolidation / repair
    from . import lifecycle as _lifecycle
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import lifecycle as _lifecycle
    except Exception:
        _lifecycle = None
try:  # task-225: P0 memory + expression extensions
    from . import extensions as _extensions
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import extensions as _extensions
    except Exception:
        _extensions = None
try:  # task-224: P0 perception/relationship/self signals
    from . import signals as _signals
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import signals as _signals
    except Exception:
        _signals = None
try:  # task-222: self layer + autonomy
    from . import self_layer as _self_layer
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import self_layer as _self_layer
    except Exception:
        _self_layer = None
try:
    from . import autonomy as _autonomy
except Exception:  # pragma: no cover
    try:
        from biocore_runtime import autonomy as _autonomy
    except Exception:
        _autonomy = None

try:
    from biocore_model import sanitize as _sanitize
except Exception:  # pragma: no cover
    _sanitize = None

try:  # task-244: shadow coordinates for memory entries (write-only, switch off)
    from biocore_memory import space as _space
except Exception:  # pragma: no cover
    try:
        from .biocore_memory import space as _space
    except Exception:
        _space = None

try:  # near-duplicate, newer wins (a separate mechanism from versioning)
    from biocore_memory.store import near_dup as _near_dup
except Exception:  # pragma: no cover
    try:
        from .biocore_memory.store import near_dup as _near_dup
    except Exception:
        _near_dup = None

try:  # coverage select: pick k from the pool by five-axis spread
    from biocore_memory.recall import cover as _cover
except Exception:  # pragma: no cover
    try:
        from .biocore_memory.recall import cover as _cover
    except Exception:
        _cover = None

try:  # point-expand: hits first, then the neighbour memories of each hit
    from biocore_memory.recall import point_expand as _point_expand
except Exception:  # pragma: no cover
    try:
        from .biocore_memory.recall import point_expand as _point_expand
    except Exception:
        _point_expand = None

try:  # segment recall (Zacks 2007 / TextTiling): the retrieval unit is the event
    from biocore_memory.recall import segments as _segments
except Exception:  # pragma: no cover
    try:
        from .biocore_memory.recall import segments as _segments
    except Exception:
        _segments = None

try:  # event segmentation (Zacks 2007): one segment per stretch of a session
    from biocore_memory.event import segment as _segment
except Exception:  # pragma: no cover
    try:
        from .biocore_memory.event import segment as _segment
    except Exception:
        _segment = None

try:  # usage feedback + axis-weight learning (spatial_feedback / spatial_learn)
    from biocore_memory import space_learning as _learning
except Exception:  # pragma: no cover
    try:
        from .biocore_memory import space_learning as _learning
    except Exception:
        _learning = None

try:  # arXiv 2610.36308: same-key version resolution (superseded / disputed)
    from biocore_memory.store import versioning as _versioning
except Exception:  # pragma: no cover
    try:
        from .biocore_memory.store import versioning as _versioning
    except Exception:
        _versioning = None

try:  # task-228: the shared field + its write-back arbiter (pure, optional)
    from biocore_runtime import field as _field_mod
    from biocore_runtime import arbiter as _arbiter_mod
except Exception:  # pragma: no cover
    try:
        from . import field as _field_mod
        from . import arbiter as _arbiter_mod
    except Exception:
        _field_mod = _arbiter_mod = None

try:  # task-230: indicative priority from field surprise
    from biocore_runtime import priority as _priority
except Exception:  # pragma: no cover
    try:
        from . import priority as _priority
    except Exception:
        _priority = None

try:  # task-234 (batch A1): the twelve perception/appraisal modules
    from biocore_runtime import perception as _perception
except Exception:  # pragma: no cover
    try:
        from . import perception as _perception
    except Exception:
        _perception = None

try:  # task-236/238/239: the batch hooks + their registry
    from biocore_runtime import batch_registry as _batch_registry
    from biocore_runtime import batch_b as _batch_b
    from biocore_runtime import batch_d as _batch_d
    from biocore_runtime import batch_e as _batch_e
except Exception:  # pragma: no cover
    try:
        from . import batch_registry as _batch_registry
        from . import batch_b as _batch_b
        from . import batch_d as _batch_d
        from . import batch_e as _batch_e
    except Exception:
        _batch_registry = _batch_b = _batch_d = _batch_e = None

try:  # batch C was written independently and may be absent in a stripped tree
    from biocore_runtime import batch_c as _batch_c
except Exception:  # pragma: no cover
    try:
        from . import batch_c as _batch_c
    except Exception:
        _batch_c = None

try:  # task-229: the three time scales
    from biocore_runtime import timescales as _timescales
except Exception:  # pragma: no cover
    try:
        from . import timescales as _timescales
    except Exception:
        _timescales = None

try:  # task-243: N-dimensional ontology (explicit / implicit, no sums)
    from biocore_runtime import dimensions as _dimensions
except Exception:  # pragma: no cover
    try:
        from . import dimensions as _dimensions
    except Exception:
        _dimensions = None

try:  # task-243 段2: the expression policy (mode + wording hints only)
    from biocore_runtime import expression as _expression
except Exception:  # pragma: no cover
    try:
        from . import expression as _expression
    except Exception:
        _expression = None

try:  # self-layer modules (all pure; optional so a stripped checkout still runs)
    from biocore_model import x_directives as _x_directives
    from biocore_model import self_intent as _self_intent
    from biocore_model import value_order as _value_order
    from biocore_model import boundary as _boundary
    from biocore_model import secrecy as _secrecy
    from biocore_model import narrative as _narrative
    from biocore_model import dissonance as _dissonance
    from biocore_model import attributor as _attributor
except Exception:  # pragma: no cover
    _x_directives = _self_intent = _value_order = None
    _boundary = _secrecy = _narrative = _dissonance = _attributor = None


# ---------------------------------------------------------------- utilities
def clean_text(value, limit=MAX_TEXT_CHARS):
    text = _WS.sub(" ", str(value or "")).strip()
    return text[:max(0, int(limit))]


def sanitize_session_id(session_id):
    raw = str(session_id or "").strip()[:SESSION_MAX_LEN]
    raw = _SESSION_SAFE.sub("_", raw).strip("._-")
    return raw or "default"


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    return bool(default)


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    return number if math.isfinite(number) else float(default)


def _clamp(value, low, high):
    return max(low, min(high, value))


def _affect_pair_from(value):
    """Normalize a caller's affect into {"v", "a"}; None when unusable."""
    block = value if isinstance(value, dict) else None
    if block is None:
        return None
    v = block.get("v", block.get("valence"))
    a = block.get("a", block.get("arousal"))
    if v is None and a is None:
        return None
    return {"v": _clamp(_num(v, 0.0), -1.0, 1.0),
            "a": _clamp(_num(a, 0.5), 0.0, 1.0)}


def _affect_from_state(state):
    """(v, a) from a state the pipeline already holds; None when absent."""
    block = state if isinstance(state, dict) else {}
    core = block.get("core") if isinstance(block.get("core"), dict) else block
    if not isinstance(core, dict):
        return None
    if core.get("v") is None and core.get("a") is None:
        return None
    return _affect_pair_from({"v": core.get("v"), "a": core.get("a")})


def _int_param(value, default, low, high):
    try:
        number = int(value)
    except Exception:
        number = int(default)
    return max(low, min(high, number))


SWITCH_KEYS = ("safety_enabled", "boundary_enabled",
               "crisis_safety_enabled", "proactive_send")
SWITCH_DEFAULTS = {key: False for key in SWITCH_KEYS}
_SWITCH_ALIASES = {"proactive_autonomy": "proactive_send"}


def normalize_switches(value):
    """Four switches, all default false; proactive_autonomy aliases proactive_send."""
    data = value if isinstance(value, dict) else {}
    out = dict(SWITCH_DEFAULTS)
    for key in SWITCH_KEYS:
        if key in data:
            out[key] = _as_bool(data.get(key), False)
    if "proactive_send" not in data and "proactive_autonomy" in data:
        out["proactive_send"] = _as_bool(data.get("proactive_autonomy"), False)
    return out


def _default_store():
    env = str(os.environ.get("BIOCORE_MEMORY_STORE") or "").strip()
    if env:
        return env
    return str(Path(_PLUGIN_ROOT) / "data" / "memory")


def _store_root(store):
    if isinstance(store, dict):
        root = store.get("root") or store.get("store") or store.get("path")
        return Path(str(root)) if root else None
    if isinstance(store, (str, os.PathLike)):
        text = str(store or "").strip()
        return Path(text) if text else None
    return None


# ---------------------------------------------------------------- storage
def session_dir(store, session_id):
    root = _store_root(store)
    if root is None:
        return None
    return root / "sessions" / sanitize_session_id(session_id)


def memory_path(store, session_id):
    directory = session_dir(store, session_id)
    return (directory / "memory.json") if directory is not None else None


def capture_state_path(store, session_id):
    directory = session_dir(store, session_id)
    return (directory / "capture_state.json") if directory is not None else None


def _empty_doc(session_id):
    return {"schema_version": 1, "session_id": sanitize_session_id(session_id),
            "entries": []}


def _load_json(path, fallback):
    try:
        if path is None or not Path(path).exists():
            return fallback
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


STORE_MODE_ENV = "BIOCORE_STORE"
_MEM_DOC_CACHE = {}          # db path -> (mtime_ns, size, doc, {id: raw json})
_MEM_DOC_CACHE_MAX = 8


def store_mode():
    """sqlite (default) | json (rollback: the old single-file behaviour).

    One switch for the whole store, deliberately coarse: mixing the two backends
    per call is what produced the position drift this task started from.
    """
    value = str(os.environ.get(STORE_MODE_ENV) or "").strip().lower()
    return "json" if value in ("json", "legacy", "file") else "sqlite"


def _sql_store():
    from biocore_memory.store import sql_store
    return sql_store


_EVEC_CACHE = {}             # db path -> (mtime_ns, size, {id: vector})
_EVEC_CACHE_MAX = 4


VECTOR_META_KEYS = ("embed_model", "dim", "embed_metric", "rerank_model")


def _vector_space_config(store):
    """The embedding/rerank config this store should be using (one combo)."""
    try:
        from biocore_memory.recall import providers as _prov
    except Exception:
        return None, None
    try:
        cfg = _load_runtime_config(store) if store else {}
    except Exception:
        cfg = {}
    # a missing config file is "unknown", NOT "use the defaults": resolving the
    # defaults here is how a store ended up stamped bge-m3 while a Qwen model
    # produced the vectors
    data_dir = _store_data_dir(store) if store else None
    if not cfg or (data_dir is not None and not (Path(data_dir) / CORE_CONFIG_FILE).exists()):
        return None, None
    try:
        embed_cfg = _prov.resolve_embedding_config(cfg)
    except Exception:
        embed_cfg = None
    try:
        rerank_cfg = _prov.resolve_rerank_config(cfg)
    except Exception:
        rerank_cfg = None
    return embed_cfg, rerank_cfg


def _read_vector_meta(root, session_id):
    try:
        store_api = _sql_store()
        conn = store_api.connect(root, session_id)
        try:
            rows = conn.execute("SELECT k, v FROM meta").fetchall()
        finally:
            conn.close()
    except Exception:
        return {}
    return {str(k): str(v) for k, v in rows}


def _write_vector_meta(root, session_id, meta):
    if not meta:
        return False
    try:
        store_api = _sql_store()
        conn = store_api.connect(root, session_id)
        try:
            for key, value in meta.items():
                conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)"
                             " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                             (str(key), str(value)))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def ensure_vector_space(store, session_id, embed_cfg=None, rerank_cfg=None):
    """Refuse to read a store whose vectors came from another model/dimension.

    Cosine across two embedding spaces is a number with no meaning, and its only
    symptom is a ranking that quietly went wrong. So this raises with the two
    dimensions, the two models and the command that rebuilds the store.
    """
    try:
        from biocore_memory.recall.providers import EmbeddingSpaceMismatch
    except Exception:
        return {}
    root = _store_root(store)
    if root is None:
        return {}
    session_id = sanitize_session_id(session_id)
    if embed_cfg is None or rerank_cfg is None:
        cfg_embed, cfg_rerank = _vector_space_config(store)
        embed_cfg = embed_cfg if embed_cfg is not None else cfg_embed
        rerank_cfg = rerank_cfg if rerank_cfg is not None else cfg_rerank
    meta = _read_vector_meta(root, session_id)
    known_model = str(meta.get("embed_model") or "")
    known_dim = int(_num(meta.get("dim"), 0))
    want_model = str((embed_cfg or {}).get("model") or "")
    want_dim = int((embed_cfg or {}).get("dim") or 0)
    problems = []
    if known_model and want_model and known_model != want_model:
        problems.append("model %r -> %r" % (known_model, want_model))
    if known_dim and want_dim and known_dim != want_dim:
        problems.append("dim %d -> %d" % (known_dim, want_dim))
    if problems:
        raise EmbeddingSpaceMismatch(
            "store %s was built with a different embedding space (%s). "
            "Vector spaces cannot be mixed. Rebuild it with: "
            "python -m biocore_memory.adapters.dsh_cli reembed --store %s --session %s"
            % (str(root), ", ".join(problems), str(root), session_id))
    update = {}
    if want_model and meta.get("embed_model") != want_model:
        update["embed_model"] = want_model
    if want_dim and str(meta.get("dim")) != str(want_dim):
        update["dim"] = want_dim
    if (embed_cfg or {}).get("normalize") is not None:
        update.setdefault("embed_metric", "cosine")
    if rerank_cfg is not None and rerank_cfg.get("model"):
        update.setdefault("rerank_model", rerank_cfg.get("model"))
    if update:
        _write_vector_meta(root, session_id, update)
    return dict(meta, **update)


def reembed_store(store, session_id, provider=None, batch_size=32):
    """Rebuild every vector in this store with the configured provider.

    The only supported way out of an EmbeddingSpaceMismatch: recompute the
    entries, re-derive the event centroids from the new vectors, and stamp the
    new space into the meta. Old vectors are never blended with new ones.
    """
    root = _store_root(store)
    if root is None:
        return {"ok": False, "reason": "no_store"}
    session_id = sanitize_session_id(session_id)
    embed_cfg, rerank_cfg = _vector_space_config(store)
    want_model = str((embed_cfg or {}).get("model") or "")
    if not want_model:
        raise ValueError(
            "reembed: embedding 配置未加载（core_config.json 缺失或键名不匹配）——"
            "拒绝用默认模型名写 meta，否则向量是 A 模型算的、meta 记成 B 模型")
    if provider is None:
        try:
            from biocore_memory.recall import providers as _prov
            provider = _prov.load_embedding_provider(embed_cfg)
        except Exception as exc:
            return {"ok": False, "reason": "no_provider", "detail": type(exc).__name__}
    actual_model = str(getattr(provider, "model", "") or "")
    if actual_model and actual_model != want_model:
        raise ValueError(
            "reembed: provider 实际模型 %r 与配置模型 %r 不一致——"
            "检查 core_config.json 的 embedding 键是否被加载（键名不匹配/嵌套层错）"
            % (actual_model, want_model))
    doc = load_memory(store, session_id)
    entries = [row for row in doc.get("entries") or [] if isinstance(row, dict)]
    texts = [str(row.get("text") or "") for row in entries]
    vectors = []
    for start in range(0, len(texts), max(1, int(batch_size))):
        chunk = texts[start:start + max(1, int(batch_size))]
        vectors.extend(provider.embed(chunk) or [])
    if len(vectors) != len(entries):
        return {"ok": False, "reason": "provider_returned_%d_of_%d"
                % (len(vectors), len(entries))}
    dim = len(vectors[0]) if vectors else 0
    for row, vector in zip(entries, vectors):
        if not isinstance(vector, (list, tuple)) or not vector:
            continue
        row["vector"] = [float(x) for x in vector]
    store_api = _sql_store()
    store_api.write_doc(root, session_id, doc, changed=entries, deleted=[])
    _MEM_DOC_CACHE.pop(str(_db_path(root, session_id)), None)
    _EVEC_CACHE.pop(str(_db_path(root, session_id)), None)
    _EVENT_STATE_CACHE.pop(str(_db_path(root, session_id)), None)
    state = _load_event_state(store, session_id)
    by_id = {str(row.get("id") or ""): row.get("vector") for row in entries}
    changed_events = 0
    for ev in state.get("events") or []:
        vectors_here = []
        for item in ev.get("entries") or []:
            vector = by_id.get(str(item.get("id") or ""))
            if vector:
                item["vector"] = list(vector)
                vectors_here.append(vector)
        if vectors_here:
            ev["vector"] = _mean_vector(vectors_here)
            changed_events += 1
    if changed_events:
        _save_event_state(store, session_id, state)
    _write_vector_meta(root, session_id, {
        "embed_model": str((embed_cfg or {}).get("model") or ""),
        "dim": dim,
        "embed_metric": "cosine",
        "rerank_model": str((rerank_cfg or {}).get("model") or ""),
    })
    return {"ok": True, "session_id": session_id, "entries": len(entries),
            "events": changed_events, "dim": dim,
            "embed_model": str((embed_cfg or {}).get("model") or "")}


def _entry_vectors(store, session_id):
    """Entry coordinates, memoised on the database stamp."""
    root = _store_root(store)
    if root is None:
        return {}
    path = _db_path(root, session_id)
    token = _db_stamp(root, session_id)
    cached = _EVEC_CACHE.get(str(path))
    if cached is not None and token is not None and cached[0] == token:
        return cached[2]
    try:
        vectors = _sql_store().read_entry_vectors(root, session_id)
    except Exception:
        return {}
    try:
        if len(_EVEC_CACHE) >= _EVEC_CACHE_MAX:
            _EVEC_CACHE.pop(next(iter(_EVEC_CACHE)), None)
        if stamp is not None:
            _EVEC_CACHE[str(path)] = (stamp[0], stamp[1], vectors)
    except Exception:
        pass
    return vectors


def _sql_backed(store):
    """True when this call should read/write the sqlite store."""
    return _store_root(store) is not None and store_mode() != "json"


def _db_path(root, session_id):
    return _sql_store().db_path(root, sanitize_session_id(session_id))


def _db_stamp(root, session_id):
    """Change token for one database: only ANOTHER connection's commit moves it.

    A file (mtime, size) stamp was useless here: sqlite's WAL checkpoints touch
    the file after our own writes, so every cache missed once per turn. Our own
    writes refresh the memos explicitly, so this only has to catch strangers.
    """
    conn = None
    try:
        conn = _sql_store().connect(root, session_id)
        return int(conn.execute("PRAGMA data_version").fetchone()[0])
    except Exception:
        return None
    finally:
        # a stamp is one pragma: holding the handle would keep the db file
        # undeletable on Windows (the temp-store cleanup in every test)
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _file_stamp(path):
    try:
        info = Path(path).stat()
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return None


def _copy_doc(doc):
    out = dict(doc or {})
    out["entries"] = [dict(row) for row in (out.get("entries") or [])
                      if isinstance(row, dict)]
    return out


def _refresh_stamps(token, path, entry_cache=None, vector_cache=None):
    """Our own event write bumps the db stamp; entries/vectors did not change.

    Both memos are keyed on the file stamp so an outside writer still wins, but
    a write that only touched the events table must not throw away 759 parsed
    rows (that was the 440 ms per capture this task is removing).
    """
    if token is None:
        return
    for cache in (entry_cache, vector_cache):
        if not isinstance(cache, dict):
            continue
        cached = cache.get(str(path))
        if cached is None:
            continue
        cache[str(path)] = (token, 0) + tuple(cached[2:])


def _remember_doc(path, doc, serialized, token=None):
    try:
        if len(_MEM_DOC_CACHE) >= _MEM_DOC_CACHE_MAX:
            _MEM_DOC_CACHE.pop(next(iter(_MEM_DOC_CACHE)), None)
        _MEM_DOC_CACHE[str(path)] = (token, 0, _copy_doc(doc), dict(serialized))
    except Exception:
        pass


def _serialize_entries(entries):
    out = {}
    for row in entries or []:
        if not isinstance(row, dict):
            continue
        out[str(row.get("id") or "")] = json.dumps(row, ensure_ascii=False)
    return out


def load_memory(store, session_id):
    """Session document. sqlite is the store; memory.json is import/export only."""
    root = _store_root(store)
    if root is None:
        return {"entries": []}
    session_id = sanitize_session_id(session_id)
    if store_mode() == "json":
        doc = _load_json(memory_path(store, session_id), _empty_doc(session_id))
        entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
        doc["entries"] = entries
        doc.setdefault("session_id", session_id)
        return doc
    path = _db_path(root, session_id)
    token = _db_stamp(root, session_id)
    cached = _MEM_DOC_CACHE.get(str(path))
    if cached is not None and token is not None and cached[0] == token:
        return _copy_doc(cached[2])
    store_api = _sql_store()
    # an install that only ever had JSON imports once, on first open.
    # open_or_import hands back a live connection: close it here or it keeps
    # sessions/<sid>/memory.db locked until GC (WinError 32 at temp cleanup)
    _conn = None
    try:
        _conn, _info = store_api.open_or_import(
            root, session_id,
            events_path=_event_state_path(store, session_id))
    except Exception:
        _conn = None
    finally:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
    doc = store_api.read_doc(root, session_id)
    doc["session_id"] = str(doc.get("session_id") or session_id)
    _remember_doc(path, doc, _serialize_entries(doc["entries"]), token)
    return _copy_doc(doc)


def save_memory(store, session_id, doc):
    """Persist one session document; only changed rows reach the database."""
    root = _store_root(store)
    if root is None:
        return False
    session_id = sanitize_session_id(session_id)
    if store_mode() == "json":
        try:
            _atomic_write(memory_path(store, session_id), doc)
            return True
        except Exception:
            return False
    path = _db_path(root, session_id)
    try:
        store_api = _sql_store()
        entries = [row for row in (doc.get("entries") or [])
                   if isinstance(row, dict)]
        serialized = _serialize_entries(entries)
        cached = _MEM_DOC_CACHE.get(str(path))
        previous = cached[3] if cached is not None else None
        if previous is None:
            previous = {row_id: raw for row_id, raw in
                        store_api.read_entry_rows(root, session_id)}
        changed = [row for row in entries
                   if previous.get(str(row.get("id") or ""))
                   != serialized.get(str(row.get("id") or ""))]
        deleted = [row_id for row_id in previous if row_id not in serialized]
        store_api.write_doc(root, session_id, doc, changed=changed, deleted=deleted)
        _remember_doc(path, doc, serialized, _db_stamp(root, session_id))
        return True
    except Exception:
        return False


def export_session_json(store, session_id):
    """Write this session's JSON view out of the store (debug / interop / proof).

    JSON is an export format now: nothing in the write path produces it, so a
    reader that wants the file has to ask for it.
    """
    store = store or _default_store()
    root = _store_root(store)          # sessions/ lives under the store root
    session_id = sanitize_session_id(session_id)
    if root is None:
        return {"entries": []}
    if store_mode() == "json":
        return _load_json(memory_path(store, session_id), _empty_doc(session_id))
    store_api = _sql_store()
    store_api.export_doc_json(root, session_id,
                              path=memory_path(store, session_id))
    events_path = _event_state_path(store, session_id)
    if events_path is not None:
        store_api.export_events_json(root, session_id, path=events_path)
    return store_api.read_doc(root, session_id)


def import_session_json(store, session_id, force=False):
    """Import a JSON-only session into the store (migration and tests)."""
    store = store or _default_store()
    root = _store_root(store)
    session_id = sanitize_session_id(session_id)
    if root is None:
        return False
    if store_mode() == "json":
        return False
    try:
        store_api = _sql_store()
        _conn, info = store_api.import_session(
            root, session_id, force=force,
            events_path=_event_state_path(store, session_id))
        try:
            _conn.close()
        except Exception:
            pass
        _MEM_DOC_CACHE.pop(str(_db_path(root, session_id)), None)
        _EVENT_STATE_CACHE.pop(str(_db_path(root, session_id)), None)
        return bool(info)
    except Exception:
        return False


def load_capture_state(store, session_id):
    if _store_root(store) is None:
        return {}
    data = _load_json(capture_state_path(store, session_id), {})
    return data if isinstance(data, dict) else {}


def save_capture_state(store, session_id, state):
    if _store_root(store) is None:
        return False
    try:
        _atomic_write(capture_state_path(store, session_id), state)
        return True
    except Exception:
        return False


def _visible(entries):
    return [entry for entry in (entries or [])
            if isinstance(entry, dict) and not entry.get("deleted")
            and not entry.get("archived")]


def _compact(entry):
    if not isinstance(entry, dict):
        return {}
    return {key: entry.get(key) for key in
            ("id", "text", "role", "ts", "tags", "pin", "importance", "hits")
            if key in entry}


def _entry_position(entries):
    """Visible non-empty row count: the event layer's cursor after a write.

    The event layer numbers rows by their index in this same filtered list
    (pipeline.py:2585 assigns seen+offset+1 to a row without a turn), so the
    cursor and the length are the same number. A deduped write adds no row and
    must NOT report the matched row's index: the cutoff is "how many memories
    exist at this turn", which is what the bench maps dataset turns onto.
    """
    return len([row for row in _visible(entries)
                if str(row.get("text") or "").strip()])


# ---------------------------------------------------------------- capture
def _stamps_for(state, session_id):
    hourly = state.get("hourly")
    if isinstance(hourly, dict):
        hourly = hourly.get(sanitize_session_id(session_id), [])
    values = []
    for value in hourly if isinstance(hourly, list) else []:
        stamp = _num(value, -1.0)
        if stamp >= 0:
            values.append(stamp)
    return values


def _recent_for(state, session_id):
    recent = state.get("recent")
    if isinstance(recent, dict):
        recent = recent.get(sanitize_session_id(session_id), [])
    return [str(item) for item in recent] if isinstance(recent, list) else []


def capture_decision(session_id, role, text, state):
    """Pure per-message capture decision (no mutation, no IO)."""
    state = state if isinstance(state, dict) else {}
    role = str(role or "user").strip().lower()
    text = clean_text(text, _int_param(state.get("max_text_chars"),
                                       MAX_TEXT_CHARS, 1, 20000))
    decision = {"capture": False, "reason": "", "role": role, "text": text}
    if not _as_bool(state.get("enabled", True), True):
        decision["reason"] = "disabled"
        return decision
    if role not in ("user", "assistant"):
        decision["reason"] = "bad-role"
        return decision
    if not text:
        decision["reason"] = "empty"
        return decision
    # 0 is a legal value ("keep every non-empty line"), so the clamp starts at 0:
    # clamping to 2 made min_chars=0 silently behave like the default 8
    min_chars = _int_param(state.get("min_chars"), MIN_CHARS, 0, 200)
    if len(text) < min_chars:
        decision["reason"] = "too-short"
        return decision
    if text in _recent_for(state, session_id):
        decision["reason"] = "duplicate"
        return decision
    now = _num(state.get("now"), time.time())
    hourly_cap = _int_param(state.get("hourly_cap"), HOURLY_CAP, 0, 1000)
    live = [stamp for stamp in _stamps_for(state, session_id)
            if now - stamp < _HOUR]
    # 0 means "no rate limit": it used to mean "reject everything", which made
    # the unlimited case inexpressible and a 0 typo look like a hard stop
    if hourly_cap > 0 and len(live) >= hourly_cap:
        decision["reason"] = "hourly-limit"
        return decision
    decision["capture"] = True
    decision["reason"] = "ok"
    return decision


def capture(session_id, role, text, store, config=None):
    """Decide + remember + persist per-session capture state (thin IO)."""
    cfg = config if isinstance(config, dict) else {}
    session_id = sanitize_session_id(session_id)
    store = store or _default_store()
    now = _num(cfg.get("now"), time.time())
    state = load_capture_state(store, session_id)
    state.update({
        "now": now,
        "min_chars": cfg.get("min_chars", state.get("min_chars", MIN_CHARS)),
        "hourly_cap": cfg.get("hourly_cap", state.get("hourly_cap", HOURLY_CAP)),
        "max_text_chars": cfg.get("max_text_chars",
                                  state.get("max_text_chars", MAX_TEXT_CHARS)),
        "enabled": cfg.get("enabled", state.get("enabled", True)),
    })
    decision = capture_decision(session_id, role, text, state)
    summarizer = cfg.get("event_summarizer")
    entry = None
    position = 0
    if decision["capture"]:
        result = tool_call("remember", {
            "text": decision["text"], "role": decision["role"], "ts": now,
            "affect": cfg.get("affect"),
            "participants": cfg.get("participants"),
        }, store, session_id=session_id)
        entry = result.get("entry") if result.get("ok") else None
        position = int(result.get("position") or 0) if result.get("ok") else 0
        if entry is not None:
            hourly = _stamps_for(state, session_id) + [now]
            recent = _recent_for(state, session_id) + [decision["text"]]
            save_capture_state(store, session_id, {
                "session_id": session_id,
                "hourly": hourly[-MAX_ENTRIES:],
                "recent": recent[-50:],
                "updated_ts": now,
            })
    if summarizer is not None and _store_root(store) is not None:
        # same incremental path as injection; new entries only
        _event_layer_block(session_id, store, "", 0, summarizer=summarizer)
    return {"ok": True, "decision": decision, "entry": entry, "position": position}


# ---------------------------------------------------------------- governance
def _concepts_of(text):
    if _governance is None:
        return []
    try:
        return _governance.extract_concepts(text)
    except Exception:
        return []


def _concept_filter(entries, query):
    """Keep entries whose concepts intersect the query (fallback: all)."""
    rows = [entry for entry in (entries or []) if isinstance(entry, dict)]
    wanted = set(_concepts_of(query))
    if not wanted:
        return rows
    narrowed = [entry for entry in rows
                if wanted & set(entry.get("concepts") or [])]
    return narrowed or rows


def _signals_eval(store, session_id, user_text="", assistant_text="",
                  state=None, now=None):
    if _signals is None or not store:
        return None
    try:
        rel = (relationship_read(store)["relationship"]
               if _store_root(store) is not None else {})
        return _signals.evaluate(store, session_id=session_id,
                                 user_text=user_text,
                                 assistant_text=assistant_text,
                                 state=state or {}, relationship=rel, now=now)
    except Exception:
        return None


def _perception_state(store, payload=None, state=None, include_core=True):
    """Session state + the host's payload blocks this batch owns.

    The merged core keeps core_state authoritative for the body fields and does
    not copy other payload blocks into the session state, so needs/attachment/
    appraisal handed in by the host are overlaid here (read-time only; the
    writeback persists them).
    """
    data = payload if isinstance(payload, dict) else {}
    session_state = dict(state) if isinstance(state, dict) else {}
    payload_state = data.get("state") if isinstance(data.get("state"), dict) else {}
    for key in ("needs", "attachment", "appraisal", "affective_labor",
                "comfort_streak", "sleep", "sleep_debt", "frustration_n",
                "last_human_ts", "history", "regulation_history"):
        value = payload_state.get(key)
        if value is not None and session_state.get(key) is None:
            session_state[key] = value
    base = session_state.get("core") if isinstance(session_state.get("core"), dict) else {}
    payload_core = payload_state.get("core") if isinstance(
        payload_state.get("core"), dict) else {}
    if payload_core and include_core:
        core = dict(base)
        core.update(payload_core)
        session_state["core"] = core
    if store is not None and _store_root(store) is not None:
        shared = relationship_read(store)
        rel = shared.get("relationship") or {}
        sidecar = bool(shared.get("version")) or bool(
            str(shared.get("path") or "") and Path(shared["path"]).exists())
        current = session_state.get("relationship")
        current = dict(current) if isinstance(current, dict) else {}
        payload_rel = payload_state.get("relationship")
        payload_rel = dict(payload_rel) if isinstance(payload_rel, dict) else {}
        if sidecar:  # the shared sidecar owns trust/closeness/style
            merged = dict(current)
            merged.update(payload_rel)
            merged.update(rel)
        else:        # no sidecar yet: the host's numbers are the only data we have
            merged = dict(rel)
            merged.update(current)
            merged.update(payload_rel)
        session_state["relationship"] = merged
    return session_state


def _perception_on(store, payload=None):
    """Batch A1 switch: one key for the whole perception batch."""
    data = payload if isinstance(payload, dict) else {}
    if data.get("perception_batch") is not None:
        return _as_bool(data.get("perception_batch"), True)
    return bool(_effective_switches(store, data.get("switches")).get(
        "perception_batch", True))


def _perception_read(store, session_id, payload=None, state=None, now=None):
    """turn_start: one read-only snapshot of the twelve modules."""
    if _perception is None or not store:
        return {"enabled": False, "reason": "unavailable"}
    data = payload if isinstance(payload, dict) else {}
    try:
        session_state = _perception_state(store, data, state)
        return _perception.snapshot(
            store, session_id, payload=data, state=session_state,
            now=now, enabled_override=_perception_on(store, data))
    except Exception as error:  # a broken batch never breaks a turn
        return {"enabled": False, "reason": type(error).__name__}


def _perception_write(store, session_id, payload=None, state=None, now=None):
    """turn_end: appraisal/attachment/needs write-back + field proposals."""
    if _perception is None or not store:
        return {"enabled": False, "reason": "unavailable"}
    data = payload if isinstance(payload, dict) else {}
    try:
        # the host's own core push stays a proposal for the arbiter, so it must
        # not be written into the state behind the arbiter's back
        session_state = _perception_state(store, data, state, include_core=False)
        on = _perception_on(store, data)
        result = _perception.writeback(
            store, session_id, payload=data, state=session_state, now=now,
            enabled_override=on, own_field=not field_enabled(data))
        new_state = result.pop("_state", None)
        if isinstance(new_state, dict) and result.get("enabled"):
            _save_session_state(store, session_id, new_state)
        return result
    except Exception as error:
        return {"enabled": False, "reason": type(error).__name__}


def _push_core_deltas(store, session_id, payload=None, deltas=None,
                      field_on=True):
    """task-234: the accepted affect deltas reach the one global core state.

    The merged core keeps <dataDir>/core_state.json authoritative for v/a/
    stress/social. The arbiter (or perception, when the field is off) decides
    the bounded delta, so the numbers must land there too -- otherwise the next
    turn_start would read the old body and silently revert the turn.
    """
    adds = {key: _num(value) for key, value in (deltas or {}).items()
            if key in ("v", "a", "stress", "social") and abs(_num(value)) > 1e-6}
    if not adds or store is None:
        return None
    data = payload if isinstance(payload, dict) else {}
    core_path = _core_state_path(data)
    try:
        if (_core_state is not None and _core_state.exists(core_path)):
            doc = _core_state.apply(core_path, deltas=dict(adds),
                                    now=time.time(), session_id=session_id,
                                    intero_fn=_intero_from_core)
            if doc:
                state = _load_session_state(store, session_id)
                core = dict(state.get("core") or {})
                core.update(_core_state.core_of(doc))
                if isinstance(doc.get("intero"), dict):
                    core["intero"] = dict(doc["intero"])
                    state["intero"] = dict(doc["intero"])
                state["core"] = core
                state["core_delta"] = dict(adds)
                state["core_state_ts"] = doc.get("ts", 0.0)
                _save_session_state(store, session_id, state)
                return _core_state.snapshot(core_path)
        elif not field_on:  # no global body and no field write: do it here
            state = _load_session_state(store, session_id)
            core = dict(state.get("core") or {})
            for key, value in adds.items():
                low, high = (-1.0, 1.0) if key == "v" else (0.0, 1.0)
                core[key] = round(max(low, min(high, _num(core.get(key), 0.0)
                                               + value)), 6)
            state["core"] = core
            _save_session_state(store, session_id, state)
        return None
    except Exception:
        return None


def _timescale_tick(store, session_id, payload=None, state=None, now=None):
    """task-229: advance the seconds/minutes/hours layers once per turn."""
    if _timescales is None or not store:
        return {"enabled": False, "reason": "unavailable"}
    data = payload if isinstance(payload, dict) else {}
    try:
        switches = _effective_switches(store, data.get("switches"))
        if not switches.get("timescales", True):
            return {"enabled": False, "reason": "disabled"}
        session_state = (state if isinstance(state, dict)
                         else _load_session_state(store, session_id))
        model = _timescales.load(session_state)
        core = session_state.get("core") if isinstance(
            session_state.get("core"), dict) else {}
        relationship = session_state.get("relationship") if isinstance(
            session_state.get("relationship"), dict) else {}
        sample = {"v": _num(core.get("v"), 0.0),
                  "a": _num(core.get("a"), 0.5),
                  "trust": relationship.get("trust")}
        stamp = _num(now, time.time())
        dt = max(0.0, stamp - _num(model.get("updated_ts"), 0.0))
        model, report = _timescales.step(model, sample, dt, now=stamp)
        session_state["timescales"] = model
        _save_session_state(store, session_id, session_state)
        return {"enabled": True, "report": report,
                "values": _timescales.project(model)}
    except Exception as error:  # a broken clock never breaks a turn
        return {"enabled": False, "reason": type(error).__name__}


def _batch_hooks():
    """The four batch hooks that are importable in this checkout."""
    hooks = {}
    for name, module in (("b", _batch_b), ("c", _batch_c), ("d", _batch_d),
                         ("e", _batch_e)):
        if module is not None and callable(getattr(module, "apply_turn", None)):
            hooks[name] = module
    return hooks


def _merge_batch_state(state, deltas):
    """Merge the safe batch blocks into one session state (never core)."""
    if not isinstance(state, dict) or not isinstance(deltas, dict):
        return state
    safe = getattr(_batch_registry, "SAFE_KEYS", ())
    for key, value in deltas.items():
        if key == "batches" and isinstance(value, dict):
            bucket = state.get("batches") if isinstance(state.get("batches"),
                                                        dict) else {}
            for name, block in value.items():
                if isinstance(block, dict):
                    current = bucket.get(str(name)) if isinstance(
                        bucket.get(str(name)), dict) else {}
                    current.update(block)
                    bucket[str(name)] = current
            state["batches"] = bucket
            continue
        if safe and key not in safe:
            continue
        state[key] = value
    return state


def _batch_tick(store, session_id, phase, payload=None, state=None, now=None):
    """Run b/c/d/e once, merge their safe deltas, keep the per-module monitor."""
    if _batch_registry is None or not store:
        return {"enabled": False, "reason": "unavailable"}
    data = payload if isinstance(payload, dict) else {}
    try:
        switches = _effective_switches(store, data.get("switches"))
        session_state = dict(state) if isinstance(state, dict) else {}
        result = _batch_registry.tick(
            store, session_id, phase, data, session_state, now=now,
            switches=switches, hooks=_batch_hooks())
    except Exception as error:  # a broken registry never breaks a turn
        return {"enabled": False, "reason": type(error).__name__}
    if isinstance(state, dict):
        _merge_batch_state(state, result.get("state_deltas") or {})
    return result


def _governance_tick(store, now=None):
    """Decay/index/graph/aggregate sidecars; never deletes a memory."""
    if _governance is None or not store:
        return None
    try:
        return _governance.run(store, now=now)
    except Exception:
        return None


def _relationship_tick(store, user_text, now=None):
    """Bounded trust/closeness/conflict accumulation + attachment/repair."""
    if _relationship_state is None or not store:
        return None
    try:
        if not _relationship_state.enabled(store):
            return {"enabled": False, "skipped": True}
        before = relationship_read(store)["relationship"]
        signal = _relationship_state.signals(user_text)
        deltas = signal.get("deltas") or {}
        if deltas:
            relationship_update(store, deltas=deltas, now=now)
        after = relationship_read(store)["relationship"]
        summary = _relationship_state.summary(store, after)
        style = summary.get("attachment_style")
        if style and style != after.get("attachment_style"):
            relationship_update(store, attachment_style=style, now=now)
            after = relationship_read(store)["relationship"]
        _relationship_state.record_event(store, signal.get("kind"),
                                         user_text, deltas, now=now)
        return {"kind": signal.get("kind"), "deltas": deltas,
                "trust": round(_num(after.get("trust"), 0.5), 4),
                "closeness": round(_num(after.get("closeness"), 0.5), 4),
                "conflict": round(_num(after.get("conflict"), 0.0), 4),
                "delta_trust": round(_num(after.get("trust"), 0.5)
                                     - _num(before.get("trust"), 0.5), 4),
                "delta_closeness": round(_num(after.get("closeness"), 0.5)
                                         - _num(before.get("closeness"), 0.5), 4),
                "attachment_style": str(after.get("attachment_style") or style),
                "summary": summary}
    except Exception:
        return None


def _identity_tick(store, narrative=None, now=None):
    if _self_layer is None or not store:
        return None
    try:
        cfg = _load_runtime_config(store)
        persona_hash = _self_layer.hash_persona(cfg.get("persona_text"))
        return _self_layer.update(store, persona_hash=persona_hash,
                                  narrative=narrative, now=now)
    except Exception:
        return None


def _autonomy_tick(store, data=None, now=None):
    if _autonomy is None or not store:
        return None
    try:
        payload = data if isinstance(data, dict) else {}
        switches = _effective_switches(store, payload.get("switches"))
        if not switches.get("core_enabled", True) or not switches.get(
                "autonomy", True):
            return {"ok": True, "action": None, "reason": "disabled",
                    "metrics": _autonomy.metrics(store, now),
                    "limits": _autonomy.limits(store)}
        core_path = _core_state_path(payload)
        state = {}
        if _core_state is not None and _core_state.exists(core_path):
            doc = _core_state.load(core_path)
            state = {"core": _core_state.core_of(doc),
                     "intero": doc.get("intero")}
        elif isinstance(payload.get("state"), dict):
            state = payload["state"]
        return _autonomy.decide(
            store, now=now,
            session_id=str(payload.get("session_id") or "autonomy"),
            state=state,
            last_human_ts=_num(payload.get("last_human_ts"), 0.0),
            silence_minutes=_num(payload.get("silence_minutes"), 0.0))
    except Exception:
        return None


# ---------------------------------------------------------------- inject
def _store_data_dir(store):
    root = _store_root(store)
    if root is None:
        return None
    return root.parent if root.name == "memory" else root


def _embed_cache_path(store):
    """The embedding cache file for this store: config > env > <data>/cache/."""
    try:
        from biocore_memory.recall.embedding import cache_file
    except Exception:
        return None
    try:
        config = _load_runtime_config(store)
    except Exception:
        config = {}
    try:
        data_dir = _store_data_dir(store)
    except Exception:
        data_dir = None
    try:
        return cache_file(config, str(data_dir) if data_dir is not None else None)
    except Exception:
        return None




def _spatial_learning_snapshot(store):
    """The /state block for the learner (never raises)."""
    if _learning is None:
        return None
    try:
        flags = _effective_switches(store, None)
        data_dir = _store_data_dir(store) if store else None
        return _learning.learning_view(data_dir, flags, os.environ)
    except Exception:
        return None


def _spatial_feedback_rows(store, limit=20):
    """The newest usage rows, for the debug action."""
    if _learning is None:
        return []
    try:
        data_dir = _store_data_dir(store) if store else None
        return _learning.load_rows(_learning.feedback_path(data_dir),
                                   limit=limit)
    except Exception:
        return []


def _collect_spatial_feedback(store, session_id, data, reply_text):
    """Judge which recalled entries the reply used; append, then learn.

    Rule based and free: the reply is checked against the entities, tags, cue
    slots, numbers and long tokens the entry already carries. Nothing is
    called and nothing is written outside the store data dir.
    """
    if _learning is None or not isinstance(data, dict):
        return None
    try:
        flags = _effective_switches(store, None)
    except Exception:
        flags = {}
    if not _learning.feedback_enabled(flags, os.environ):
        return None
    data_dir = _store_data_dir(store) if store else None
    if data_dir is None:
        return None
    ids = data.get("recalled_ids")
    if not isinstance(ids, list) or not ids:
        return None
    ids = [str(item)[:40] for item in ids][:20]
    query = str(data.get("user_text") or "")[:200]
    now = _num(data.get("now"), time.time())
    entries = _visible(load_memory(store, session_id).get("entries"))
    by_id = {str(entry.get("id") or ""): entry for entry in entries}
    rows = []
    used_count = 0
    for entry_id in ids:
        entry = by_id.get(entry_id)
        if not isinstance(entry, dict):
            continue
        used = _learning.judge_used(entry, reply_text)
        rows.append({"query": query, "id": entry_id, "used": bool(used),
                     "ts": round(now, 3),
                     "d": _learning.distance_block(query, entry, now=now)})
        used_count += 1 if used else 0
    if not rows:
        return None
    _learning.append_rows(_learning.feedback_path(data_dir), rows)
    out = {"rows": len(rows), "used": used_count}
    if _learning.learn_enabled(flags, os.environ):
        all_rows = _learning.load_rows(_learning.feedback_path(data_dir),
                                       limit=_learning.FEEDBACK_READ_LIMIT)
        if len(all_rows) >= _learning.MIN_SAMPLES:
            state = _learning.learn_and_save(
                _learning.weights_path(data_dir), all_rows,
                _learning.eta(flags, os.environ), now=now)
            out["weights"] = state.get("weights")
            out["samples"] = state.get("samples")
    return out





def _event_expand_on(store, payload=None):
    """spatial_event_expand: payload flag > switches/config > default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("event_expand"), bool):
        return bool(data["event_expand"])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    return bool(switches.get("spatial_event_expand"))


def _event_extra(entries, pool, rows, limit=3):
    """Rows a hit's own event segment brings along (never duplicates a hit)."""
    if _segment is None or not rows:
        return []
    by_id = {str(entry.get("id") or ""): entry for entry in pool or []
             if isinstance(entry, dict)}
    by_event = {}
    for entry in entries or []:
        if not isinstance(entry, dict) or entry.get("deleted"):
            continue
        event_id = str(entry.get("event_id") or "")
        if event_id:
            by_event.setdefault(event_id, []).append(entry)
    for bucket in by_event.values():
        bucket.sort(key=lambda item: _num(item.get("event_index"), 0))
    present = {str(row.get("id") or "") for row in rows}
    extra = []
    cap = max(0, 2 * max(1, int(limit)))
    for row in list(rows):
        hit = by_id.get(str(row.get("id") or ""))
        if not isinstance(hit, dict):
            continue
        index = int(_num(hit.get("event_index"), 0))
        for neighbour in by_event.get(str(hit.get("event_id") or ""), []):
            if len(extra) >= cap:
                return extra
            neighbour_id = str(neighbour.get("id") or "")
            if neighbour_id in present:
                continue
            if abs(int(_num(neighbour.get("event_index"), 0)) - index) > 1:
                continue
            item = _compact(neighbour)
            item["score"] = 0.0
            item["mode"] = "event_expand"
            item["event_expand"] = True
            extra.append(item)
            present.add(neighbour_id)
    return extra


def _recall_stage_snapshot(store, entries):
    """recall_stage: pool size, depth and the per-stage counts of the last recall."""
    try:
        from biocore_memory.core.config import RECALL_DEPTH_DEFAULT, RECALL_DEPTH_MAX
        raw = _load_runtime_config(store).get("recall_depth")
        depth = int(float(raw)) if raw is not None else RECALL_DEPTH_DEFAULT
    except Exception:
        depth = 5
        RECALL_DEPTH_MAX = 40
    depth = max(1, min(RECALL_DEPTH_MAX, depth))
    pool = len([row for row in entries or [] if isinstance(row, dict)])
    return {"pool": pool, "depth": depth, "after_activation": 0,
            "after_rerank": 0, "after_mmr": 0,
            "source": "host", "ts": round(time.time(), 3)}


def _activation_snapshot(store, entries):
    """activation_rank: the switch, the weights and the term presence."""
    from biocore_memory.recall import activation as _act
    from biocore_memory.store import near_dup as _near
    flags = _near_dup_flags(store) if _near is not None else {}
    on = _act.enabled(flags, os.environ)
    weights = _act.weights_for(flags)
    vectors = sum(1 for row in entries or []
                  if isinstance(row.get("vector"), (list, tuple))
                  and row.get("vector"))
    return {"enabled": bool(on), "terms": {"B": "hits/ts",
            "sem": ("vectors" if vectors else "none"),
            "ppr": "graph_edges", "spec": ("vectors" if vectors else "none")},
            "d": _act.decay(flags), "lambda": round(weights["lambda"], 3),
            "mu": round(weights["mu"], 3), "ts": round(time.time(), 3)}


def _near_dup_flags(store):
    """Effective switches plus the numeric near-dup threshold.

    _effective_switches keeps booleans only, so a float such as
    near_dup_cosine has to come from the runtime config directly.
    """
    try:
        flags = dict(_effective_switches(store, None))
    except Exception:
        flags = {}
    try:
        cfg = _load_runtime_config(store)
    except Exception:
        cfg = {}
    if isinstance(cfg, dict):
        for key in ("near_dup_cosine", "near_dup_jaccard"):
            value = cfg.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                flags[key] = float(value)
    data_dir = _store_data_dir(store) if store else None
    if data_dir is not None:
        stored = _load_json(Path(data_dir) / "flags.json", {})
        for key in ("near_dup_cosine", "near_dup_jaccard"):
            value = stored.get(key) if isinstance(stored, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                flags[key] = float(value)
    return flags


def _space_stats_snapshot(entries):
    """Per-axis spread + dead axes for /state (read-only, never raises)."""
    try:
        from biocore_memory import space as _space
    except Exception:
        return None
    try:
        stats = _space.axis_stats(entries)
        if not stats:
            return {"mode": "raw", "reason": "small_sample", "dead_axes": [],
                    "entries": len([row for row in (entries or [])
                                   if isinstance(row, dict)])}
        return {"mode": "zscore", "dead_axes": _space.dead_axes(stats),
                "entries": stats.get("entries"),
                "sample": stats.get("sample"),
                "axis_std": {axis: (stats["axes"].get(axis) or {}).get("std")
                             for axis in _space.AXES}}
    except Exception:
        return None


def _embedding_cache_snapshot(store):
    """hit / miss / size for /state; counters may come from the stats file."""
    info = {"hit": 0, "miss": 0, "size": 0, "hit_rate": 0.0,
            "file": "", "corrupt": 0}
    try:
        from biocore_memory.recall.embedding import cache_summary
        info.update(cache_summary(path=_embed_cache_path(store)))
    except Exception:
        pass
    stats = _embed_stats_snapshot()
    hit = int(stats.get("hit", 0) or 0) + int(stats.get("disk_hit", 0) or 0)
    miss = int(stats.get("miss", 0) or 0)
    if hit or miss:
        info["hit"], info["miss"] = hit, miss
        info["hit_rate"] = round(hit / float(hit + miss), 4)
    return info


def _data_flags(store):
    """<dataDir>/flags.json booleans (learning switches live next to memory/).

    task-221口径: DSH learning switches default ON; an explicit file value wins.
    """
    merged = {"mood_recall": True, "affect_encoding": True,
              "memory_feedback": True, "preference_drift": True}
    data_dir = _store_data_dir(store)
    if data_dir is None:
        return merged
    raw = _load_json(data_dir / "flags.json", {})
    for key, value in raw.items():
        if isinstance(value, bool):
            merged[str(key)] = value
    cfg = _load_runtime_config(store)
    switches = cfg.get("switches") if isinstance(cfg.get("switches"), dict) else {}
    for key, value in switches.items():
        if isinstance(value, bool):
            merged[str(key)] = value
    return merged


def _inject_engine(store, entries):
    """MemoryEngine over this session's entries, with the env embedder."""
    try:
        from biocore_memory.engine import MemoryEngine
        from biocore_memory.recall.embedding import load_provider
        from biocore_memory.store.json_store import MemoryStore
    except Exception:
        return None
    embedder = None
    try:
        cfg = _load_runtime_config(store)
        emb = cfg.get("embedding") if isinstance(cfg.get("embedding"), dict) else {}
        provider_cfg = {}
        if emb:
            provider_cfg = {
                "embedding_mode": emb.get("mode") or "auto",
                "embedding_base_url": emb.get("base_url") or "",
                "embedding_model": emb.get("model") or "",
                "embedding_api_key": emb.get("api_key") or "",
            }
        embedder = load_provider(provider_cfg)
    except Exception:
        embedder = None
    try:
        memory = MemoryStore(doc={"entries": [dict(item) for item in entries
                                              if isinstance(item, dict)]})
        config = {"flags": _data_flags(store),
                  "embedding": {**emb, "cache_file": _embed_cache_path(store)}}
        return MemoryEngine(store=memory, embedder=embedder, config=config)
    except Exception:
        return None


def _rerank_entries(query, entries, rerank_config):
    """Reorder candidates by the optional rerank API; None keeps local order."""
    if _rerank_mod is None or not isinstance(rerank_config, dict):
        return None
    if not rerank_config.get("rerank_enabled"):
        return None
    try:
        texts = [str(entry.get("text") or "") for entry in entries]
        ranked = _rerank_mod.rerank_documents(query, texts, rerank_config)
    except Exception:
        return None
    if not ranked:
        return None
    ordered = []
    for item in ranked:
        try:
            index = int(item.get("index", -1))
        except Exception:
            continue
        if 0 <= index < len(entries) and entries[index] not in ordered:
            ordered.append(entries[index])
    for entry in entries:
        if entry not in ordered:
            ordered.append(entry)
    return ordered or None


def _query_entries(store, session_id, query, top_k, rerank_config,
                   now=None, include_superseded=False):
    """engine.recall(query) over the injected candidates; None means fallback.

    now anchors retrieval to the moment the question was asked (Howard &
    Kahana 2002); include_superseded=True is the historical question.
    """
    entries = _visible(load_memory(store, session_id).get("entries"))
    if not entries:
        return None
    if _versioning is not None:
        try:
            entries = _versioning.visible(
                entries, include_superseded=bool(include_superseded))
        except Exception:
            pass
    if not entries:
        return None
    engine = _inject_engine(store, entries)
    if engine is None:
        return None
    rows = engine.recall(str(query)[:MAX_TEXT_CHARS], budget=top_k,
                         query_ts=now,
                         include_superseded=bool(include_superseded))
    if not isinstance(rows, list) or not rows:
        return None
    picked = [row.get("entry") for row in rows
              if isinstance(row, dict) and isinstance(row.get("entry"), dict)]
    if not picked:
        return None
    # task-223: concept filter (entries written with concepts only).
    narrowed = _concept_filter(picked, query)
    if 0 < len(narrowed) < len(picked):
        picked = narrowed
        if _governance is not None:
            try:
                _governance.note_concept_filter(store, len(picked))
            except Exception:
                pass
    if len(picked) > 1:
        reordered = _rerank_entries(query, picked, rerank_config)
        if reordered:
            picked = reordered
    # task-223: index hit + decay weight (cold memories sink, never deleted).
    if _governance is not None:
        try:
            hits = set(_governance.lookup(store, query))
            if hits:
                _governance.note_index_hit(store)
            if hits:
                picked.sort(key=lambda entry: (
                    1 if str(entry.get("id") or "") in hits else 0,
                    _governance.weight_of(store, str(entry.get("id") or "")),
                    _num(entry.get("importance"), 0.5)), reverse=True)
        except Exception:
            pass
    if _retrieval_plus is not None and query:
        try:
            text_query = str(query)
            switches = _effective_switches(store)
            enabled = bool(switches.get("retrieval_plus", True))
            _retrieval_plus.record_query(store, text_query, now=time.time())
            rerank_on = isinstance(rerank_config, dict) and bool(
                rerank_config.get("rerank_enabled")
                or rerank_config.get("enabled"))
            if enabled and not rerank_on and len(picked) > 1:
                ranked = _retrieval_plus.rank(
                    store, session_id, text_query, picked,
                    now=time.time(), limit=len(picked))
                if ranked:
                    _retrieval_plus.record_debug(store, text_query, ranked)
                    engine_scores = {str(row.get("entry", {}).get("id") or ""):
                                     _num(row.get("score"), 0.0) for row in rows}
                    top = max(engine_scores.values() or [1.0]) or 1.0
                    combined = []
                    for item in ranked:
                        entry_id = str(item["entry"].get("id") or "")
                        engine_norm = engine_scores.get(entry_id, 0.0) / top
                        combined.append((0.7 * engine_norm + 0.3 * item["score"],
                                         item))
                    combined.sort(key=lambda pair: pair[0], reverse=True)
                    picked = [item["entry"] for _score, item in combined]
        except Exception:
            pass
    if _lifecycle is not None:
        try:
            _lifecycle.record_recall(store, session_id,
                                     [str(entry.get("id") or "")
                                      for entry in picked], now=time.time())
            _lifecycle.tier_tick(store, picked, now=time.time())
        except Exception:
            pass
    return picked[:top_k]


DATE_PREFIX_KEY = "memory_date_prefix"


def _date_prefix_on(store, payload=None):
    """memory_date_prefix: payload flag > switches/config > default ON."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get(DATE_PREFIX_KEY), bool):
        return data[DATE_PREFIX_KEY]
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    return bool(switches.get(DATE_PREFIX_KEY, True))


def _memory_date(entry):
    """YYYY-MM-DD HH:MM for the entry's ts in the local zone; "" without ts."""
    raw = (entry or {}).get("ts")
    try:
        stamp = float(raw)
    except Exception:
        return ""
    if stamp != stamp or stamp <= 0:
        return ""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


POINT_STATE_FILE = "point_expand.json"


def _point_expand_on(store, payload=None):
    """point_expand: payload flag > switches/config > default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("point_expand"), bool):
        return bool(data["point_expand"])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    return bool(switches.get("point_expand"))


def _point_expand_flags(store):
    """Switches plus the numeric radius/token budget (switches keep bools)."""
    try:
        flags = dict(_effective_switches(store, None))
    except Exception:
        flags = {}
    try:
        cfg = _load_runtime_config(store)
    except Exception:
        cfg = {}
    sources = [cfg]
    data_dir = _store_data_dir(store) if store else None
    if data_dir is not None:
        sources.append(_load_json(Path(data_dir) / "flags.json", {}))
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("point_expand_radius", "point_expand_tokens"):
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                flags[key] = value
    return flags


def _point_state_path(store):
    data_dir = _store_data_dir(store) if store else None
    return (Path(data_dir) / POINT_STATE_FILE) if data_dir else None


def _record_point_state(store, stats):
    path = _point_state_path(store)
    if path is None or not isinstance(stats, dict):
        return False
    try:
        payload = dict(stats)
        payload["ts"] = round(time.time(), 3)
        _atomic_write(path, payload)
        return True
    except Exception:
        return False


def _point_expand_snapshot(store):
    """The /state block: {hits, expanded, lines, tokens, dropped_expanded}."""
    enabled = _point_expand_on(store, None)
    base = {"enabled": bool(enabled), "hits": 0, "expanded": 0, "lines": 0,
            "tokens": 0, "dropped_expanded": 0, "ts": 0.0}
    path = _point_state_path(store)
    if path is not None and path.exists():
        stored = _load_json(path, {})
        if isinstance(stored, dict):
            base.update(stored)
    base["last_run"] = bool(base.get("ts"))
    if not enabled and not base["last_run"]:
        base["reason"] = "switch_off"
    return base

COVER_STATE_FILE = "cover_select.json"


def _cover_on(store, payload=None):
    """spatial_cover_select: payload flag > switches/config > default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("spatial_cover_select"), bool):
        return bool(data["spatial_cover_select"])
    if _cover is None:
        return False
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    return _cover.enabled(switches, os.environ)


def _cover_flags(store):
    """Switches plus the numeric lambda and pool depth."""
    try:
        flags = dict(_effective_switches(store, None))
    except Exception:
        flags = {}
    try:
        cfg = _load_runtime_config(store)
    except Exception:
        cfg = {}
    sources = [cfg]
    data_dir = _store_data_dir(store) if store else None
    if data_dir is not None:
        sources.append(_load_json(Path(data_dir) / "flags.json", {}))
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("spatial_cover_lambda", "spatial_cover_pool"):
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                flags[key] = value
    return flags


def _cover_state_path(store):
    data_dir = _store_data_dir(store) if store else None
    return (Path(data_dir) / COVER_STATE_FILE) if data_dir else None


def _record_cover_state(store, stats):
    path = _cover_state_path(store)
    if path is None or not isinstance(stats, dict):
        return False
    try:
        payload = dict(stats)
        payload["ts"] = round(time.time(), 3)
        _atomic_write(path, payload)
        return True
    except Exception:
        return False


def _cover_snapshot(store):
    """The /state block: {pool, kept, lambda, avg_pairwise_dist, dropped_by_cover}."""
    enabled = _cover_on(store, None)
    base = {"enabled": bool(enabled), "pool": 0, "kept": 0, "lambda": 0.0,
            "avg_pairwise_dist": 0.0, "dropped_by_cover": 0, "ts": 0.0}
    path = _cover_state_path(store)
    if path is not None and path.exists():
        stored = _load_json(path, {})
        if isinstance(stored, dict):
            base.update(stored)
    base["last_run"] = bool(base.get("ts"))
    if not enabled and not base["last_run"]:
        base["reason"] = "switch_off"
    return base


def _cover_distances(store, pool):
    """Five-axis weighted distance between pool entries (standardize aware)."""
    if _space is None:
        return lambda left, right: 0.0
    flags = _cover_flags(store)
    try:
        weights_map = _space.weights(flags, os.environ)
    except Exception:
        weights_map = None
    spaces = []
    for entry in pool:
        try:
            spaces.append(_space.build(entry, now=time.time()))
        except Exception:
            spaces.append({})
    stats = None
    try:
        if _space.standardize_enabled(flags, os.environ):
            stats = _space.stats_of_spaces(spaces)
    except Exception:
        stats = None
    by_id = {str((entry or {}).get("id") or ""): space
             for entry, space in zip(pool, spaces)}

    def distance(left, right):
        a = by_id.get(str((left or {}).get("id") or ""))
        b = by_id.get(str((right or {}).get("id") or ""))
        if not a or not b:
            return 0.0
        try:
            raw = _space.distance(a, b)
            if stats is not None:
                return float(_space.standardized_distance(raw, stats, weights_map))
            return float(_space.weighted_distance(raw, weights_map))
        except Exception:
            return 0.0

    return distance


def _cover_pick(store, session_id, query, limit, now=None, rerank_config=None,
                payload=None):
    """Pool -> rerank scores -> MMR pick -> (ordered entries, stats, pool ids)."""
    if _cover is None:
        return [], {}, []
    flags = _cover_flags(store)
    depth = _cover.pool_depth(flags)
    pool = []
    if query:
        try:
            pool = list(_query_entries(store, session_id, query, depth,
                                       rerank_config, now=now) or [])
        except Exception:
            pool = []
    if not pool:
        pool = sorted(_visible(load_memory(store, session_id).get("entries")),
                      key=lambda entry: (1 if entry.get("pin") else 0,
                                         _num(entry.get("ts"), 0.0)),
                      reverse=True)[:depth]
    if not pool:
        return [], {}, []
    rel = None
    scores = None
    if query:
        try:
            scores = _rerank_scores(store, query, pool, rerank_config)
        except Exception:
            scores = None
    if scores:
        rel = [float(scores.get(str((entry or {}).get("id") or ""), 0.0))
               for entry in pool]
    else:
        count = max(1, len(pool))
        rel = [1.0 - (index / float(count)) for index in range(len(pool))]

    picked, stats = _cover.select(pool, rel, limit,
                                  _cover.lam(flags), _cover_distances(store, pool))
    _record_cover_state(store, stats)
    ordered = _cover.order(picked)
    return ordered, stats, [str((entry or {}).get("id") or "") for entry in pool]

SEGMENT_STATE_FILE = "segment_recall.json"


def _segment_recall_on(store, payload=None):
    """segment_recall: payload flag > switches/config > default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("segment_recall"), bool):
        return bool(data["segment_recall"])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    return bool(switches.get("segment_recall"))


def _segment_state_path(store):
    data_dir = _store_data_dir(store) if store else None
    return (Path(data_dir) / SEGMENT_STATE_FILE) if data_dir else None


def _record_segment_state(store, stats):
    """Persist the last segment recall so /state (another process) sees it."""
    path = _segment_state_path(store)
    if path is None or not isinstance(stats, dict):
        return False
    try:
        payload = dict(stats)
        payload["ts"] = round(time.time(), 3)
        _atomic_write(path, payload)
        return True
    except Exception:
        return False


def _segment_recall_snapshot(store):
    """The /state block: {segments, lines, dropped_segments, avg_len}."""
    enabled = _segment_recall_on(store, None)
    base = {"enabled": bool(enabled), "segments": 0, "lines": 0,
            "dropped_segments": 0, "avg_len": 0.0, "ts": 0.0}
    path = _segment_state_path(store)
    if path is not None and path.exists():
        stored = _load_json(path, {})
        if isinstance(stored, dict):
            base.update(stored)
    base["last_run"] = bool(base.get("ts"))
    if not enabled and not base["last_run"]:
        base["reason"] = "switch_off"
    return base

def _segment_line(entry, use_date):
    """One rendered line: date prefix (optional) + text, no clipping yet."""
    content = clean_text(entry.get("text"), 500)
    if not content:
        return ""
    prefix = ""
    if use_date:
        day = _memory_date(entry)
        if day:
            prefix = "[" + day + "] "
    return "\n- " + prefix + content


def _inject_segments(session_id, store, query, limit, budget, header, use_date):
    """Segment-mode injection: whole events, best-first, time inside."""
    if _segments is None:
        return None
    entries = _visible(load_memory(store, session_id).get("entries"))
    if _versioning is not None:
        try:
            entries = _versioning.visible(entries, include_superseded=False)
        except Exception:
            pass
    zero = {"segments": 0, "lines": 0, "dropped_segments": 0, "avg_len": 0.0}
    if budget <= len(header) + 3:
        return {"text": "", "chars": 0, "ids": [], "segment": zero}
    grouped = _segments.group(entries)
    if not grouped:
        return {"text": "", "chars": 0, "ids": [], "segment": zero}

    def score_of(entry):
        return _score(query, entry.get("text")) if query else 0.0

    ranked = _segments.rank(grouped, score_of)
    kept = []
    dropped = 0
    lines = 0
    chars = len(header)
    rendered_rows = []
    for row in ranked:
        members = row["segment"]["members"]
        rendered = []
        for member in members:
            line = _segment_line(member, use_date)
            if line:
                rendered.append(line)
        if not rendered:
            continue
        if lines + len(rendered) > limit:
            dropped += 1
            continue
        cost = sum(len(line) for line in rendered)
        if chars + cost > budget:
            dropped += 1
            continue
        kept.append(row)
        rendered_rows.append((row, rendered))
        lines += len(rendered)
        chars += cost
    text = header
    ids = []
    for row, rendered in rendered_rows:
        for index, line in enumerate(rendered):
            if len(text) + len(line) > budget:
                break
            text += line
            ids.append(str(row["segment"]["members"][index].get("id") or ""))
    stats = _segments.stats(kept, lines, dropped)
    _record_segment_state(store, stats)
    if len(text) <= len(header) + 2:
        return {"text": "", "chars": 0, "ids": [], "segment": stats}
    return {"text": text, "chars": len(text), "ids": ids, "segment": stats}

def _point_rerank_on(store, payload=None):
    """point_expand_rerank: payload flag > switches/config > default ON."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("point_expand_rerank"), bool):
        return bool(data["point_expand_rerank"])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    return bool(switches.get("point_expand_rerank", True))


def _rerank_ready(store, rerank_config=None):
    """The existing rerank client config, or None when nothing is set up."""
    if _rerank_mod is None:
        return None
    try:
        base = dict(rerank_config) if isinstance(rerank_config, dict) else {}
    except Exception:
        base = {}
    if not base.get("rerank_enabled"):
        try:
            merged = dict(_rerank_config(store, {}))
        except Exception:
            merged = {}
        merged.update(base)
        base = merged
    if not base.get("rerank_enabled"):
        return None
    if not (base.get("base_url") or base.get("url") or base.get("endpoint")
            or base.get("model")):
        return None
    base["rerank_enabled"] = True
    return base


def _rerank_scores(store, query, entries, rerank_config=None):
    """{entry_id: score} from the existing client, or None when unavailable."""
    config = _rerank_ready(store, rerank_config)
    if config is None or not entries:
        return None
    texts = [str((entry or {}).get("text") or "") for entry in entries]
    try:
        ranked = _rerank_mod.rerank_documents(query, texts, config)
    except Exception:
        return None
    if not ranked:
        return None
    scores = {}
    for item in ranked:
        try:
            index = int(item.get("index", -1))
        except Exception:
            continue
        if not 0 <= index < len(entries):
            continue
        entry_id = str((entries[index] or {}).get("id") or "")
        value = item.get("relevance_score")
        if value is None:
            value = item.get("score")
        try:
            scores[entry_id] = float(value)
        except Exception:
            scores[entry_id] = 1.0 / (len(scores) + 1.0)
    return scores or None

def _inject_point_expand(session_id, store, hits, header, use_date, flags=None,
                         query="", limit=None, rerank_config=None):
    """Hits union neighbours -> rerank the pool -> hits guaranteed -> order.

    The neighbour is a *candidate*, not a fact: it only enters the block after
    the same reranker that scored the hits has scored it too. Without a
    reranker the block falls back to the hits only (the v9 behaviour).
    """
    if _point_expand is None:
        return None
    span = _point_expand.radius(flags)
    budget = _point_expand.token_budget(flags)
    entries = _visible(load_memory(store, session_id).get("entries"))
    if _versioning is not None:
        try:
            entries = _versioning.visible(entries, include_superseded=False)
        except Exception:
            pass
    extra = _point_expand.neighbours(hits, entries, span)
    hit_ids = {str((hit or {}).get("id") or "") for hit in hits or []}
    reranked = {"pool": 0, "kept": len(hits or []), "dropped": 0}
    policy = None
    if isinstance(flags, dict) and isinstance(flags.get("point_expand_rerank"), bool):
        policy = bool(flags["point_expand_rerank"])
    use_rerank = _point_rerank_on(store, None) if policy is None else policy
    rows = []
    if use_rerank:
        pool = list(hits or []) + [entry for entry in extra
                                   if str(entry.get("id") or "") not in hit_ids]
        scores = (_rerank_scores(store, query, pool, rerank_config)
                  if query else None)
        reranked["pool"] = len(pool)
        if not scores:
            # no reranker configured: neighbours cannot be scored, so they do
            # not go in; only the hits (v9 behaviour).
            rows = [{"entry": hit, "hit": True, "score": 0.0} for hit in hits or []]
            reranked["kept"] = len(rows)
            reranked["dropped"] = len(extra)
        else:
            slots = max(0, int(limit or len(hits) or 1) - len(hit_ids))
            others = [entry for entry in pool
                      if str(entry.get("id") or "") not in hit_ids]
            others.sort(key=lambda entry: (
                -float(scores.get(str(entry.get("id") or ""), 0.0)),
                -_num(entry.get("ts"), 0.0),
                str(entry.get("id") or "")))
            chosen = others[:slots]
            reranked["kept"] = len(hit_ids) + len(chosen)
            reranked["dropped"] = len(others) - len(chosen)
            for hit in hits or []:
                rows.append({"entry": hit, "hit": True,
                             "score": float(scores.get(str(hit.get("id") or ""), 0.0))})
            for entry in chosen:
                rows.append({"entry": entry, "hit": False,
                             "score": float(scores.get(str(entry.get("id") or ""), 0.0))})
    else:
        for rank, hit in enumerate(hits or []):
            rows.append({"entry": hit, "hit": True, "score": 1.0 / (1.0 + rank)})
        for entry in extra:
            rows.append({"entry": entry, "hit": False, "score": 0.0})
    ordered = _point_expand.order(rows)
    prepared = []
    for row in ordered:
        line = _segment_line(row["entry"], use_date)
        if line:
            prepared.append((row, line))
    used = _point_expand.tokens(header)
    keep = []
    for row, line in prepared:
        if not row["hit"]:
            continue
        keep.append((row, line))      # a hit is never dropped for budget
        used += _point_expand.tokens(line)
    dropped = 0
    for row, line in prepared:
        if row["hit"]:
            continue
        cost = _point_expand.tokens(line)
        if used + cost <= budget:
            keep.append((row, line))
            used += cost
        else:
            dropped += 1
    keep_ids = {str((row.get("entry") or {}).get("id") or "")
                for row, _ in keep}
    text = header
    ids = []
    for row, line in prepared:
        entry_id = str((row.get("entry") or {}).get("id") or "")
        if entry_id not in keep_ids:
            continue
        text += line
        ids.append(entry_id)
    stats = {"hits": len(hits or []),
             "expanded": len([row for row in rows if not row["hit"]]),
             "lines": len(ids), "tokens": used, "dropped_expanded": dropped,
             "reranked": reranked}
    _record_point_state(store, stats)
    if len(text) <= len(header) + 2:
        return {"text": "", "chars": 0, "ids": [], "point": stats}
    return {"text": text, "chars": len(text), "ids": ids, "point": stats}

def _render_cover(entries, header, use_date, stats):
    """Render the cover-selected entries with the existing line format."""
    text = header
    ids = []
    for entry in entries:
        line = _segment_line(entry, use_date)
        if not line:
            continue
        text += line
        ids.append(str((entry or {}).get("id") or ""))
    if len(text) <= len(header) + 2:
        return {"text": "", "chars": 0, "ids": [], "cover": stats}
    return {"text": text, "chars": len(text), "ids": ids, "cover": stats}


EVENT_STATE_DIRNAME = "events"


def _event_layer_on(store, payload=None):
    """event_layer: payload flag > switches/config > default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("event_layer"), bool):
        return bool(data["event_layer"])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    return bool(switches.get("event_layer"))


def _event_state_path(store, session_id):
    data_dir = _store_data_dir(store) if store else None
    if not data_dir:
        return None
    return Path(data_dir) / EVENT_STATE_DIRNAME / (sanitize_session_id(session_id) + ".json")


_EVENT_STATE_CACHE = {}          # path -> (mtime_ns, size, state); bounded below
_EVENT_STATE_CACHE_MAX = 4


def _copy_event_state(state):
    """Copy the containers a caller may mutate, so the cache never leaks writes.

    Event dicts and their entry/claim lists are copied (a few thousand small
    dicts); the heavy part -- per-entry vectors -- is shared, because nothing
    outside the event layer rewrites a vector in place and a derivable field is
    never the thing a caller needs isolated.
    """
    out = {"seen": int(state.get("seen") or 0), "events": [], "state": {},
           "open": []}
    for ev in state.get("events") or []:
        if not isinstance(ev, dict):
            continue
        row = dict(ev)
        for key in ("entries", "claims", "members"):
            value = row.get(key)
            if isinstance(value, list):
                row[key] = [dict(item) if isinstance(item, dict) else item
                            for item in value]
        out["events"].append(row)
    out["state"] = dict(state.get("state") or {})
    out["open"] = [dict(item) if isinstance(item, dict) else item
                   for item in (state.get("open") or [])]
    return out


def _event_state_stamp(path):
    try:
        info = path.stat()
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return None


def _cache_event_state(path, state, token=None):
    """Remember one parsed state; a change token mismatch invalidates it."""
    try:
        if len(_EVENT_STATE_CACHE) >= _EVENT_STATE_CACHE_MAX:
            _EVENT_STATE_CACHE.pop(next(iter(_EVENT_STATE_CACHE)), None)
        _EVENT_STATE_CACHE[str(path)] = (token, 0, _copy_event_state(state))
    except Exception:
        pass


def _load_event_state_sql(root, session_id):
    """Event state straight out of sqlite (one row per event, centroid as BLOB)."""
    store_api = _sql_store()
    path = _db_path(root, session_id)
    token = _db_stamp(root, session_id)
    cached = _EVENT_STATE_CACHE.get(str(path))
    if cached is not None and token is not None and cached[0] == token:
        return _copy_event_state(cached[2])
    state = store_api.load_event_state(root, session_id)
    if state is None:
        # Importing the legacy file costs a 31 MB parse. A copied store repeats
        # that cost on every copy, so the fact of the import is persisted: once
        # the flag is set the JSON file is never read again, not even when it is
        # absent (an exported copy may not carry it at all).
        if str(_read_vector_meta(root, session_id).get("legacy_events_imported")) == "1":
            state = {"seen": 0, "events": [], "state": {}, "open": []}
        else:
            legacy = _load_event_state_json(root, session_id)
            if legacy.get("events") or legacy.get("seen"):
                try:
                    store_api.save_event_state(root, session_id,
                                               legacy.get("seen") or 0,
                                               legacy.get("events") or [],
                                               legacy.get("state") or {},
                                               legacy.get("open") or [])
                    _write_vector_meta(root, session_id,
                                       {"legacy_events_imported": 1})
                except Exception:
                    pass
            state = legacy
    _cache_event_state(path, state)
    return _copy_event_state(state)


def _load_event_state(store, session_id):
    """Parsed event state: sqlite by default, memoised on (mtime, size)."""
    root = _store_root(store)
    if root is not None and store_mode() != "json":
        return _load_event_state_sql(root, session_id)
    return _load_event_state_json(store, session_id)


def _load_event_state_json(store, session_id):
    """Parsed event state, memoised on (mtime, size): 31.8 MB must not be re-read.

    The event layer is consulted several times per turn (capacity guard, capture
    maintenance, injection), and each call used to parse the whole file. A stat
    is O(1); any external writer still invalidates because the stamp changes.
    """
    path = _event_state_path(store, session_id)
    blank = {"seen": 0, "events": [], "state": {}, "open": []}
    if path is None or not path.exists():
        if path is not None:
            _EVENT_STATE_CACHE.pop(str(path), None)
        return blank
    stamp = _event_state_stamp(path)
    cached = _EVENT_STATE_CACHE.get(str(path))
    if cached is not None and stamp is not None and cached[0] == stamp[0] \
            and cached[1] == stamp[1]:
        return _copy_event_state(cached[2])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return blank
    out = dict(blank)
    out["seen"] = int(data.get("seen") or 0)
    out["events"] = data.get("events") if isinstance(data.get("events"), list) else []
    out["state"] = data.get("state") if isinstance(data.get("state"), dict) else {}
    # the event that was still open when the last call saved
    out["open"] = data.get("open") if isinstance(data.get("open"), list) else []
    _cache_event_state(path, out, None)
    return _copy_event_state(out)


def _save_event_state(store, session_id, state):
    """Persist the event layer: sqlite rows only (JSON is an export format now)."""
    payload = dict(state or {})
    root = _store_root(store)
    if root is not None and store_mode() != "json":
        try:
            store_api = _sql_store()
            events = payload.get("events") or []
            opened = payload.get("open") or []
            # the vector of a row lives in the event that quotes it: keep the
            # entries table authoritative for coordinates before the payload
            # drops them (the JSON payload is id/turn/ts/role/text only)
            try:
                written = store_api.update_entry_vectors(
                    root, session_id,
                    store_api.harvest_event_vectors(events, opened))
                if written:
                    _EVEC_CACHE.pop(str(_db_path(root, session_id)), None)
            except Exception:
                pass
            store_api.save_event_state(root, session_id,
                                       payload.get("seen") or 0,
                                       events,
                                       payload.get("state") or {},
                                       opened)
        except Exception:
            return False
        # seed the memo with what we just wrote: the next turn must not reparse
        db_file = _db_path(root, session_id)
        token = _db_stamp(root, session_id)
        _cache_event_state(db_file, payload, token)
        _refresh_stamps(token, db_file, _MEM_DOC_CACHE, _EVEC_CACHE)
        return True
    if root is not None:
        try:
            from biocore_memory.store import sql_store as _S
            _S.save_event_state(root, session_id, payload.get("seen") or 0,
                                payload.get("events") or [], payload.get("state") or {},
                                payload.get("open") or [])
        except Exception:
            pass
    path = _event_state_path(store, session_id)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, payload)
    except Exception:
        return False
    # the write we just made is the freshest state there is: seed the memo with
    # it instead of letting the next turn re-parse 31.8 MB of our own output
    _cache_event_state(path, payload)
    return True


def _entry_vector(store, entry, config=None, payload=None):
    vector = entry.get("vector")
    if isinstance(vector, (list, tuple)) and vector:
        return list(vector)
    text = str(entry.get("text") or "").strip()
    if not text:
        return None
    try:
        from biocore_memory.recall.embedding import embed as _embed_fn
        from biocore_memory.recall.embedding import load_provider as _load_prov
        _payload_cfg = {}
        try:
            _pl = payload if isinstance(payload, dict) else {}
            if _pl.get("embedding_base_url"):
                _payload_cfg = {
                    "embedding_mode": _pl.get("embedding_mode") or "remote",
                    "embedding_base_url": _pl.get("embedding_base_url"),
                    "embedding_model": _pl.get("embedding_model"),
                    "embedding_dim": int(_pl.get("embedding_dim") or 1024),
                    "embedding_api_key": _pl.get("embedding_api_key") or "",
                    "embedding_timeout": 30,
                }
        except Exception:
            _payload_cfg = {}
        provider = _load_prov(_payload_cfg) if _payload_cfg else _load_prov(dict(config or {}))
        if provider is None:
            provider = _load_prov({})      # env-configured provider (host default)
        if provider is None:
            return None
        return _embed_fn(text, provider, path=_embed_cache_path(store))
    except Exception:
        return None


def _event_layer_notes(ev, buf, summarizer, global_state, chunk_tokens=400):
    """One note per chunk of a long span; the event boundary itself does not move."""
    from biocore_memory.event import events as _E
    from biocore_memory.event import rolling as _R
    chunks, cur, used = [], [], 0
    for row in buf:
        size = _E._tokens(str(row.get("text") or ""))
        if cur and used + size > chunk_tokens:
            chunks.append(cur)
            cur, used = [], 0
        cur.append(row)
        used += size
    if cur:
        chunks.append(cur)
    notes = []
    for index, part in enumerate(chunks):
        body = "\n".join("%s：%s" % (row.get("role") or "user", row.get("text") or "")
                         for row in part)
        part_ev = dict(ev)
        part_ev.update({"start": int(part[0].get("turn") or 0),
                        "end": int(part[-1].get("turn") or 0),
                        "text": body, "tokens": _E._tokens(body)})
        try:
            data = json.loads(summarizer(_R.rolling_prompt(global_state, part_ev)) or "{}")
        except Exception:
            continue
        if index == 0 and isinstance(data.get("state"), dict) and data["state"]:
            global_state.clear()
            global_state.update(_R.normalize_state(data["state"]))
        note = str(data.get("overview") or "").strip()
        if note:
            notes.append(note)
    return notes




JOURNAL_KINDS = ("capture", "event_close", "claim_merge", "inject",
                 "trim", "audit_warning")
JOURNAL_MAX_LINES = 2000


def _journal(store, session_id, kind, **fields):
    """Append one line to <store>/journal/<session>.jsonl; never raise."""
    try:
        root = _store_root(store)
        if root is None:
            return None
        folder = Path(root) / "journal"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (sanitize_session_id(session_id) + ".jsonl")
        row = {"ts": round(time.time(), 3), "kind": str(kind)}
        for key, value in fields.items():
            if isinstance(value, (list, dict)):
                row[key] = value
            elif isinstance(value, (int, float, bool)) or value is None:
                row[key] = value
            else:
                row[key] = str(value)[:200]
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        try:
            from biocore_memory.store import sql_store as _S
            conn = _S.connect(root, session_id)
            conn.execute("INSERT INTO journal (ts, kind, payload) VALUES (?,?,?)",
                         (row["ts"], row["kind"], json.dumps(row, ensure_ascii=False)))
            conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            if path.stat().st_size > 400_000:
                lines = path.read_text(encoding="utf-8").splitlines()
                path.write_text("\n".join(lines[-JOURNAL_MAX_LINES:]) + "\n",
                                encoding="utf-8")
        except Exception:
            pass
        return row
    except Exception:
        if os.environ.get("BIOCORE_JOURNAL_DEBUG"):
            print("journal_failed kind=%s" % kind, flush=True)
        return None

def _loads_tolerant(text):
    """Parse model JSON even when it is truncated or wrapped in prose."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(raw)):
        ch = raw[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except Exception:
                    break
    # truncated: close open braces and retry
    frag = raw[start:]
    frag += "}" * max(0, frag.count("{") - frag.count("}"))
    try:
        return json.loads(frag)
    except Exception:
        return {}


def _event_layer_close(events, buf, summarizer, global_state, store=None,
                       session_id=""):
    """Close one open event: one model call for state + overview."""
    from biocore_memory.event import events as _E
    from biocore_memory.event import rolling as _R
    body = "\n".join("%s：%s" % (row.get("role") or "user", row.get("text") or "")
                      for row in buf)
    ev = {"start": int(buf[0].get("turn") or 0), "end": int(buf[-1].get("turn") or 0),
          "members": [int(row.get("turn") or 0) for row in buf],
          "entries": [{"turn": int(row.get("turn") or 0), "ts": float(row.get("ts") or 0.0),
                       "role": row.get("role") or "user", "text": str(row.get("text") or ""),
                       "vector": row.get("vector"),
                       "id": str(row.get("id") or "")} for row in buf],
          "text": body, "tokens": _E._tokens(body),
          "vector": _mean_vector([row.get("vector") for row in buf]),
          "event_id": "EV%03d" % (len(events) + 1)}
    overview = ""
    _claims_done = False
    _day = None
    try:
        from datetime import datetime as _dt0
        _day = _dt0.fromtimestamp(float(buf[0].get("ts") or 0.0)).strftime("%Y-%m-%d")
    except Exception:
        _day = None
    if summarizer is not None and int(ev["tokens"]) > 800:
        overview = "；".join(_event_layer_notes(ev, buf, summarizer, global_state))
    elif summarizer is not None:
        from biocore_memory.event import claims as _C1
        prompt = _C1.combined_prompt(ev, state=global_state,
                                     known=sorted(global_state.keys())[:60], day=_day)
        _ov1, _st1, _cl1 = _C1.parse_combined(summarizer(prompt), day=_day)
        if _st1:
            global_state.clear()
            global_state.update(_R.normalize_state(_st1))
        overview = _ov1
        for _c in _cl1:
            _c["turn"] = int(ev.get("end") or 0)
        ev["claims"] = _cl1
        _claims_done = True
    if not overview:
        overview = str(ev["text"]).replace("\n", " ")[:30]
    ev["overview"] = overview
    if not _claims_done:
        ev["claims"] = []
    if summarizer is not None and not _claims_done:
        try:
            from biocore_memory.event import claims as _C
            _day = None
            try:
                from datetime import datetime as _dt
                _day = _dt.fromtimestamp(float(buf[0].get("ts") or 0.0)).strftime("%Y-%m-%d")
            except Exception:
                _day = None
            _known = sorted(global_state.keys())[:60]
            _raw = summarizer(_C.claims_prompt(ev, known=_known, day=_day))
            _ov2, _cs = _C.parse_claims(_raw, day=_day)
            for _c in _cs:
                _c["turn"] = int(ev.get("end") or 0)
            ev["claims"] = _cs
            if not ev.get("overview") and _ov2:
                ev["overview"] = _ov2
        except Exception as _exc:
            ev["claims_error"] = str(_exc)[:120]
    events.append(ev)
    try:
        _journal(store, session_id, "event_close", event=ev.get("event_id"),
                 start=ev.get("start"), end=ev.get("end"),
                 claims=len(ev.get("claims") or []),
                 threads=len({c.get("thread") for c in (ev.get("claims") or [])
                              if c.get("thread")}),
                 overview=ev.get("overview"))
    except Exception:
        pass



def _fold_event(dst, src):
    """Fold src into dst: members, span, centroid, note and claims all follow."""
    dst["entries"] = (dst.get("entries") or []) + (src.get("entries") or [])
    dst["members"] = (dst.get("members") or []) + (src.get("members") or [])
    dst["start"] = min(int(dst.get("start") or 0), int(src.get("start") or 0))
    dst["end"] = max(int(dst.get("end") or 0), int(src.get("end") or 0))
    dst["text"] = ((dst.get("text") or "") + "\n" + (src.get("text") or "")).strip()
    dst["tokens"] = int(dst.get("tokens") or 0) + int(src.get("tokens") or 0)
    dst["vector"] = _mean_vector([item.get("vector") for item in dst["entries"]])
    note = str(src.get("overview") or "").strip()
    if note and note not in str(dst.get("overview") or ""):
        dst["overview"] = (str(dst.get("overview") or "") + "；" + note).strip("；")
    dst["claims"] = (dst.get("claims") or []) + (src.get("claims") or [])
    return dst


def _merge_small_events(events, min_turns=2):
    """A one-turn event joins its neighbour: no span shorter than min_turns."""
    if len(events) < 2:
        return list(events)
    out = []
    for ev in events:
        if len(ev.get("members") or []) >= min_turns or not out:
            out.append(dict(ev))
            continue
        _fold_event(out[-1], ev)
    if len(out) > 1 and len(out[0].get("members") or []) < min_turns:
        out[1] = _fold_event(out[0], out[1])
        out.pop(0)
    return out


def _event_layer_close_adaptive(events, buf, summarizer, global_state, embed_fn=None,
                                 depth=0, store=None, session_id=""):
    """Close one buffer; bisect the span while its note does not cover the turns.

    The trial close is a real close (state included): when the note does not
    cover the span we drop the event and re-close the two halves, so the only
    thing lost is the note we rejected.
    """
    from biocore_memory.event import segment_adaptive as _SA
    if (embed_fn is None or depth >= 6 or len(buf) < 2 * _SA.MIN_TURNS):
        _event_layer_close(events, buf, summarizer, global_state,
                           store=store, session_id=session_id)
        return
    _event_layer_close(events, buf, summarizer, global_state,
                       store=store, session_id=session_id)
    ev = events[-1]
    try:
        note_vec = embed_fn(str(ev.get("overview") or ev.get("text") or ""))
    except Exception:
        note_vec = None
    turns = [row.get("vector") for row in buf]
    covered = _SA.coverage(note_vec, turns) if note_vec else 1.0
    _span = int(ev.get("end") or 0) - int(ev.get("start") or 0) + 1
    _chars = len(str(ev.get("text") or ""))
    _too_big = ((EVENT_MAX_TURNS > 0 and _span > EVENT_MAX_TURNS)
                or _chars > EVENT_MAX_CHARS)
    if covered >= _SA.COVER_MIN and not _too_big:
        return
    events.pop()
    cut = _SA.largest_jump(turns)
    if cut <= 0 or cut >= len(buf):
        _event_layer_close(events, buf, summarizer, global_state)
        return
    for part in _SA.merge_singletons([buf[:cut], buf[cut:]]):
        _event_layer_close_adaptive(events, part, summarizer, global_state,
                                    embed_fn, depth + 1)


def _mean_vector(vectors):
    rows = [list(v) for v in (vectors or []) if isinstance(v, (list, tuple)) and v]
    if not rows:
        return []
    dim = len(rows[0])
    return [sum(row[i] for row in rows if len(row) == dim) / len(rows) for i in range(dim)]


def _embedding_enabled(store, config, payload):
    """True when this store asks for real embeddings (either config shape)."""
    pl = payload if isinstance(payload, dict) else {}
    block = pl.get("embedding") if isinstance(pl.get("embedding"), dict) else {}
    if block.get("model") or block.get("base_url"):
        return True
    if pl.get("embedding_base_url") and pl.get("embedding_model"):
        return True
    cfg = config if isinstance(config, dict) else {}
    inner = cfg.get("embedding") if isinstance(cfg.get("embedding"), dict) else {}
    if inner.get("model") or inner.get("base_url"):
        return True
    if cfg.get("embedding_model") or cfg.get("embedding_base_url"):
        return True
    try:
        runtime = _load_runtime_config(store) if store else {}
    except Exception:
        runtime = {}
    inner = runtime.get("embedding") if isinstance(runtime.get("embedding"), dict) else {}
    return bool(inner.get("model") or inner.get("base_url")
                or runtime.get("embedding_model") or runtime.get("embedding_base_url"))


def _embedding_required(store, config, payload):
    return _embedding_enabled(store, config, payload)

def _event_embed_fn(store, config, payload):
    """One embed callable for this block; payload > config.json > env.

    Accepts both config shapes: the new {"embedding": {...}} block and the old
    flat embedding_* keys. When embedding is configured but no provider could be
    built this raises -- a silent fallback to lexical matching makes every query
    look alike and is far harder to notice than an error.
    """
    pl_cfg = {}
    pl = payload if isinstance(payload, dict) else {}
    block = pl.get("embedding") if isinstance(pl.get("embedding"), dict) else {}
    if block:
        pl_cfg = {"embedding_mode": block.get("mode") or "remote",
                  "embedding_base_url": block.get("base_url") or "",
                  "embedding_model": block.get("model") or "",
                  "embedding_api_key": block.get("key") or "",
                  "embedding_dim": int(block.get("dim") or 1024),
                  "embedding_timeout": 30}
    if pl.get("embedding_base_url"):
        # the caller's payload wins over config.json for this embedding call
        pl_cfg = {"embedding_mode": pl.get("embedding_mode") or "remote",
                  "embedding_base_url": pl.get("embedding_base_url"),
                  "embedding_model": pl.get("embedding_model") or "",
                  "embedding_dim": int(pl.get("embedding_dim") or 1024),
                  "embedding_api_key": pl.get("embedding_api_key") or "",
                  "embedding_timeout": 30}
    try:
        from biocore_memory.recall.embedding import embed as _embed
        from biocore_memory.recall.embedding import load_provider as _load_prov
        provider = _load_prov(pl_cfg) if pl_cfg else _load_prov(dict(config or {}))
        if provider is None:
            provider = _load_prov({})          # env-configured provider
    except Exception as exc:
        if _embedding_required(store, config, payload):
            raise RuntimeError(
                "embedding 已启用但未能构造 embedder (%s)：检查 core_config.json 的 "
                "embedding 键（新结构与旧扁平 embedding_* 都支持）；拒绝静默退化为词匹配"
                % type(exc).__name__)
        return None
    if provider is None:
        if _embedding_required(store, config, payload):
            raise RuntimeError(
                "embedding 已启用但未能构造 embedder：检查 core_config.json 里 "
                "embedding 块的 base_url/model；拒绝静默退化为词匹配")
        return None
    batch = None
    try:
        from biocore_memory.recall.embedding import embed_many as _embed_many
        batch = lambda texts: _embed_many(list(texts), provider,
                                          path=_embed_cache_path(store))
    except Exception:
        batch = None

    def _one(text):
        return _embed(str(text), provider, path=_embed_cache_path(store))

    # claim lines score dozens of short texts; batching them is the difference
    # between one round-trip and one per claim on a remote provider
    _one.embed_many = batch
    return _one



def _rerank_fn_from(payload, config=None):
    """(question, docs) -> scores, from payload > config > env; None when unset."""
    import os as _os
    src = payload if isinstance(payload, dict) else {}
    base = src.get("rerank_base_url")
    model = src.get("rerank_model")
    key = src.get("rerank_api_key")
    if not (base and model):
        cfg = config if isinstance(config, dict) else {}
        base = base or cfg.get("rerank_base_url") or _os.environ.get("BIOCORE_RERANK_BASE_URL") or _os.environ.get("BCMB_RERANK_BASE_URL")
        model = model or cfg.get("rerank_model") or _os.environ.get("BIOCORE_RERANK_MODEL") or _os.environ.get("BCMB_RERANK_MODEL")
        key = key or cfg.get("rerank_api_key") or _os.environ.get("BIOCORE_RERANK_KEY") or ""
    if not (base and model):
        return None
    endpoint = str(base).rstrip("/") + "/rerank"

    def _rerank(question, docs, text="sentence"):
        import urllib.request as _rq
        texts = [str(d.get("text") or d.get("overview") or "") if isinstance(d, dict) else str(d)
                 for d in (docs or [])]
        body = {"model": model, "query": str(question), "documents": texts}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        req = _rq.Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers)
        data = None
        for _attempt in range(3):
            try:
                data = json.loads(_rq.urlopen(req, timeout=30).read().decode("utf-8"))
                break
            except Exception:
                time.sleep(1.5 * (_attempt + 1))
        if data is None:
            return []          # rerank is an optimisation: fall back to cosine order
        rows = data.get("results") or data.get("data") or []
        scores = [0.0] * len(texts)
        for row in rows:
            try:
                scores[int(row.get("index") or 0)] = float(
                    row.get("relevance_score") if row.get("relevance_score") is not None
                    else row.get("score") or 0.0)
            except Exception:
                continue
        return scores

    return _rerank




def _claim_lines(query, events, embed_fn, top=8, min_score=0.35):
    """Facts first: score claim texts, keep the evidence sentence of each hit."""
    from biocore_memory.event import events as _E2
    if embed_fn is None or not str(query or "").strip():
        return []
    try:
        qv = embed_fn(str(query))
    except Exception:
        return []
    # one batch call for every claim text, then score from the results: the
    # order and the scores are identical to the per-call path (same vectors),
    # only the number of round-trips changes
    items, texts = [], []
    for ev in events or []:
        for claim in ev.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            text = "%s·%s：%s" % (claim.get("subject") or "", claim.get("attr") or "",
                                 claim.get("value") or "")
            if len(text) < 4:
                continue
            items.append((claim, ev, text))
            texts.append(text)
    vectors = None
    batch = getattr(embed_fn, "embed_many", None)
    if callable(batch) and texts:
        try:
            vectors = batch(texts)
        except Exception:
            vectors = None
    picked = []
    for slot, (claim, ev, text) in enumerate(items):
        vec = None
        if isinstance(vectors, list) and slot < len(vectors):
            vec = vectors[slot]
        if vec is None:
            try:
                vec = embed_fn(text)
            except Exception:
                continue
        if vec is None:
            continue
        try:
            score = _E2._cos(qv, vec)
        except Exception:
            continue
        if score >= min_score:
            picked.append((score, claim, ev, text))
    picked.sort(key=lambda item: item[0], reverse=True)
    lines = []
    seen = set()
    for score, claim, ev, text in picked[:top]:
        key = "%s|%s|%s" % (claim.get("subject"), claim.get("attr"), claim.get("value"))
        if key in seen:
            continue
        seen.add(key)
        turn = int(claim.get("turn") or 0)
        evidence = ""
        for row in ev.get("entries") or []:
            if int(row.get("turn") or 0) == turn:
                evidence = str(row.get("text") or "")
                break
        head = "【事实】%s（第%d轮｜相关度 %.2f）" % (text, turn, score)
        if claim.get("status") == "coexist":
            head += " ［两种说法并存］"
        lines.append(head)
        if evidence:
            lines.append("  - 原句：" + evidence[:160])
    return lines

def _event_entry_ids(store, session_id):
    """Entry ids the event table still refers to (old tables carry none)."""
    ids = set()
    try:
        state = _load_event_state(store, session_id)
    except Exception:
        return ids
    for ev in state.get("events") or []:
        for item in ev.get("entries") or []:
            if isinstance(item, dict) and item.get("id"):
                ids.add(str(item.get("id")))
    return ids


def _capacity_guard(store, session_id, entries):
    """Above MAX_ENTRIES: protect everything an event points at.

    No eviction policy is configured, so nothing is dropped: losing a row here
    is what silently emptied whole events (an entry vanished while the event
    that quoted it stayed), and the event table is the only reason those rows
    are alive at all.
    """
    keep = list(entries)
    protected = _event_entry_ids(store, session_id)
    if not protected:
        return keep
    # when an eviction policy lands it must consult this set; until then the
    # answer is "keep everything", which is exactly what the guard returns
    keep_ids = {str(row.get("id") or "") for row in keep}
    return [row for row in keep
            if str(row.get("id") or "") in protected or str(row.get("id") or "") in keep_ids]


def _event_layer_block(session_id, store, query, budget, rerank_config=None,
                       payload=None, summarizer=None, as_of=None):
    """Incremental event maintenance + two-stage recall, rendered for injection."""
    from biocore_memory.event import events as _E
    if not _E.enabled({_E.FLAG_KEY: True}):
        return None
    if summarizer is None:
        # no silent "no notes" degradation: the host must pass its LLM
        raise RuntimeError("event_layer is on but event_summarizer is missing")
    # the store keeps writes in memory (debounced); prefer it over the file
    try:
        live_entries = list(store.entries)
    except Exception:
        live_entries = []
    if not live_entries:
        live_entries = load_memory(store, session_id).get("entries") or []
    entries = [row for row in _visible(live_entries)
               if isinstance(row, dict) and str(row.get("text") or "").strip()]
    if not entries:
        stored0 = _load_event_state(store, session_id)
        for ev0 in stored0.get("events") or []:
            for item0 in ev0.get("entries") or []:
                if isinstance(item0, dict) and str(item0.get("text") or "").strip():
                    entries.append(item0)
    stored = _load_event_state(store, session_id)
    seen = min(int(stored.get("seen") or 0), len(entries))
    events = list(stored.get("events") or [])
    global_state = dict(stored.get("state") or {})
    config = {}
    try:
        config = _load_runtime_config(store) if store else {}
    except Exception:
        config = {}
    if _sql_backed(store):
        # sqlite keeps a row's vector in entries.vector, not in the event payload:
        # hydrate here so the two-stage recall sees what the JSON store carried
        vectors = _entry_vectors(store, session_id)
        if vectors:
            for row in events:
                for item in row.get("entries") or []:
                    if item.get("vector"):
                        continue
                    vector = vectors.get(str(item.get("id") or ""))
                    if vector:
                        item["vector"] = list(vector)
    for row in events:
        for item in row.get("entries") or []:
            if not item.get("vector"):
                item["vector"] = None
    buf = []
    for row in stored.get("open") or []:
        if isinstance(row, dict):
            buf.append(dict(row))          # an event that was still open last call
    new_rows = entries[seen:]
    # drift threshold from this session's own adjacent-turn similarities
    _thr = None
    try:
        from biocore_memory.event import segment_adaptive as _SA
        _window = entries[-ADAPTIVE_WINDOW:] if ADAPTIVE_WINDOW > 0 else entries
        _stamp = (len(entries), str((_window[-1].get("id") if _window else "") or ""))
        if _THR_MEMO.get("stamp") != _stamp:
            _THR_MEMO["stamp"] = _stamp
            _THR_MEMO["thr"] = _SA.adaptive_threshold(
                _SA.adjacent_similarities([row.get("vector") for row in _window]))
        _thr = _THR_MEMO.get("thr")
    except Exception:
        _thr = None
    thr = EVENT_SIM_CLOSE if _thr is None else _thr
    _entry_embedder = _event_embed_fn(store, config, payload)
    for offset, row in enumerate(new_rows):
        vec = _entry_vector(store, row, config, payload)
        # memory entries carry ts, not turn: fall back to their position
        turn = int(row.get("turn") or (seen + offset + 1))
        item = {"turn": turn, "ts": float(row.get("ts") or 0.0),
                "role": row.get("role") or "user", "text": str(row.get("text") or ""),
                "vector": vec, "id": str(row.get("id") or "")}
        if buf:
            gap = float(item["ts"]) - float(buf[-1]["ts"])
            sim = _E._cos(_mean_vector([b.get("vector") for b in buf]), vec) if vec else 1.0
            if sim < thr or gap > EVENT_GAP_S:
                _event_layer_close_adaptive(events, buf, summarizer, global_state,
                                            _entry_embedder)
                buf = []
        buf.append(item)
    tail_closed = False
    if buf and (not new_rows or str(query or "").strip()):
        # a recall call finalises the open event; a capture call keeps it open
        _event_layer_close_adaptive(events, buf, summarizer, global_state,
                                    _entry_embedder, store=store, session_id=session_id)
        buf = []
        tail_closed = True
    if len(events) > 1:
        events[:] = _merge_small_events(events)
    for index, ev in enumerate(events, 1):
        # bisecting pops and re-closes halves, so ids are renumbered here
        ev["event_id"] = "EV%03d" % index
    if new_rows or seen != len(entries) or tail_closed:
        _save_event_state(store, session_id,
                          {"seen": len(entries), "events": events,
                           "state": global_state, "open": buf})
    _as_of_ts = None
    if isinstance(payload, dict):
        try:
            _as_of_ts = float(payload.get("as_of_ts")) if payload.get("as_of_ts") else None
        except Exception:
            _as_of_ts = None
    if _as_of_ts is not None:
        # time is the only stable identity across rebuilds: never filter by position
        _kept = []
        for ev in events:
            _ts = [float(item.get("ts") or 0.0) for item in ev.get("entries") or []]
            _last = max(_ts) if _ts else 0.0
            if _last and _last <= _as_of_ts:
                _kept.append(ev)
        events = _kept
    elif as_of is not None:
        try:
            limit = float(as_of)
        except Exception:
            limit = None
        if limit is not None:
            events = [ev for ev in events if float(ev.get("start") or 0) <= limit]
    if not events or not str(query or "").strip():
        return None
    live = []
    for ev in events:
        for item in ev.get("entries") or []:
            if item.get("vector"):
                live.append({"turn": item["turn"], "vector": item["vector"],
                             "text": item.get("text") or ""})
    embed_fn = _event_embed_fn(store, config, payload)
    filled = 0
    if not live and embed_fn is not None:
        for ev in events:
            for item in ev.get("entries") or []:
                if item.get("vector"):
                    continue
                try:
                    item["vector"] = embed_fn(str(item.get("text") or ""))
                    live.append({"turn": item.get("turn"), "vector": item["vector"],
                                 "text": item.get("text") or ""})
                    filled += 1
                except Exception:
                    continue
    if not live:
        if os.environ.get("BIOCORE_DEBUG_EV"):
            print("DBG-EV no-live events=%d entries=%d seen=%d side=%s"
                  % (len(events), len(entries), seen, "sql" if _sql_backed(store) else "json"),
                  file=sys.stderr)
        return None
    for ev in events:
        if not ev.get("vector"):
            # an event whose entries were only just embedded needs its centroid
            ev["vector"] = _mean_vector([item.get("vector")
                                        for item in ev.get("entries") or []])
    if filled:
        # keep them: re-embedding every turn would cost a model call per entry
        _save_event_state(store, session_id,
                          {"seen": int(stored.get("seen") or 0), "events": events,
                           "state": global_state})
    rerank_fn = _rerank_fn_from(payload if isinstance(payload, dict) else {}, config)
    try:
        _journal(store, session_id, "rerank_probe",
                 enabled=bool(rerank_fn), base=(payload or {}).get("rerank_base_url")
                 if isinstance(payload, dict) else None)
    except Exception:
        pass
    selected = _E.event_recall(
        query, events, budget_tokens=8000, flags={_E.FLAG_KEY: True},
        embed=embed_fn,
        entry=(os.environ.get("BIOCORE_ENTRY") or
               ("two_stage" if embed_fn is not None else "summary")),
        entries=live,
        coarse_events=int(os.environ.get("BIOCORE_COARSE_EVENTS") or 30),
        fine_pool=int(os.environ.get("BIOCORE_FINE_POOL") or 100),
        fine_keep=int(os.environ.get("BIOCORE_FINE_KEEP") or 30),
        sent_pool=int(os.environ.get("BIOCORE_SENT_POOL") or 60),
        rerank=rerank_fn, rerank_text="sentence")
    lines = []
    try:
        from biocore_memory.event.timerender import normalize_relative_time as _nrt
    except Exception:
        _nrt = None
    try:
        from datetime import datetime as _dt
    except Exception:
        _dt = None
    def _day(ts):
        try:
            return _dt.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "无时间"
    seed_vec = None
    if embed_fn is not None:
        try:
            seed_vec = embed_fn(query)
        except Exception:
            seed_vec = None
    def _cos2(a, b):
        try:
            import math as _m
            dot = sum(x * y for x, y in zip(a, b)); na = _m.sqrt(sum(x * x for x in a)); nb = _m.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0.0
        except Exception:
            return 0.0
    by_turn2 = {}
    by_id2 = {}
    by_evid2 = {}
    # an event row is self-contained (id + text); the store is only a hint for
    # rows written before ids existed, and for refreshing an empty body
    for _row in entries:
        _rid = str(_row.get("id") or "")
        if _rid:
            by_id2[_rid] = _row
    for _ev_row in events:
        _evid = str(_ev_row.get("event_id") or "")
        _bundle = []
        for _item in _ev_row.get("entries") or []:
            _rid = str(_item.get("id") or "")
            if _rid and _rid in by_id2 and not str(_item.get("text") or "").strip():
                _live = by_id2[_rid]
                _item = dict(_item)
                _item["text"] = str(_live.get("text") or "")
                _item["ts"] = float(_live.get("ts") or _item.get("ts") or 0.0)
            _bundle.append(_item)
            try:
                by_turn2.setdefault(int(_item.get("turn") or 0), []).append(_item)
            except Exception:
                continue
        if _evid:
            by_evid2[_evid] = _bundle
    _ordered = list(selected)
    if os.environ.get("BIOCORE_DEBUG_EV"):
        print("DBG-EV selected=%d ordered=%d entries=%d bt2_keys=%s row_keys=%s"
              % (len(selected), len(_ordered), len(entries), sorted(by_turn2)[:12],
                 sorted(entries[0].keys()) if entries else []), file=sys.stderr)
    if as_of is not None:
        try:
            _recent = [ev for ev in events
                       if int(ev.get("end") or 0) <= int(as_of)
                       and int(ev.get("end") or 0) > int(as_of) - 10]
            _recent.sort(key=lambda ev: int(ev.get("end") or 0), reverse=True)
            _have = {str(ev.get("event_id") or "") for ev in _ordered}
            for ev in _recent[:3]:
                if str(ev.get("event_id") or "") not in _have:
                    _ordered.append(ev)
                    _have.add(str(ev.get("event_id") or ""))
        except Exception:
            pass
    for ev in _ordered:
        start, end = int(ev.get("start") or 0), int(ev.get("end") or 0)
        # the event carries its own rows: never look them up by store position
        rows = list(by_evid2.get(str(ev.get("event_id") or "")) or [])
        if not rows:                      # legacy events without an event id
            for turn in range(start, end + 1):
                rows.extend(by_turn2.get(turn) or [])
        if not rows:
            continue
        _cap = 5
        try:
            from biocore_memory.event import claims as _CL
            _cap, _dens = _CL.budget_hint(ev)
        except Exception:
            _cap = 5
        _mode = str((payload or {}).get("event_cap_mode") or EVENT_CAP_MODE)
        if _mode == "flat":
            _cap = 5
        elif _mode == "min3":
            _cap = max(3, int(_cap))
        EVENT_CAP_STATS["events"] += 1
        if _cap <= 0:
            EVENT_CAP_STATS["skipped"] += 1
        if seed_vec is not None:
            ranked_rows = sorted(rows, key=lambda r: _cos2(seed_vec, r.get("vector") or []),
                                 reverse=True)
        else:
            ranked_rows = list(rows)
        if SENT_POOL > 0:
            # only the best N rows compete: a long noisy event cannot flood the block
            ranked_rows = sorted(ranked_rows,
                                 key=lambda r: float(r.get("ts") or 0.0))[:0] + ranked_rows[:SENT_POOL]
        # the note may carry a low-density event, but never at the price of the one
        # turn that actually matches: the best row is rendered whatever the cap says
        rows = ranked_rows[:_cap] if _cap > 0 else []
        for row in ranked_rows[:1]:
            if all(row is not kept for kept in rows):
                rows.append(row)
        rows.sort(key=lambda r: float(r.get("ts") or 0.0))
        EVENT_CAP_STATS["rows"] += len(rows)
        if os.environ.get("BIOCORE_DEBUG_EV"):
            print("DBG-EV ev=%d-%d rows=%d" % (start, end, len(rows)), file=sys.stderr)
        lines.append("【事件｜第%d-%d轮】%s" % (start, end, str(ev.get("overview") or ev.get("summary") or "")[:60]))
        for row in rows:
            body = str(row.get("text") or "")
            if _nrt is not None:
                try:
                    body = _nrt(body, float(row.get("ts") or 0.0))
                except Exception:
                    pass
            who = "用户" if str(row.get("role")) == "user" else "助手"
            lines.append("- [%s %s] %s" % (_day(row.get("ts")), who, body))
    if not lines:
        return None
    state_lines = []
    try:
        from biocore_memory.event import claims as _claims
        _raw = []
        for _ev in _ordered:
            for _item in _ev.get("claims") or []:
                if isinstance(_item, dict):
                    _raw.append(_item)
        if _raw:
            state_lines = _claims.render_claims(_claims.merge_claims(_raw), limit=8)
    except Exception:
        state_lines = []
    _private = []
    try:
        from biocore_memory.event import claims as _CL2
        _praw = []
        for _ev in _ordered:
            for _it in _ev.get("claims") or []:
                if isinstance(_it, dict):
                    _praw.append(_it)
        if _praw:
            _private = _CL2.private_lines(_CL2.merge_claims(_praw))
    except Exception:
        _private = []
    head = ["【注意】若记录里同一件事出现过两种不同说法，先说明两种说法并注明记录不足以确定、需向用户确认；若后一种是对前一种的更正或核对过的结果，采用后一种。"]
    if _private:
        _keys = [str(line).split("：")[0].replace("【不可外传】", "") for line in _private]
        _keys = [k for k in _keys if k]
        if _keys:
            head.append("【禁止主动披露】以下条目只有用户直接问起时才可提及，不要主动展开："
                        + "、".join(_keys[:6]))
    _claims = []
    try:
        _claims = _claim_lines(query, _ordered, embed_fn)
    except Exception:
        _claims = []
    lines = head + _private + state_lines + (_claims + [""] if _claims else []) + lines
    text = "你记得这些事：\n" + "\n".join(lines)
    try:
        _journal(store, session_id, "inject", query=str(query)[:60],
                 events=len(_ordered), lines=len(lines),
                 state_lines=len(state_lines), chars=len(text))
    except Exception:
        pass
    text = _trim_lines(text, budget)
    return {"text": text, "chars": len(text),
            "ids": [str(ev.get("event_id") or "") for ev in selected]}




def _trim_lines(text, budget):
    """Trim to the budget on line boundaries; never cut mid-sentence."""
    raw = str(text or "")
    try:
        budget = int(budget or 0)
    except Exception:
        return raw
    if budget <= 0 or len(raw) <= budget:
        return raw
    lines = raw.split("\n")
    kept, used = [], 0
    for line in lines:
        if used + len(line) + 1 > budget - 24:
            break
        kept.append(line)
        used += len(line) + 1
    dropped = len(lines) - len(kept)
    note = "（已省略 %d 行，超出本次注入预算）" % dropped
    return "\n".join(kept) + "\n" + note

def inject_block(session_id, store, max_chars=MAX_CHARS, top_k=TOP_K,
                 query="", mode="query", rerank_config=None, now=None,
                 include_superseded=False, payload=None, as_of=None):
    """Top-k session memories as one bounded Chinese prompt block.

    mode="query"  recall this turn's words (engine.recall + env embedder,
                  optional rerank); any failure falls back to recent.
    mode="recent" keep the pin+ts ordering.
    """
    session_id = sanitize_session_id(session_id)
    # a store whose vectors came from another model must never be read silently
    ensure_vector_space(store, session_id)
    budget = _int_param(max_chars, MAX_CHARS, 0, max(MAX_CHARS, INJECT_MAX_CHARS))
    limit = _int_param(top_k, TOP_K, 1, INJECT_MAX_K)
    text_query = clean_text(query, MAX_TEXT_CHARS)
    chosen = str(mode or "query").strip().lower()
    if _event_layer_on(store, payload):
        # no fallback here: a broken event layer must fail loudly
        event_block = _event_layer_block(
            session_id, store, text_query, budget, rerank_config=rerank_config,
            payload=payload,
            summarizer=(payload.get("event_summarizer")
                        if isinstance(payload, dict) else None),
            as_of=as_of)
        if not event_block or not event_block.get("text"):
            raise RuntimeError("event_layer returned an empty block")
        return event_block
    if _segment_recall_on(store, payload) and _segments is not None:
        segmented = _inject_segments(
            session_id, store, text_query, limit, budget,
            "你记得这些事：", _date_prefix_on(store, payload))
        if segmented is not None:
            return segmented
    entries = []
    query_used = False
    if chosen == "query" and text_query:
        try:
            picked = _query_entries(store, session_id, text_query, limit,
                                    rerank_config, now=now,
                                    include_superseded=include_superseded)
        except Exception:
            picked = None
        if picked:
            entries = list(picked)
            query_used = True
    if not entries:
        # fetch a wider window so the answer-type bias has room to lift a
        # memory that the recent order alone would have cut
        entries = sorted(_visible(load_memory(store, session_id).get("entries")),
                         key=lambda entry: (1 if entry.get("pin") else 0,
                                            _num(entry.get("ts"), 0.0)),
                         reverse=True)[:max(limit, 20)]
    if (query_used and text_query and entries and _extensions is not None):
        try:
            all_entries = _visible(load_memory(store, session_id).get("entries"))
            ext = _extensions.expand_recall(
                store, all_entries, text_query,
                [str(entry.get("id") or "") for entry in entries])
            for row in ext.get("extra") or []:
                if row not in entries:
                    entries.append(row)
            entries = entries[:max(limit, min(limit + 2, INJECT_MAX_K))]
        except Exception:
            pass
    entries = entries[:limit]
    header = "你记得这些事："
    ids = []
    if not entries or budget <= len(header) + 3:
        return {"text": "", "chars": 0, "ids": []}
    use_date = _date_prefix_on(store, payload)
    if _point_expand_on(store, payload) and _point_expand is not None:
        point_flags = _point_expand_flags(store)
        if (isinstance(payload, dict)
                and isinstance(payload.get("point_expand_rerank"), bool)):
            point_flags = dict(point_flags)
            point_flags["point_expand_rerank"] = payload["point_expand_rerank"]
        expanded = _inject_point_expand(session_id, store, entries[:limit],
                                        header, use_date, point_flags,
                                        query=text_query, limit=limit,
                                        rerank_config=rerank_config)
        if expanded is not None:
            return expanded
    if _cover_on(store, payload) and _cover is not None:
        picked, cover_stats, _pool_ids = _cover_pick(
            store, session_id, text_query, limit, now=now,
            rerank_config=rerank_config, payload=payload)
        if picked:
            rendered = _render_cover(picked, header, use_date, cover_stats)
            if rendered["text"]:
                return rendered
    text = header
    for entry in entries:
        content = clean_text(entry.get("text"), 500)
        if not content:
            continue
        prefix = ""
        if use_date:
            day = _memory_date(entry)
            if day:
                prefix = "[" + day + "] "
        room = budget - len(text)
        if room <= 2:
            break
        line = "\n- " + prefix + content
        if len(line) > room:
            clipped = room - 4 - len(prefix)
            if clipped <= 1:
                break
            line = "\n- " + prefix + content[:clipped] + "…"
        text += line
        ids.append(str(entry.get("id") or ""))
    if len(text) <= len(header) + 2:
        return {"text": "", "chars": 0, "ids": []}
    return {"text": text, "chars": len(text), "ids": ids}


# ---------------------------------------------------------------- gate
def gate_reply(reply_text, flags=None):
    """Expression gate using the same rules as the AstrBot boundary path."""
    data = flags if isinstance(flags, dict) else {}
    raw_switches = data.get("switches") if isinstance(data.get("switches"), dict) else data
    effective = normalize_switches(raw_switches)
    user_text = str(data.get("user_text") or "")
    text = str(reply_text or "")
    if _boundary_gate is None:
        return {"ok": True, "hit": False, "blocked": False, "action": "pass",
                "rule": "", "label": "", "reason": "gate_unavailable",
                "text": text, "changed": False, "rules": []}
    decision = _boundary_gate.evaluate(text, user_text=user_text,
                                       flags=effective)
    blocked = bool(decision.get("blocked"))
    rule = str(decision.get("rule") or "")
    final = str(decision.get("text") or text)
    if not blocked:
        action = "pass"
    elif rule == "crisis_safety":
        action = "replace"
    else:
        action = "truncate"
    return {
        "ok": True,
        "hit": blocked,
        "blocked": blocked,
        "action": action,
        "rule": rule,
        "label": str(decision.get("label") or rule),
        "reason": str(decision.get("label") or rule),
        "text": final,
        "changed": bool(decision.get("changed")),
        "rules": list(decision.get("rules") or []),
    }


# ---------------------------------------------------------------- prompt block
def _state_block(state, budget):
    state = state if isinstance(state, dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    intero = state.get("intero") if isinstance(state.get("intero"), dict) else {}
    if not intero and isinstance(core.get("intero"), dict):
        intero = core["intero"]
    relation = state.get("relation") if isinstance(state.get("relation"), dict) else {}
    tone = state.get("tone") if isinstance(state.get("tone"), dict) else {}
    autonomy = state.get("autonomy") if isinstance(state.get("autonomy"), dict) else {}
    v = _num(state.get("v", core.get("v", state.get("valence"))), 0.0)
    parts = ["心情不错" if v >= 0.35 else ("心情有点低" if v <= -0.35 else "心情平稳")]
    for key, high, low in (
        ("tension", "绷得有点紧", "还算松"),
        ("warmth", "想靠近一点", None),
        ("heaviness", "有点沉", None),
        ("clarity", None, "没听太清"),
    ):
        value = _num(intero.get(key), 0.5)
        if high and value >= 0.62:
            parts.append(high)
        if low and value <= 0.38:
            parts.append(low)
    label = str(tone.get("label") or "").strip()
    if label:
        parts.append(label)
    stage = str(relation.get("stage") or "").strip()
    if stage:
        parts.append("关系" + stage)
    autonomy_state = str(autonomy.get("state") or "").strip()
    if autonomy_state and autonomy_state not in ("静", ""):
        parts.append("自主" + autonomy_state)
    text = "此刻：" + "；".join(parts) + "。"
    if len(text) > budget:
        text = text[:max(1, budget - 1)] + "…"
    return text


def _constraints_block(state, switches, payload):
    state = state if isinstance(state, dict) else {}
    switches = switches if isinstance(switches, dict) else {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    intero = state.get("intero") if isinstance(state.get("intero"), dict) else {}
    if not intero and isinstance(core.get("intero"), dict):
        intero = core["intero"]
    tension = _num(intero.get("tension"), 0.5)
    v = _num(state.get("v", core.get("v", state.get("valence"))), 0.0)
    lines = []
    if v <= -0.3 or tension >= 0.65:
        lines.append("先接住情绪再谈事，句子短一点、语气放软。")
    else:
        lines.append("语气自然平稳，先回应对方在意的事。")
    if _as_bool(payload.get("length_hint"), False):
        target = _int_param(payload.get("length_target"), 10, 1, 30)
        hard = _int_param(payload.get("length_max"), 30, target, 60)
        lines.append("一次只说一句，通常 %d 字以内，最多 %d 字；需要停顿用换行。"
                     % (target, hard))
    if _as_bool(switches.get("proactive_send"), False):
        lines.append("可以主动一点，但不连发、不催促。")
    else:
        lines.append("先不主动发新消息，等对方开口。")
    allow = _as_bool(payload.get("allow_correction"), False)
    lines.append("允许改口：" + ("是，说错了可以补一句。" if allow else "否，先确认再答。"))
    return "\n".join("- " + line for line in lines[:6])


def prompt_block(payload):
    """State block (<=200 chars) + short expression constraints (task-204)."""
    data = payload if isinstance(payload, dict) else {}
    phase = str(data.get("phase") or "turn").strip().lower()
    if phase not in ("boot", "turn"):
        phase = "turn"
    budget = _int_param(data.get("max_chars"), MAX_STATE_CHARS, 40,
                        MAX_STATE_CHARS)
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    switches = normalize_switches(data.get("switches"))
    state_text = _state_block(state, budget)
    constraints = _constraints_block(state, switches, data)
    text = (state_text + "\n" + constraints).strip()
    if _lifecycle is not None:
        try:
            repair = _lifecycle.repair_lines(data.get("store"))
            if repair:
                text = text + "\n" + "\n".join("- " + line for line in repair)
        except Exception:
            pass
    expression = None
    if _extensions is not None:
        try:
            target = _int_param(data.get("length_target"), 0, 0, 400)
            hard = _int_param(data.get("length_max"), 0, 0, 400)
            expression = _extensions.expression_block(
                data.get("store"), state, data.get("relationship"),
                soft_target=target, soft_max=hard)
            extra = [value for value in (expression.get("rules"),
                                         expression.get("template"),
                                         expression.get("topic"),
                                         expression.get("voice")) if value]
            lines = []
            for value in extra:
                for line in str(value).splitlines():
                    line = line.strip()
                    if line:
                        lines.append(line if line.startswith("- ") else "- " + line)
            if lines:
                text = text + "\n" + "\n".join(lines[:6])
        except Exception:
            expression = None
    policy, policy_extra = expression_prompt_extra(state, data)
    policy_rows = [str(row.get("text") or "")
                   for row in (policy_extra.get("hints") or [])
                   if isinstance(row, dict)
                   and row.get("source") == "expression_policy"
                   and row.get("text")]
    if policy_rows:
        text = text + "\n" + "\n".join("- " + row for row in policy_rows[:2])
    thinking_line = thinking_style_line(data)
    persona_line = persona_prompt_line(data)
    if thinking_line:
        text = text + "\n" + thinking_line
    if persona_line:
        text = text + "\n" + persona_line
    sections = {"state": state_text, "constraints": constraints}
    if thinking_line:
        sections["thinking_style"] = thinking_line
    if expression:
        sections["expression"] = expression
    if persona_line:
        sections["persona"] = persona_line
    if policy.get("enabled"):
        sections["expression_policy"] = policy
    return {"ok": True, "phase": phase, "text": text, "chars": len(text),
            "sections": sections}


# ---------------------------------------------------------------- constraints
def constraint_hint(query, open_loops=None, commitments=None):
    """Same <=140-char hint as the existing AstrBot constraints path (thin)."""
    try:
        from biocore_memory.recall.constraints import check_constraints
        return check_constraints(query, open_loops=open_loops,
                                 commitments=commitments)
    except Exception:
        return None


# ---------------------------------------------------------------- tools
def _tokens(text):
    lowered = str(text or "").lower()
    out = _LATIN.findall(lowered)
    for run in _CJK.findall(lowered):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[index:index + 2] for index in range(len(run) - 1))
    return out


def _score(query, text):
    q_tokens = set(_tokens(query))
    if not q_tokens:
        return 0.0
    t_tokens = set(_tokens(text))
    if not t_tokens:
        return 0.0
    overlap = len(q_tokens & t_tokens)
    if not overlap:
        return 1.0 if str(query) and str(query) in str(text) else 0.0
    return round(overlap / float(len(q_tokens)), 4)


def _space_switch(store, payload=None):
    """spatial_recall: payload flag > flags.json / config > env > default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("spatial_recall"), bool):
        return bool(data["spatial_recall"])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    if isinstance(switches.get("spatial_recall"), bool):
        return bool(switches["spatial_recall"])
    if _space is not None:
        return _space.enabled(flags=data, env=os.environ)
    return False


def _select_switch(store, payload=None):
    """spatial_select: payload flag > switches/config > core default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("spatial_select"), bool):
        return bool(data["spatial_select"])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    if isinstance(switches.get("spatial_select"), bool):
        return bool(switches["spatial_select"])
    if _space is not None:
        return _space.select_enabled(flags=data, env=os.environ)
    return False


def _reconsolidate_switch(store, payload=None):
    """spatial_reconsolidate: payload flag > switches/config > default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("reconsolidate"), bool):
        return bool(data["reconsolidate"])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    if isinstance(switches.get("spatial_reconsolidate"), bool):
        return switches["spatial_reconsolidate"]
    if _space is not None:
        return _space.reconsolidate_enabled(flags=data, env=os.environ)
    return False


def _refresh_hit_space(store, session_id, doc, entries, rows, payload=None):
    """Nader 2000 on the host path: every hit rewrites its own coordinates.

    Only the rows that were actually returned are rewritten, with the
    relationship that is current now; the doc is saved once at the end.
    """
    if _space is None or not rows:
        return {"refreshed": 0, "ids": [], "drift": 0.0, "at": 0.0}
    stamp = _num((payload or {}).get("ts"), time.time()) if isinstance(payload, dict) else time.time()
    try:
        relationship = relationship_read(store)["relationship"]
    except Exception:
        relationship = {}
    embed = _space_embed_info(store)
    by_id = {str(entry.get("id") or ""): entry for entry in (entries or [])
             if isinstance(entry, dict)}
    ids, drift = [], 0.0
    for row in rows:
        entry = by_id.get(str((row or {}).get("id") or ""))
        if not isinstance(entry, dict):
            continue
        fresh = _space.refresh(entry, relationship, now=stamp, embed=embed)
        if not isinstance(fresh, dict):
            continue
        entry["space"] = fresh
        ids.append(str(entry.get("id") or ""))
        try:
            drift += float((fresh.get("drift") or {}).get("weighted") or 0.0)
        except Exception:
            pass
    if ids and doc is not None:
        save_memory(store, session_id, doc)
    return {"refreshed": len(ids), "ids": ids,
            "drift": round(drift, 6) if ids else 0.0,
            "at": round(float(stamp), 3)}


def _space_embed_info(store):
    """Embedding provider / model names, kept in the coordinates for auditing."""
    info = {"provider": "", "model": ""}
    try:
        cfg = _load_runtime_config(store)
    except Exception:
        cfg = {}
    block = cfg.get("embedding") if isinstance(cfg.get("embedding"), dict) else cfg
    if isinstance(block, dict):
        info["provider"] = str(block.get("provider")
                              or block.get("embedding_provider") or "")[:64]
        info["model"] = str(block.get("model")
                           or block.get("embedding_model") or "")[:64]
    return info


def _attach_displacement(entry, entries, now=None):
    """TransE displacement from the previous memory about the same fact.

    (Bordes 2013) h + r ~= t: two adjacent memories of one (subject,
    attribute) give the relation between them; the later one carries it.
    Nothing is written when the entry has no coordinates or no subject.
    """
    if _space is None or not isinstance(entry, dict):
        return entry
    coords = entry.get("space")
    if not isinstance(coords, dict):
        return entry
    subject = str(entry.get("subject") or "").strip()
    attribute = str(entry.get("attribute") or "").strip()
    if not subject or not attribute:
        return entry
    latest = None
    for other in (entries or []):
        if not isinstance(other, dict) or other is entry or other.get("deleted"):
            continue
        if str(other.get("subject") or "").strip() != subject:
            continue
        if str(other.get("attribute") or "").strip() != attribute:
            continue
        if latest is None or _num(other.get("ts"), 0.0) > _num(latest.get("ts"), 0.0):
            latest = other
    if latest is None:
        return entry
    shift = _space.displacement(latest, entry, now=now)
    if isinstance(shift, dict):
        coords["displacement"] = shift
    return entry


def _attach_space(entry, store, session_id, payload=None, now=None):
    """Add the shadow coordinates to one NEW entry; failure leaves it untouched.

    recall never reads this field: it is a write-only coordinate snapshot, and
    a duplicate write keeps the coordinates the entry already has.
    """
    if _space is None or not isinstance(entry, dict):
        return entry
    data = payload if isinstance(payload, dict) else {}
    if not _space_switch(store, data):
        return entry
    try:
        relationship = relationship_read(store)["relationship"]
    except Exception:
        relationship = {}
    try:
        space = _space.build(entry, relationship, now=now,
                             embed=_space_embed_info(store))
    except Exception:      # coordinates are a shadow; never a reason to fail
        space = None
    if isinstance(space, dict):
        entry = dict(entry)
        entry["space"] = space
    return entry


# ------------------------------------------------------ surprise priority (task-230)
def priority_enabled(payload=None):
    """surprise_priority: payload flag > flags.json / config > env > default ON."""
    if _priority is None:
        return False
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("surprise_priority"), bool):
        return bool(data["surprise_priority"])
    try:
        switches = _effective_switches(data.get("store") or _default_store(),
                                       data.get("switches"))
    except Exception:
        switches = {}
    if isinstance(switches.get("surprise_priority"), bool):
        return bool(switches["surprise_priority"])
    return _priority.enabled(flags=data, env=os.environ)


def _priority_values(store, session_id):
    """The six field numbers this session is currently sitting at."""
    state = _load_session_state(store, session_id)
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    relationship = {}
    try:
        relationship = relationship_read(store)["relationship"]
    except Exception:
        relationship = state.get("relationship") or {}
    return _priority.field_values(core, relationship), relationship


def consolidation_priority(store, session_id, payload=None, limit=10):
    """Read-only /state block: top candidates + each factor line."""
    data = payload if isinstance(payload, dict) else {}
    empty = {"schema": 0, "enabled": False, "reason": "unavailable",
             "field_surprise": {}, "top": []}
    if _priority is None:
        return dict(empty)
    sid = sanitize_session_id(session_id)
    on = priority_enabled(data)
    values, relationship = _priority_values(store, sid)
    entries = _visible(load_memory(store, sid).get("entries"))
    row = _priority.summary(entries, values, relationship, limit,
                            enabled_override=on)
    row["reason"] = "ok" if on else "disabled"
    return row


# ------------------------------------------- spatial recall / rerank (task-244)
SPATIAL_RERANK_KEY = "spatial_rerank"
RETRIEVAL_LAST_FILE = "retrieval_last.json"
RERANK_ENV = {"rerank_base_url": "BIOCORE_RERANK_BASE_URL",
              "rerank_model": "BIOCORE_RERANK_MODEL",
              "rerank_api_key": "BIOCORE_RERANK_API_KEY",
              "rerank_timeout": "BIOCORE_RERANK_TIMEOUT",
              "rerank_top_n": "BIOCORE_RERANK_TOP_N"}


def _spatial_rerank_switch(store, payload=None):
    """spatial_rerank: payload flag > flags.json / config > env > default OFF."""
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get(SPATIAL_RERANK_KEY), bool):
        return bool(data[SPATIAL_RERANK_KEY])
    try:
        switches = _effective_switches(store, None)
    except Exception:
        switches = {}
    if isinstance(switches.get(SPATIAL_RERANK_KEY), bool):
        return bool(switches[SPATIAL_RERANK_KEY])
    raw = str(os.environ.get("BIOCORE_SPATIAL_RERANK") or "").strip().lower()
    if raw in ("1", "true", "on", "yes"):
        return True
    if raw in ("0", "false", "off", "no"):
        return False
    return False


def _rerank_config(store, payload=None):
    """BIOCORE_RERANK_* env > runtime config rerank block > payload.rerank."""
    data = payload if isinstance(payload, dict) else {}
    try:
        cfg = _load_runtime_config(store) if store else {}
    except Exception:
        cfg = {}
    block = cfg.get("rerank") if isinstance(cfg.get("rerank"), dict) else cfg
    out = dict(block) if isinstance(block, dict) else {}
    for key, env_key in RERANK_ENV.items():
        value = str(os.environ.get(env_key) or "").strip()
        if value:
            out[key] = value
    if isinstance(data.get("rerank"), dict):
        out.update({key: value for key, value in data["rerank"].items()
                    if not isinstance(value, dict)})
    return out


def _record_retrieval(store, row):
    """<dataDir>/retrieval_last.json: what the last recall stage did."""
    try:
        data_dir = _store_data_dir(store) if store else None
        if data_dir is None:
            return False
        row = dict(row)
        row["ts"] = round(time.time(), 3)
        _atomic_write(Path(data_dir) / RETRIEVAL_LAST_FILE, row)
        return True
    except Exception:
        return False


def _retrieval_last(store):
    try:
        data_dir = _store_data_dir(store) if store else None
        if data_dir is None:
            return {}
        row = _load_json(Path(data_dir) / RETRIEVAL_LAST_FILE, {})
        return row if isinstance(row, dict) else {}
    except Exception:
        return {}


def _rerank_rows(store, query, rows, payload=None, stage="recall",
                 transport=None, top_n=None):
    """Optional recall post-stage: rerank the candidates, never break recall.

    Off by default (spatial_rerank). Any failure -- missing config, timeout,
    bad payload, exception -- returns the original list untouched and records
    the reason in retrieval_last{stage, reranked, reason}.
    """
    data = payload if isinstance(payload, dict) else {}
    rows = list(rows or [])
    status = {"stage": str(stage), "enabled": False, "reranked": False,
              "reason": "disabled", "candidates": len(rows), "kept": len(rows),
              "session_id": str(data.get("session_id") or "")}
    if not _spatial_rerank_switch(store, data):
        _record_retrieval(store, status)
        return rows, status
    status["enabled"] = True
    if _rerank_mod is None:
        status["reason"] = "unavailable"
        _record_retrieval(store, status)
        return rows, status
    if len(rows) < 2:
        status["reason"] = "too_few"
        _record_retrieval(store, status)
        return rows, status
    config = _rerank_config(store, data)
    config["rerank_enabled"] = True
    if top_n:
        config["rerank_top_n"] = int(top_n)
    reasons = []
    try:
        reranked = _rerank_mod.rerank_documents(
            query, [str(row.get("text") or "") for row in rows], config,
            transport=transport, on_reason=reasons.append)
    except Exception:
        reranked = None
        reasons.append("error")
    if not reranked:
        status["reason"] = str(reasons[0] if reasons else "fallback")
        _record_retrieval(store, status)
        return rows, status
    seen = set()
    ordered = []
    for item in reranked:
        try:
            index = int(item.get("index", -1))
        except Exception:
            continue
        if 0 <= index < len(rows) and index not in seen:
            seen.add(index)
            row = dict(rows[index])
            row["rerank_score"] = item.get("relevance_score")
            ordered.append(row)
    for index, row in enumerate(rows):
        if index not in seen:
            ordered.append(row)
    status.update({"reranked": True, "reason": "ok", "kept": len(ordered)})
    _record_retrieval(store, status)
    return ordered, status


def _space_vector(entry, store, payload=None):
    """Write the embedding into the entry when a provider is configured."""
    if _space is None or not isinstance(entry, dict):
        return entry
    data = payload if isinstance(payload, dict) else {}
    if not _space_switch(store, data):
        return entry   # switch off: no embedding cost, no vector written
    text = str(entry.get("text") or "").strip()
    if not text:
        return entry
    try:
        from biocore_memory.recall.embedding import embed as _embed
        from biocore_memory.recall.embedding import load_provider as _load_provider
    except Exception:
        return entry
    config = {}
    try:
        config = _load_runtime_config(store) if store else {}
    except Exception:
        config = {}
    merged = dict(config) if isinstance(config, dict) else {}
    for key in ("embedding", "embedding_mode", "embedding_base_url",
                "embedding_model", "embedding_api_key", "embedding_dim",
                "base_url", "model", "api_key"):
        if key in data:
            merged[key] = data[key]
    provider = None
    try:
        provider = _load_provider(merged)
    except Exception:
        provider = None
    if provider is None:
        return entry
    try:
        vector = _embed(text, provider, path=_embed_cache_path(store))
    except Exception:
        vector = None
    if not vector:
        return entry
    out = dict(entry)
    out["vector"] = [round(float(value), 6) for value in vector]
    out["embedding_model"] = str(getattr(provider, "model", "") or "")[:64]
    out["embedding_provider"] = str(getattr(provider, "mode", "") or "")[:64]
    return out


# ------------------------------------------------------- space bench (task-244)
BENCH_LABELS = {"A": "旧 recall", "B": "旧 recall + rerank",
                "C": "空间邻居", "D": "空间邻居 + rerank"}


def _bench_rank(ranked_ids, relevant, limit=5):
    """rank of the first relevant id in the list (1-based, 0 = not found)."""
    wanted = set(str(item) for item in (relevant or []))
    for index, entry_id in enumerate(list(ranked_ids or [])[:limit]):
        if str(entry_id) in wanted:
            return index + 1
    return 0


def bench_metrics(ranked_ids, relevant, limit=5):
    """Overlap@k and MRR for one query. No cross-combo number is invented."""
    wanted = set(str(item) for item in (relevant or []))
    top = [str(item) for item in list(ranked_ids or [])[:limit]]
    if not wanted:
        return {"overlap": None, "mrr": None, "found": 0}
    rank = _bench_rank(top, wanted, limit)
    return {"overlap": round(len(wanted & set(top)) / len(wanted), 6),
            "mrr": round(1.0 / rank, 6) if rank else 0.0,
            "found": 1 if rank else 0}


def _bench_old_recall(entries, query, depth):
    """The old recall exactly as tool_call('recall') ranks it (no rerank)."""
    rows = []
    for entry in entries:
        score = _score(query, entry.get("text"))
        if score <= 0:
            continue
        rows.append({"id": str(entry.get("id") or ""),
                     "text": str(entry.get("text") or ""),
                     "ts": _num(entry.get("ts"), 0.0), "score": score})
    rows.sort(key=lambda row: (-row["score"], -row["ts"]))
    return rows[:depth]


def _bench_space_recall(entries, query, depth, now=None):
    """The spatial neighbour order: lexicographic over the five axes."""
    probed = _space.probe(entries, query=query, limit=depth, now=now) \
        if _space is not None else {}
    return [{"id": str(row.get("id") or ""),
             "text": str(row.get("text") or ""),
             "distance": row.get("distance") or {}}
            for row in (probed.get("results") or [])]


def _bench_rerank(store, payload, query, rows, transport=None, top_n=None):
    """One rerank pass over a candidate list; failure returns it untouched."""
    if _rerank_mod is None or len(rows) < 2:
        return rows, "unavailable" if _rerank_mod is None else "too_few"
    config = _rerank_config(store, payload)
    config["rerank_enabled"] = True
    if top_n:
        config["rerank_top_n"] = int(top_n)
    reasons = []
    try:
        reranked = _rerank_mod.rerank_documents(
            query, [str(row.get("text") or "") for row in rows], config,
            transport=transport, on_reason=reasons.append)
    except Exception:
        reranked = None
        reasons.append("error")
    if not reranked:
        return rows, str(reasons[0] if reasons else "fallback")
    seen = set()
    ordered = []
    for item in reranked:
        try:
            index = int(item.get("index", -1))
        except Exception:
            continue
        if 0 <= index < len(rows) and index not in seen:
            seen.add(index)
            ordered.append(rows[index])
    for index, row in enumerate(rows):
        if index not in seen:
            ordered.append(row)
    return ordered, "ok"


def space_bench(store, session_id="s1", queries=None, limit=5, now=None,
                transport=None, top_n=None, depth=None, mode="text"):
    """A/B/C/D comparison: old recall / +rerank / space / space+rerank.

    Pseudo queries (no explicit list):
      mode="text"  each entry's own text, ground truth = that entry (self recall)
      mode="tag"   each entry's first tag, ground truth = every entry carrying it
    """
    sid = sanitize_session_id(session_id or "default")
    stamp = _num(now, time.time())
    entries = _visible(load_memory(store, sid).get("entries"))
    depth = int(_int_param(depth if depth is not None else top_n,
                           10, 2, 50))
    limit = int(_int_param(limit, 5, 1, 20))
    items = []
    if isinstance(queries, list) and queries:
        for raw in queries[:64]:
            if isinstance(raw, dict):
                items.append({"query": str(raw.get("query") or raw.get("text")
                                           or ""),
                              "ids": [str(item) for item in
                                      (raw.get("ids") or [])]})
            else:
                items.append({"query": str(raw), "ids": []})
    elif str(mode or "text").lower() == "tag":
        groups = {}
        for entry in entries:
            for tag in (entry.get("tags") or []):
                groups.setdefault(str(tag), []).append(
                    str(entry.get("id") or ""))
        for tag in sorted(groups)[:20]:
            ids = [item for item in groups[tag] if item]
            if ids:
                items.append({"query": tag, "ids": ids})
    else:
        for entry in sorted(entries,
                            key=lambda row: -_num(row.get("ts"), 0.0))[:20]:
            text = str(entry.get("text") or "").strip()
            if text:
                items.append({"query": text,
                              "ids": [str(entry.get("id") or "")]})
    by_text = {str(entry.get("text") or ""): str(entry.get("id") or "")
               for entry in entries}
    stats = {key: {"overlap": [], "mrr": []} for key in BENCH_LABELS}
    timings = {key: [] for key in BENCH_LABELS}
    skipped = 0
    details = []
    for item in items:
        query = item["query"].strip()
        if not query:
            continue
        relevant = item["ids"] or ([by_text[query]] if query in by_text else [])
        if not relevant:
            skipped += 1
            continue
        started = time.perf_counter()
        a_rows = _bench_old_recall(entries, query, depth)
        a_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        b_rows, b_reason = _bench_rerank(store, {}, query, a_rows,
                                         transport=transport, top_n=top_n)
        b_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        c_rows = _bench_space_recall(entries, query, depth, now=stamp)
        c_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        d_rows, d_reason = _bench_rerank(store, {}, query, c_rows,
                                         transport=transport, top_n=top_n)
        d_ms = (time.perf_counter() - started) * 1000.0
        # a combo's latency is the whole path it runs, not just its last step
        timings["A"].append(a_ms)
        timings["B"].append(a_ms + b_ms)
        timings["C"].append(c_ms)
        timings["D"].append(c_ms + d_ms)
        for key, rows in (("A", a_rows), ("B", b_rows),
                          ("C", c_rows), ("D", d_rows)):
            metric = bench_metrics([row.get("id") for row in rows],
                                   relevant, limit)
            stats[key]["overlap"].append(metric["overlap"])
            stats[key]["mrr"].append(metric["mrr"])
        details.append({"query": query[:60], "relevant": relevant,
                        "A": [row.get("id") for row in a_rows[:limit]],
                        "B": [row.get("id") for row in b_rows[:limit]],
                        "C": [row.get("id") for row in c_rows[:limit]],
                        "D": [row.get("id") for row in d_rows[:limit]],
                        "rerank_B": b_reason, "rerank_D": d_reason})
    combos = {}
    for key, label in BENCH_LABELS.items():
        overlaps = [value for value in stats[key]["overlap"]
                    if value is not None]
        mrrs = [value for value in stats[key]["mrr"] if value is not None]
        combos[key] = {
            "label": label,
            "overlap@5": round(sum(overlaps) / len(overlaps), 4) if overlaps else 0.0,
            "mrr": round(sum(mrrs) / len(mrrs), 4) if mrrs else 0.0,
            "ms": round(sum(timings[key]) / len(timings[key]), 3)
            if timings[key] else 0.0,
            "queries": len(overlaps)}
    return {"ok": True, "session_id": sid, "store": str(store),
            "mode": str(mode or "text"),
            "queries": len(items) - skipped, "skipped": skipped,
            "limit": limit, "depth": depth,
            "combos": combos, "details": details[:10],
            "rerank": {"enabled": bool(_spatial_rerank_switch(store, {})),
                       "transport": "injected" if transport else "urllib",
                       "config": sorted(_rerank_config(store, {}).keys())}}


def _new_entry(text, role, tags, now):
    base = "%s|%s|%s" % (role, text, now)
    return {
        "id": hashlib.sha1(base.encode("utf-8")).hexdigest()[:12],
        "text": text,
        "role": role,
        "ts": round(float(now), 3),
        "tags": [str(tag)[:32] for tag in (tags or []) if str(tag).strip()],
        "pin": False,
        "importance": 0.5,
        "hits": 1,
        "concepts": _concepts_of(text),
    }


def tool_call(name, args, store, session_id=None):
    """remember / recall / forget against one session store."""
    name = str(name or "").strip()
    if name in ("biocore_remember", "remember"):
        name = "remember"
    elif name in ("biocore_recall", "recall"):
        name = "recall"
    elif name in ("biocore_forget", "forget"):
        name = "forget"
    else:
        return {"ok": False, "reason": "unknown_tool"}
    args = args if isinstance(args, dict) else {}
    sid = sanitize_session_id(session_id or args.get("session_id") or "default")
    store = store or _default_store()
    doc = load_memory(store, sid)
    entries = doc.setdefault("entries", [])
    if name == "remember":
        ensure_vector_space(store, sid)
        text = clean_text(args.get("text"))
        role = str(args.get("role") or "user").strip().lower()
        if not text:
            return {"ok": False, "reason": "text_required"}
        if role not in ("user", "assistant"):
            role = "user"
        now = _num(args.get("ts"), time.time())
        for existing in entries:
            if (str(existing.get("text") or "") == text
                    and str(existing.get("role") or "user") == role):
                existing["hits"] = int(existing.get("hits", 1) or 1) + 1
                # same rule as the engine merge: keep the coordinates written
                # last and record the id the duplicate write would have had
                if _space is not None and isinstance(existing.get("space"), dict):
                    folded = hashlib.sha1(
                        ("%s|%s|%s" % (role, text, now)).encode("utf-8")
                    ).hexdigest()[:12]
                    merged = _space.merge_space(
                        existing, {"id": folded, "ts": now}, removed_id=folded)
                    if isinstance(merged, dict):
                        existing["space"] = merged
                save_memory(store, sid, doc)
                # a deduped write adds no row, but the caller still needs the
                # position of the row it hit (the bench maps turns by position)
                return {"ok": True, "entry": _compact(existing), "deduped": True,
                        "position": _entry_position(doc.get("entries"))}
        entry = _new_entry(text, role, args.get("tags"), now)
        # explicit fact annotation only: the caller names the attribute, the
        # core never guesses one from the text (version resolution needs it).
        for key in ("subject", "attribute", "fact_value", "attribute_value"):
            value = args.get(key)
            if value not in (None, ""):
                entry[key] = str(value)[:64]
        # who the turn was about: the host names them, the core never guesses
        participants = args.get("participants")
        if isinstance(participants, str):
            participants = [participants]
        if isinstance(participants, list):
            people = [str(item)[:32] for item in participants
                      if str(item or "").strip()][:8]
            if people:
                entry["participants"] = people
        social_scope = args.get("social_scope")
        if social_scope not in (None, ""):
            entry["social_scope"] = str(social_scope)[:32]
        extra_meta = args.get("metadata")
        if isinstance(extra_meta, dict) and extra_meta:
            entry["metadata"] = {str(k): v for k, v in extra_meta.items()}
        # the turn's own affect when the caller has it; absent = old structure
        affect = _affect_pair_from(args.get("affect"))
        if affect:
            entry["affect"] = dict(affect)

        if _segment is not None:
            try:   # event segmentation runs before the coordinates are built
                _segment.assign(entry, entries, now=now)
            except Exception:
                pass
        entry = _space_vector(entry, store, args)
        entry = _attach_space(entry, store, sid, args, now=now)
        entry = _attach_displacement(entry, entries, now=now)
        # near_dup_time: mark the older of two near-duplicate memories (the
        # newer value wins). Identical text never reaches this branch.
        if _near_dup is not None:
            try:
                _near_dup.apply(entries, entry, flags=_near_dup_flags(store),
                                env=os.environ, now=now,
                                data_dir=_store_data_dir(store))
            except Exception:
                pass
        entries.append(entry)
        if _versioning is not None:
            try:   # same-key resolution: the older value becomes history
                _versioning.apply(entry, entries, now=now)
            except Exception:
                pass
        if len(entries) > MAX_ENTRIES:
            doc["entries"] = _capacity_guard(store, sid, entries)
        save_memory(store, sid, doc)
        # the position the event layer will give this row, computed from the list
        # we already hold: avoids a full memory read per capture
        return {"ok": True, "entry": _compact(entry), "deduped": False,
                "position": _entry_position(doc.get("entries"))}
    if name == "recall":
        query = str(args.get("query") or "").strip()
        if not query:
            return {"ok": False, "reason": "query_required"}
        limit = _int_param(args.get("limit"), 3, 1, 10)
        pool = _visible(entries)
        if _versioning is not None:
            try:   # superseded values are hidden unless asked for history
                pool = _versioning.visible(
                    pool,
                    include_superseded=bool(args.get("include_superseded")))
            except Exception:
                pass
        # spatial_select (default OFF) / mode="spatial": rank the whole visible
        # pool by the weighted five-axis distance first and hand only the
        # nearest candidates to the scorer below. Off: pool is untouched.
        select_report = None
        if (_space is not None
                and (str(args.get("mode") or "").strip().lower() == "spatial"
                     or _select_switch(store, args))):
            try:
                switches = _effective_switches(store, None)
            except Exception:
                switches = {}
            flags = switches if isinstance(switches, dict) else {}
            cap = _space.depth(flags, os.environ)
            learned = None
            if _learning is not None:
                learned = _learning.active_weights(
                    _store_data_dir(store), flags, os.environ)
            picked = _space.select(pool, query,
                                   query_ts=_num(args.get("ts"), time.time()),
                                   limit=cap, flags=flags, env=os.environ,
                                   base_weights=learned)
            ids = [str(entry_id) for entry_id in (picked.get("ids") or [])]
            wanted = set(ids)
            kept = [entry for entry in pool
                    if str(entry.get("id") or "") in wanted]
            if kept:
                order = {entry_id: index for index, entry_id in enumerate(ids)}
                kept.sort(key=lambda entry: order.get(str(entry.get("id") or ""), 0))
                pool = kept
                select_report = {"enabled": True,
                                 "pool": int(picked.get("pool") or 0),
                                 "depth": cap, "selected": len(kept),
                                 "mode": str(picked.get("mode") or "")}
            else:
                select_report = {"enabled": True, "pool": 0, "depth": cap,
                                 "selected": 0, "mode": "", "reason": "empty"}
        rows = []
        for entry in pool:
            score = _score(query, entry.get("text"))
            if score <= 0:
                continue
            row = _compact(entry)
            row["score"] = score
            if _versioning is not None:
                try:
                    status = _versioning.status_of(entry)
                    if status != _versioning.ACTIVE:
                        row["status"] = status
                except Exception:
                    pass
            rows.append(row)
        rows.sort(key=lambda row: (-row["score"], -_num(row.get("ts"), 0.0)))
        if _priority is not None and priority_enabled(args) and rows:
            # task-230: a surprising field lifts the memories that are far from
            # the current expectation; everything else keeps its score.
            try:
                values, _rel = _priority_values(store, sid)
                surprise = _priority.field_surprise(values)["value"]
                if surprise >= _priority.SURPRISE_FLOOR:
                    pool = {str(entry.get("id")): entry
                            for entry in _visible(entries)}
                    for row in rows:
                        weight = _priority.recall_weight(
                            pool.get(str(row.get("id"))), values)
                        if weight != 1.0:
                            row["score"] = round(row["score"] * weight, 6)
                            row["surprise_weight"] = weight
                    rows.sort(key=lambda row: (-row["score"],
                                               -_num(row.get("ts"), 0.0)))
            except Exception:
                pass    # priority is optional; recall keeps the old order
        rerank_config = args.get("rerank_config")
        if (_rerank_mod is not None and isinstance(rerank_config, dict)
                and rerank_config.get("rerank_enabled")):
            try:
                reranked = _rerank_mod.rerank_documents(
                    query, [row.get("text", "") for row in rows], rerank_config)
                if reranked:
                    seen = set()
                    ordered = []
                    for item in reranked:
                        index = int(item.get("index", -1))
                        if 0 <= index < len(rows) and index not in seen:
                            seen.add(index)
                            ordered.append(rows[index])
                    for index, row in enumerate(rows):
                        if index not in seen:
                            ordered.append(row)
                    rows = ordered
            except Exception:
                pass  # rerank is optional; recall keeps the local order
        if not (isinstance(rerank_config, dict)
                and rerank_config.get("rerank_enabled")):
            # spatial_rerank (default off): the core-owned post-stage
            rows, retrieval = _rerank_rows(store, query, rows, args,
                                           stage="recall")
        else:
            retrieval = {"stage": "recall", "enabled": True, "reranked": True,
                         "reason": "caller_config", "candidates": len(rows),
                         "kept": len(rows)}
        space_refresh = None
        if (_space is not None and rows
                and _reconsolidate_switch(store, args)):
            space_refresh = _refresh_hit_space(store, sid, doc, entries,
                                               rows[:limit], args)
        final_rows = list(rows[:limit])
        if _event_expand_on(store, args):
            final_rows = final_rows + _event_extra(entries, pool, final_rows,
                                                    limit)
        result = {"ok": True, "count": len(final_rows),
                  "results": final_rows, "retrieval": retrieval}
        if select_report is not None:   # off: the payload stays as it was
            result["spatial_select"] = select_report
        if space_refresh and space_refresh.get("refreshed"):
            result["space_refresh"] = space_refresh
        return result
    target = str(args.get("id") or args.get("query") or "").strip()
    if not target:
        return {"ok": False, "reason": "id_or_query_required"}
    removed = []
    for entry in list(entries):
        if str(entry.get("id") or "") == target:
            removed.append(entry)
            entries.remove(entry)
            break
    if not removed:
        rows = tool_call("recall", {"query": target, "limit": 1}, store,
                         session_id=sid).get("results") or []
        if rows:
            target_id = str(rows[0].get("id") or "")
            for entry in list(entries):
                if str(entry.get("id") or "") == target_id:
                    removed.append(entry)
                    entries.remove(entry)
                    break
    if not removed:
        return {"ok": False, "reason": "not_found"}
    save_memory(store, sid, doc)
    return {"ok": True, "id": str(removed[0].get("id") or ""),
            "removed": True}


# ---------------------------------------------------------------- proactive
# task-205 follow-up: the proactive DECISION lives here; Node only executes it.
PROACTIVE_MIN_INTERVAL = 5
PROACTIVE_MAX_INTERVAL = 240
PROACTIVE_DEFAULT_MIN_GAP = 180
PROACTIVE_DEFAULT_PER_HOUR = 2
PROACTIVE_DEFAULT_MIN_TRUST = 0.6
PROACTIVE_DEFAULT_MAX_CHARS = 60
_COMMITMENT_CUES = ("明天", "后天", "下周", "下个月", "回头", "改天", "记得",
                    "答应", "约好", "体检", "报告", "考试", "面试", "见面",
                    "打算", "要去做")
_DUE_SOON = ("明天", "后天", "下周")


def _ms(value, fallback=0.0):
    """Normalize a timestamp to epoch milliseconds (accepts seconds or ms)."""
    number = _num(value, fallback)
    if number <= 0:
        return 0.0
    return number * 1000.0 if number < 1e12 else number


def _switch_value(switches, *names, default=False):
    data = switches if isinstance(switches, dict) else {}
    for name in names:
        if name in data:
            return _as_bool(data.get(name), default)
    return bool(default)


def _proactive_state_path(store):
    root = _store_root(store)
    return (root / "proactive.json") if root is not None else None


def _proactive_session_state(store, session_id, state_file=None):
    """Per-session dsh_adapter state: explicit file, else <store>/../sessions/<id>.json."""
    path = None
    if state_file:
        path = Path(str(state_file))
    else:
        root = _store_root(store)
        if root is not None:
            path = root.parent / "sessions" / (sanitize_session_id(session_id) + ".json")
    if path is None or not path.exists():
        return {}
    data = _load_json(path, {})
    return data if isinstance(data, dict) else {}


def _proactive_commitments(store, session_id, limit=5):
    """Pending commitments from this session's memory texts (read-only)."""
    doc = load_memory(store, session_id)
    entries = [entry for entry in (doc.get("entries") or [])
               if isinstance(entry, dict) and not entry.get("deleted")
               and not entry.get("archived")]
    entries.sort(key=lambda entry: _num(entry.get("ts"), 0.0), reverse=True)
    loops = []
    seen = set()
    for entry in entries[:max(limit * 6, 12)]:
        text = clean_text(entry.get("text"), 120)
        if not text or not any(cue in text for cue in _COMMITMENT_CUES):
            continue
        key = text[:40]
        if key in seen:
            continue
        seen.add(key)
        due = "soon" if any(cue in text for cue in _DUE_SOON) else ""
        loops.append({"key": "p%d" % (len(loops) + 1), "title": key,
                      "status": "open", "due_hint": due})
        if len(loops) >= limit:
            break
    return loops


def _proactive_pick(loops):
    rows = [row for row in (loops or [])
            if isinstance(row, dict) and row.get("status") != "closed"]
    due = [row for row in rows
           if str(row.get("due_hint") or "") in ("soon", "tomorrow")]
    return (due or rows or [None])[0]


def _proactive_compose(loop, max_chars=PROACTIVE_DEFAULT_MAX_CHARS):
    title = clean_text((loop or {}).get("title") or (loop or {}).get("text")
                       or (loop or {}).get("key"), 30)
    text = ("你之前提过「" + title + "」，后来怎么样了？"
            if title else "在忙吗？突然想问你一句。")
    cap = _int_param(max_chars, PROACTIVE_DEFAULT_MAX_CHARS, 10, 120)
    return text if len(text) <= cap else text[:cap - 1] + "…"


def proactive_tick(session_id, last_human_ts=None, switches=None, store=None,
                   now=None, state_file=None):
    """One proactive decision tick (policy only; the caller performs delivery).

    Inputs: session_id, last_human_ts, switches, store (memory store root),
    optional now / state_file. Output:
      {ok, should_send, text, reason, gap_minutes}
    Cooldown state is booked here only when should_send is true; Node then
    only delivers the returned text (and nothing else).
    """
    sid = sanitize_session_id(session_id)
    data = switches if isinstance(switches, dict) else {}
    enabled = _switch_value(data, "proactiveEnabled", "proactive_enabled",
                            default=False)
    send = _switch_value(data, "proactiveSend", "proactive_send",
                         default=False)
    now_ms = _ms(now, time.time() * 1000.0) or time.time() * 1000.0
    last_ms = _ms(last_human_ts, 0.0)
    gap_minutes = round(max(0.0, now_ms - last_ms) / 60000.0, 1) if last_ms > 0 else 0.0
    result = {"ok": True, "should_send": False, "text": "",
              "reason": "", "gap_minutes": gap_minutes}
    if not enabled:
        result["reason"] = "disabled"
        return result
    if not send:
        result["reason"] = "send_off"
        return result
    if not str(session_id or "").strip():
        result["reason"] = "no_session"
        return result

    min_gap = _int_param(data.get("proactiveMinGapMinutes",
                                  data.get("proactive_min_gap_minutes")),
                         PROACTIVE_DEFAULT_MIN_GAP, 10, 48 * 60)
    if last_ms <= 0 or gap_minutes < min_gap:
        result["reason"] = "too_soon"
        return result

    per_hour = _int_param(data.get("proactivePerHour",
                                   data.get("proactive_per_hour")),
                          PROACTIVE_DEFAULT_PER_HOUR, 1, 6)
    min_trust = _num(data.get("proactiveMinTrust",
                              data.get("proactive_min_trust")),
                     PROACTIVE_DEFAULT_MIN_TRUST)
    max_chars = _int_param(data.get("proactiveMaxChars",
                                    data.get("proactive_max_chars")),
                           PROACTIVE_DEFAULT_MAX_CHARS, 10, 120)
    require_loop = _as_bool(data.get(
        "proactiveRequireOpenLoop",
        data.get("proactive_require_open_loop", True)), True)

    state_path = _proactive_state_path(store)
    persist = _load_json(state_path, {}) if state_path is not None else {}
    sent = []
    for item in persist.get("sent") or []:
        value = _ms(item, 0.0)
        if value > 0:
            sent.append(value)
    sent = [stamp for stamp in sent if now_ms - stamp < _HOUR * 1000.0]
    if len(sent) >= per_hour:
        result["reason"] = "hourly_cap"
        return result
    last_sent_ms = _ms(persist.get("lastSentAt"), 0.0)
    if last_sent_ms > 0 and now_ms - last_sent_ms < min_gap * 60000.0:
        result["reason"] = "cooldown"
        return result

    session_state = _proactive_session_state(store, sid, state_file=state_file)
    rel = session_state.get("relationship") if isinstance(
        session_state.get("relationship"), dict) else {}
    trust = _num(rel.get("trust"), 0.5)
    if trust < min_trust:
        result["reason"] = "not_close"
        result["trust"] = round(trust, 4)
        return result

    loops = _proactive_commitments(store, sid)
    loop = _proactive_pick(loops)
    if require_loop and loop is None:
        result["reason"] = "no_commitment"
        return result

    text = _proactive_compose(loop, max_chars)
    result.update({"should_send": True, "text": text, "reason": "ok",
                   "trust": round(trust, 4),
                   "loop": (loop or {}).get("title") or "",
                   "interval_minutes": _int_param(
                       data.get("proactiveIntervalMinutes",
                                data.get("proactive_interval_minutes")),
                       30, PROACTIVE_MIN_INTERVAL, PROACTIVE_MAX_INTERVAL)})
    if state_path is not None:
        _atomic_write(state_path, {"lastSentAt": now_ms,
                                   "sent": (sent + [now_ms])[-24:],
                                   "lastText": text[:80], "ts": now_ms})
    return result


# ---------------------------------------------------------------- self layer
def _module_flags(payload, name):
    """Per-module switch from payload.modules[name] (bool or {enabled,...})."""
    data = payload if isinstance(payload, dict) else {}
    modules = data.get("modules") if isinstance(data.get("modules"), dict) else {}
    entry = modules.get(name, True)
    if isinstance(entry, dict):
        flags = dict(entry)
        flags["enabled"] = _as_bool(entry.get("enabled", True), True)
        return flags
    return {"enabled": _as_bool(entry, True)}


def self_layer_hints(payload, switches=None):
    """Run the self-layer modules (missing module/data is skipped, never raises)."""
    data = payload if isinstance(payload, dict) else {}
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    relationship = (data.get("relationship")
                    if isinstance(data.get("relationship"), dict) else {})
    hooks = []
    if _self_intent is not None:
        flags = _module_flags(data, "self_intent")
        if flags["enabled"]:
            try:
                result = _self_intent.evaluate(
                    snapshot=state, relationship=relationship,
                    needs=data.get("needs"),
                    other_estimate=data.get("other_estimate"),
                    expected=data.get("expected"), flags=flags,
                    silence_seconds=_num(data.get("silence_seconds"), 0.0))
                hooks.append(("self_intent", _self_intent.directives(result)))
            except Exception:
                pass
    if _value_order is not None and isinstance(data.get("options"), list) and data.get("options"):
        flags = _module_flags(data, "value_order")
        if flags["enabled"]:
            try:
                context = data.get("value_context")
                context = context if isinstance(context, dict) else {}
                result = _value_order.rank(data.get("options"),
                                           weights=data.get("value_weights"),
                                           context=context, flags=flags)
                hooks.append(("value_order", _value_order.directives(result)))
            except Exception:
                pass
    if _boundary is not None:
        flags = _module_flags(data, "boundary")
        if flags["enabled"]:
            try:
                result = _boundary.judge(text=data.get("user_text"),
                                         relationship=relationship, flags=flags)
                if result.get("crossed"):
                    hooks.append(("boundary", {
                        "tone": "先守住边界",
                        "length_scale": 0.85,
                        "allow_correction": False,
                        "note": "底线：" + str(result.get("kind") or ""),
                        "sources": ["boundary"],
                    }))
            except Exception:
                pass
    if _secrecy is not None and isinstance(data.get("secrecy"), dict):
        flags = _module_flags(data, "secrecy")
        if flags["enabled"]:
            try:
                raw = data.get("secrecy") or {}
                decision = _secrecy.decide(
                    raw.get("sensitivity"), raw.get("relation"),
                    raw.get("setting_safety"))
                action = str(decision.get("action") or "")
                if action in ("withhold", "reframe"):
                    hooks.append(("secrecy", {
                        "tone": "有些话先不说",
                        "length_scale": 0.9,
                        "note": "秘密：" + action,
                        "sources": ["secrecy"],
                    }))
            except Exception:
                pass
    if _narrative is not None and isinstance(data.get("events"), list):
        flags = _module_flags(data, "narrative")
        if flags["enabled"]:
            try:
                result = _narrative.summarize(data.get("events"), flags=flags)
                hooks.append(("narrative", _narrative.directives(result)))
            except Exception:
                pass
    if _dissonance is not None and (data.get("stances") or data.get("behavior")):
        flags = _module_flags(data, "dissonance")
        if flags["enabled"]:
            try:
                result = _dissonance.strength(stances=data.get("stances"),
                                              behavior=data.get("behavior"),
                                              flags=flags)
                hooks.append(("dissonance", _dissonance.directives(result)))
            except Exception:
                pass
    if _attributor is not None and (data.get("dims") or data.get("event")):
        flags = _module_flags(data, "attributor")
        if flags["enabled"]:
            try:
                result = _attributor.attribute(dims=data.get("dims"),
                                               event=data.get("event"),
                                               relationship=relationship,
                                               flags=flags)
                hooks.append(("attributor", _attributor.directives(result)))
            except Exception:
                pass
    return hooks


def self_layer_constraints(payload, switches=None):
    """Six-key canonical constraints from the self layer (defaults all neutral)."""
    hooks = self_layer_hints(payload, switches=switches)
    if _x_directives is not None and hooks:
        return _x_directives.merge_named(hooks)
    return {"length_scale": 1.0, "initiative": 0.5, "tone": "",
            "allow_correction": False, "note": "", "sources": []}


# ---------------------------------------------------------------- interoception
def _intero_source(state):
    """Flatten core + relationship + body fields into one intero input dict."""
    state = state if isinstance(state, dict) else {}
    source = {}
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    source.update(core)
    relationship = state.get("relationship") if isinstance(state.get("relationship"), dict) else {}
    if relationship:
        for key in ("trust", "closeness", "conflict"):
            if key in relationship and key not in source:
                source[key] = relationship[key]
    nested = source.get("relationship_context")
    if isinstance(nested, dict):
        rel = nested.get("state") if isinstance(nested.get("state"), dict) else nested
        for key in ("trust", "closeness", "conflict"):
            if key in rel:
                source[key] = rel[key]
    for key in ("v", "a", "arousal", "stress", "energy", "social",
                "social_pain", "self_esteem", "trust", "closeness",
                "conflict", "sleep_debt", "allostatic_load", "sadness",
                "loneliness", "noise", "labels"):
        if key in state and key not in source:
            source[key] = state[key]
    if "conflict" not in source and "conflict_ema" in source:
        source["conflict"] = source["conflict_ema"]
    return source


def compute_intero(state, dt_hours=1.0, now=None):
    """Derive tension/warmth/heaviness/clarity from the current body state.

    Same pure intero_core formulas as the AstrBot bio_tick path: previous
    intero present -> intero_core.update(prev, source, dt); otherwise target.
    """
    state = state if isinstance(state, dict) else {}
    source = _intero_source(state)
    if _intero_core is None:  # stripped checkout fallback
        return {"tension": 0.3, "warmth": 0.6,
                "heaviness": 0.3, "clarity": 0.7}
    prev = None
    core = state.get("core") if isinstance(state.get("core"), dict) else {}
    if isinstance(core.get("intero"), dict):
        prev = core["intero"]
    elif isinstance(state.get("intero"), dict):
        prev = state["intero"]
    if isinstance(prev, dict) and any(key in prev for key in ("tension", "warmth",
                                                              "heaviness", "clarity")):
        return _intero_core.update(prev, source, dt_hours=dt_hours, now=now)
    return _intero_core.target(source)


def apply_intero_to_state(state, payload_state=None):
    """Compute intero from session+payload state, write state.intero/core.intero."""
    state = dict(state) if isinstance(state, dict) else {}
    merged = dict(state)
    if isinstance(payload_state, dict):
        if isinstance(payload_state.get("core"), dict):
            core = dict(merged.get("core")) if isinstance(merged.get("core"), dict) else {}
            core.update(payload_state["core"])
            merged["core"] = core
        for key, value in payload_state.items():
            if key == "core":
                continue
            if key not in merged:
                merged[key] = value
    intero = compute_intero(merged)
    merged["intero"] = intero
    core = dict(merged.get("core")) if isinstance(merged.get("core"), dict) else {}
    core["intero"] = intero
    merged["core"] = core
    return merged


# ---------------------------------------------------------------- shared relationship
RELATIONSHIP_FILE = "relationship.json"
RELATIONSHIP_BASE_FILE = "relationship_base.json"
RELATIONSHIP_FIELDS = ("trust", "closeness", "conflict")
# [engineering] .02/turn is a hand-set step, not a fitted rate (PAPER-MAP.md).
RELATIONSHIP_DELTA_LIMITS = {"trust": 0.02, "closeness": 0.02, "conflict": 0.02}
ATTACHMENT_STYLES = ("secure", "anxious", "avoidant", "disorganized", "mixed")
LOCK_TIMEOUT_S = 3.0
LOCK_STALE_S = 10.0
DEFAULT_RELATIONSHIP = {
    "trust": 0.5,
    "closeness": 0.5,
    "conflict": 0.0,
    "attachment_style": "secure",
    "bids": {"made": 0, "answered": 0},
    "days_known": 0,
}


def relationship_path(store):
    root = _store_root(store)
    return (root / RELATIONSHIP_FILE) if root is not None else None


def state_path(store, session_id):
    directory = session_dir(store, session_id)
    return (directory / "state.json") if directory is not None else None


def _validated_relationship(raw):
    data = raw if isinstance(raw, dict) else {}
    out = {key: value for key, value in DEFAULT_RELATIONSHIP.items()}
    for key in RELATIONSHIP_FIELDS:
        out[key] = round(_clamp(_num(data.get(key), out[key]), 0.0, 1.0), 4)
    style = str(data.get("attachment_style") or out["attachment_style"]).strip().lower()
    out["attachment_style"] = style if style in ATTACHMENT_STYLES else out["attachment_style"]
    bids = data.get("bids") if isinstance(data.get("bids"), dict) else {}
    out["bids"] = {key: max(0, int(_num(bids.get(key), 0))) for key in ("made", "answered")}
    out["days_known"] = max(0, int(_num(data.get("days_known"), 0)))
    return out


def relationship_read(store):
    """Read <store>/relationship.json; missing/bad file -> defaults (never creates)."""
    path = relationship_path(store)
    if path is None:
        return {"relationship": dict(DEFAULT_RELATIONSHIP), "version": 0,
                "updated_ts": 0.0, "path": ""}
    raw = _load_json(path, {})
    rel = raw.get("relationship") if isinstance(raw.get("relationship"), dict) else raw
    return {
        "relationship": _validated_relationship(rel),
        "version": max(0, int(_num(raw.get("version"), 0))),
        "updated_ts": _num(raw.get("updated_ts"), 0.0),
        "path": str(path),
    }


def _acquire_lock(path):
    lock = Path(str(path) + ".lock")
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    deadline = time.time() + LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, b"1")
            finally:
                os.close(fd)
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            except Exception:
                pass
            if time.time() >= deadline:
                return None  # last-write-wins fallback, still versioned
            time.sleep(0.005)
        except OSError:
            # Transient Windows sharing/lock races: retry until the deadline.
            if time.time() >= deadline:
                return None
            time.sleep(0.005)


def _release_lock(lock):
    if lock is None:
        return
    try:
        lock.unlink()
    except Exception:
        pass


def relationship_update(store, deltas=None, now=None, attachment_style=None,
                        bids=None, days_known=None):
    """Versioned, locked update of shared relationship values; deltas are capped."""
    root = _store_root(store)
    if root is None:
        return {"ok": False, "reason": "no_store",
                "relationship": dict(DEFAULT_RELATIONSHIP), "version": 0}
    path = relationship_path(store)
    lock = _acquire_lock(path)
    try:
        current = relationship_read(store)
        value = dict(current["relationship"])
        data = deltas if isinstance(deltas, dict) else {}
        for key in RELATIONSHIP_FIELDS:
            if key not in data:
                continue
            cap = RELATIONSHIP_DELTA_LIMITS[key]
            delta = _clamp(_num(data.get(key), 0.0), -cap, cap)
            value[key] = round(_clamp(value[key] + delta, 0.0, 1.0), 4)
        if isinstance(attachment_style, str):
            style = attachment_style.strip().lower()
            if style in ATTACHMENT_STYLES:
                value["attachment_style"] = style
        if isinstance(bids, dict):
            for key in ("made", "answered"):
                if key in bids:
                    step = int(_num(bids.get(key), 0))
                    step = max(-3, min(3, step))
                    value["bids"][key] = max(0, value["bids"][key] + step)
        if days_known is not None:
            value["days_known"] = max(value["days_known"],
                                      max(0, int(_num(days_known, 0))))
        stamp = _num(now, time.time())
        doc = {"schema_version": 1, "version": current["version"] + 1,
               "updated_ts": round(stamp, 3),
               "relationship": _validated_relationship(value)}
        try:
            _atomic_write(path, doc)
        except Exception:
            return {"ok": False, "reason": "write_failed",
                    "relationship": current["relationship"],
                    "version": current["version"]}
        return {"ok": True, "relationship": doc["relationship"],
                "version": doc["version"], "path": str(path)}
    finally:
        _release_lock(lock)


def _load_session_state(store, session_id):
    path = state_path(store, session_id)
    data = _load_json(path, {})
    return data if isinstance(data, dict) else {}


def _save_session_state(store, session_id, state):
    path = state_path(store, session_id)
    if path is None:
        return False
    try:
        _atomic_write(path, state)
        return True
    except Exception:
        return False


def _shared_relationship_enabled(payload):
    data = payload if isinstance(payload, dict) else {}
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    raw = data.get("relationship_shared")
    if raw is None:
        raw = switches.get("relationship_shared")
    return _as_bool(raw, True)


def _relationship_store(payload):
    data = payload if isinstance(payload, dict) else {}
    raw = data.get("relationship_store") or data.get("store")
    return raw or None


def merge_shared_relationship_into_state(session_id, payload):
    """turn_start: shared relationship wins for the six fields of this session."""
    store = _relationship_store(payload)
    if store is None or not _shared_relationship_enabled(payload):
        return None
    sid = sanitize_session_id(session_id)
    shared = relationship_read(store)["relationship"]
    state = _load_session_state(store, sid)
    session_rel = state.get("relationship")
    merged = dict(session_rel) if isinstance(session_rel, dict) else {}
    merged.update(shared)
    state["relationship"] = merged
    state.setdefault("session_id", sid)
    _save_session_state(store, sid, state)
    base_path = session_dir(store, sid) / RELATIONSHIP_BASE_FILE
    try:
        _atomic_write(base_path, {"relationship": shared,
                                  "base_ts": round(time.time(), 3)})
    except Exception:
        pass
    return shared


def merge_state_relationship_into_shared(session_id, payload):
    """turn_end: bounded session changes are folded back into shared relationship."""
    store = _relationship_store(payload)
    if store is None or not _shared_relationship_enabled(payload):
        return None
    sid = sanitize_session_id(session_id)
    shared_doc = relationship_read(store)
    shared = shared_doc["relationship"]
    state = _load_session_state(store, sid)
    session_rel = state.get("relationship")
    session_rel = session_rel if isinstance(session_rel, dict) else {}
    base_path = session_dir(store, sid) / RELATIONSHIP_BASE_FILE
    base_doc = _load_json(base_path, {})
    base = base_doc.get("relationship") if isinstance(base_doc.get("relationship"), dict) else shared
    deltas = {}
    for key in RELATIONSHIP_FIELDS:
        try:
            session_value = float(session_rel.get(key, base.get(key, shared[key])))
            base_value = float(base.get(key, shared[key]))
        except Exception:
            continue
        deltas[key] = round(session_value - base_value, 4)
    # Conservative: conflict rising halves the trust drop allowed this turn.
    if deltas.get("conflict", 0.0) > 0.0 and deltas.get("trust", 0.0) < 0.0:
        deltas["trust"] = max(deltas["trust"], -0.01)
    result = relationship_update(
        store, deltas=deltas, now=time.time(),
        attachment_style=session_rel.get("attachment_style"),
        bids=session_rel.get("bids"),
        days_known=session_rel.get("days_known"))
    updated = result.get("relationship") or shared
    merged = dict(session_rel)
    merged.update(updated)
    state["relationship"] = merged
    _save_session_state(store, sid, state)
    try:
        if base_path.exists():
            base_path.unlink()
    except Exception:
        pass
    return updated


# ---------------------------------------------------------------- field + arbiter (task-228)
# The six coupled fields live in biocore_runtime/field.py: read once at
# turn_start, written once at turn_end. Learners only propose deltas;
# arbiter.py resolves them (weighted median on conflict, per-apply cap, range
# clip, txid idempotency). Switch "field_arbiter" defaults ON -- with it off
# this whole section is inert and the host keeps its old direct writes.
FIELD_LEARNERS = ("mood_recall", "affect_encoding", "memory_feedback",
                  "preference_drift", "consolidation", "state_sync")


def field_enabled(payload=None):
    """Explicit payload key > flags.json > BIOCORE_FIELD_ARBITER > default ON."""
    if _field_mod is None:
        return False
    data = payload if isinstance(payload, dict) else {}
    return _field_mod.enabled(flags=data, env=os.environ,
                              store=_relationship_store(data))


def _field_store(payload):
    data = payload if isinstance(payload, dict) else {}
    return data.get("field_store") or _relationship_store(data)


def _field_proposals(payload, field_value, state=None):
    """Every learner delta for this turn, in one list.

    * learner_deltas: {"memory_feedback": {"v": 0.03}, ...} or a list of
      {"learner", "field", "delta", "weight"} -- the contract added by task-228.
    * state (payload) and the persisted session state: whatever the host changed
      on its own becomes one "state_sync" proposal, so a write the arbiter never
      saw is still capped and counted instead of bypassing the field.

    Identical proposals do not double-count: the arbiter takes the weighted
    median, so two identical deltas collapse into one delta.
    """
    data = payload if isinstance(payload, dict) else {}
    items = []
    raw = data.get("learner_deltas")
    if isinstance(raw, dict):
        for learner, mapping in raw.items():
            if not isinstance(mapping, dict):
                continue
            for key, delta in mapping.items():
                items.append({"learner": str(learner), "field": key,
                              "delta": delta})
    elif isinstance(raw, (list, tuple)):
        items.extend(dict(item) for item in raw if isinstance(item, dict))
    # The persisted state is reconciled (the body's four values are adopted), so
    # only its relationship change is still a proposal; a payload state is new
    # input and may propose any field, always capped by the arbiter.
    for source, names in ((data.get("state"), _field_mod.FIELDS),
                          (state, _field_mod.RELATION_FIELDS)):
        if not isinstance(source, dict) or not source:
            continue
        carried = _field_mod.present(source)
        derived = _field_mod.from_state(source)
        for name in names:
            if name not in carried:
                continue
            if (name in _field_mod.RELATION_FIELDS
                    and not isinstance(source.get("relationship"), dict)):
                continue
            delta = float(derived.get(name)) - float(field_value.get(name))
            if abs(delta) > _field_mod.NOISE_EPS:
                items.append({"learner": "state_sync", "field": name,
                              "delta": round(delta, 6)})
    return items


def _field_current(session_id, payload, store, state=None):
    """Persisted field (reconciled with the state) -> (Field, doc, reconciled)."""
    sid = sanitize_session_id(session_id)
    doc = _field_mod.load(store, sid)
    if state is None:
        state = _load_session_state(store, sid)
    relationship = relationship_read(store)["relationship"]
    derived = _field_mod.from_state(state, relationship)
    stored = _field_mod.from_doc(doc) if doc.get("values") else None
    resolved, reconciled = _field_mod.reconcile(stored, derived)
    resolved.session_id = sid
    resolved.version = max(int(doc.get("version") or 0),
                           int(getattr(resolved, "version", 0) or 0))
    return resolved, doc, bool(reconciled)


def field_state_view(session_id, payload=None):
    """Read-only projection for /state: {enabled, field, arbiter, version}."""
    data = payload if isinstance(payload, dict) else {}
    empty = {"enabled": False, "field": None, "arbiter": None, "version": 0}
    if _field_mod is None:
        return dict(empty, reason="unavailable")
    if not field_enabled(data):
        return dict(empty, reason="disabled")
    store = _field_store(data)
    if store is None:
        return dict(empty, enabled=True, reason="no_store")
    sid = sanitize_session_id(session_id)
    doc = _field_mod.load(store, sid)
    if doc.get("values"):
        value = _field_mod.from_doc(doc)
    else:  # nothing written yet: derive, never create the file on a read
        value = _field_mod.from_state(_load_session_state(store, sid),
                                      relationship_read(store)["relationship"])
    arbiter_state = doc.get("arbiter") if isinstance(doc.get("arbiter"), dict) else {}
    return {"enabled": True, "reason": "ok", "field": value.read(),
            "version": int(value.version),
            "arbiter": {"applied": int(_num(arbiter_state.get("applied"), 0)),
                        "rejected": int(_num(arbiter_state.get("rejected"), 0)),
                        "conflicts": int(_num(arbiter_state.get("conflicts"), 0)),
                        "batches": int(_num(arbiter_state.get("batches"), 0)),
                        "duplicates": int(_num(arbiter_state.get("duplicates"), 0)),
                        # every proposal of the last batch, per field
                        "strategy": str(arbiter_state.get("strategy") or ""),
                        "proposals": dict(arbiter_state.get("proposals") or {})}}


def field_turn_start(session_id, payload=None, state=None):
    """turn_start: derive + reconcile + persist the field, hand back a copy."""
    data = payload if isinstance(payload, dict) else {}
    result = {"enabled": False, "field": None, "version": 0,
              "reconciled": False, "source": "", "path": ""}
    if _field_mod is None:
        return dict(result, reason="unavailable")
    if not field_enabled(data):
        return dict(result, reason="disabled")
    store = _field_store(data)
    if store is None:
        return dict(result, enabled=True, reason="no_store")
    sid = sanitize_session_id(session_id)
    value, doc, reconciled = _field_current(session_id, data, store, state=state)
    value.ts = time.time()
    out = _field_mod.doc(value, arbiter_state=doc.get("arbiter"), now=value.ts)
    saved = _field_mod.save(store, out, sid)
    return {"enabled": True, "reason": "ok", "field": value.read(),
            "version": int(value.version), "reconciled": bool(reconciled),
            "source": str(value.source),
            "path": str(_field_mod.path(store, sid) or ""),
            "saved": bool(saved)}


def field_turn_end(session_id, payload=None):
    """turn_end: arbitrate learner deltas and write the field back once."""
    data = payload if isinstance(payload, dict) else {}
    result = {"enabled": False, "field": None, "version": 0,
              "arbiter": None, "applied": {}, "rejected": [], "conflicts": []}
    if _field_mod is None or _arbiter_mod is None:
        return dict(result, reason="unavailable")
    if not field_enabled(data):
        return dict(result, reason="disabled")
    store = _field_store(data)
    if store is None:
        return dict(result, enabled=True, reason="no_store")
    sid = sanitize_session_id(session_id)
    state = _load_session_state(store, sid)
    # turn_end adopts the body's own four values (core_state owns them, so its
    # drift is not a proposal) while trust/closeness stay capped proposals.
    doc = _field_mod.load(store, sid)
    derived = _field_mod.from_state(state)
    if doc.get("values"):
        value = _field_mod.reconcile(_field_mod.from_doc(doc), derived,
                                     adopt=_field_mod.AFFECT_FIELDS)[0]
    else:
        value = derived
    value.session_id = sid
    value.version = max(int(doc.get("version") or 0), int(value.version or 0))
    value.ts = time.time()
    arbiter = _arbiter_mod.Arbiter(state=doc.get("arbiter"))
    proposals = _field_proposals(data, value, state=state)
    txid = str(data.get("txid") or data.get("turn_id") or "").strip()
    applied_out = arbiter.apply(value, proposals, txid=txid, enabled=True,
                                now=value.ts)
    new_state = _field_mod.to_state(state, value)
    _save_session_state(store, sid, new_state)
    _field_mod.save(store, _field_mod.doc(value, arbiter_state=arbiter.snapshot(),
                                          now=value.ts), sid)
    return {"enabled": True, "reason": "ok", "field": value.read(),
            "version": int(value.version),
            "arbiter": arbiter.stats(),
            "applied": applied_out.get("applied") or {},
            "rejected": applied_out.get("rejected") or [],
            "conflicts": applied_out.get("conflicts") or [],
            "resolved": applied_out.get("resolved") or {},
            "duplicate": bool(applied_out.get("duplicate")),
            "proposal_count": len(proposals),
            "proposals": applied_out.get("proposals") or {},
            "strategy": str(applied_out.get("strategy") or "")}


# ------------------------------------------------------- dimensions (task-243)
def dimensions_enabled(payload=None):
    """dimensions_v2: payload flag > flags.json / config > env > default ON."""
    if _dimensions is None:
        return False
    data = payload if isinstance(payload, dict) else {}
    if isinstance(data.get("dimensions_v2"), bool):
        return bool(data["dimensions_v2"])
    try:
        switches = _effective_switches(data.get("store") or _default_store(),
                                       data.get("switches"))
    except Exception:
        switches = {}
    if isinstance(switches.get("dimensions_v2"), bool):
        return bool(switches["dimensions_v2"])
    return _dimensions.enabled(flags=data, env=os.environ)


def _dimensions_on(payload=None, store=None):
    data = payload if isinstance(payload, dict) else {}
    if store is not None and data.get("store") is None:
        data = dict(data, store=str(store))
    return dimensions_enabled(data)


def dimensions_view(session_id, payload=None, state=None, store=None):
    """Read-only /state.dimensions: {axis: {explicit, implicit, ambivalence}},
    plus the four-channel projection. Never writes a file."""
    data = payload if isinstance(payload, dict) else {}
    empty = {"enabled": False, "schema": 0, "ts": 0.0, "hops": 0,
             "axes": {}, "projection": {}, "actions": []}
    if _dimensions is None:
        return dict(empty, reason="unavailable")
    if not _dimensions_on(data, store=store):
        return dict(empty, reason="disabled")
    root = store if store is not None else (data.get("store") or _default_store())
    sid = sanitize_session_id(session_id)
    if state is None:
        state = _load_session_state(root, sid)
    show_conflict = _dimensions.conflict_enabled(data, env=os.environ)
    row = _dimensions.project(_dimensions.load(state), conflict=show_conflict)
    return {"enabled": True, "reason": "ok",
            "conflict_axis": bool(show_conflict),
            "schema": int(_num(row.get("schema"), _dimensions.SCHEMA)),
            "ts": _num(row.get("ts"), 0.0),
            "hops": int(_num(row.get("hops"), 0)),
            "axes": row.get("dims") or {},
            "projection": row.get("projection") or {},
            "actions": row.get("behavior") or []}


def _dimension_writes(payload, applied_fields=None):
    """Every write for this turn, one group per source, channel decided here.

    explicit  what the turn said        payload.dimension_deltas.explicit,
                                       arbiter-approved field deltas
    implicit  what the body did        payload.dimension_deltas.implicit,
                                       host state sync (delta/deltas keys)
    Groups are never merged: each keeps its own evidence rows.
    """
    data = payload if isinstance(payload, dict) else {}
    explicit, implicit = [], []
    raw = data.get("dimension_deltas")
    if isinstance(raw, dict):
        for key, bucket in (("explicit", explicit), ("implicit", implicit)):
            mapping = raw.get(key)
            if isinstance(mapping, dict):
                bucket.append((mapping, "payload." + key))
    if isinstance(applied_fields, dict) and applied_fields:
        explicit.append((applied_fields, "field_applied"))
    synced = _state_deltas(data)
    if synced:
        implicit.append((synced, "state_sync"))
    return explicit, implicit


def dimensions_write(session_id, payload=None, state=None, applied_fields=None,
                     store=None, now=None):
    """turn_end: absorb this turn's writes, persist them, hand back the view."""
    data = payload if isinstance(payload, dict) else {}
    result = {"enabled": False, "written": 0, "sources": [],
              "axes": {}, "projection": {}, "actions": []}
    if _dimensions is None:
        return dict(result, reason="unavailable")
    if not _dimensions_on(data, store=store):
        return dict(result, reason="disabled")
    root = store if store is not None else (data.get("store") or _default_store())
    sid = sanitize_session_id(session_id)
    state = state if isinstance(state, dict) else _load_session_state(root, sid)
    stamp = now if now is not None else time.time()
    model = _dimensions.load(state)
    explicit, implicit = _dimension_writes(data, applied_fields)
    written = 0
    sources = []
    for channel, groups in (("explicit", explicit), ("implicit", implicit)):
        for mapping, source in groups:
            picked = _dimensions.pick(mapping)
            if "conflict" in picked:
                # relationship conflict only: a task disagreement never lands
                event = str(data.get("conflict_event") or source)
                if not _dimensions.is_conflict_event(event):
                    picked.pop("conflict", None)
            if not picked:
                continue
            model = _dimensions.absorb(model, **{channel: picked},
                                       source=source, now=stamp)
            written += len(picked)
            sources.append({"channel": channel, "source": source,
                            "axes": sorted(picked)})
    if written:
        new_state = dict(state)
        new_state["dimensions"] = model
        _save_session_state(root, sid, new_state)
    row = _dimensions.project(
        model, conflict=_dimensions.conflict_enabled(data, env=os.environ))
    return {"enabled": True, "reason": "ok", "written": written,
            "sources": sources,
            "schema": int(row.get("schema") or _dimensions.SCHEMA),
            "ts": _num(row.get("ts"), 0.0),
            "hops": int(row.get("hops") or 0),
            "axes": row.get("dims") or {},
            "projection": row.get("projection") or {},
            "actions": row.get("behavior") or []}


# ------------------------------------------------------- expression (task-243)
def expression_enabled(payload=None):
    """expression_policy: payload flag > flags.json / config > env > default ON."""
    if _expression is None:
        return False
    data = payload if isinstance(payload, dict) else {}
    for key in ("expression_policy", "expr_policy"):
        if isinstance(data.get(key), bool):
            return bool(data[key])
    try:
        switches = _effective_switches(data.get("store") or _default_store(),
                                       data.get("switches"))
    except Exception:
        switches = {}
    if isinstance(switches.get("expression_policy"), bool):
        return bool(switches["expression_policy"])
    return _expression.enabled(flags=data, env=os.environ)


def _expression_intent(payload):
    data = payload if isinstance(payload, dict) else {}
    return str(data.get("intent") or data.get("tendency") or "")


def expression_policy_for(state=None, payload=None):
    """Read-only: {mode, hints, sources}. Never rendered, never persisted."""
    data = payload if isinstance(payload, dict) else {}
    empty = {"enabled": False, "schema": 0, "mode": "authentic", "hints": {},
             "sources": [], "reason": "unavailable"}
    if _expression is None:
        return dict(empty)
    if not expression_enabled(data):
        return dict(empty, reason="disabled")
    session_state = state if isinstance(state, dict) else {}
    model = _dimensions.load(session_state) if _dimensions is not None else None
    relationship = session_state.get("relationship")
    if not isinstance(relationship, dict):
        relationship = None
        root = data.get("store")
        if root:
            try:
                relationship = relationship_read(root)["relationship"]
            except Exception:
                relationship = None
    row = _expression.policy(model, relationship, _expression_intent(data))
    return {"enabled": True,
            "schema": int(row.get("schema") or _expression.SCHEMA),
            "mode": str(row.get("mode") or "authentic"),
            "hints": dict(row.get("hints") or {}),
            "sources": list(row.get("sources") or []),
            "reason": str(row.get("reason") or "")}


def expression_prompt_extra(state=None, payload=None):
    """One seam: batch_d.prompt_extra merged with the expression rows.

    batch_d keeps ownership of tone / length / avoid / sources; the expression
    policy only appends its own hint rows into that same list.
    """
    data = payload if isinstance(payload, dict) else {}
    policy_row = expression_policy_for(state, data)
    base = {}
    if _batch_d is not None:
        try:
            base = _batch_d.prompt_extra(state if isinstance(state, dict) else {},
                                         data)
        except Exception:
            base = {}
    if _expression is None:
        return policy_row, base
    return policy_row, _expression.merge_extra(base, policy_row)


# ---------------------------------------------------------------- persona profile
PERSONA_PROFILE_FILE = "persona_profile.json"
PERSONA_APPLY_ORDER = ("traits", "affect", "drives", "autonomy")
PERSONA_FIELDS = (
    "O", "C", "E", "A", "N", "stress_reactivity", "recovery_rate",
    "social_baseline", "energy_baseline", "curiosity_baseline",
    "safety_baseline", "da_baseline", "oa_baseline", "ht_baseline",
    "autonomy_gain", "baseline_v", "baseline_a", "learning_rate",
)
PERSONA_RANGES = {
    "O": (0.0, 1.0), "C": (0.0, 1.0), "E": (0.0, 1.0),
    "A": (0.0, 1.0), "N": (0.0, 1.0),
    "stress_reactivity": (0.0, 1.0), "recovery_rate": (0.0, 1.0),
    "social_baseline": (0.0, 1.0), "energy_baseline": (0.0, 1.0),
    "curiosity_baseline": (0.0, 1.0), "safety_baseline": (0.0, 1.0),
    "da_baseline": (0.0, 1.0), "oa_baseline": (0.0, 1.0),
    "ht_baseline": (0.0, 1.0), "autonomy_gain": (0.0, 1.5),
    "baseline_v": (-1.0, 1.0), "baseline_a": (0.0, 1.0),
    "learning_rate": (0.0, 0.5),
}


def _persona_home():
    override = str(os.environ.get("BIOCORE_HOME") or "").strip()
    return Path(override) if override else Path.home()


def persona_profile_path(payload):
    """Explicit path -> ~/.dsh/biocore shared -> store -> store parent."""
    data = payload if isinstance(payload, dict) else {}
    explicit = data.get("persona_profile") or data.get("persona_profile_path")
    if isinstance(explicit, str) and explicit.strip():
        return Path(explicit.strip())  # explicit wins even if the file is missing
    candidates = []
    try:
        candidates.append(_persona_home() / ".dsh" / "biocore"
                          / PERSONA_PROFILE_FILE)
    except Exception:
        pass
    root = _store_root(_relationship_store(payload))
    if root is not None:
        candidates.append(root / PERSONA_PROFILE_FILE)
        candidates.append(root.parent / PERSONA_PROFILE_FILE)
    data_dir = data.get("data_dir")
    if data_dir:
        candidates.append(Path(str(data_dir)) / PERSONA_PROFILE_FILE)
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return None


def load_persona_profile(payload):
    """Load + bound persona profile; missing/bad file -> None (silent skip)."""
    data = payload if isinstance(payload, dict) else {}
    inline = data.get("persona_profile")
    doc = None
    path = ""
    if isinstance(inline, dict):
        doc = inline
    else:
        candidate = persona_profile_path(data)
        if candidate is None:
            return None
        try:
            if not candidate.exists():
                return None
            doc = json.loads(candidate.read_text(encoding="utf-8"))
            path = str(candidate)
        except Exception:
            return None
    if not isinstance(doc, dict):
        return None
    raw = doc.get("profile") if isinstance(doc.get("profile"), dict) else doc
    fields = {}
    for key in PERSONA_FIELDS:
        if key not in raw:
            continue
        low, high = PERSONA_RANGES[key]
        fields[key] = round(_clamp(_num(raw.get(key), low), low, high), 4)
    if not fields:
        return None
    version = str(raw.get("version") or doc.get("persona_hash") or "")
    if not version:
        version = hashlib.sha256(
            json.dumps(fields, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
    persona_text = doc.get("persona") if isinstance(doc.get("persona"), str) else ""
    return {"fields": fields, "version": version[:64], "path": path,
            "persona_text": persona_text}


PERSONA_LINE_LIMIT = 160
THINKING_STYLE_TEXT = "思考就是我的内心想法。"
THINKING_STYLE_PREFIX = ""
THINKING_STYLE_LIMIT = 60
PERSONA_PREFIX = "人设："
_SENTENCE_END = ("。", "！", "？", "!", "?")


def _clip_persona_text(text, budget):
    text = _WS.sub(" ", str(text or "")).strip()
    if budget <= 0 or len(text) <= budget:
        return text  # 0 / negative = no truncation (full original persona)
    head = text[:budget]
    cut = 0
    for index in range(budget - 1, -1, -1):
        if head[index] in _SENTENCE_END:
            cut = index + 1
            break
    return head[:cut] if cut else head


def _numeric_persona_sentence(fields):
    fields = fields if isinstance(fields, dict) else {}
    parts = []
    energy = fields.get("E")
    agree = fields.get("A")
    neurotic = fields.get("N")
    order = fields.get("C")
    openness = fields.get("O")
    baseline_v = fields.get("baseline_v")
    if energy is not None:
        parts.append("偏外向" if energy >= 0.6 else ("偏内敛" if energy <= 0.4 else "内外平衡"))
    if agree is not None:
        parts.append("宜人" if agree >= 0.6 else ("有棱角" if agree <= 0.4 else "待人温和"))
    if neurotic is not None:
        parts.append("情绪敏感" if neurotic >= 0.6 else ("情绪稳定" if neurotic <= 0.4 else "情绪中等"))
    if baseline_v is not None:
        parts.append("情绪基线略高" if baseline_v >= 0.1 else
                     ("情绪基线偏低" if baseline_v <= -0.1 else "情绪基线平稳"))
    if order is not None and order >= 0.65:
        parts.append("做事严谨")
    if openness is not None and openness >= 0.65:
        parts.append("好奇")
    if not parts:
        return ""
    return "、".join(parts) + "；先接情绪再谈事"


def thinking_style_line(payload):
    """Universal expression rule (independent of any persona)."""
    data = payload if isinstance(payload, dict) else {}
    if not _as_bool(data.get("thinking_style"), True):
        return ""
    line = THINKING_STYLE_TEXT
    if len(line) > THINKING_STYLE_LIMIT:
        line = line[:THINKING_STYLE_LIMIT - 1] + "…"
    return line


def persona_prompt_line(payload):
    """Persona original text (<=160-char line) or a numeric fallback line."""
    data = payload if isinstance(payload, dict) else {}
    if not _as_bool(data.get("persona_prompt"), True):
        return ""
    profile = load_persona_profile(data)
    if not profile:
        return ""
    raw_budget = data.get("persona_prompt_max_chars", 0)
    try:
        budget = 0 if isinstance(raw_budget, bool) else int(raw_budget)
    except Exception:
        budget = 0
    budget = max(0, min(100000, budget))
    content = _clip_persona_text(profile.get("persona_text"), budget)
    if not content:
        content = _numeric_persona_sentence(profile.get("fields"))
    if not content:
        return ""
    return PERSONA_PREFIX + content


def apply_persona_to_state(state, profile):
    """Whitelisted persona -> session state (traits -> affect -> drives -> autonomy)."""
    if not isinstance(profile, dict) or not profile.get("fields"):
        return state if isinstance(state, dict) else {}
    state = dict(state) if isinstance(state, dict) else {}
    core = dict(state.get("core")) if isinstance(state.get("core"), dict) else {}
    fields = profile["fields"]
    applied = {}
    # 1) traits: validated but never written into memory/identity/safety policy.
    for key in ("O", "C", "E", "A", "N", "stress_reactivity"):
        if key in fields:
            applied[key] = fields[key]
    # 2) affect baseline
    if "baseline_v" in fields:
        core["v"] = round(fields["baseline_v"], 3)
        applied["baseline_v"] = fields["baseline_v"]
    if "baseline_a" in fields:
        core["a"] = round(fields["baseline_a"], 3)
        applied["baseline_a"] = fields["baseline_a"]
    # 3) drives: social/energy/curiosity/safety + recovery -> decay half-life
    for key, target in (("social_baseline", "social"),
                        ("energy_baseline", "energy"),
                        ("curiosity_baseline", "curiosity"),
                        ("safety_baseline", "safety")):
        if key in fields:
            core[target] = round(fields[key], 3)
            core[key] = round(fields[key], 3)
            applied[key] = fields[key]
    recovery = _clamp(_num(fields.get("recovery_rate"), 0.7), 0.0, 1.0)
    factor = round(1.25 - 0.50 * recovery, 3)
    core["valence_decay_minutes"] = round(120.0 * factor, 1)
    core["arousal_decay_minutes"] = round(30.0 * factor, 1)
    core["social_decay_minutes"] = round(180.0 * factor, 1)
    if "recovery_rate" in fields:
        applied["recovery_rate"] = fields["recovery_rate"]
    # 4) autonomy / learning
    for key in ("autonomy_gain", "learning_rate"):
        if key in fields:
            core[key] = round(fields[key], 4)
            applied[key] = fields[key]
    state["core"] = core
    state["persona_version"] = profile["version"]
    state["persona_profile"] = dict(applied, version=profile["version"])
    return state


def apply_persona_to_session(session_id, payload):
    """Apply persona to the session state file (or in-memory state if no store)."""
    profile = load_persona_profile(payload)
    store = _relationship_store(payload)
    session_id = sanitize_session_id(session_id)
    if profile is None and store is None:
        return None
    state = _load_session_state(store, session_id) if store is not None else {}
    if profile is not None:
        state = apply_persona_to_state(state, profile)
        if store is not None:
            _save_session_state(store, session_id, state)
    return state




# ---------------------------------------------------------------- core state
def _core_state_path(payload):
    """<dataDir>/core_state.json for any payload (store = <dataDir>/memory)."""
    if _core_state is None:
        return None
    data = payload if isinstance(payload, dict) else {}
    try:
        return _core_state.path_for(data.get("store"),
                                    data.get("data_dir") or data.get("dataDir"))
    except Exception:
        return None


def _intero_from_core(doc, prev, dt_hours, now):
    """Recompute intero from the global body, using its own intero as prev."""
    body = dict(doc) if isinstance(doc, dict) else {}
    merged = {"core": body}
    if isinstance(prev, dict) and prev:
        merged["core"] = dict(body, intero=prev)
        merged["intero"] = dict(prev)
    return compute_intero(merged, dt_hours=dt_hours or 0.0, now=now)


def _state_deltas(payload):
    """This turn's numeric deltas: direct dict, or diagnostics before/after."""
    data = payload if isinstance(payload, dict) else {}
    out = {}

    def add(key, value):
        if key not in _CORE_FIELDS:
            return
        try:
            out[key] = out.get(key, 0.0) + float(value)
        except Exception:
            pass

    for source_key in ("delta", "deltas", "state_delta"):
        raw = data.get(source_key)
        if isinstance(raw, dict):
            for key, value in raw.items():
                add(str(key), value)
        elif isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                add(str(item.get("field") or item.get("key") or ""),
                    _num(item.get("after"), 0.0) - _num(item.get("before"), 0.0))
    return {key: round(value, 4) for key, value in out.items()
            if abs(value) > 1e-9}


_CORE_FIELDS = ("v", "a", "stress", "energy", "social", "social_pain",
                "trust", "closeness", "conflict")


def _recall_count(store, session_id):
    """Recalled memory hits for this session (0 when traces are empty)."""
    try:
        total = 0
        for row in trace_read(store, session_id, TRACE_KEEP):
            memory = row.get("memory") if isinstance(row.get("memory"), dict) else {}
            ids = memory.get("recalled_ids")
            if isinstance(ids, list):
                total += len(ids)
        return total
    except Exception:
        return 0


def _proactive_sent_today(store):
    """Messages delivered by the proactive path today (0 when none)."""
    try:
        root = _store_root(store)
        if root is None:
            return 0
        data = _load_json(root / "proactive.json", {})
        sent = data.get("sent") if isinstance(data.get("sent"), list) else []
        now = time.time()
        start = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
        return sum(1 for item in sent if _num(item, 0.0) / 1000.0 >= start)
    except Exception:
        return 0


def _series_payload(store, payload=None):
    """Newest <=24 points from the global history + growth_history.jsonl."""
    data = payload if isinstance(payload, dict) else {}
    limit = _int_param(data.get("limit"), 24, 1, 288)
    rows = []
    try:
        rows = _core_state.points(_core_state_path(data), limit) if _core_state else []
    except Exception:
        rows = []
    growth = []
    try:
        root = _store_root(store)
        path = (root / "growth_history.jsonl") if root is not None else None
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict) and _num(item.get("ts"), 0.0) > 0:
                    growth.append({"ts": round(_num(item.get("ts")), 3),
                                   "trust": round(_num(item.get("trust"), 0.5), 4),
                                   "closeness": round(_num(item.get("closeness"),
                                                           0.5), 4)})
    except Exception:
        growth = []
    if growth:
        known = {round(_num(row.get("ts"), 0.0), 0) for row in rows}
        for item in growth[-limit:]:
            if round(_num(item.get("ts"), 0.0), 0) not in known:
                rows.append(item)
        rows.sort(key=lambda row: _num(row.get("ts"), 0.0))
        rows = rows[-limit:]
    series = {key: [row.get(key) for row in rows
                    if isinstance(row, dict) and row.get(key) is not None]
              for key in ("ts", "v", "tension", "warmth", "heaviness",
                          "clarity", "trust", "closeness")}
    return {"ok": True, "series": series, "points": rows,
            "source": "core_state" if _core_state else "unavailable"}


_RUNTIME_CONFIG = {}
CORE_CONFIG_FILE = "core_config.json"
CORE_DEFAULTS = {
    # contract: everything core-side is on; only external/irreversible off.
    "core_enabled": True,
    "mood_recall": True, "affect_encoding": True,
    "memory_feedback": True, "preference_drift": True,
    "governance": True, "index": True, "consolidate": True,
    "evict": True, "evict_delete": False,
    "relationship_governance": True,
    "perception_batch": True,
    "batch_b": True, "batch_c": True, "batch_d": True, "batch_e": True,
    "timescales": True,
    "self_layer": True, "motivation": True,
    "autonomy": True, "standby": False, "retrieval_plus": True,
    "safety_enabled": False, "boundary_enabled": False,
    "crisis_safety_enabled": False,
    "proactive_send": False,
    "recall_mode": "query",
    # A date prefix on each injected memory (default ON).
    "memory_date_prefix": True,
    # Recall by event segment instead of by entry (default OFF).
    "segment_recall": False,
    # Point-expand: hits first, then the neighbours of each hit (default OFF).
    "point_expand": False,
    # point_expand_rerank: expand, then rerank the pool (ON); OFF is the v11
    # order where neighbours are injected without a score.
    "point_expand_rerank": True,
    # Coverage select: pick k by five-axis spread instead of rank (default OFF).
    "spatial_cover_select": False,


    # spatial_select: full-store candidate stage in front of the scorer
    # (default OFF; the host turns it on per store, mode="spatial" per call).
    "spatial_select": False,
    # spatial_reconsolidate: a recall hit rewrites its own coordinates
    # (default OFF; recall never mutates the store unless asked).
    "spatial_reconsolidate": False,
}


def _load_runtime_config(store):
    data_dir = _store_data_dir(store)
    doc = {}
    if data_dir is not None:
        doc = _load_json(data_dir / CORE_CONFIG_FILE, {})
    if not isinstance(doc, dict) or not doc:
        doc = _RUNTIME_CONFIG
    return doc if isinstance(doc, dict) else {}


def configure(payload):
    """task-223: whole config arrives once; the core owns every decision."""
    data = payload if isinstance(payload, dict) else {}
    store = data.get("store")
    data_dir = data.get("data_dir")
    if not data_dir:
        data_dir = _store_data_dir(store) if store else None
    doc = {key: value for key, value in data.items()
           if key not in ("store", "data_dir")}
    doc["updated_at"] = round(time.time(), 3)
    if data_dir is not None:
        try:
            _atomic_write(Path(data_dir) / CORE_CONFIG_FILE, doc)
        except Exception:
            pass
    _RUNTIME_CONFIG.clear()
    _RUNTIME_CONFIG.update(doc)
    return {"ok": True, "configured": True,
            "switches": doc.get("switches") if isinstance(
                doc.get("switches"), dict) else {}}


def _effective_switches(store, overrides=None):
    merged = dict(CORE_DEFAULTS)
    data_dir = _store_data_dir(store)
    if data_dir is not None:
        flags = _load_json(data_dir / "flags.json", {})
        for key, value in flags.items():
            if isinstance(value, bool):
                merged[str(key)] = value
    cfg = _load_runtime_config(store)
    switches = cfg.get("switches") if isinstance(cfg.get("switches"), dict) else {}
    for key, value in switches.items():
        if isinstance(value, bool):
            merged[str(key)] = value
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if isinstance(value, bool):
                merged[str(key)] = value
    return merged


def _rerank_config_from(raw):
    """Accept either the adapter's rerank payload or config.json's rerank block."""
    if not isinstance(raw, dict):
        return None
    if "rerank_enabled" in raw:
        return raw
    return {"rerank_enabled": raw.get("enabled") is True,
            "rerank_base_url": str(raw.get("base_url") or ""),
            "rerank_model": str(raw.get("model") or ""),
            "rerank_api_key": str(raw.get("api_key") or ""),
            "rerank_top_n": int(raw.get("top_n") or 20),
            "rerank_timeout": 8}


def _recall_mode(store, requested=None):
    mode = str(requested or "").strip().lower()
    if mode in INJECT_MODES:
        return mode
    cfg = _load_runtime_config(store)
    mode = str(cfg.get("recall_mode") or "").strip().lower()
    return mode if mode in INJECT_MODES else "query"


MOTIVATIONS = {
    "hold": "想先听着，不急着推进",
    "approach": "想靠近一点，再问一句",
    "withdraw": "想退半步，留点空间",
    "probe": "想探一探，但还不确定",
    "repair": "想把话圆回来",
    "rest": "有点累，想安静待着",
    "share": "想说说自己这边的事",
}


def _ui_state_body(store, session_id, data):
    """task-223: the /state payload is assembled by the core, JS forwards it."""
    entries = _visible(load_memory(store, session_id).get("entries"))
    stored_state = _load_session_state(store, session_id)
    core_path = _core_state_path(data)
    core_state_ts = 0.0
    if _core_state is not None and _core_state.exists(core_path):
        doc = _core_state.load(core_path)
        core = _core_state.core_of(doc)
        intero = doc.get("intero")
        if not isinstance(intero, dict):
            intero = compute_intero({"core": core})
        core["intero"] = intero
        core_state_ts = doc.get("ts", 0.0)
        history = list(doc.get("history") or [])[-120:]
    else:
        merged_state = apply_intero_to_state(stored_state, data.get("state"))
        intero = merged_state.get("intero") or {}
        core = dict(merged_state.get("core") or {})
        core["intero"] = intero
        history = list(stored_state.get("history") or [])[-120:]
    relationship = (relationship_read(store)["relationship"]
                    if _store_root(store) is not None else {})
    recent = []
    for entry in sorted(entries, key=lambda item: _num(item.get("ts"), 0.0),
                        reverse=True)[:10]:
        text = clean_text(entry.get("text"), 500)
        if not text:
            continue
        recent.append({"ts": round(_num(entry.get("ts"), 0.0) * 1000, 0),
                       "text": text[:80],
                       "source": str(entry.get("memory_source") or "direct"),
                       "kind": str(entry.get("kind") or "")})
    memory_versions = None
    memory_conflicts = None
    if _versioning is not None:
        try:   # arXiv 2610.36308: {active, superseded, disputed} + last five
            memory_versions = _versioning.summary(entries)
            memory_conflicts = _versioning.conflicts(entries)
        except Exception:
            memory_versions, memory_conflicts = None, None
    if isinstance(memory_versions, dict) and _near_dup is not None:
        try:   # near_dup_time: what the newer-wins rule marked on this store
            memory_versions["near_dup"] = _near_dup.state_of(
                entries, _store_data_dir(store),
                _near_dup_flags(store), os.environ)
        except Exception:
            pass
    rel_metrics = {"closeness": round(_num(relationship.get("closeness"), 0.5), 2),
                   "trust": round(_num(relationship.get("trust"), 0.5), 2),
                   "conflict": round(_num(relationship.get("conflict"), 0.0), 2),
                   "bids": round(_num(relationship.get("bids"), 0.0), 2)}
    body = {"self_esteem": round(_num(core.get("self_esteem"), 0.0), 2),
            "social_pain": round(_num(core.get("social_pain"), 0.0), 2),
            "energy": round(_num(core.get("energy"), 0.5), 2),
            "social": round(_num(core.get("social"), 0.5), 2)}
    trace_rows = trace_read(store, session_id, 1)
    last_trace = trace_rows[-1] if trace_rows else {}
    last_turn = last_trace.get("intent") if isinstance(last_trace, dict) else {}
    intent = str((last_turn or {}).get("kind") or "")[:24]
    governance_summary = None
    if _governance is not None:
        try:
            governance_summary = _governance.summary(store)
        except Exception:
            governance_summary = None
    relationship_summary = None
    if _relationship_state is not None:
        try:
            relationship_summary = _relationship_state.summary(store, relationship)
        except Exception:
            relationship_summary = None
    identity_summary = None
    if _self_layer is not None:
        try:
            identity_summary = _self_layer.summary(store)
        except Exception:
            identity_summary = None
    autonomy_view = None
    if _autonomy is not None:
        try:
            switches = _effective_switches(store)
            metrics = _autonomy.metrics(store)
            autonomy_view = {
                "enabled": bool(switches.get("autonomy", True)),
                "actions_today": metrics["actions_today"],
                "sends_today": metrics["sends_today"],
                "actions_hour": metrics["actions_hour"],
                "sends_hour": metrics["sends_hour"],
                "limits": _autonomy.limits(store)}
        except Exception:
            autonomy_view = None
    standby_view = None
    try:
        from . import standby as _standby_view
    except Exception:
        _standby_view = None
    if _standby_view is not None:
        try:
            standby_view = _standby_view.summary(
                store, enabled=bool(_effective_switches(store).get("standby")))
        except Exception:
            standby_view = None
    signals_summary = None
    if _signals is not None:
        try:
            signals_summary = _signals.summary(store)
        except Exception:
            signals_summary = None
    extensions_summary = None
    if _extensions is not None:
        try:
            extensions_summary = _extensions.extension_summary(store)
        except Exception:
            extensions_summary = None
    identity = {"v": round(_num(core.get("v"), 0.0), 2),
                "intero": intero,
                "governance": governance_summary,
                "relationship_summary": relationship_summary,
                "identity": identity_summary,
                "signals": signals_summary,
                "extensions": extensions_summary,
                "standby": standby_view,
                "recall_debug": (_retrieval_plus.summary(store)
                                 if _retrieval_plus is not None else None),
                "tiers": (_lifecycle.tier_summary(store)
                          if _lifecycle is not None else None),
                "reconsolidation": (_lifecycle.reconsolidation_summary(store)
                                    if _lifecycle is not None else None),
                "repair": (_lifecycle.repair_state(store)
                           if _lifecycle is not None else None),
                "available": True,
                "session_id": sanitize_session_id(session_id),
                "memory_count": len(entries),
                "memory": {"count": len(entries)},
                "memory_recent": recent,
                "memory_versions": memory_versions,
                "segment_recall": _segment_recall_snapshot(store),
                "point_expand": _point_expand_snapshot(store),
                "cover_select": _cover_snapshot(store),
                "memory_conflicts": memory_conflicts,
                "relationship_metrics": rel_metrics,
                "body_metrics": body,
                "narrative": {"intent": intent, "length_factor": 1.0,
                              "initiative": 0.5, "metacog_band": "",
                              "allow_correction": False},
                "motivation": MOTIVATIONS.get(intent, "安静待着，等你开口"),
                "tone": {"label": ""},
                "relation": {"stage": ""},
                "autonomy": {"state": "静", **((autonomy_view or {}))},
                "history": history,
                "core_state_ts": core_state_ts,
                "recall_count": _recall_count(store, session_id),
                "governance_numbers": (governance_summary or {}),
                "proactive_sent_today": _proactive_sent_today(store),
                "core": core,
                "embedding_cache": _embedding_cache_snapshot(store),
                "space": _space_stats_snapshot(entries),
                "spatial_learning": _spatial_learning_snapshot(store),
                "activation_rank": _activation_snapshot(store, entries),
                "recall_stage": _recall_stage_snapshot(store, entries),
                "source": "core"}
    return identity


def _embed_stats_snapshot():
    """Embedding counters: persisted file (spawn-per-call) wins over process."""
    data = {}
    try:
        from biocore_memory.recall.embedding import embed_stats as _embed_stats
        data = dict(_embed_stats())
    except Exception:
        data = {}
    path = str(os.environ.get("BIOCORE_EMBED_STATS_FILE") or "").strip()
    if path and os.path.isfile(path):
        persisted = _load_json(Path(path), {})
        if isinstance(persisted, dict) and persisted:
            data = {key: int(persisted.get(key, data.get(key, 0)) or 0)
                    for key in ("hit", "disk_hit", "miss", "remote",
                                "local", "fail")}
    return data


# ---------------------------------------------------------------- turn trace
TRACE_DIR = "traces"
TRACE_KEEP = 50
TRACE_DEFAULT_LIMIT = 20


def trace_path(store, session_id):
    root = _store_root(store)
    if root is None:
        return None
    return root / TRACE_DIR / (sanitize_session_id(session_id) + ".jsonl")


def _atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _trace_state_delta(raw):
    rows = []

    def add(key, before, after, source=""):
        if not key:
            return
        if isinstance(before, bool) or isinstance(after, bool):
            return
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            return
        if abs(float(after) - float(before)) < 1e-9:
            return  # only values that actually changed
        origin = str(source or "").strip().lower()
        if origin in ("", "user", "bio", "bio_tick", "biotick"):
            origin = "bio_tick" if origin in ("bio", "bio_tick", "biotick") else "user"
        else:
            origin = origin[:20]
        rows.append({"field": str(key)[:40],
                     "before": round(float(before), 4),
                     "after": round(float(after), 4),
                     "source": origin})

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            add(item.get("field") or item.get("key") or item.get("name"),
                item.get("before"), item.get("after"), item.get("source"))
    elif isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict) and "before" in value and "after" in value:
                add(key, value.get("before"), value.get("after"),
                    value.get("source"))
    return rows[:20]


def _trace_intent(raw):
    data = raw if isinstance(raw, dict) else {}
    return {
        "kind": str(data.get("kind") or "")[:20],
        "weight": round(_clamp(_num(data.get("weight"), 0.0), 0.0, 1.0), 4),
        "reason": str(data.get("reason") or "")[:120],
    }


def _trace_constraints(raw):
    data = raw if isinstance(raw, dict) else {}
    out = {}
    for key in ("length_scale", "initiative", "tone",
                "allow_correction", "note", "sources"):
        if key not in data:
            continue
        value = data.get(key)
        if key == "sources":
            out[key] = [str(item)[:40] for item in value][:10] if isinstance(value, list) else []
        elif key == "tone":
            out[key] = str(value or "")[:60]
        elif key == "note":
            out[key] = str(value or "")[:120]
        elif key == "allow_correction":
            out[key] = _as_bool(value, False)
        elif key == "length_scale":
            out[key] = round(_clamp(_num(value, 1.0), 0.5, 1.5), 4)
        else:
            out[key] = round(_clamp(_num(value, 0.5), 0.0, 1.0), 4)
    return out


def _trace_length(raw, constraints):
    data = raw if isinstance(raw, dict) else {}
    scale = data.get("scale")
    if scale is None:
        scale = constraints.get("length_scale", 1.0)
    source = str(data.get("source") or ("constraints" if constraints else "default"))[:40]
    return {"scale": round(_clamp(_num(scale, 1.0), 0.5, 1.5), 4),
            "source": source}


def _trace_memory(raw, captured):
    data = raw if isinstance(raw, dict) else {}
    ids = data.get("recalled_ids")
    ids = [str(item)[:40] for item in ids][:20] if isinstance(ids, list) else []
    return {"recalled_ids": ids,
            "captured_id": str((captured or {}).get("entry_id") or "")[:40]}


def _trace_modules(raw):
    data = raw if isinstance(raw, dict) else {}
    ran = data.get("ran") if isinstance(data.get("ran"), list) else []
    skipped = data.get("skipped") if isinstance(data.get("skipped"), list) else []
    return {"ran": [str(item)[:30] for item in ran][:20],
            "skipped": [str(item)[:30] for item in skipped][:20]}


def build_trace(session_id, payload, gate, captured):
    """Diagnostic row; purely observational (never drives gate/capture)."""
    data = payload if isinstance(payload, dict) else {}
    constraints = _trace_constraints(data.get("constraints"))
    return {
        "ts": round(time.time(), 3),
        "session_id": sanitize_session_id(session_id),
        "state_delta": _trace_state_delta(data.get("state_delta")),
        "intent": _trace_intent(data.get("intent")),
        "constraints": constraints,
        "length": _trace_length(data.get("length"), constraints),
        "gate": {"action": str((gate or {}).get("action") or "pass")[:20],
                 "rule": str((gate or {}).get("rule") or "")[:40],
                 "label": str((gate or {}).get("label") or "")[:40]},
        "memory": _trace_memory(data.get("memory"), captured),
        "modules": _trace_modules(data.get("modules_trace")),
    }


def _read_trace_rows(path):
    rows = []
    try:
        if path is None or not Path(path).exists():
            return rows
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue  # bad data is skipped, never breaks diagnostics
            if isinstance(row, dict):
                rows.append(row)
    except Exception:
        return []
    return rows


def trace_append(store, session_id, row, keep=TRACE_KEEP):
    """Append one row, keeping the newest keep rows; returns trace file path."""
    path = trace_path(store, session_id)
    if path is None or not isinstance(row, dict):
        return ""
    limit = _int_param(keep, TRACE_KEEP, 1, TRACE_KEEP)
    lock = _acquire_lock(path)
    try:
        rows = _read_trace_rows(path)
        rows.append(row)
        rows = rows[-limit:]
        try:
            _atomic_write_text(path, "\n".join(
                json.dumps(item, ensure_ascii=False,
                           separators=(",", ":")) for item in rows) + "\n")
        except Exception:
            return ""
        return str(path)
    finally:
        _release_lock(lock)


def trace_read(store, session_id, limit=TRACE_DEFAULT_LIMIT):
    """Read-only: newest limit valid rows (chronological order, bad lines skipped)."""
    path = trace_path(store, session_id)
    count = _int_param(limit, TRACE_DEFAULT_LIMIT, 1, TRACE_KEEP)
    return _read_trace_rows(path)[-count:]


# ---------------------------------------------------------------- CLI dispatch
def dispatch(action, payload=None):
    """One CLI action -> JSON-safe result (never raises)."""
    data = payload if isinstance(payload, dict) else {}
    action = str(action or data.get("action") or "").strip().lower()
    store = data.get("store") or _default_store()

    def bad(detail):
        return {"ok": False, "reason": "bad_request", "detail": str(detail)[:300]}

    try:
        if action == "boot":
            session_id = str(data.get("session_id") or "").strip()
            if not session_id:
                return bad("missing session_id")
            block = prompt_block(dict(
                data, phase="boot", session_id=session_id,
                state=data.get("state") or {},
                switches=data.get("switches"),
                max_chars=data.get("max_chars")))
            session_state = apply_persona_to_session(session_id, data)
            session_state = session_state if isinstance(session_state, dict) else {}
            session_state = apply_intero_to_state(session_state, data.get("state"))
            return {"ok": True, "prompt_block": block["text"],
                    "state": session_state}
        if action == "turn_start":
            session_id = str(data.get("session_id") or "").strip()
            if not session_id:
                return bad("missing session_id")
            if "user_text" not in data:
                return bad("missing user_text")
            user_text = clean_text(data.get("user_text"))
            switches = _effective_switches(store, data.get("switches"))
            data["switches"] = switches
            if not switches.get("core_enabled", True):
                return {"ok": True, "prompt_block": "", "state": {},
                        "disabled": True, "reason": "core_disabled"}
            merge_shared_relationship_into_state(session_id, data)
            session_state = apply_persona_to_session(session_id, data)
            session_state = session_state if isinstance(session_state, dict) else {}
            field_host_state = dict(session_state)
            state_store = _relationship_store(data)
            core_path = _core_state_path(data)
            if _core_state is not None and core_path is not None:
                payload_state = (data.get("state")
                                 if isinstance(data.get("state"), dict) else {})
                payload_core = (payload_state.get("core")
                                if isinstance(payload_state.get("core"), dict)
                                else {})
                legacy_core = dict(payload_core)
                session_core = session_state.get("core")
                if isinstance(session_core, dict):
                    legacy_core.update(session_core)
                if _core_state.exists(core_path):
                    _core_state.migrate_session(core_path, legacy_core,
                                                session_id, now=time.time())
                else:
                    passed = {key: legacy_core[key] for key in _CORE_FIELDS
                              if key in legacy_core}
                    _core_state.apply(core_path, absolute=passed,
                                      now=time.time(), session_id=session_id,
                                      intero_fn=_intero_from_core)
                doc = _core_state.load(core_path)
                if doc.get("intero") is None:
                    _core_state.apply(core_path, now=time.time(),
                                      session_id=session_id,
                                      intero_fn=_intero_from_core)
                    doc = _core_state.load(core_path)
                core = dict(legacy_core)
                core.update(_core_state.core_of(doc))
                if isinstance(doc.get("intero"), dict):
                    core["intero"] = dict(doc["intero"])
                    session_state["intero"] = dict(doc["intero"])
                session_state["core"] = core
                session_state["core_delta"] = {}
                session_state["core_state_ts"] = doc.get("ts", 0.0)
            else:
                session_state = apply_intero_to_state(session_state,
                                                      data.get("state"))
            session_state["last_human_ts"] = time.time()
            if state_store is not None:
                _save_session_state(state_store, session_id, session_state)
            field_state = dict(session_state)
            if not isinstance(data.get("state"), dict):
                host_core = field_host_state.get("core")
                if isinstance(host_core, dict):
                    merged_core = dict(field_state.get("core") or {})
                    merged_core.update(host_core)
                    field_state["core"] = merged_core
            field_view = field_turn_start(session_id, data, state=field_state)
            _signals_eval(store, session_id, user_text=user_text,
                          state=session_state, now=time.time())
            perception_view = _perception_read(store, session_id, data,
                                               state=session_state,
                                               now=time.time())
            batch_view = _batch_tick(store, session_id, "turn_start", data,
                                     state=session_state, now=time.time())
            if state_store is not None and batch_view.get("enabled"):
                _save_session_state(state_store, session_id, session_state)
            # read-only: the turn opens on the dimensions written last time
            dimensions_view_start = dimensions_view(
                session_id, data, state=session_state, store=state_store)
            capture_enabled = _as_bool(data.get("capture"), True)
            captured_user = {"captured": False, "entry_id": "", "reason": "disabled"}
            capture_store = data.get("store")
            # the turn opens on the state this handler just assembled
            affect_now = _affect_from_state(session_state)
            if capture_enabled and capture_store:
                user_capture = capture(session_id, "user", user_text, capture_store, {
                    "enabled": _as_bool(data.get("memoryEnabled", True), True),
                    "hourly_cap": data.get("hourly_cap", HOURLY_CAP),
                    "min_chars": data.get("min_chars", MIN_CHARS),
                    "affect": affect_now,
                    "participants": data.get("participants"),
                })
                decision = user_capture.get("decision") or {}
                entry = user_capture.get("entry") or {}
                captured_user = {
                    "captured": bool(decision.get("capture")),
                    "entry_id": str(entry.get("id") or ""),
                    "reason": str(decision.get("reason") or ""),
                }
            elif capture_enabled:
                captured_user["reason"] = "no_store"
            block = prompt_block(dict(
                data, phase="turn", session_id=session_id,
                user_text=user_text,
                state=session_state,
                switches=data.get("switches"),
                max_chars=data.get("max_chars"),
                length_target=data.get("length_target"),
                length_max=data.get("length_max"),
                allow_correction=data.get("allow_correction")))
            return {"ok": True, "prompt_block": block["text"],
                    "constraints": self_layer_constraints(
                        dict(data, user_text=user_text)),
                    "state": session_state,
                    "field": field_view,
                    "perception": perception_view,
                    "batches": batch_view,
                    "dimensions": dimensions_view_start,
                    "captured_user": captured_user}
        if action == "turn_end":
            session_id = str(data.get("session_id") or "").strip()
            if not session_id:
                return bad("missing session_id")
            if "assistant_text" not in data:
                return bad("missing assistant_text")
            switches = _effective_switches(store, data.get("switches"))
            data["switches"] = switches
            if not switches.get("core_enabled", True):
                return {"ok": True, "gate": {"blocked": False, "action": "pass",
                                             "text": str(data.get("assistant_text") or ""),
                                             "rule": "", "label": ""},
                        "captured": None, "clean_text": str(data.get("assistant_text") or ""),
                        "trace": None, "trace_file": "", "disabled": True,
                        "reason": "core_disabled"}
            raw_assistant = clean_text(data.get("assistant_text"))
            do_sanitize = _as_bool(data.get("sanitize_reply"), True)
            cleaned = raw_assistant
            sanitized = False
            removed_tags = 0
            if do_sanitize and _sanitize is not None:
                stats = getattr(_sanitize, "STATS", {}) or {}
                before = (int(stats.get("tag_stripped", 0) or 0),
                          int(stats.get("json_stripped", 0) or 0),
                          int(stats.get("fenced_stripped", 0) or 0))
                try:
                    cleaned = _sanitize.clean(raw_assistant)
                except Exception:
                    cleaned = raw_assistant
                after = (int(stats.get("tag_stripped", 0) or 0),
                         int(stats.get("json_stripped", 0) or 0),
                         int(stats.get("fenced_stripped", 0) or 0))
                removed_tags = max(0, sum(after) - sum(before))
                sanitized = cleaned != raw_assistant or removed_tags > 0
            assistant_text = cleaned
            switches = normalize_switches(data.get("switches"))
            gate = gate_reply(assistant_text, {
                "switches": switches, "user_text": data.get("user_text", "")})
            if do_sanitize and _sanitize is not None:
                try:
                    gate = dict(gate)
                    gate["text"] = _sanitize.clean(gate.get("text") or "")
                except Exception:
                    pass
            capture_enabled = _as_bool(data.get("capture"), True)
            capture_store = data.get("store")
            session_doc = (_load_session_state(store, session_id)
                           if store is not None else {})
            merge_state_relationship_into_shared(session_id, data)
            core_snapshot = None
            core_path = _core_state_path(data)
            if _core_state is not None and core_path is not None:
                deltas = _state_deltas(data)
                legacy_core = session_doc.get("core")
                legacy_core = legacy_core if isinstance(legacy_core, dict) else {}
                if not _core_state.exists(core_path):
                    passed = {key: legacy_core[key] for key in _CORE_FIELDS
                              if key in legacy_core}
                    _core_state.apply(core_path, absolute=passed,
                                      now=time.time(), session_id=session_id,
                                      intero_fn=_intero_from_core)
                shared_rel = (relationship_read(store)["relationship"]
                              if store is not None else {})
                fixed = {key: shared_rel[key]
                         for key in ("trust", "closeness", "conflict")
                         if isinstance(shared_rel.get(key), (int, float))}
                doc = _core_state.apply(core_path, deltas=deltas,
                                        absolute=fixed, now=time.time(),
                                        session_id=session_id,
                                        intero_fn=_intero_from_core)
                if doc:
                    core = dict(legacy_core)
                    core.update(_core_state.core_of(doc))
                    if isinstance(doc.get("intero"), dict):
                        core["intero"] = dict(doc["intero"])
                        session_doc["intero"] = dict(doc["intero"])
                    session_doc["core"] = core
                    session_doc["core_delta"] = dict(deltas)
                    session_doc["core_state_ts"] = doc.get("ts", 0.0)
                    if store is not None:
                        _save_session_state(store, session_id, session_doc)
                    core_snapshot = _core_state.snapshot(core_path)
            # the turn's affect is the state this handler just settled on,
            # captured here so the entry carries the value that was current
            # at the end of the turn (no extra read: session_doc is in hand)
            affect_now = (_affect_from_state({"core": session_doc.get("core")})
                          or _affect_from_state(data.get("state")))
            if capture_enabled and capture_store:
                captured = capture(session_id, "assistant", assistant_text,
                                   capture_store, {
                    "enabled": _as_bool(data.get("memoryEnabled",
                                                 switches.get("memoryEnabled", True)),
                                        True),
                    "hourly_cap": data.get("hourly_cap", HOURLY_CAP),
                    "min_chars": data.get("min_chars", MIN_CHARS),
                    "affect": affect_now,
                    "participants": data.get("participants"),
                })
            else:
                captured = {"ok": True, "decision": {
                    "capture": False,
                    "reason": "disabled" if not capture_enabled else "no_store",
                }, "entry": None}
            # spatial_feedback: judge the recalled entries against the reply
            # this turn actually sent, append the rows and (when enough of
            # them exist) move the axis weights. Read-only for the memory.
            feedback = _collect_spatial_feedback(store, session_id, data,
                                                 assistant_text)
            governance_info = _governance_tick(store, now=time.time())
            relationship_info = _relationship_tick(
                store, data.get("user_text"), now=time.time())
            signals_end = _signals_eval(
                store, session_id,
                user_text=str(data.get("user_text") or ""),
                assistant_text=assistant_text,
                state=(_load_session_state(store, session_id)
                       if store is not None else {}),
                now=time.time())
            if _extensions is not None:
                try:
                    all_entries = _visible(
                        load_memory(store, session_id).get("entries"))
                    picked_ids = [str(row.get("id") or "")
                                  for row in all_entries[:5]]
                    commitment = ((signals_end or {}).get("relationship", {})
                                  .get("commitment_extractor") or {})
                    if commitment.get("has_commitment"):
                        _extensions.add_commitment(
                            store, str(commitment.get("what") or ""),
                            float(commitment.get("due_ts") or 0.0),
                            now=time.time())
                    expression = _extensions.expression_block(
                        store, _load_session_state(store, session_id),
                        (relationship_read(store)["relationship"]
                         if store is not None else {}))
                    snapshot = {
                        "graph": {"entities": 0, "edges": 0},
                        "layered": _extensions.layered_view(all_entries,
                                                            picked_ids),
                        "prospective": _extensions.prospective_view(
                            store, time.time()),
                        "reconstruction": _extensions.reconstruction_view(
                            all_entries),
                        "turn_memory": _extensions.turn_memory_view(
                            [{"entry_id": row.get("id"),
                              "text": row.get("text"), "source": "recall"}
                             for row in all_entries[:5]],
                            reply=assistant_text, now=time.time()),
                        "expression": expression,
                    }
                    hits, graph_stats = _extensions.graph_hits(
                        all_entries, str(data.get("user_text") or ""))
                    snapshot["graph"] = graph_stats
                    _extensions.record_extension_snapshot(store, snapshot)
                except Exception:
                    pass
            if _lifecycle is not None:
                try:
                    _lifecycle.reconsolidate(store, now=time.time())
                    if gate.get("blocked"):
                        _lifecycle.arm_repair(store, gate.get("rule") or "",
                                              now=time.time())
                except Exception:
                    pass
            identity_info = None
            if relationship_info:
                identity_info = _identity_tick(
                    store, narrative={"kind": relationship_info.get("kind"),
                                      "text": str(data.get("user_text") or "")[:60]},
                    now=time.time())
            perception_out = _perception_write(
                store, session_id, data,
                state=(_load_session_state(store, session_id)
                       if store is not None else {}),
                now=time.time())
            perception_fields = perception_out.get("field_deltas") or {}
            batch_state = (_load_session_state(store, session_id)
                           if store is not None else {})
            batch_view = _batch_tick(store, session_id, "turn_end", data,
                                     state=batch_state, now=time.time())
            if store is not None and batch_view.get("enabled"):
                _save_session_state(store, session_id, batch_state)
            batch_fields = batch_view.get("field_deltas") or {}
            if perception_fields or batch_fields:
                data = dict(data)
                merged_learner = dict(data.get("learner_deltas") or {})
                merged_learner.update(perception_fields)
                if batch_fields:
                    merged_learner["batch"] = dict(batch_fields)
                data["learner_deltas"] = merged_learner
            field_on = field_enabled(data)
            decision = captured.get("decision") or {}
            entry = captured.get("entry") or {}
            trace = build_trace(session_id, data, gate, {"entry_id": entry.get("id")})
            trace_file = trace_append(store, session_id, trace)
            field_view = field_turn_end(session_id, data)
            applied_fields = dict((field_view or {}).get("applied") or {})
            if not applied_fields and not field_on:
                applied_fields = dict((perception_fields or {})
                                      .get("appraisal") or {})
            core_pushed = _push_core_deltas(store, session_id, data,
                                            applied_fields, field_on=field_on)
            dimensions_out = dimensions_write(session_id, data,
                                              applied_fields=applied_fields,
                                              store=store)
            timescale_view = _timescale_tick(store, session_id, data,
                                             now=time.time())
            return {
                "ok": True,
                "gate": {"blocked": gate["blocked"], "action": gate["action"],
                         "text": gate["text"], "rule": gate["rule"],
                         "label": gate["label"]},
                "captured": {"captured": bool(decision.get("capture")),
                             "entry_id": str(entry.get("id") or ""),
                             "reason": str(decision.get("reason") or "")},
                "clean_text": cleaned,
                "sanitized": bool(sanitized),
                "removed_tags": int(removed_tags),
                "trace": trace,
                "trace_file": trace_file,
                "field": field_view,
                "perception": perception_out,
                "batches": batch_view,
                "dimensions": dimensions_out,
                "timescales": timescale_view,
                "spatial_feedback": feedback,
                "core_state": core_pushed or core_snapshot,
                "governance": governance_info,
                "relationship": relationship_info,
                "identity": identity_info,
            }
        if action == "usage_event":
            if _cache_stats is None:
                return {"ok": False, "reason": "cache_stats_unavailable"}
            payload = data.get("event") if isinstance(data.get("event"), dict) else data
            row = _cache_stats.record_event(store, payload,
                                            now=data.get("now"))
            return {"ok": row is not None, "event": row,
                    "cache": _cache_stats.summary(store, now=data.get("now"))}
        if action == "stats":
            switches = _effective_switches(store, data.get("switches"))
            if not switches.get("core_enabled", True):
                return {"ok": True, "disabled": True, "reason": "core_disabled",
                        "embed": {key: 0 for key in ("hit", "disk_hit", "miss",
                                                     "remote", "local", "fail")},
                        "switches": {}, "store": str(store)}
            embed = _embed_stats_snapshot()
            cache_info = None
            if _cache_stats is not None:
                try:
                    cache_info = _cache_stats.summary(store)
                except Exception:
                    cache_info = None
            names = ("mood_recall", "affect_encoding", "memory_feedback",
                     "preference_drift")
            out = {name: {"enabled": bool(switches.get(name)), "source": "core"}
                   for name in names}
            out["core_enabled"] = {"enabled": True, "source": "core"}
            governance_info = None
            if _governance is not None:
                try:
                    governance_info = _governance.summary(store)
                except Exception:
                    governance_info = None
            relationship_info = None
            if _relationship_state is not None:
                try:
                    relationship_info = _relationship_state.summary(
                        store, relationship_read(store)["relationship"])
                except Exception:
                    relationship_info = None
            identity_info = None
            if _self_layer is not None:
                try:
                    identity_info = _self_layer.summary(store)
                except Exception:
                    identity_info = None
            autonomy_info = None
            if _autonomy is not None:
                try:
                    metrics = _autonomy.metrics(store)
                    autonomy_info = {"enabled": bool(switches.get("autonomy", True)),
                                     "actions_today": metrics["actions_today"],
                                     "sends_today": metrics["sends_today"],
                                     "limits": _autonomy.limits(store)}
                except Exception:
                    autonomy_info = None
            signals_info = None
            if _signals is not None:
                try:
                    signals_info = _signals.summary(store)
                except Exception:
                    signals_info = None
            return {"ok": True, "embed": embed,
                    "embedding_cache": _embedding_cache_snapshot(store),
                    "switches": out,
                    "governance": governance_info,
                    "relationship": relationship_info,
                    "identity": identity_info,
                    "autonomy": autonomy_info,
                    "signals": signals_info,
                    "cache": cache_info,
                    "store": str(store)}
        if action == "standby_tick":
            try:
                from . import standby as _standby
            except Exception:
                from biocore_runtime import standby as _standby
            payload = data if isinstance(data, dict) else {}
            cfg = payload.get("standby")
            if not isinstance(cfg, dict):
                cfg = {}
            runtime = _load_runtime_config(store) if store is not None else {}
            section = runtime.get("standby")
            merged = dict(section) if isinstance(section, dict) else {}
            merged.update(cfg)
            merged["standby_store"] = str(store or "")
            merged["standby_session_id"] = str(
                payload.get("session_id") or "standby")
            return _standby.tick(now=payload.get("now"), config=merged)
        if action == "autonomy_tick":
            return _autonomy_tick(store, data) or {
                "ok": False, "reason": "autonomy_unavailable"}
        if action == "state":
            session_id = str(data.get("session_id") or "").strip()
            if not session_id:
                return bad("missing session_id")
            switches = _effective_switches(store, data.get("switches"))
            if not switches.get("core_enabled", True):
                return {"ok": True, "state": {"available": False,
                                              "reason": "core_disabled",
                                              "session_id": sanitize_session_id(session_id)}}
            body = _ui_state_body(store, session_id, data)
            stored_state = _load_session_state(store, session_id)
            if stored_state.get("persona_version"):
                body["persona_version"] = str(
                    stored_state.get("persona_version") or "")
            if _store_root(store) is not None:
                body["relationship"] = relationship_read(store)["relationship"]
            field_view = field_state_view(session_id, data)
            if field_view.get("field") is not None:
                body["field"] = field_view["field"]
                body["field_version"] = int(field_view.get("version") or 0)
                body["arbiter"] = field_view.get("arbiter") or {}
            if _perception is not None:
                perception_view = _perception.summary(
                    store, session_id,
                    enabled_override=_perception_on(store, data))
                if perception_view.get("enabled"):
                    body["emotion"] = perception_view.get("emotion") or {}
                    # the six coupled values as they stand now, not as they
                    # stood when the turn started
                    body["affect"] = dict(field_view.get("field")
                                          or perception_view.get("affect") or {})
                    body["attachment"] = perception_view.get("attachment") or {}
                    body["needs"] = perception_view.get("needs") or {}
                    body["appraisal"] = perception_view.get("appraisal") or {}
                    body["regulation"] = perception_view.get("regulation") or {}
                    body["sleep"] = perception_view.get("sleep") or {}
                    body["situation"] = perception_view.get("situation") or {}
                    body["waiting"] = perception_view.get("waiting") or {}
                    body["esteem"] = perception_view.get("esteem") or {}
                    # per-source components (no fused single number)
                    body["labor"] = perception_view.get("labor") or {}
                    body["envy"] = perception_view.get("envy") or {}
                    body["needs_bias_rows"] = (
                        perception_view.get("needs_bias_rows") or {})
                    body["perception"] = {
                        "modules": perception_view.get("modules") or {},
                        "counts": perception_view.get("counts") or {},
                        "writeback": perception_view.get("writeback") or {}}
            if _timescales is not None:
                scale_view = _timescales.summary(
                    _load_session_state(store, session_id),
                    enabled_override=bool(switches.get("timescales", True)))
                if scale_view.get("enabled"):
                    body["timescales"] = {key: scale_view[key] for key in
                                          ("fast", "medium", "slow", "ts")}
            if _batch_registry is not None:
                batch_summary = _batch_registry.summary(store)
                body["batches"] = batch_summary.get("batches") or {}
                body["batch_monitor"] = {
                    "modules": batch_summary.get("modules") or {},
                    "totals": batch_summary.get("totals") or {},
                    "ts": batch_summary.get("ts")}
            expression_show = expression_policy_for(
                _load_session_state(store, session_id),
                dict(data, store=str(store)))
            if expression_show.get("enabled"):
                body["expression_policy"] = expression_show
            retrieval_last = _retrieval_last(store)
            if retrieval_last:
                body["retrieval_last"] = retrieval_last
            priority_view = consolidation_priority(store, session_id, data)
            if priority_view.get("enabled") or priority_view.get("top"):
                body["consolidation_priority"] = priority_view
            dimensions_show = dimensions_view(session_id, data, store=store)
            if dimensions_show.get("enabled"):
                body["dimensions"] = {
                    key: dimensions_show[key] for key in
                    ("schema", "ts", "hops", "axes", "projection", "actions")}
            body["switches"] = {key: bool(switches.get(key)) for key in
                                ("core_enabled", "mood_recall",
                                 "affect_encoding", "memory_feedback",
                                 "preference_drift")}
            return {"ok": True, "state": body,
                    "ui_payload": {"intero": body.get("intero") or {}}}
        if action == "series":
            switches = _effective_switches(store, data.get("switches"))
            if not switches.get("core_enabled", True):
                return {"ok": True, "series": {key: [] for key in
                                               ("ts", "v", "tension", "warmth",
                                                "heaviness", "clarity", "trust",
                                                "closeness")},
                        "points": [], "source": "disabled", "disabled": True}
            return _series_payload(store, data)
        if action == "switches_get":
            current = normalize_switches(data.get("switches"))
            key = str(data.get("key") or "").strip()
            if key:
                if key not in SWITCH_KEYS:
                    return bad("unknown switch key")
                return {"ok": True, "switches": {key: current[key]}}
            return {"ok": True, "switches": current}
        if action == "switches_set":
            key = str(data.get("key") or "").strip()
            if key not in SWITCH_KEYS:
                return bad("unknown switch key")
            if not isinstance(data.get("value"), bool):
                return bad("value must be boolean")
            if data.get("confirm") != key:
                return bad("confirm must equal key")
            current = normalize_switches(data.get("switches"))
            current[key] = bool(data.get("value"))
            return {"ok": True, "switches": current}
        if action == "recall":
            query = str(data.get("query") or "").strip()
            documents = data.get("documents")
            if not isinstance(documents, list):
                documents = data.get("docs") if isinstance(data.get("docs"), list) else []
            fallback = [{"index": index,
                         "document": str((item.get("text") or item.get("document"))
                                         if isinstance(item, dict) else (item or "")).strip()}
                        for index, item in enumerate(documents)]
            if _rerank_mod is None:
                return {"ok": True, "reranked": False, "results": fallback,
                        "reason": "unavailable"}
            config = data.get("config") if isinstance(data.get("config"), dict) else data
            result = _rerank_mod.rerank_documents(query, documents, config)
            if not result:
                return {"ok": True, "reranked": False, "results": fallback}
            return {"ok": True, "reranked": True, "results": result}
        if action == "space":
            if _space is None:
                return {"ok": False, "reason": "space_unavailable"}
            session_id = str(data.get("session_id") or "").strip()
            if not session_id:
                return bad("missing session_id")
            sid = sanitize_session_id(session_id)
            rows = _visible(load_memory(store, sid).get("entries"))
            probed = _space.probe(rows, entry_id=data.get("id"),
                                  query=data.get("query"),
                                  vector=data.get("vector"),
                                  limit=data.get("limit"),
                                  now=_num(data.get("now"), time.time()))
            return {"ok": bool(probed.get("ok")),
                    "enabled": _space_switch(store, data),
                    "session_id": sid, "probe": probed}
        if action == "space_bench":
            if _space is None:
                return {"ok": False, "reason": "space_unavailable"}
            session_id = str(data.get("session_id") or "").strip() or "default"
            return space_bench(store, session_id=session_id,
                               queries=data.get("queries"),
                               limit=data.get("limit"), now=data.get("now"),
                               top_n=data.get("top_n"),
                               depth=data.get("depth"),
                               mode=data.get("mode"))
        if action == "trace":
            session_id = str(data.get("session_id") or "").strip()
            if not session_id:
                return bad("missing session_id")
            rows = trace_read(store, session_id, data.get("limit"))
            return {"ok": True, "rows": rows}
        if action == "inject":
            return prompt_block(data)
        if action == "gate":
            reply = data.get("reply", data.get("reply_text", ""))
            return gate_reply(reply, data)
        if action == "near_dup":
            sid = str(data.get("session_id") or "s1")
            entries_now = _visible(load_memory(store, sid).get("entries"))
            block = (_near_dup.state_of(entries_now, _store_data_dir(store),
                                        _near_dup_flags(store),
                                        os.environ)
                     if _near_dup is not None else {})
            return {"ok": True, "threshold": block.get("threshold"),
                    "marked": block.get("marked", 0),
                    "pairs": block.get("pairs") or [],
                    "last_pair": block.get("last_pair") or {}}
        if action == "cover_select":
            sid = str(data.get("session_id") or "s1")
            query = str(data.get("query") or "").strip()
            limit = _int_param(data.get("limit"), TOP_K, 1, INJECT_MAX_K)
            old = []
            if query:
                try:
                    old = list(_query_entries(store, sid, query, limit,
                                             None, now=data.get("now")) or [])
                except Exception:
                    old = []
            picked, stats, pool_ids = _cover_pick(
                store, sid, query, limit, now=data.get("now"),
                rerank_config=data.get("rerank_config"))
            return {"ok": True, "query": query, "limit": limit,
                    "old": [str((entry or {}).get("id") or "") for entry in old],
                    "cover": [str((entry or {}).get("id") or "") for entry in picked],
                    "pool": pool_ids, "stats": stats}
        if action == "spatial_feedback":
            rows = _spatial_feedback_rows(store, limit=20)
            return {"ok": True, "count": len(rows), "rows": rows,
                    "learning": _spatial_learning_snapshot(store)}
        if action == "capture":
            session_id = data.get("session_id") or data.get("session") or "default"
            switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
            enabled = _as_bool(switches.get("memoryEnabled", True), True)
            affect = (_affect_from_state(data.get("state"))
                      or _affect_pair_from(data.get("affect")))
            result = capture(session_id, data.get("role", "user"),
                             data.get("text", ""), store,
                             {"enabled": enabled,
                              "hourly_cap": data.get("hourly_cap", HOURLY_CAP),
                              "min_chars": data.get("min_chars", MIN_CHARS),
                              "now": data.get("now"),
                              "affect": affect})
            decision = result.get("decision") or {}
            entry = result.get("entry") or {}
            return {"ok": True, "captured": bool(decision.get("capture")),
                    "reason": str(decision.get("reason") or ""),
                    "entry_id": entry.get("id") or ""}
        if action in ("reembed", "rebuild-embeddings"):
            session_id = sanitize_session_id(
                data.get("session_id") or data.get("session") or "default")
            return reembed_store(store, session_id,
                                 provider=data.get("provider") or None,
                                 batch_size=int(_num(data.get("batch_size"), 32) or 32))
        if action in ("export", "export-json"):
            # JSON exists only because this command made it: debug, interop, and
            # the byte-equality check that proves a migration changed nothing.
            session_id = sanitize_session_id(
                data.get("session_id") or data.get("session") or "default")
            root = _store_data_dir(store)
            if root is None or store_mode() == "json":
                return {"ok": False, "reason": "sqlite_store_required"}
            try:
                store_api = _sql_store()
                store_root = _store_root(store)
                memory_file = store_api.export_doc_json(
                    store_root, session_id, path=memory_path(store, session_id))
                events_file = store_api.export_events_json(
                    store_root, session_id,
                    path=_event_state_path(store, session_id))
            except Exception as exc:
                return {"ok": False, "reason": "export_failed",
                        "detail": type(exc).__name__}
            doc = store_api.read_doc(_store_root(store), session_id)
            meta = _read_vector_meta(_store_root(store), session_id)
            try:   # the export carries the vector-space stamp, so a later run
                   # can tell which model produced the file it is reading
                Path(memory_file).parent.joinpath("meta.json").write_text(
                    json.dumps({key: meta.get(key, "")
                                for key in VECTOR_META_KEYS},
                               ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            return {"ok": True, "session_id": session_id,
                    "entries": len(doc.get("entries") or []),
                    "memory_json": str(memory_file),
                    "events_json": str(events_file),
                    "meta": {key: meta.get(key, "") for key in VECTOR_META_KEYS}}
        if action == "tool":
            session_id = data.get("session_id") or data.get("session") or "default"
            result = tool_call(data.get("name", ""), data.get("args") or {},
                               store, session_id=session_id)
            if not isinstance(result, dict):
                result = {"reason": "tool_failed"}
            inner_ok = bool(result.get("ok"))
            flat = {key: value for key, value in result.items() if key != "ok"}
            return {"ok": inner_ok, "result": flat}
        if action == "proactive_tick":
            return proactive_tick(
                data.get("session_id") or data.get("session") or "",
                data.get("last_human_ts"), data.get("switches") or {},
                store, now=data.get("now"), state_file=data.get("state_file"))
        if action in ("memory_inject", "memory"):
            session_id = data.get("session_id") or data.get("session") or "default"
            switches = _effective_switches(store, data.get("switches"))
            if not switches.get("core_enabled", True):
                return {"ok": True, "text": "", "chars": 0, "ids": [],
                        "disabled": True, "reason": "core_disabled"}
            result = inject_block(
                session_id, store,
                max_chars=data.get("max_chars", MAX_CHARS),
                top_k=data.get("top_k", TOP_K),
                query=data.get("query") or data.get("user_text") or "",
                mode=_recall_mode(store, data.get("mode")),
                now=(float(data["now"]) if isinstance(data.get("now"), (int, float))
                     else time.time()),
                include_superseded=bool(data.get("include_superseded")),
                rerank_config=(data.get("rerank_config")
                               or _rerank_config_from(
                                   _load_runtime_config(store).get("rerank"))),
                payload=data)
            return {"ok": True, **result}
        if action == "configure":
            return configure(data)
        return {"ok": False, "reason": "unknown_action", "action": action}
    except Exception as exc:  # CLI must always answer one JSON line
        return {"ok": False, "reason": "pipeline_error",
                "detail": type(exc).__name__ + ": " + str(exc)[:200]}


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:])
    action = args[0] if args else ""
    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
    except Exception:
        raw = ""
    payload = {}
    if raw.strip():
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    if action:
        payload.setdefault("action", action)
    result = dispatch(action or payload.get("action"), payload)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
