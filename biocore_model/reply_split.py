# -*- coding: utf-8 -*-
"""BioCore-owned reply splitting (does not touch AstrBot segmented_reply)."""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULTS = {
    "enabled": False,
    "mode": "astrbot",
    "words": ["。", "？", "！", "~", "…"],
    "max_chars": 400,
    "min_chars": 12,
    "inject_newlines": True,
}
MODES = ("astrbot", "punct", "newline", "words")
MAX_SEGMENTS = 6


def _cfg(cfg) -> dict:
    data = dict(DEFAULTS)
    if isinstance(cfg, dict):
        for key in DEFAULTS:
            if cfg.get(key) is not None:
                data[key] = cfg[key]
    if data["mode"] not in MODES:
        data["mode"] = "astrbot"
    try:
        data["max_chars"] = int(data["max_chars"])
    except Exception:
        data["max_chars"] = 400
    try:
        data["min_chars"] = int(data["min_chars"])
    except Exception:
        data["min_chars"] = 12
    if not isinstance(data["words"], list) or not data["words"]:
        data["words"] = list(DEFAULTS["words"])
    return data


def _raw_split(text: str, cfg: dict) -> list:
    mode = cfg["mode"]
    if mode == "newline":
        return [line for line in text.split("\n") if line.strip()]
    pieces, buf = [], ""
    words = [str(w) for w in cfg["words"] if str(w)]
    for ch in text:
        buf += ch
        if any(buf.endswith(w) for w in words):
            pieces.append(buf); buf = ""
    if buf.strip():
        pieces.append(buf)
    return [piece for piece in pieces if piece.strip()]


def split_reply(text, cfg=None) -> list:
    body = str(text or "")
    data = _cfg(cfg)
    if not body.strip() or not data["enabled"]:
        return [body] if body else []
    if data["mode"] == "astrbot":
        settings = cfg.get("astrbot") if isinstance(cfg, dict) and isinstance(cfg.get("astrbot"), dict) else read_astrbot_settings(None)
        if data.get("inject_newlines", True):
            return [inject_sentence_newlines(body, settings)]
        return split_astrbot(body, settings)
    if len(body) > data["max_chars"]:
        return [body]
    segments = _raw_split(body, data)
    merged = []
    for segment in segments:
        if merged and len(segment) < data["min_chars"]:
            merged[-1] = merged[-1] + segment
        else:
            merged.append(segment)
    if len(merged) <= 1:
        return [body]
    while len(merged) > MAX_SEGMENTS:
        merged[-2] = merged[-2] + merged[-1]
        merged.pop()
    return merged


def status(plugin) -> dict:
    """Read-only reply_split projection for /page/status."""
    cfg = getattr(plugin, "config", None) or {}
    data = _cfg({"enabled": getattr(plugin, "reply_split_enabled", cfg.get("reply_split_enabled", False)),
                 "mode": getattr(plugin, "reply_split_mode", cfg.get("reply_split_mode", "punct")),
                 "max_chars": getattr(plugin, "reply_split_max_chars", cfg.get("reply_split_max_chars", 400)),
                 "min_chars": getattr(plugin, "reply_split_min_chars", cfg.get("reply_split_min_chars", 12))})
    return {"enabled": bool(data["enabled"]), "mode": data["mode"],
            "max_chars": int(data["max_chars"]), "min_chars": int(data["min_chars"]),
            "effective": effective(plugin), "inject_newlines": True}


def _active_config():
    try:
        from . import reply_limit as _reply_limit
    except Exception:
        from biocore_model import reply_limit as _reply_limit
    return _reply_limit.find_active_config(None)


def read_astrbot_settings(plugin=None) -> dict:
    """platform_settings.segmented_reply from the active AstrBot config."""
    defaults = {"enable": False, "only_llm_result": True, "words_count_threshold": 150,
                "split_mode": "regex", "regex": r"[^\n]+",
                "split_words": ["。", "？", "！", "~", "…"], "content_cleanup_rule": ""}
    try:
        path = _active_config()
        if path is None:
            return defaults
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = ((raw.get("platform_settings") or {}).get("segmented_reply") or {})
        merged = dict(defaults)
        if isinstance(settings, dict):
            merged.update(settings)
        return merged
    except Exception:
        return defaults


def split_astrbot(text: str, settings) -> list:
    """Same algorithm as AstrBot's segmented_reply (regex/words)."""
    body = str(text or "")
    cfg = settings if isinstance(settings, dict) else {}
    if not cfg.get("enable"):
        return [body]
    try:
        threshold = int(cfg.get("words_count_threshold", 150))
    except Exception:
        threshold = 150
    if threshold and len(body) > threshold:
        return [body]
    pieces = []
    if str(cfg.get("split_mode") or "regex") == "words":
        words = [str(w) for w in (cfg.get("split_words") or []) if str(w)]
        buf = ""
        for ch in body:
            buf += ch
            if any(buf.endswith(w) for w in words):
                pieces.append(buf); buf = ""
        if buf.strip():
            pieces.append(buf)
    else:
        pattern = str(cfg.get("regex") or r"[^\n]+")
        try:
            pieces = re.findall(pattern, body, re.DOTALL | re.MULTILINE)
        except Exception:
            pieces = [body]
    cleanup = str(cfg.get("content_cleanup_rule") or "")
    cleaned = []
    for piece in pieces:
        if cleanup:
            try:
                piece = re.sub(cleanup, "", piece)
            except Exception:
                pass
        if str(piece).strip():
            cleaned.append(piece)
    return cleaned if len(cleaned) >= 2 else [body]


def effective(plugin=None) -> dict:
    settings = read_astrbot_settings(plugin)
    mode = str(settings.get("split_mode") or "regex")
    detail = settings.get("regex") if mode == "regex" else settings.get("split_words")
    return {"enable": bool(settings.get("enable")),
            "threshold": int(settings.get("words_count_threshold", 150) or 150),
            "mode": mode, "regex_or_words": detail}


_PUNCT_END = "。！？~…"
_SOFT_BREAK = ("，", "——", "；")
_SOFT_BREAK_MIN = 20


def inject_sentence_newlines(text, settings=None) -> str:
    """Turn sentence boundaries into newlines so AstrBot's own regex split applies."""
    body = str(text or "")
    if not body:
        return body
    cfg = settings if isinstance(settings, dict) else {}
    if not cfg.get("enable"):
        return body
    try:
        threshold = int(cfg.get("words_count_threshold", 150))
    except Exception:
        threshold = 150
    if threshold and len(body) > threshold:
        return body
    out = []
    segment_len = 0
    for index, ch in enumerate(body):
        out.append(ch)
        segment_len += 1
        nxt = body[index + 1] if index + 1 < len(body) else ""
        if ch in _PUNCT_END and nxt and nxt != "\n":
            out.append("\n"); segment_len = 0
        elif segment_len >= _SOFT_BREAK_MIN and any(ch == mark[-1] for mark in _SOFT_BREAK) and nxt and nxt != "\n":
            out.append("\n"); segment_len = 0
    merged = re.sub(r"\n{2,}", "\n", "".join(out)).strip()
    return merged
