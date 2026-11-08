# -*- coding: utf-8 -*-
"""Pluggable embedding and rerank providers (stdlib only, no model branches).

The recall layer never asks "which model is this": it asks a provider for
vectors or scores. Everything model-specific lives here, in one of two
adapters, and the only thing that selects behaviour is configuration.

Embedding config keys (all optional; the defaults are one explicit combo):
    provider    "openai"            wire protocol, not a vendor
    base_url    SilikonFlow /v1     remote and local share this adapter
    model       "BAAI/bge-m3"
    key         ""
    dim         1024                never derived from a model name
    normalize   False               True L2-normalises before returning
    batch_size  32

Rerank config keys:
    provider    "openai"
    base_url, model, key
    scoring     "score_array" | "logit_margin"   REQUIRED, never guessed
    top_n       20

Scoring kinds are not interchangeable: a cross-encoder that returns two logits
(P(no), P(yes)) must be read as a margin, not as a 0..1 relevance score. Reading
one as the other silently inverts the order -- that is the bug this module
exists to prevent.
"""
from __future__ import annotations

import json
import math
import socket
import urllib.error
import urllib.request

EMBED_DEFAULTS = {
    "provider": "openai",
    "base_url": "https://api.siliconflow.cn/v1",
    "model": "BAAI/bge-m3",
    "key": "",
    "dim": 1024,
    "normalize": False,
    "batch_size": 32,
    "timeout": 30.0,
}

RERANK_DEFAULTS = {
    "provider": "openai",
    "base_url": "https://api.siliconflow.cn/v1",
    "model": "BAAI/bge-reranker-v2-m3",
    "key": "",
    "scoring": "score_array",
    "top_n": 20,
    "timeout": 8.0,
}

SCORING_KINDS = ("score_array", "logit_margin")


class ProviderError(RuntimeError):
    """Configuration or protocol problem the caller must fix.

    reason is a short, stable string the caller may log or surface; it is the
    only wire detail that escapes this module.
    """

    def __init__(self, message, reason="provider_error"):
        super().__init__(message)
        self.reason = str(reason or "provider_error")


class UnknownScoring(ProviderError):
    """A rerank scoring kind that this module does not implement."""

    def __init__(self, message):
        super().__init__(message, reason="unknown_scoring")


class EmbeddingSpaceMismatch(ProviderError):
    """The stored vectors were produced by another model / dimension.

    Mixing vector spaces is never allowed silently: cosine across two models is
    a number with no meaning, and it looks like a ranking bug for weeks.
    """


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
    return bool(default)


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    return number if math.isfinite(number) else float(default)


def _first(data, keys, default=""):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def resolve_embedding_config(config=None):
    """Merge caller config over the defaults; nothing is inferred from a name."""
    data = config if isinstance(config, dict) else {}
    nested = data.get("embedding") if isinstance(data.get("embedding"), dict) else {}
    merged = dict(EMBED_DEFAULTS)
    for key, value in nested.items():
        merged[key] = value
    for key in ("provider", "base_url", "model", "key", "dim", "normalize",
                "batch_size", "timeout"):
        if key in data and data[key] not in (None, ""):
            merged[key] = data[key]
    out = {
        "provider": str(merged.get("provider") or "openai").strip().lower(),
        "base_url": str(merged.get("base_url") or "").strip().rstrip("/"),
        "model": str(merged.get("model") or "").strip(),
        "key": str(merged.get("key") or ""),
        "dim": int(_num(merged.get("dim"), EMBED_DEFAULTS["dim"])),
        "normalize": _as_bool(merged.get("normalize"), False),
        "batch_size": max(1, min(512, int(_num(merged.get("batch_size"), 32)))),
        "timeout": max(0.1, min(120.0, _num(merged.get("timeout"), 30.0))),
    }
    if out["provider"] != "openai":
        raise ProviderError(
            "unknown embedding provider %r (implemented: openai)" % out["provider"])
    return out


def resolve_rerank_config(config=None):
    """Merge caller config; an unknown scoring kind is an error, not a guess."""
    data = config if isinstance(config, dict) else {}
    nested = data.get("rerank") if isinstance(data.get("rerank"), dict) else {}
    merged = dict(RERANK_DEFAULTS)
    for key, value in nested.items():
        merged[key] = value
    aliases = {"rerank_enabled": "enabled", "rerank_base_url": "base_url",
               "rerank_model": "model", "rerank_api_key": "key",
               "rerank_scoring": "scoring", "rerank_top_n": "top_n",
               "rerank_timeout": "timeout"}
    for key, value in data.items():
        merged[aliases.get(key, key)] = value
    out = {
        "provider": str(merged.get("provider") or "openai").strip().lower(),
        "base_url": str(merged.get("base_url") or "").strip().rstrip("/"),
        "model": str(merged.get("model") or "").strip(),
        "key": str(merged.get("key") or ""),
        "scoring": str(merged.get("scoring") or "").strip().lower(),
        "top_n": max(1, min(1000, int(_num(merged.get("top_n"), 20)))),
        "timeout": max(0.1, min(120.0, _num(merged.get("timeout"), 8.0))),
        "enabled": _as_bool(merged.get("enabled"), False),
    }
    if out["provider"] != "openai":
        raise ProviderError(
            "unknown rerank provider %r (implemented: openai)" % out["provider"])
    if out["scoring"] and out["scoring"] not in SCORING_KINDS:
        raise UnknownScoring(
            "unknown rerank scoring %r (implemented: %s)"
            % (out["scoring"], ", ".join(SCORING_KINDS)))
    return out


def _urllib_transport(url, payload, timeout, headers):
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200) or 200)
        body = response.read()
    return status, body


def _json_body(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _l2(vector):
    norm = math.sqrt(sum(float(x) * float(x) for x in vector)) or 1.0
    return [float(x) / norm for x in vector]


class OpenAICompatEmbeddings:
    """POST {base_url}/embeddings -- the protocol almost every vendor speaks.

    Remote and local differ only by base_url; there is no "local mode" branch.
    """

    mode = "remote"

    def __init__(self, config=None, transport=None):
        self.cfg = resolve_embedding_config(config)
        self.transport = transport or _urllib_transport
        self.model = self.cfg["model"]
        self.dim = self.cfg["dim"]
        self.base_url = self.cfg["base_url"]
        self.api_key = self.cfg["key"]
        self.timeout = self.cfg["timeout"]
        self.batch_size = self.cfg["batch_size"]

    @property
    def endpoint(self):
        base = self.cfg["base_url"]
        if base.endswith("/embeddings"):
            return base
        return base + "/embeddings"

    # -- provider protocol -------------------------------------------------
    def embed(self, texts):
        """texts -> vectors, one batch of rows at a time."""
        rows = [str(text or "") for text in (texts or [])]
        if not rows:
            return []
        out = []
        size = self.cfg["batch_size"]
        for start in range(0, len(rows), size):
            out.extend(self._embed_batch(rows[start:start + size]))
        return out

    def embed_text(self, text):
        """Single-text convenience (the shape the old provider exposed)."""
        vectors = self.embed([text])
        return vectors[0] if vectors else None

    def _embed_batch(self, batch):
        if not self.cfg["base_url"] or not self.cfg["model"]:
            raise ProviderError("embedding base_url/model not configured")
        payload = {"model": self.cfg["model"], "input": batch,
                   "encoding_format": "float"}
        headers = {"Content-Type": "application/json"}
        if self.cfg["key"]:
            headers["Authorization"] = "Bearer " + self.cfg["key"]
        url = self.cfg["base_url"] + "/embeddings"
        try:
            status, body = self.transport(url, payload, self.cfg["timeout"], headers)
        except (TimeoutError, socket.timeout):
            raise ProviderError("embedding request timed out")
        except urllib.error.HTTPError as error:
            raise ProviderError("embedding http_%s" % getattr(error, "code", "error"))
        if not (200 <= int(status or 0) < 300):
            raise ProviderError("embedding http_%s" % status)
        doc = _json_body(body)
        rows = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise ProviderError("embedding response shape: expected %d rows" % len(batch))
        vectors = []
        for row in rows:
            vector = row.get("embedding") if isinstance(row, dict) else row
            if not isinstance(vector, (list, tuple)) or not vector:
                raise ProviderError("embedding row without a vector")
            vector = [float(x) for x in vector]
            if self.cfg["dim"] and len(vector) != self.cfg["dim"]:
                raise ProviderError(
                    "embedding dim mismatch: model %r returned %d, config says %d "
                    "(set dim in the config, or the store must be rebuilt)"
                    % (self.cfg["model"], len(vector), self.cfg["dim"]))
            if self.cfg["normalize"]:
                vector = _l2(vector)
            vectors.append(vector)
        return vectors


class RerankProvider:
    """POST {base_url}/rerank with an explicit scoring kind."""

    def __init__(self, config=None, transport=None):
        self.cfg = resolve_rerank_config(config)
        self.transport = transport or _urllib_transport

    def rank(self, query, docs, top_k=None):
        """Ranked pairs [(index, score)], best first -- the only rerank output.

        Only rows the endpoint actually scored are returned: a document the
        service skipped must not silently become a 0.0 that still ranks.
        """
        pairs = self._pairs(query, docs, top_k=top_k)
        pairs.sort(key=lambda pair: (-pair[1], pair[0]))
        return pairs

    def rerank(self, query, docs, top_k=None):
        """Dense scores aligned to the input docs (0.0 where unscored)."""
        pairs = self._pairs(query, docs, top_k=top_k)
        scores = [0.0 for _ in (docs or [])]
        for index, score in pairs:
            if 0 <= index < len(scores):
                scores[index] = float(score)
        return scores

    def _pairs(self, query, docs, top_k=None):
        texts = []
        for item in docs or []:
            if isinstance(item, dict):
                texts.append(str(item.get("text") or item.get("document") or "").strip())
            else:
                texts.append(str(item or "").strip())
        if not texts:
            return []
        text = str(query or "").strip()
        cfg = self.cfg
        if not text or not cfg["enabled"] or not cfg["base_url"] or not cfg["model"]:
            return []
        if not cfg["scoring"]:
            raise UnknownScoring("rerank scoring is required: set it in providers config")
        top_n = int(top_k or cfg["top_n"])
        payload = {"model": cfg["model"], "query": text, "documents": texts,
                   "top_n": min(max(1, top_n), len(texts))}
        headers = {"Content-Type": "application/json"}
        if cfg["key"]:
            headers["Authorization"] = "Bearer " + cfg["key"]
        urls = [cfg["base_url"] + "/rerank"]
        if not cfg["base_url"].endswith("/v1"):
            urls.append(cfg["base_url"] + "/v1/rerank")
        status, body, last_reason = 0, b"", "http_error"
        for url in urls:
            try:
                status, body = self.transport(url, payload, cfg["timeout"], headers)
            except (TimeoutError, socket.timeout):
                raise ProviderError("rerank request timed out", reason="timeout")
            except urllib.error.HTTPError as error:
                status = int(getattr(error, "code", 0) or 0)
                last_reason = "http_%s" % status
                continue
            except Exception:
                raise ProviderError("rerank request failed", reason="request_failed")
            if 200 <= int(status or 0) < 300:
                break
            last_reason = "http_%s" % status
        else:
            raise ProviderError("rerank http_%s" % status, reason=last_reason)
        if not (200 <= int(status or 0) < 300):
            raise ProviderError("rerank http_%s" % status, reason=last_reason)
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        try:
            doc = json.loads(body or "{}")
        except Exception:
            raise ProviderError("rerank bad json", reason="bad_json")
        if not isinstance(doc, dict):
            raise ProviderError("rerank bad json", reason="bad_json")
        results = doc.get("results")
        if not isinstance(results, list):
            raise ProviderError("rerank response without results", reason="bad_results")
        pairs = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except Exception:
                continue
            if not (0 <= index < len(texts)):
                continue
            try:
                score = float(self._score_of(item))
            except Exception:
                continue
            if not math.isfinite(score):
                continue
            pairs.append((index, score))
        if not pairs:
            raise ProviderError("rerank returned no usable rows", reason="empty_results")
        return pairs
    def _score_of(self, item):
        """The scoring branch lives HERE and nowhere else."""
        kind = self.cfg["scoring"]
        if kind == "score_array":
            for key in ("relevance_score", "score", "similarity"):
                value = item.get(key)
                if value is None:
                    continue
                try:                     # strict: "bad" must be skipped, not 0.0
                    return float(value)
                except Exception:
                    raise ProviderError("score_array result with a non-numeric score",
                                        reason="bad_score")
            raise ProviderError("score_array result without relevance_score",
                                reason="bad_score")
        if kind == "logit_margin":
            margin = self._logit_margin(item)
            if margin is None:
                raise ProviderError("logit_margin result without two logits",
                                    reason="bad_score")
            return margin
        raise UnknownScoring("unknown rerank scoring %r" % kind)

    @staticmethod
    def _logit_margin(item):
        """logit(yes) - logit(no); also accepts a P(yes) probability pair."""
        pairs = []
        logits = item.get("logits")
        if isinstance(logits, (list, tuple)) and len(logits) >= 2:
            pairs = [float(logits[0]), float(logits[1])]
        else:
            yes = item.get("yes_logit", item.get("logit_yes"))
            no = item.get("no_logit", item.get("logit_no"))
            if yes is not None and no is not None:
                pairs = [float(no), float(yes)]
            else:
                scores = item.get("scores")
                if isinstance(scores, (list, tuple)) and len(scores) >= 2:
                    pairs = [float(scores[0]), float(scores[1])]
        if not pairs:
            return None
        no, yes = pairs[0], pairs[1]
        if 0.0 <= no <= 1.0 and 0.0 <= yes <= 1.0 and abs(no + yes - 1.0) < 1e-6:
            # a probability pair: the margin is the log-odds difference
            no = max(1e-9, no)
            yes = max(1e-9, yes)
            return math.log(yes / no)
        return yes - no


def load_embedding_provider(config=None, transport=None):
    """Adapter instance (raises ProviderError on bad config)."""
    return OpenAICompatEmbeddings(config, transport=transport)


def load_rerank_provider(config=None, transport=None):
    return RerankProvider(config, transport=transport)