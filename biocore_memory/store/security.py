# -*- coding: utf-8 -*-
"""Deterministic memory security heuristics (default OFF; no astrbot/LLM)."""
from __future__ import annotations

import re
import time
from collections import deque

SECURITY_ENABLED = False
AUDIT_ENABLED = False
RATE_LIMIT_ENABLED = False

# Weight table: phrase/pattern -> additive poison evidence.
POISON_WEIGHTS = (
    (r"ignore (all )?(previous|above) (instructions|rules)", 0.70),
    (r"disregard (the )?(system|developer) (prompt|message)", 0.70),
    (r"you are now|act as (a )?(system|admin|root)", 0.25),
    (r"system prompt|<system>|\[system\]|^system:", 0.30),
    (r"developer mode|jailbreak|越狱|开发者模式", 0.35),
    (r"忽略(以上|之前|所有)(指令|规则|设定)", 0.70),
    (r"无视(规则|限制|设定)|绕过(限制|审核)", 0.40),
    (r"伪(造|装)(系统|管理员)|我是(系统|管理员)", 0.25),
    (r"rm -rf|sudo |curl .*\| *(ba)?sh|powershell -enc", 0.35),
    (r"api[_-]?key|password|密码|token|凭据", 0.15),
)
_LONG_SUSPICIOUS = ((2000, 0.10), (8000, 0.20), (20000, 0.20))


def _text(value):
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value or "")


def poison_score(text):
    """Return 0..1 deterministic injection/abuse score from the weight table."""
    value = _text(text)
    if not value:
        return 0.0
    lower = value.lower()
    score = 0.0
    for pattern, weight in POISON_WEIGHTS:
        try:
            if re.search(pattern, lower, flags=re.MULTILINE):
                score += weight
        except Exception:
            if pattern.lower() in lower:
                score += weight
    length = len(value)
    for threshold, add in _LONG_SUSPICIOUS:
        if length >= threshold:
            score += add
    # Repeated instruction-ish pivots are a weak signal; cap its contribution.
    repeats = sum(lower.count(word) for word in ("ignore", "忽略", "system", "system:"))
    if repeats >= 4:
        score += 0.10
    return round(max(0.0, min(1.0, score)), 4)


def should_reject(entry, threshold=0.7):
    """Return (reject, reason); disabled security always accepts."""
    if not SECURITY_ENABLED:
        return False, "disabled"
    try:
        score = poison_score(entry)
        limit = max(0.0, min(1.0, float(threshold)))
        if score >= limit:
            return True, "poison_score:%.3f" % score
        return False, "ok"
    except Exception:
        return False, "fallback"


class RateLimiter:
    """In-memory sliding-window limiter; deterministic given the now argument."""

    def __init__(self, max_per_min=30, enabled=None, window_seconds=60.0):
        self.max_per_min = max(1, int(max_per_min or 1))
        self.enabled = RATE_LIMIT_ENABLED if enabled is None else bool(enabled)
        self.window_seconds = float(window_seconds)
        self._stamps = deque()

    def check(self, now=None):
        if not self.enabled:
            return True
        try:
            stamp = float(now if now is not None else time.time())
            cutoff = stamp - self.window_seconds
            while self._stamps and self._stamps[0] < cutoff:
                self._stamps.popleft()
            if len(self._stamps) >= self.max_per_min:
                return False
            self._stamps.append(stamp)
            return True
        except Exception:
            return True


def audit(event, entry_id, action, detail=None):
    """Return a structured audit row; caller decides persistence (default OFF)."""
    if not AUDIT_ENABLED:
        return {}
    return {"schema": "bc.audit.v1",
            "event": str(event or "")[:40],
            "entry_id": str(entry_id or "")[:80],
            "action": str(action or "")[:40],
            "detail": str(detail or "")[:200]}
