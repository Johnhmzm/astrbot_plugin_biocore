# -*- coding: utf-8 -*-
"""Normalization / hash / time helpers (stdlib only)."""
from __future__ import annotations
import hashlib, re, time


def sha12(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def clamp01(value, default=0.0):
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default


def normalize_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def now_ts(now=None):
    try:
        return float(now if now is not None else time.time())
    except Exception:
        return time.time()
