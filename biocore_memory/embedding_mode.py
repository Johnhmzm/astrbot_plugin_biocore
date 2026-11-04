# -*- coding: utf-8 -*-
"""Embedding backend mode resolution (auto probe; read-only).

task-211: embedding_mode now defaults to "auto" in the plugin schema. The
selection is a pure, read-only probe:

  a) remote keys complete (base_url + model + key) -> remote
  b) else local model file exists and onnxruntime is importable -> local
  c) else -> off (lexical/strength recall only; never an error)

The probe never imports onnxruntime, never creates a session and never loads the
model. The model is loaded lazily on the first real embed (see
recall.embedding._LazyLocalEmbedder).

Explicit values keep working unchanged: off / remote / local /
remote_with_local_fallback. An old config without embedding_mode still uses the
legacy loader path (requested == "legacy").
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

MODES = ("auto", "off", "remote", "local", "remote_with_local_fallback")
REMOTE_KEYS = ("embedding_base_url", "embedding_model", "embedding_api_key")
ENV_BASE_URL = "BIOCORE_EMBEDDING_BASE_URL"
ENV_MODEL = "BIOCORE_EMBEDDING_MODEL"
ENV_API_KEY = "BIOCORE_EMBEDDING_KEY"
ENV_MODE = "BIOCORE_EMBEDDING_MODE"


def _text(value):
    return str(value or "").strip()


def _flatten(config):
    merged = {}
    if isinstance(config, dict):
        merged.update({key: value for key, value in config.items()
                       if not isinstance(value, dict)})
        for key in ("embedding", "embeddings", "provider"):
            nested = config.get(key)
            if isinstance(nested, dict):
                merged.update(nested)
    return merged


def remote_settings(config=None):
    """Remote endpoint keys with the same aliases/env fallbacks as recall."""
    cfg = _flatten(config)
    base_url = (cfg.get("embedding_base_url") or cfg.get("base_url")
                or cfg.get("api_base") or cfg.get("url")
                or cfg.get("embedding_api_base")
                or os.environ.get(ENV_BASE_URL) or "")
    model = (cfg.get("embedding_model") or cfg.get("model")
             or os.environ.get(ENV_MODEL) or "")
    api_key = (cfg.get("embedding_api_key") or cfg.get("api_key")
               or cfg.get("key") or os.environ.get(ENV_API_KEY) or "")
    return {"base_url": _text(base_url), "model": _text(model),
            "api_key": _text(api_key)}


def remote_complete(config=None):
    """True only when base_url, model AND key are all non-empty."""
    settings = remote_settings(config)
    return bool(settings["base_url"] and settings["model"]
                and settings["api_key"]), settings


def local_model_file(model_path):
    """Existing model.onnx path (a directory resolves to <dir>/model.onnx)."""
    raw = _text(model_path)
    if not raw:
        return None
    path = Path(raw)
    if path.is_dir():
        path = path / "model.onnx"
    try:
        return path if path.is_file() else None
    except Exception:
        return None


def onnxruntime_available(find_spec=None):
    """Importability probe only: never imports or initializes onnxruntime."""
    try:
        finder = find_spec if find_spec is not None else importlib.util.find_spec
        return finder("onnxruntime") is not None
    except Exception:
        return False


def resolve_mode(config=None, *, remote_ready=None, model_exists=None,
                 onnx_available=None, find_spec=None):
    """Resolve the effective embedding backend.

    Injectable booleans make the probe testable without a filesystem/runtime.
    Returns {requested, mode, source, reason, remote_ready,
             local_model_exists, local_model_path, onnxruntime_available}.
    """
    cfg = _flatten(config)
    raw = cfg.get("embedding_mode")
    if raw is None:
        raw = os.environ.get(ENV_MODE)
    requested = _text(raw).lower()
    if remote_ready is None:
        remote_ready, _settings = remote_complete(cfg)
    else:
        remote_ready = bool(remote_ready)
        _settings = remote_settings(cfg)
    model_path = _text(cfg.get("embedding_local_model_path"))
    if model_exists is None:
        local_file = local_model_file(model_path)
        local_model_exists = local_file is not None
    else:
        local_model_exists = bool(model_exists)
        local_file = Path(model_path) if model_path else None
    if onnx_available is None:
        onnx_available = onnxruntime_available(find_spec)
    else:
        onnx_available = bool(onnx_available)
    base = {
        "requested": requested or "legacy",
        "remote_ready": bool(remote_ready),
        "local_model_exists": bool(local_model_exists),
        "local_model_path": str(local_file or model_path or ""),
        "onnxruntime_available": bool(onnx_available),
    }
    if not requested:
        base.update({"mode": "", "source": "legacy",
                     "reason": "旧配置未设置 embedding_mode：沿用旧规则"})
        return base
    if requested in ("off", "remote", "local", "remote_with_local_fallback"):
        base.update({"mode": requested, "source": "explicit",
                     "reason": "显式配置 embedding_mode=" + requested})
        return base
    if requested != "auto":
        base.update({"mode": "off", "source": "explicit",
                     "reason": "未知 embedding_mode=" + requested + "：按 off 处理"})
        return base
    if remote_ready:
        base.update({"mode": "remote", "source": "auto",
                     "reason": "auto→remote：远程配置齐全（base_url + model + key）"})
        return base
    if local_model_exists and onnx_available:
        base.update({"mode": "local", "source": "auto",
                     "reason": "auto→local：远程配置不全，但本地模型存在且 onnxruntime 可导入"})
        return base
    if local_model_exists and not onnx_available:
        base.update({"mode": "off", "source": "auto",
                     "reason": "auto→off：本地模型存在但 onnxruntime 不可导入"})
        return base
    base.update({"mode": "off", "source": "auto",
                 "reason": "auto→off：远程配置不全且无本地模型"})
    return base
