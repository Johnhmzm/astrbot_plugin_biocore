# -*- coding: utf-8 -*-
"""Autonomy readiness diagnostics (read-only; never sends)."""
from __future__ import annotations

FIELDS = ("ready", "impulse", "impulse_ema", "threshold", "max_chars", "drive",
          "parts", "gate", "no_response_count", "sent", "sent_count", "sent_day",
          "last_sent_ts", "block_reason")


def snapshot(state) -> dict:
    src = state if isinstance(state, dict) else {}
    return {key: src.get(key) for key in FIELDS if key in src}


def reason(state, private=True, session=True, now=None) -> str:
    if not private:
        return "not_private"
    if not session:
        return "no_session"
    src = state if isinstance(state, dict) else {}
    if not src.get("enabled", True) or not src.get("ready"):
        return "not_ready"
    try:
        threshold = float(src.get("threshold", 0.6) or 0.6)
        impulse = float(src.get("impulse", 0.0) or 0.0)
    except Exception:
        threshold, impulse = 0.6, 0.0
    if impulse < threshold:
        return "not_ready"
    import time
    current = float(now if now is not None else time.time())
    hour = time.localtime(current).tm_hour
    try:
        from . import main as _main  # noqa: F401  (constants live in main)
    except Exception:
        pass
    quiet_start = globals().get("QUIET_START", 23)
    quiet_end = globals().get("QUIET_END", 8)
    if quiet_start <= hour < quiet_end:
        return "quiet_hours"
    last_ts = float(src.get("last_sent_ts", 0.0) or 0.0)
    cooldown = float(src.get("cooldown_seconds", 0) or 0)
    if last_ts > 0 and cooldown and (current - last_ts) < cooldown:
        return "cooldown"
    day = time.strftime("%Y-%m-%d", time.localtime(current))
    sent_count = int(src.get("sent_count", 0) or 0)
    if str(src.get("sent_day") or "") != day:
        sent_count = 0
    cap = int(src.get("daily_cap", 0) or 0)
    if cap and sent_count >= cap:
        return "daily_cap"
    return "ready"


CHINESE = {
    "ready": "可发送",
    "not_ready": "未达阈值",
    "cooldown": "冷却中",
    "daily_cap": "今日已达上限",
    "quiet_hours": "静默时段",
    "no_session": "无可用会话",
    "not_private": "非私聊会话",
}


def reason_text(code) -> str:
    return CHINESE.get(str(code or ""), str(code or "—"))
