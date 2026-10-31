# -*- coding: utf-8 -*-
"""Perception -> decision -> action -> feedback -> learning loop."""
from __future__ import annotations

RESPONSE_WINDOW_S = 6 * 3600.0
TUNE_EVERY_SEND = 10
TUNE_INTERVAL_S = 86400.0


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


def record_attempt(acc, now, code="", weight=0.0, text_len=0):
    acc = dict(acc or {})
    acc["last_attempt"] = {"ts": round(float(now), 3), "code": str(code or ""),
                           "weight": round(_num(weight), 4), "text_len": int(text_len or 0),
                           "closed": False, "responded": False}
    acc["sent_count"] = int(acc.get("sent_count", 0) or 0) + 1
    return acc


def on_user_reply(acc, now, window_s=RESPONSE_WINDOW_S):
    """Perception: a quick reply after a proactive send counts as responded."""
    acc = dict(acc or {})
    attempt = acc.get("last_attempt") if isinstance(acc.get("last_attempt"), dict) else {}
    if attempt and not attempt.get("closed"):
        age = float(now) - _num(attempt.get("ts"))
        if age <= window_s:
            acc["responded_count"] = int(acc.get("responded_count", 0) or 0) + 1
            acc["last_response_latency_s"] = round(age, 1)
            attempt = dict(attempt, closed=True, responded=True)
            acc["last_attempt"] = attempt
    return acc


def settle(acc, now, window_s=RESPONSE_WINDOW_S):
    """Feedback: an un-answered attempt older than the window is ignored."""
    acc = dict(acc or {})
    attempt = acc.get("last_attempt") if isinstance(acc.get("last_attempt"), dict) else {}
    if attempt and not attempt.get("closed") and (float(now) - _num(attempt.get("ts"))) > window_s:
        acc["ignored_count"] = int(acc.get("ignored_count", 0) or 0) + 1
        acc["last_attempt"] = dict(attempt, closed=True, responded=False)
    return acc


def response_rate(acc):
    responded = int((acc or {}).get("responded_count", 0) or 0)
    ignored = int((acc or {}).get("ignored_count", 0) or 0)
    return round(responded / max(1, responded + ignored), 4)


def per_code_stats(learning, code, responded):
    """EWMA 0.8/0.2 rate per reason code."""
    learning = dict(learning or {})
    per_code = dict(learning.get("per_code") or {})
    row = dict(per_code.get(code) or {"sent": 0, "responded": 0, "rate": 0.5})
    row["sent"] = int(row.get("sent", 0) or 0) + 1
    if responded:
        row["responded"] = int(row.get("responded", 0) or 0) + 1
    target = 1.0 if responded else 0.0
    row["rate"] = round(_clamp(0.8 * _num(row.get("rate"), 0.5) + 0.2 * target, 0.0, 1.0), 4)
    per_code[code] = row
    learning["per_code"] = per_code
    return learning


def tune_weights(learning, weights, now, total_sent=None):
    """Every 10 sends (or daily): w *= clamp(0.95+0.10*rate, 0.85, 1.15), normalize."""
    learning = dict(learning or {})
    current = float(now)
    last = _num(learning.get("last_tune_ts"), 0.0)
    per_code = dict(learning.get("per_code") or {})
    sent = int(total_sent if total_sent is not None else learning.get("sent_at_tune", 0) or 0)
    due = (last <= 0) or ((current - last) >= TUNE_INTERVAL_S) or (sent > 0 and sent % TUNE_EVERY_SEND == 0)
    weights = dict(weights or {})
    if not due or not weights or not per_code:
        learning["last_tune_ts"] = last
        return weights, learning
    codes = [code for code in weights if code in per_code]
    if not codes:
        return weights, learning
    for code in codes:
        rate = _clamp(_num(per_code[code].get("rate"), 0.5), 0.0, 1.0)
        factor = _clamp(0.95 + 0.10 * rate, 0.85, 1.15)
        weights[code] = float(weights.get(code, 0.0)) * factor
    total = sum(float(v) for v in weights.values())
    if total > 0:
        for key in weights:
            weights[key] = round(float(weights[key]) / total, 6)
    learning["last_tune_ts"] = round(current, 3)
    learning["sent_at_tune"] = int(total_sent if total_sent is not None else 0)
    return weights, learning


def loop_view(acc, learning=None):
    acc = acc or {}
    attempt = acc.get("last_attempt") if isinstance(acc.get("last_attempt"), dict) else {}
    per_code = {}
    for code, row in ((learning or {}).get("per_code") or {}).items():
        per_code[code] = {"sent": int(row.get("sent", 0) or 0), "rate": round(_num(row.get("rate")), 3)}
    return {"sent": int(acc.get("sent_count", 0) or 0),
            "responded": int(acc.get("responded_count", 0) or 0),
            "ignored": int(acc.get("ignored_count", 0) or 0),
            "response_rate": response_rate(acc),
            "avg_latency_s": _num(acc.get("last_response_latency_s"), 0.0),
            "last_attempt": {"code": attempt.get("code", ""), "ts": _num(attempt.get("ts"))},
            "per_code": per_code}


def tick_stalled(acc, now, interval_s=300.0):
    last = _num((acc or {}).get("last_tick_ts"), 0.0)
    if last <= 0:
        return False
    return (float(now) - last) > 2.0 * float(interval_s)
