# -*- coding: utf-8 -*-
"""Optional remote cross-encoder rerank (stdlib only, silent degradation).

Config keys (all optional, defaults shown):
  rerank_enabled  False
  rerank_base_url ""
  rerank_model    ""
  rerank_api_key  ""
  rerank_timeout  8.0 seconds
  rerank_top_n    20

Two common wire protocols are tried automatically:
  POST {base_url}/rerank      {"model", "query", "documents", "top_n"}
  POST {base_url}/v1/rerank   same payload

A disabled call, missing config, timeout, non-2xx response, bad JSON or an
invalid result list returns None and records a short reason; callers keep the
original ordering. Only stdlib urllib is used.
"""
from __future__ import annotations

import json
import logging
import math
import socket
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
    # how the endpoint reports relevance: "score_array" (a 0..1 relevance score,
    # bge-reranker-v2-m3) or "logit_margin" (a (P(no), P(yes)) logit pair,
    # Qwen3-Reranker). Config, never a guess: reading one as the other inverts
    # the order, which is exactly the bug this key exists to prevent.
    "rerank_scoring": "score_array",
}


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    return number if math.isfinite(number) else float(default)


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
    out["rerank_scoring"] = (str(data.get("rerank_scoring")
                                 or DEFAULTS["rerank_scoring"]).strip().lower())
    timeout = _num(data.get("rerank_timeout"), DEFAULTS["rerank_timeout"])
    out["rerank_timeout"] = max(0.1, min(60.0, timeout))
    top_n = int(_num(data.get("rerank_top_n"), DEFAULTS["rerank_top_n"]))
    out["rerank_top_n"] = max(1, min(1000, top_n))
    return out


def score_of(item, scoring):
    """Model-free scoring rules live in the provider module (one definition)."""
    from biocore_memory.recall.providers import RerankProvider

    class _ScoringOnly(RerankProvider):
        """Skip the config/transport setup: only the scoring rule is needed."""

        def __init__(self, kind):
            self.cfg = {"scoring": kind}

    return _ScoringOnly(scoring)._score_of(item)


def _document_text(item):
    if isinstance(item, dict):
        return str(item.get("text") or item.get("document") or "").strip()
    return str(item or "").strip()


def _candidate_urls(base_url):
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return []
    if base.endswith("/rerank"):
        return [base]
    urls = [base + "/rerank"]
    if not base.endswith("/v1"):
        urls.append(base + "/v1/rerank")
    return urls


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


def rerank_documents(query, documents, config=None, transport=None,
                     on_reason=None):
    """Return [{index, document, relevance_score}] sorted/truncated, or None."""
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
    try:
        from biocore_memory.recall.providers import SCORING_KINDS
    except Exception:          # flat checkout (plugin root on sys.path)
        SCORING_KINDS = ("score_array", "logit_margin")
    if cfg["rerank_scoring"] not in SCORING_KINDS:
        _notify(on_reason, "unknown_scoring:" + cfg["rerank_scoring"])
        return None
    top_n = min(cfg["rerank_top_n"], len(text_docs))
    payload = {
        "model": cfg["rerank_model"],
        "query": text,
        "documents": [content for _index, content in text_docs],
        "top_n": top_n,
    }
    headers = {"Content-Type": "application/json"}
    if cfg["rerank_api_key"]:
        headers["Authorization"] = "Bearer " + cfg["rerank_api_key"]
    call = transport or _urllib_transport
    reason = "failed"
    for url in _candidate_urls(cfg["rerank_base_url"]):
        try:
            status, body = call(url, payload, cfg["rerank_timeout"], headers)
        except (TimeoutError, socket.timeout):
            _notify(on_reason, "timeout")
            return None
        except urllib.error.HTTPError as error:
            reason = "http_%s" % getattr(error, "code", "error")
            continue
        except Exception:
            _notify(on_reason, "request_failed")
            return None
        try:
            status = int(status)
        except Exception:
            status = 0
        if status < 200 or status >= 300:
            reason = "http_%s" % status
            continue
        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8", "replace")
            data = json.loads(body)
        except Exception:
            reason = "bad_json"
            continue
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            reason = "bad_results"
            continue
        parsed = []
        by_index = dict(text_docs)
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
                score = score_of(item, cfg["rerank_scoring"])
            except Exception:
                continue
            if index not in by_index or not math.isfinite(float(score)):
                continue
            score = float(score)
            parsed.append({"index": index, "document": by_index[index],
                           "relevance_score": round(score, 6)})
        if not parsed:
            reason = "empty_results"
            continue
        parsed.sort(key=lambda row: (-row["relevance_score"], row["index"]))
        return parsed[:top_n]
    _notify(on_reason, reason)
    return None
