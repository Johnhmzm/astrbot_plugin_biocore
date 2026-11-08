# -*- coding: utf-8 -*-
"""Optional embedding provider for recall (stdlib only; no astrbot import).

Embeddings are OPTIONAL: load_provider() returns None unless a base URL and
model are configured (dict or BIOCORE_EMBEDDING_* env). embed() normalizes text,
uses a hash-keyed LRU (<=512), and returns None on timeout/error so recall
degrades to lexical instead of failing. urllib + stdlib only.
"""
from __future__ import annotations

import atexit
import contextlib
import hashlib
import json
import logging
import math
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import List, Optional, Protocol, runtime_checkable

try:  # package import (plugin runtime)
    from ..embedding_mode import resolve_mode
except Exception:  # pragma: no cover - top-level/standalone tests
    from embedding_mode import resolve_mode  # type: ignore

EMBED_CACHE_MAX = 512

# task-221: observable cache/provider counters (process-local, never raises).
EMBED_STATS = {"hit": 0, "disk_hit": 0, "miss": 0, "remote": 0, "local": 0,
               "fail": 0, "corrupt": 0}


def embed_stats(reset=False):
    data = dict(EMBED_STATS)
    if reset:
        for key in EMBED_STATS:
            EMBED_STATS[key] = 0
    return data
EMBED_TEXT_MAX_CHARS = 2000
DEFAULT_TIMEOUT, MIN_TIMEOUT, MAX_TIMEOUT = 5.0, 0.1, 60.0
ENV_BASE_URL = "BIOCORE_EMBEDDING_BASE_URL"
ENV_API_KEY, ENV_MODEL = "BIOCORE_EMBEDDING_KEY", "BIOCORE_EMBEDDING_MODEL"
ENV_TIMEOUT = "BIOCORE_EMBEDDING_TIMEOUT"
ENV_LOCAL_MODEL = "BIOCORE_EMBEDDING_LOCAL_MODEL"
ENV_LOCAL_FALLBACK = "BIOCORE_EMBEDDING_LOCAL_FALLBACK"
ENV_LOCAL_TOKENIZER = "BIOCORE_EMBEDDING_LOCAL_TOKENIZER"
ENV_LOCAL_THREADS = "BIOCORE_EMBEDDING_LOCAL_THREADS"
ENV_MODE = "BIOCORE_EMBEDDING_MODE"
ENV_DIM = "BIOCORE_EMBEDDING_DIM"
EMBEDDING_MODES = ("off", "remote", "local", "remote_with_local_fallback")
MODE_ALIASES = {
    "remote_generic": "remote",
    "remote_openai": "remote",
    "local_onnx": "local",
    "onnx": "local",
    "fallback": "remote_with_local_fallback",
    "remote_local_fallback": "remote_with_local_fallback",
    "remote_with_fallback": "remote_with_local_fallback",
    "disabled": "off",
    "none": "off",
}
LOCAL_FALLBACK_DEFAULT_ENABLED = False
LOCAL_TIMEOUT_DEFAULT_S = 8.0
LOCAL_THREADS_DEFAULT = 2
LOCAL_THREADS_MAX = 8
LOCAL_DIM_DEFAULT = 512
LOCAL_STATUSES = ("ok", "missing", "failed")
_LOCAL_WARNED = set()
logger = logging.getLogger("biocore_memory.embedding")


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> Optional[List[float]]:
        ...


def _as_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(text) -> str:
    """Normalize before both hashing and sending (one truncation rule)."""
    return _clean(text)[:EMBED_TEXT_MAX_CHARS]


def cache_key(text, model="") -> str:
    """Cache identity: the model that produced the vector + the normalized text.

    Text alone is not an identity -- a model swap would be answered with a
    stale vector -- so the model name is part of the hash (an empty model keeps
    the historical text-only key for providers that do not name one).
    """
    body = "%s|%s" % (str(model or "").strip().lower(), normalize_text(text))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def _timeout_for(provider, timeout=None) -> float:
    value = timeout if timeout is not None else getattr(provider, "timeout", None)
    if value is None:
        value = os.environ.get(ENV_TIMEOUT) or DEFAULT_TIMEOUT
    value = _as_float(value, DEFAULT_TIMEOUT)
    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, value))


def _validate_vector(value) -> Optional[List[float]]:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    out = []
    for item in value:
        number = _as_float(item, float("nan"))
        if not math.isfinite(number):
            return None
        out.append(number)
    return out


# The persisted cache is what makes an embedding deterministic ACROSS runs:
# the key is the normalized text AND the model that produced it, so a model
# swap can never be answered with a stale vector. One JSON object written
# through a temp file + os.replace (a half-written cache never becomes the
# cache), and a corrupt file degrades to a miss instead of raising.
CACHE_FILE_ENV = "BIOCORE_EMBEDDING_CACHE_FILE"
CACHE_DIR_ENV = "BIOCORE_EMBEDDING_CACHE_DIR"
CACHE_FORMAT = 1
DEFAULT_CACHE_FILE = ("data", "cache", "embedding.json")
_CONFIGURED_CACHE_FILE = None


def default_cache_file(data_dir=None):
    """<data_dir>/cache/embedding.json; the bare default is data/cache/embedding.json."""
    if data_dir:
        return os.path.join(str(data_dir), "cache", "embedding.json")
    return os.path.join(*DEFAULT_CACHE_FILE)


def cache_file(config=None, data_dir=None):
    """Resolve the cache file: config -> env -> <data_dir>/cache/embedding.json.

    None when nothing names a directory: an engine without a data dir must not
    scatter cache files into the caller's working directory.
    """
    block = config if isinstance(config, dict) else {}
    if isinstance(block.get("embedding"), dict):
        block = block["embedding"]
    for key in ("cache_file", "cache_path"):
        value = str(block.get(key) or "").strip()
        if value:
            return value
    env_file = str(os.environ.get(CACHE_FILE_ENV) or "").strip()
    if env_file:
        if env_file.lower().endswith((".json", ".jsonl")):
            return env_file
        return os.path.join(env_file, "embedding.json")
    env_dir = str(os.environ.get(CACHE_DIR_ENV) or "").strip()
    if env_dir:
        return os.path.join(env_dir, "embedding.json")
    if data_dir:
        return default_cache_file(data_dir)
    return None


def set_cache_file(path):
    """Process-wide default used by embed(); the engine sets it from its config."""
    global _CONFIGURED_CACHE_FILE
    _CONFIGURED_CACHE_FILE = str(path) if path else None
    return _CONFIGURED_CACHE_FILE


def configured_cache_file():
    """The path embed() uses when its caller does not pass one."""
    return _CONFIGURED_CACHE_FILE or cache_file(None, None)


_CACHE_MEMO = {"target": None, "stamp": None, "rows": {}}


def _cache_stamp(target):
    try:
        info = os.stat(target)
        return (int(info.st_mtime_ns), int(info.st_size))
    except Exception:
        return None


def read_cache(path=None):
    """The cache mapping; a corrupt or unreadable file is simply a miss.

    Dispatches to the active backend: under sqlite the whole table is returned
    (this is a debug/inspection read, not the hot path -- embed() uses
    cache_get_many for one key).

    A stat-keyed memo keeps the hot path from re-parsing the file for every
    embedding in one process; another writer (or any mtime change) invalidates
    it, so it can only save a read, never serve a stale vector.
    """
    target = path or configured_cache_file()
    if target and cache_backend(target) == "sqlite":
        return _sqlite_rows(target)
    if not target or not os.path.isfile(target):
        return {}
    stamp = _cache_stamp(target)
    if (stamp is not None and _CACHE_MEMO.get("target") == target
            and _CACHE_MEMO.get("stamp") == stamp):
        return dict(_CACHE_MEMO.get("rows") or {})
    try:
        with open(target, encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        EMBED_STATS["corrupt"] = int(EMBED_STATS.get("corrupt", 0)) + 1
        return {}
    rows = doc.get("entries") if isinstance(doc, dict) else doc
    if not isinstance(rows, dict):
        return {}
    out = {}
    for key, value in rows.items():
        vector = _validate_vector(value.get("v") if isinstance(value, dict) else value)
        if vector is None:
            continue
        out[str(key)] = vector
    _CACHE_MEMO.update({"target": target, "stamp": stamp, "rows": out})
    return dict(out)


def write_cache(rows, path=None):
    """Temp file + os.replace; returns False when the file cannot be written."""
    target = path or configured_cache_file()
    if not target or not isinstance(rows, dict):
        return False
    try:
        folder = os.path.dirname(os.path.abspath(target))
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"format": CACHE_FORMAT, "entries": rows}, fh,
                      ensure_ascii=False)
        os.replace(tmp, target)
        _CACHE_MEMO.update({"target": target, "stamp": _cache_stamp(target),
                            "rows": dict(rows)})
        return True
    except Exception:
        return False


def cache_backend(path=None):
    """'sqlite' when the incremental cache is switched on, else 'json'.

    The pooled writer keeps a handle on the file, so anything that copies or
    deletes a store calls cache_close() first (the test suite does it in an
    autouse fixture). BIOCORE_EMBED_CACHE=json keeps the old single-file cache.
    """
    mode = str(os.environ.get("BIOCORE_EMBED_CACHE") or "").strip().lower()
    if mode in ("json", "file", "legacy", "off", "0"):
        return "json"
    return "sqlite"


def sqlite_cache_path(path=None):
    """The incremental cache beside the legacy json file (None when unset)."""
    target = path or configured_cache_file()
    if not target:
        return None
    return os.path.splitext(str(target))[0] + ".sqlite"


_SQL_READY = {"path": None, "ready": False}
_SQL_CONN = {"path": None, "conn": None}


def _close_conn():
    """Drop the pooled writer; safe to call any number of times."""
    conn = _SQL_CONN.get("conn")
    _SQL_CONN.update({"path": None, "conn": None})
    if conn is None:
        return False
    try:
        conn.commit()
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass
    return True


def cache_close(path=None):
    """Release the cache handle so the files can be moved or deleted.

    The writer connection is pooled for speed (opening sqlite per vector
    dominated the write), which on Windows keeps a handle on the file: temp-dir
    cleanup, a store copy, or a re-point at another cache all need this. A
    path argument closes only when it matches the open one.
    """
    db = sqlite_cache_path(path) if path else None
    if db is not None and _SQL_CONN.get("path") not in (None, db):
        return False
    closed = _close_conn()
    _SQL_READY.update({"path": None, "ready": False})
    return closed


atexit.register(cache_close)


@contextlib.contextmanager
def cache_open(path=None):
    """Hold the cache for one block and release the handle on the way out."""
    cache_init(path)
    try:
        yield sqlite_cache_path(path)
    finally:
        cache_close(path)


def _shared_conn(db):
    """One write connection per process: opening sqlite per vector dominated the write."""
    current = _SQL_CONN.get("conn")
    if _SQL_CONN["path"] == db and current is not None:
        return current
    if current is not None:          # re-pointing at another cache closes the old one
        _close_conn()
        _SQL_READY.update({"path": None, "ready": False})
    conn = _sql_connect(db)
    _SQL_CONN.update({"path": db, "conn": conn})
    return conn


def _sql_connect(db, create=True):
    import sqlite3
    folder = os.path.dirname(os.path.abspath(db))
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(db, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if create:
        conn.execute("CREATE TABLE IF NOT EXISTS vec ("
                     "key TEXT PRIMARY KEY, vector BLOB, dim INTEGER, updated REAL)")
    return conn


def cache_init(path=None):
    """Create the db and import the legacy json once; the json is renamed after.

    A partial or corrupt import leaves the json in place: nothing is deleted
    until every row it held has been written and counted.
    """
    target = path or configured_cache_file()
    db = sqlite_cache_path(target)
    if not db:
        return None
    if _SQL_READY["path"] == db and _SQL_READY["ready"]:
        return db
    try:
        conn = _shared_conn(db)
        try:
            have = conn.execute("SELECT COUNT(*) FROM vec").fetchone()[0]
            legacy = target if os.path.isfile(target) else None
            if legacy:
                rows = read_cache(legacy)
                if rows:
                    now = time.time()
                    conn.executemany(
                        "INSERT OR REPLACE INTO vec (key, vector, dim, updated) VALUES (?,?,?,?)",
                        [(str(k), pack_vector(v), len(v), now)
                         for k, v in rows.items() if _validate_vector(v) is not None])
                    conn.commit()
                total = conn.execute("SELECT COUNT(*) FROM vec").fetchone()[0]
                if total >= len(rows):
                    os.replace(legacy, legacy + ".migrated")
                else:
                    return db          # keep the json: the import lost rows
        except Exception:
            return db
    except Exception:
        return db
    _SQL_READY.update({"path": db, "ready": True})
    return db


def pack_vector(vector):
    """float32 blob: 4 KB per 1024-d vector, written one row at a time."""
    try:
        import struct
        rows = [float(x) for x in (vector or [])]
        if not rows:
            return None
        return struct.pack("<%df" % len(rows), *rows)
    except Exception:
        return None


def unpack_vector(blob):
    try:
        import struct
        if not blob:
            return []
        return list(struct.unpack("<%df" % (len(blob) // 4), blob))
    except Exception:
        return []


def cache_get_many(keys, path=None):
    """{key: vector} in one query; empty when the db is absent."""
    db = cache_init(path)
    rows = [str(k) for k in (keys or [])]
    if not db or not rows:
        return {}
    try:
        conn = _sql_connect(db, create=False)
        try:
            out = {}
            for spot in range(0, len(rows), 500):
                chunk = rows[spot:spot + 500]
                marks = ",".join("?" * len(chunk))
                for key, blob in conn.execute(
                        "SELECT key, vector FROM vec WHERE key IN (%s)" % marks, chunk):
                    vector = unpack_vector(blob)
                    if vector:
                        out[str(key)] = vector
            return out
        finally:
            conn.close()
    except Exception:
        return {}


def cache_put(key, vector, path=None):
    """Upsert one vector; the write is one row, not the whole cache."""
    db = cache_init(path)
    if not db:
        return False
    try:
        conn = _shared_conn(db)
        conn.execute(
            "INSERT OR REPLACE INTO vec (key, vector, dim, updated) VALUES (?,?,?,?)",
            (str(key), pack_vector(vector), len(vector or []), time.time()))
        conn.commit()
        return True
    except Exception:
        return False


def _sqlite_rows(path=None):
    """Every row of the db cache as {key: vector} (debug/inspection only)."""
    db = sqlite_cache_path(path)
    if not db or not os.path.isfile(db):
        return {}
    try:
        conn = _sql_connect(db, create=False)
        try:
            out = {}
            for key, blob in conn.execute("SELECT key, vector FROM vec"):
                vector = unpack_vector(blob)
                if vector:
                    out[str(key)] = vector
            return out
        finally:
            conn.close()
    except Exception:
        return {}


def cache_count(path=None):
    db = sqlite_cache_path(path)
    if not db or not os.path.isfile(db):
        return 0
    try:
        conn = _sql_connect(db, create=False)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM vec").fetchone()[0])
        finally:
            conn.close()
    except Exception:
        return 0


def cache_summary(path=None, data_dir=None):
    """hit / miss / size for /state; hit already includes the disk hits."""
    target = path or configured_cache_file() or cache_file(None, data_dir)
    size = cache_count(target) if target else 0
    rows = read_cache(target) if (target and not size) else {}
    memory_hit = int(EMBED_STATS.get("hit", 0))
    disk_hit = int(EMBED_STATS.get("disk_hit", 0))
    miss = int(EMBED_STATS.get("miss", 0))
    total = memory_hit + disk_hit + miss
    return {"hit": memory_hit + disk_hit, "miss": miss, "size": size or len(rows),
            "hit_rate": (round((memory_hit + disk_hit) / float(total), 4)
                         if total else 0.0),
            "memory_hit": memory_hit, "disk_hit": disk_hit,
            "corrupt": int(EMBED_STATS.get("corrupt", 0)),
            "file": str((sqlite_cache_path(target)
                         if target and cache_backend(target) == "sqlite"
                         else target) or ""),
            "backend": cache_backend(target) if target else "none"}


def _cache_trim(rows, keep=EMBED_CACHE_MAX):
    while len(rows) > keep:
        rows.pop(next(iter(rows)), None)
    return rows


def _cache_get(cache, key):
    if cache is None:
        return None
    try:
        return _validate_vector(cache.get(key))
    except Exception:
        return None


def _cache_put(cache, key, vector) -> None:
    if cache is None:
        return
    try:
        cache[key] = list(vector)
        while len(cache) > EMBED_CACHE_MAX:
            cache.pop(next(iter(cache)), None)
    except Exception:
        return


# ---------------------------------------------------- local int8 fallback
def _as_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return bool(default)


def _warn_once(key, message):
    """One warning per reason/path for the whole process (no log spam)."""
    if key in _LOCAL_WARNED:
        return
    _LOCAL_WARNED.add(key)
    try:
        logger.warning("[biocore-memory] %s", message)
    except Exception:
        pass


def local_config(config=None):
    """Parse the local-fallback knobs from a flat or nested config dict."""
    cfg = _provider_config(config)
    enabled = _as_bool(
        cfg.get("embedding_local_fallback_enabled",
                os.environ.get(ENV_LOCAL_FALLBACK, "0")),
        LOCAL_FALLBACK_DEFAULT_ENABLED)
    model_path = str(cfg.get("embedding_local_model_path")
                     or os.environ.get(ENV_LOCAL_MODEL) or "").strip()
    tokenizer_path = str(cfg.get("embedding_local_tokenizer_path")
                         or os.environ.get(ENV_LOCAL_TOKENIZER) or "").strip()
    threads = int(_as_float(
        cfg.get("embedding_local_threads",
                os.environ.get(ENV_LOCAL_THREADS, LOCAL_THREADS_DEFAULT)),
        LOCAL_THREADS_DEFAULT))
    threads = max(1, min(LOCAL_THREADS_MAX, threads))
    timeout_s = _as_float(
        cfg.get("embedding_timeout_s",
                os.environ.get(ENV_TIMEOUT, LOCAL_TIMEOUT_DEFAULT_S)),
        LOCAL_TIMEOUT_DEFAULT_S)
    timeout_s = max(MIN_TIMEOUT, min(MAX_TIMEOUT, timeout_s))
    raw_dim = cfg.get("embedding_dim")
    if raw_dim is None:
        raw_dim = os.environ.get(ENV_DIM)
    try:
        dim = int(_as_float(raw_dim, 0))
    except Exception:
        dim = 0
    if dim < 0 or dim > 8192:
        dim = 0
    return {"enabled": enabled, "model_path": model_path,
            "tokenizer_path": tokenizer_path, "threads": threads,
            "timeout_s": timeout_s, "dim": dim}


def _load_local_embedder(cfg):
    """Build + load the CPU int8 embedder once; False when unusable."""
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return False
    if not cfg.get("model_path"):
        return False
    try:
        from ..embedding_local import LocalEmbedder
    except Exception as exc:
        _warn_once("import:" + str(cfg.get("model_path")),
                   "local embedding component unavailable (%s); staying on "
                   "remote" % exc)
        return False
    try:
        dimension = int(cfg.get("dim") or LOCAL_DIM_DEFAULT)
        embedder = LocalEmbedder(
            cfg.get("model_path"), dim=dimension,
            tokenizer_path=cfg.get("tokenizer_path") or None,
            threads=cfg.get("threads", LOCAL_THREADS_DEFAULT))
        embedder.load()
        embedder.warmup()
        return embedder
    except Exception as exc:
        _warn_once("load:" + str(cfg.get("model_path")),
                   "local embedding model configured but failed to load "
                   "(%s); remote only until restart" % exc)
        return False


def preload_local_fallback(provider):
    """Startup probe: ok | missing | failed (never raises)."""
    cfg = getattr(provider, "fallback_config", None)
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        try:
            provider.local_status = "missing"
        except Exception:
            pass
        return "missing"
    if not cfg.get("model_path"):
        try:
            provider.local_status = "missing"
        except Exception:
            pass
        return "missing"
    embedder = _load_local_embedder(cfg)
    try:
        provider.local_embedder = embedder
        provider.local_status = "ok" if embedder else "failed"
        return provider.local_status
    except Exception:
        return "failed"


def local_embedding_status(provider=None):
    """Health string: ok | missing | failed."""
    if provider is None:
        return "missing"
    if getattr(provider, "local_only", False):
        return ("ok" if getattr(provider, "local_embedder", None)
                not in (None, False) else "failed")
    status = getattr(provider, "local_status", None)
    if status in LOCAL_STATUSES:
        return status
    cfg = getattr(provider, "fallback_config", None)
    if (not isinstance(cfg, dict) or not cfg.get("enabled")
            or not cfg.get("model_path")):
        return "missing"
    return "missing"


def embedding_health(provider=None):
    """Read-only embedding health for /health and the panel."""
    cfg = getattr(provider, "fallback_config", None)
    cfg = cfg if isinstance(cfg, dict) else {}
    return {
        "local_embedding": local_embedding_status(provider),
        "embedding_mode": str(getattr(provider, "embedding_mode", "") or ""),
        "embedding_mode_requested": str(
            getattr(provider, "embedding_mode_requested", "") or ""),
        "embedding_mode_source": str(
            getattr(provider, "embedding_mode_source", "") or ""),
        "embedding_mode_reason": str(
            getattr(provider, "embedding_mode_reason", "") or ""),
        "embedding_mode_onnxruntime": bool(
            getattr(provider, "embedding_mode_onnxruntime", False)),
        "remote_configured": bool(provider is not None
                                  and not getattr(provider, "local_only",
                                                  False)),
        "local_only": bool(getattr(provider, "local_only", False)),
        "local_model_path": str(cfg.get("model_path") or ""),
        "local_threads": int(cfg.get("threads") or 0),
        "timeout_s": float(cfg.get("timeout_s") or 0.0),
    }


def _fallback_embed(provider, text):
    """Remote failed/timed out -> one local int8 vector, or None."""
    if provider is None or getattr(provider, "local_only", False):
        return None
    cfg = getattr(provider, "fallback_config", None)
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    embedder = getattr(provider, "local_embedder", None)
    if embedder is False:
        return None
    if embedder is None:
        embedder = _load_local_embedder(cfg)
        try:
            provider.local_embedder = embedder
            provider.local_status = "ok" if embedder else "failed"
        except Exception:
            pass
    if not embedder:
        return None
    try:
        vectors = embedder.encode([text])
    except Exception as exc:
        _warn_once("encode:" + str(cfg.get("model_path")),
                   "local embedding inference failed (%s); no vector" % exc)
        try:
            provider.local_embedder = False
            provider.local_status = "failed"
        except Exception:
            pass
        return None
    if not vectors:
        return None
    vector = _validate_vector(vectors[0])
    if vector is None:
        return None
    try:
        expected = int(getattr(embedder, "dim", LOCAL_DIM_DEFAULT))
    except Exception:
        expected = LOCAL_DIM_DEFAULT
    if expected > 0 and len(vector) != expected:
        return None
    return vector


class OpenAICompatibleProvider:
    """POST {base_url}/embeddings with the OpenAI-compatible JSON shape."""

    mode = "remote"

    def __init__(self, base_url, model, api_key="", timeout=DEFAULT_TIMEOUT,
                 dim=0):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout = max(MIN_TIMEOUT, min(MAX_TIMEOUT,
                                           _as_float(timeout, DEFAULT_TIMEOUT)))
        try:
            self.dim = max(0, min(8192, int(dim or 0)))
        except Exception:
            self.dim = 0

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/embeddings"):
            return self.base_url
        return self.base_url + "/embeddings"

    def embed_text(self, text: str) -> List[float]:
        payload = {"model": self.model, "input": [normalize_text(text)],
                   "encoding_format": "float"}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST")
        response = urllib.request.urlopen(request, timeout=self.timeout)
        try:
            body = json.loads(response.read().decode("utf-8"))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        checked = _validate_vector(body["data"][0]["embedding"])
        if checked is None:
            raise ValueError("invalid embedding payload")
        if self.dim > 0 and len(checked) != self.dim:
            raise ValueError(
                "embedding dimension mismatch: expected %d, got %d"
                % (self.dim, len(checked)))
        return checked


OpenAIProvider = OpenAICompatibleProvider


class LocalOnlyEmbeddingProvider:
    """No remote configured: serve embeddings from the local CPU int8 model."""

    local_only = True
    mode = "local_only"

    def __init__(self, embedder, timeout=LOCAL_TIMEOUT_DEFAULT_S, dim=0,
                 mode_name="local_only"):
        self.local_embedder = embedder
        self.local_status = "ok" if embedder else "failed"
        self.mode = str(mode_name or "local_only")
        try:
            self.dim = max(0, int(dim or getattr(embedder, "dim", 0) or 0))
        except Exception:
            self.dim = 0
        self.timeout = max(MIN_TIMEOUT, min(MAX_TIMEOUT,
                                           _as_float(timeout,
                                                      LOCAL_TIMEOUT_DEFAULT_S)))
        self.fallback_config = {
            "enabled": True,
            "model_path": str(getattr(embedder, "model_path", "") or ""),
            "tokenizer_path": str(getattr(embedder, "tokenizer_path", "") or ""),
            "threads": int(getattr(embedder, "threads", LOCAL_THREADS_DEFAULT)),
            "timeout_s": self.timeout,
        }

    def embed_text(self, text: str) -> List[float]:
        vectors = self.local_embedder.encode([normalize_text(text)])
        if not vectors:
            raise ValueError("empty local embedding")
        vector = _validate_vector(vectors[0])
        if vector is None:
            raise ValueError("invalid local embedding")
        if self.dim > 0 and len(vector) != self.dim:
            raise ValueError(
                "local embedding dimension mismatch: expected %d, got %d"
                % (self.dim, len(vector)))
        return vector


def _provider_config(config) -> dict:
    merged = {}
    if isinstance(config, dict):
        merged.update({k: v for k, v in config.items() if not isinstance(v, dict)})
        for key in ("embedding", "embeddings", "provider"):
            nested = config.get(key)
            if isinstance(nested, dict):
                merged.update(nested)
    return merged


def embedding_mode(config=None):
    """Resolved mode: "", off, remote, local, remote_with_local_fallback.

    An empty string means the config has no embedding_mode key, so legacy
    auto-selection is kept for old configs. Unknown values behave like off
    (no network, no local model load).
    """
    cfg = _provider_config(config)
    raw = cfg.get("embedding_mode")
    if raw is None:
        raw = os.environ.get(ENV_MODE)
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    return MODE_ALIASES.get(text, text)


def embedding_dim(config=None):
    """Configured expected embedding dimension, or 0 when not enforced."""
    cfg = _provider_config(config)
    raw = cfg.get("embedding_dim")
    if raw is None:
        raw = os.environ.get(ENV_DIM)
    try:
        dim = int(_as_float(raw, 0))
    except Exception:
        dim = 0
    return dim if 0 < dim <= 8192 else 0


def _remote_settings(cfg):
    """One OpenAI-compatible remote endpoint (new keys first, old keys after)."""
    base_url = (cfg.get("embedding_base_url") or cfg.get("base_url")
                or cfg.get("api_base") or cfg.get("url")
                or cfg.get("embedding_api_base")
                or os.environ.get(ENV_BASE_URL) or "")
    model = (cfg.get("embedding_model") or cfg.get("model")
             or os.environ.get(ENV_MODEL) or "")
    api_key = (cfg.get("embedding_api_key") or cfg.get("api_key")
               or cfg.get("key") or os.environ.get(ENV_API_KEY) or "")
    timeout = cfg.get("timeout")
    if timeout is None:
        seconds = cfg.get("embedding_timeout_s")
        if seconds is None:
            millis = cfg.get("embedding_timeout_ms")
            if millis is not None:
                seconds = _as_float(millis, DEFAULT_TIMEOUT * 1000.0) / 1000.0
        timeout = seconds if seconds is not None else (
            os.environ.get(ENV_TIMEOUT) or DEFAULT_TIMEOUT)
    return {"base_url": str(base_url or "").strip(),
            "model": str(model or "").strip(),
            "api_key": str(api_key or "").strip(),
            "timeout": _as_float(timeout, DEFAULT_TIMEOUT),
            "dim": embedding_dim(cfg)}


def _disabled_fallback_config(timeout):
    return {"enabled": False, "model_path": "", "tokenizer_path": "",
            "threads": LOCAL_THREADS_DEFAULT,
            "timeout_s": _as_float(timeout, LOCAL_TIMEOUT_DEFAULT_S),
            "dim": 0}


def _remote_provider(cfg):
    remote = _remote_settings(cfg)
    if not remote["base_url"]:
        return None
    if not str(remote["model"] or "").strip():
        # cache_key(text, model) = sha256("model|text"): an empty model degrades
        # the key to text-only, so a model swap would silently answer from the
        # previous model's vectors. None keeps the "not configured" contract;
        # embed() still raises if such a provider ever reaches it.
        _warn_once("provider:no-model",
                   "embedding base_url set but model empty: provider disabled "
                   "(cache_key would degrade to text-only)")
        return None
    model = str(remote["model"]).strip()
    provider = OpenAICompatibleProvider(
        remote["base_url"], model, remote["api_key"],
        remote["timeout"], dim=remote["dim"])
    provider.mode = "remote"
    provider.fallback_config = _disabled_fallback_config(remote["timeout"])
    provider.local_embedder = None
    provider.local_status = "missing"
    return provider


class _LazyLocalEmbedder:
    """Local int8 embedder proxy: loads the model on the first real encode.

    task-211: the auto probe is read-only, so startup must not load onnxruntime
    or the model. This proxy exposes the same metadata and defers load().
    """

    def __init__(self, local_cfg):
        self._cfg = dict(local_cfg or {})
        self._impl = None
        self._failed = None

    @property
    def model(self):
        """A non-empty identity for the cache key.

        The local model has no vendor name, but cache_key must never be
        text-only: two different local checkpoints would otherwise share rows.
        """
        name = str(self._cfg.get("model_id") or "").strip()
        if name:
            return name
        base = os.path.basename(str(self.model_path or "").rstrip("/\\"))
        return ("local:" + base) if base else "local"

    @property
    def model_path(self):
        return str(self._cfg.get("model_path") or "")

    @property
    def tokenizer_path(self):
        return str(self._cfg.get("tokenizer_path") or "")

    @property
    def threads(self):
        try:
            return int(self._cfg.get("threads") or LOCAL_THREADS_DEFAULT)
        except Exception:
            return LOCAL_THREADS_DEFAULT

    @property
    def dim(self):
        try:
            return int(self._cfg.get("dim") or 0) or LOCAL_DIM_DEFAULT
        except Exception:
            return LOCAL_DIM_DEFAULT

    def _ensure(self):
        if self._impl is False:
            return False
        if self._impl is not None:
            return self._impl
        if self._failed is not None:
            raise self._failed
        try:
            embedder = _load_local_embedder(self._cfg)
        except Exception as exc:  # pragma: no cover - defensive
            embedder = False
            self._failed = RuntimeError(
                "local embedding unavailable: %s" % exc)
        if not embedder:
            self._impl = False
            if self._failed is None:
                self._failed = RuntimeError("local embedding unavailable")
            raise self._failed
        self._impl = embedder
        return embedder

    def encode(self, texts):
        embedder = self._ensure()
        if not embedder:
            raise RuntimeError("local embedding unavailable")
        return embedder.encode(texts)


def _with_mode(provider, resolved):
    """Attach the resolved mode/reason to a provider for /health and the panel."""
    if provider is None or not isinstance(resolved, dict):
        return provider
    try:
        provider.embedding_mode = str(resolved.get("mode") or "")
        provider.embedding_mode_requested = str(resolved.get("requested") or "")
        provider.embedding_mode_source = str(resolved.get("source") or "")
        provider.embedding_mode_reason = str(resolved.get("reason") or "")
        provider.embedding_mode_onnxruntime = bool(
            resolved.get("onnxruntime_available"))
    except Exception:
        pass
    return provider


def _lazy_local_provider(cfg):
    """Local provider whose model/onnxruntime load at the first embed call."""
    local_cfg = dict(cfg)
    local_cfg["embedding_local_fallback_enabled"] = True
    local = local_config(local_cfg)
    if not local.get("model_path"):
        return None
    proxy = _LazyLocalEmbedder(local)
    expected = int(local.get("dim") or 0) or LOCAL_DIM_DEFAULT
    return LocalOnlyEmbeddingProvider(
        proxy, local.get("timeout_s"), dim=expected, mode_name="local")


def _local_provider(cfg):
    local_cfg = dict(cfg)
    local_cfg["embedding_local_fallback_enabled"] = True
    local = local_config(local_cfg)
    if not local.get("model_path"):
        return None
    embedder = _load_local_embedder(local)
    if not embedder:
        return None
    expected = int(local.get("dim") or 0) or int(
        getattr(embedder, "dim", 0) or LOCAL_DIM_DEFAULT)
    return LocalOnlyEmbeddingProvider(
        embedder, local.get("timeout_s"), dim=expected, mode_name="local")


def _fallback_provider(cfg):
    remote = _remote_settings(cfg)
    local_cfg = dict(cfg)
    local_cfg["embedding_local_fallback_enabled"] = True
    local = local_config(local_cfg)
    if not remote["base_url"]:
        return _local_provider(cfg) if local.get("model_path") else None
    if not str(remote["model"] or "").strip():
        raise ValueError(
            "embedding model 未配置（base_url 已给但 model 为空）："
            "cache_key 会退化为纯文本键，换模型将静默命中旧向量")
    provider = OpenAICompatibleProvider(
        remote["base_url"], str(remote["model"]).strip(), remote["api_key"],
        remote["timeout"], dim=remote["dim"])
    provider.mode = "remote_with_local_fallback"
    if local.get("model_path"):
        local["enabled"] = True
    else:
        local["enabled"] = False
    provider.fallback_config = local
    provider.local_embedder = None
    provider.local_status = "missing"
    if local["enabled"]:
        provider.timeout = local["timeout_s"]
        preload_local_fallback(provider)
    return provider


def load_provider(config=None):
    """Build a provider from dict/env; None when nothing is configured.

    embedding_mode selects one backend (new, default off in _conf_schema.json):
      off                           no vector at all (no network, no local load)
      remote                        any OpenAI-compatible {base_url}/embeddings
      local                         local bge-small-zh-int8 ONNX (embedding_local_*)
      remote_with_local_fallback    remote first, local on failure/timeout/dim

    Old configs without embedding_mode keep the legacy auto behaviour
    (remote when base_url/model exist, else local-only when the old local
    fallback switch and model path are set).

    Remote keys (flat or under "embedding"): embedding_base_url, embedding_model,
    embedding_api_key, embedding_dim; old aliases base_url/api_base/url,
    model, api_key/key and env BIOCORE_EMBEDDING_BASE_URL/_KEY/_MODEL still work.
    Timeout: embedding_timeout_s (or embedding_timeout_ms) / timeout / env.
    """
    cfg = _provider_config(config)
    if cfg.get("enabled") is False:
        return None
    mode = embedding_mode(cfg)
    resolved = resolve_mode(cfg)
    if mode == "auto":
        # task-211: read-only probe already ran; local mode stays lazy.
        if resolved.get("mode") == "remote":
            return _with_mode(_remote_provider(cfg), resolved)
        if resolved.get("mode") == "local":
            return _with_mode(_lazy_local_provider(cfg), resolved)
        return None
    if mode == "off":
        return None
    if mode == "remote":
        return _with_mode(_remote_provider(cfg), resolved)
    if mode == "local":
        return _with_mode(_local_provider(cfg), resolved)
    if mode == "remote_with_local_fallback":
        return _with_mode(_fallback_provider(cfg), resolved)
    if mode:
        # Unknown mode value: same as off (no network, no local model load).
        return None

    # ---- legacy auto mode (no embedding_mode key) ---------------------
    base_url = (cfg.get("base_url") or cfg.get("api_base") or cfg.get("url")
                or os.environ.get(ENV_BASE_URL) or "")
    model = (cfg.get("model") or cfg.get("embedding_model")
             or os.environ.get(ENV_MODEL) or "")
    api_key = (cfg.get("api_key") or cfg.get("key")
               or os.environ.get(ENV_API_KEY) or "")
    timeout = cfg.get("timeout", os.environ.get(ENV_TIMEOUT) or DEFAULT_TIMEOUT)
    local = local_config(cfg)
    if str(base_url).strip() and str(model).strip():
        provider = OpenAICompatibleProvider(base_url, model, api_key, timeout)
        provider.fallback_config = local
        provider.local_embedder = None
        provider.local_status = "missing"
        if local["enabled"]:
            # remote timeout is configurable (default 8s) whenever the local
            # fallback is armed; then probe the optional component at startup.
            provider.timeout = local["timeout_s"]
            preload_local_fallback(provider)
        return _with_mode(provider, resolved)
    if local["enabled"] and local["model_path"]:
        embedder = _load_local_embedder(local)
        if embedder:
            return _with_mode(
                LocalOnlyEmbeddingProvider(embedder, local["timeout_s"]),
                resolved)
    return None


def _call_provider(provider, text, timeout):
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(provider.embed_text, text).result(timeout=timeout)
    except (FutureTimeout, TimeoutError):
        return None
    except Exception:
        return None
    finally:
        executor.shutdown(wait=False)


def embed(text, provider, cache=None, timeout=None, path=None):
    """Return a vector for text, or None.

    Raises ValueError for a provider that does not name its model: that is a
    wiring bug, not a transient failure, and a silent text-only cache key would
    poison every later lookup.


    Both caches are optional: the caller may pass an in-memory LRU, and the
    disk cache lives at path (default: the configured cache file, or none).
    The same text through the same model returns the same vector bit for bit --
    the first call writes it, every later call reads it back unchanged.
    """
    if provider is None:
        return None
    normalized = normalize_text(text)
    if not normalized:
        return None
    model = str(getattr(provider, "model", "") or "").strip()
    if not model and str(getattr(provider, "mode", "") or "") in (
            "remote", "remote_with_local_fallback"):
        # last line of defence for a REMOTE provider: cache_key(text, "") is
        # text-only, so a model swap would answer from the previous model's
        # vectors. A local checkpoint identifies itself by its path instead.
        raise ValueError(
            "embedding provider has no model name; cache_key would degrade to "
            "text-only and a model swap would hit stale vectors")
    key = cache_key(normalized, model)
    cached = _cache_get(cache, key)
    if cached is not None:
        EMBED_STATS["hit"] += 1
        try:  # true LRU when the caller passes an OrderedDict
            cache.move_to_end(key)
        except Exception:
            pass
        return cached
    target = path or configured_cache_file()
    if target and cache_backend(target) == "sqlite":
        from_disk = cache_get_many([key], target).get(key)
        rows = None
    else:
        rows = read_cache(target) if target else {}
        from_disk = rows.get(key)
    if from_disk is not None:
        EMBED_STATS["disk_hit"] += 1
        _cache_put(cache, key, from_disk)
        return from_disk
    EMBED_STATS["miss"] += 1
    checked = _validate_vector(
        _call_provider(provider, normalized, _timeout_for(provider, timeout)))
    if checked is not None:
        EMBED_STATS["remote"] += 1
        _cache_put(cache, key, checked)
        if target:
            if rows is None:
                cache_put(key, checked, target)          # one row, not the file
            else:
                rows.pop(key, None)
                rows[key] = list(checked)
                write_cache(_cache_trim(rows), target)
        return checked
    # Remote failed / timed out / missing key: try the local CPU int8 model.
    local = _fallback_embed(provider, normalized)
    if local is None:
        EMBED_STATS["fail"] += 1
        return None
    EMBED_STATS["local"] += 1
    _cache_put(cache, key, local)
    if target:
        if rows is None:
            cache_put(key, local, target)
        else:
            rows.pop(key, None)
            rows[key] = list(local)
            write_cache(_cache_trim(rows), target)
    return local
