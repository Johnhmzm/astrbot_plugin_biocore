# -*- coding: utf-8 -*-
"""Optional remote cross-encoder rerank (stdlib only, silent degradation).

This module owns *when* to rerank and what the caller gets back. It does not own
*how* a score is produced: the wire protocol, the relevance scale and the
per-model interpretation all live in biocore_memory.recall.providers, behind one
call:

    provider.rank(query, docs, top_k) -> [(index, score)]   # best first

That split is deliberate and greppable: this file must stay free of every
per-model relevance-scale name (the two kind names defined in providers.py must
not appear here at all). A new model is added in providers.py, never here.

Config keys (all optional, defaults shown):
  rerank_enabled  False
  rerank_base_url ""
  rerank_model    ""
  rerank_api_key  ""
  rerank_timeout  8.0 seconds
  rerank_top_n    20
  ... plus whatever the provider needs; unknown rerank_* keys are passed through
      untouched, so a new model is a config change and not a code change.

A disabled call, missing config, timeout, non-2xx response or an invalid result
list returns None and records a short reason; callers keep the original
ordering. Only stdlib urllib is used.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULTS = {
    "rerank_enabled": False,
    "rerank_base_url": "",
    "rerank_model": "",
    "rerank_api_key": "",
    "rerank_timeout": 8.0,
    "rerank_top_n": 20,
}


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


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


def normalize_config(config=None):
    """Merge caller config with defaults and clamp timeout/top_n."""
    data = config if isinstance(config, dict) else {}
    out = dict(DEFAULTS)
    out["rerank_enabled"] = _as_bool(data.get("rerank_enabled"), False)
    for key in ("rerank_base_url", "rerank_model", "rerank_api_key"):
        out[key] = str(data.get(key) or "").strip()
    timeout = _num(data.get("rerank_timeout"), DEFAULTS["rerank_timeout"])
    out["rerank_timeout"] = max(0.1, min(60.0, timeout))
    top_n = int(_num(data.get("rerank_top_n"), DEFAULTS["rerank_top_n"]))
    out["rerank_top_n"] = max(1, min(1000, top_n))
    return out


def _document_text(item):
    if isinstance(item, dict):
        return str(item.get("text") or item.get("document") or "").strip()
    return str(item or "").strip()


def _urllib_transport(url, payload, timeout, headers):
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200) or 200)
        body = response.read()
    return status, body


def _notify(callback, reason):
    try:
        logger.info("[rerank] fallback: %s", reason)
    except Exception:
        pass
    if callable(callback):
        try:
            callback(reason)
        except Exception:
            pass


def _provider_config(cfg, raw):
    """Normalized keys plus every caller key that belongs to the provider.

    Nothing is enumerated here on purpose: a provider key this module has never
    heard of still reaches the adapter, which is what makes a new model a
    configuration change.
    """
    out = dict(cfg)
    source = raw if isinstance(raw, dict) else {}
    for key, value in source.items():
        out[str(key)] = value
    return out


def rerank_documents(query, documents, config=None, transport=None,
                     on_reason=None):
    """Return [{index, document, relevance_score}] sorted/truncated, or None."""
    from biocore_memory.recall import providers as _providers

    cfg = normalize_config(config)
    if not cfg["rerank_enabled"]:
        _notify(on_reason, "disabled")
        return None
    if not cfg["rerank_base_url"] or not cfg["rerank_model"]:
        _notify(on_reason, "missing_config")
        return None
    text = str(query or "").strip()
    if not text:
        _notify(on_reason, "empty_query")
        return None
    text_docs = []
    for index, item in enumerate(documents or []):
        content = _document_text(item)
        if content:
            text_docs.append((index, content))
    if not text_docs:
        _notify(on_reason, "empty_documents")
        return None
    top_n = min(cfg["rerank_top_n"], len(text_docs))
    provider = _providers.RerankProvider(
        _provider_config(cfg, config), transport=transport or _urllib_transport)
    try:
        ranked = provider.rank(text, [content for _index, content in text_docs],
                               top_k=top_n)
    except _providers.ProviderError as error:
        _notify(on_reason, getattr(error, "reason", "provider_error"))
        return None
    out = []
    by_index = dict(text_docs)
    for index, score in ranked:
        if index not in by_index:
            continue
        out.append({"index": index, "document": by_index[index],
                    "relevance_score": round(float(score), 6)})
    if not out:
        _notify(on_reason, "empty_results")
        return None
    return out[:top_n]
