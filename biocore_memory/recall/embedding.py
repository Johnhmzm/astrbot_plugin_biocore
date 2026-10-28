# -*- coding: utf-8 -*-
"""Optional embedding provider for recall (stdlib only; no astrbot import).

Embeddings are OPTIONAL: load_provider() returns None unless a base URL and
model are configured (dict or BIOCORE_EMBEDDING_* env). embed() normalizes text,
uses a hash-keyed LRU (<=512), and returns None on timeout/error so recall
degrades to lexical instead of failing. urllib + stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import List, Optional, Protocol, runtime_checkable
EMBED_CACHE_MAX = 512
EMBED_TEXT_MAX_CHARS = 2000
DEFAULT_TIMEOUT, MIN_TIMEOUT, MAX_TIMEOUT = 5.0, 0.1, 60.0
ENV_BASE_URL = "BIOCORE_EMBEDDING_BASE_URL"
ENV_API_KEY, ENV_MODEL = "BIOCORE_EMBEDDING_KEY", "BIOCORE_EMBEDDING_MODEL"
ENV_TIMEOUT = "BIOCORE_EMBEDDING_TIMEOUT"


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


def cache_key(text) -> str:
    """Stable hash key for the normalized text."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:32]


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


class OpenAICompatibleProvider:
    """POST {base_url}/embeddings with the OpenAI-compatible JSON shape."""

    def __init__(self, base_url, model, api_key="", timeout=DEFAULT_TIMEOUT):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout = max(MIN_TIMEOUT, min(MAX_TIMEOUT,
                                           _as_float(timeout, DEFAULT_TIMEOUT)))

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
        return checked


OpenAIProvider = OpenAICompatibleProvider


def _provider_config(config) -> dict:
    merged = {}
    if isinstance(config, dict):
        merged.update({k: v for k, v in config.items() if not isinstance(v, dict)})
        for key in ("embedding", "embeddings", "provider"):
            nested = config.get(key)
            if isinstance(nested, dict):
                merged.update(nested)
    return merged


def load_provider(config=None):
    """Build a provider from dict/env; None when not configured.

    Keys (flat or under "embedding"): base_url/api_base/url, api_key/key,
    model/embedding_model, timeout. Env: BIOCORE_EMBEDDING_BASE_URL/_KEY/_MODEL.
    """
    cfg = _provider_config(config)
    if cfg.get("enabled") is False:
        return None
    base_url = (cfg.get("base_url") or cfg.get("api_base") or cfg.get("url")
                or os.environ.get(ENV_BASE_URL) or "")
    model = (cfg.get("model") or cfg.get("embedding_model")
             or os.environ.get(ENV_MODEL) or "")
    api_key = (cfg.get("api_key") or cfg.get("key")
               or os.environ.get(ENV_API_KEY) or "")
    timeout = cfg.get("timeout", os.environ.get(ENV_TIMEOUT) or DEFAULT_TIMEOUT)
    if not str(base_url).strip() or not str(model).strip():
        return None
    return OpenAICompatibleProvider(base_url, model, api_key, timeout)


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


def embed(text, provider, cache=None, timeout=None):
    """Return a vector for text, or None (never raises); LRU cache optional."""
    if provider is None:
        return None
    normalized = normalize_text(text)
    if not normalized:
        return None
    key = cache_key(normalized)
    cached = _cache_get(cache, key)
    if cached is not None:
        try:  # true LRU when the caller passes an OrderedDict
            cache.move_to_end(key)
        except Exception:
            pass
        return cached
    checked = _validate_vector(
        _call_provider(provider, normalized, _timeout_for(provider, timeout)))
    if checked is None:
        return None
    _cache_put(cache, key, checked)
    return checked
