# -*- coding: utf-8 -*-
"""Gottman bids + Reis & Shaver responsiveness + Rempel trust (GAP-D)."""
from __future__ import annotations

BID_WINDOW_S = 6 * 3600.0
FREQ_MIN = 0.5
FREQ_MAX = 1.3
RESP_WINDOW = 0.4
TRUST_BASE = 0.5


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def record_bid(bids, now, code=""):
    items = list(bids or [])
    items.append({"ts": float(now), "reason_code": str(code or ""), "turned": None})
    return items[-30:]


def settle_bids(bids, now, responded_ts=None, window_s=BID_WINDOW_S):
    items = []
    for bid in bids or []:
        bid = dict(bid or {})
        if bid.get("turned") is None:
            age = float(now) - float(bid.get("ts", 0.0) or 0.0)
            if responded_ts is not None and float(responded_ts) >= float(bid.get("ts", 0.0)) and age <= window_s:
                bid["turned"] = "toward"
            elif age > window_s:
                bid["turned"] = "away"
        items.append(bid)
    return items


def streaks(bids):
    toward = away = 0
    mode = None
    for bid in reversed(list(bids or [])):
        turned = (bid or {}).get("turned")
        if turned not in ("toward", "away"):
            break
        if mode is None:
            mode = turned
        if turned != mode:
            break
        if turned == "away":
            away += 1
        else:
            toward += 1
    return toward, away


def bid_frequency(bids, current=1.0):
    toward, away = streaks(bids)
    value = clamp(current, FREQ_MIN, FREQ_MAX)
    if away >= 3:
        value = clamp(value * 0.7, FREQ_MIN, FREQ_MAX)
    elif toward >= 3:
        value = clamp(value * 1.1, FREQ_MIN, FREQ_MAX)
    return round(value, 4)


def bid_view(bids, frequency=1.0):
    items = list(bids or [])
    toward = sum(1 for bid in items if bid.get("turned") == "toward")
    away = sum(1 for bid in items if bid.get("turned") == "away")
    t_streak, a_streak = streaks(items)
    return {"sent": len(items), "toward": toward, "away": away,
            "streak": {"toward": t_streak, "away": a_streak},
            "frequency": round(float(frequency or 1.0), 4)}


def responsiveness_update(current, responded):
    try:
        value = clamp(current if current is not None else 0.5)
    except Exception:
        value = 0.5
    value += (0.1 * (1.0 - value)) if responded else (-0.1 * value)
    return round(clamp(value), 4)


def gate_cost_adjust(responsiveness):
    value = clamp(responsiveness)
    if value < RESP_WINDOW:
        return 0.05
    if value > 0.7:
        return -0.05
    return 0.0


def disclosure_mult(responsiveness):
    return 0.7 if clamp(responsiveness) < RESP_WINDOW else 1.0


def trust_from_relationship(relationship):
    """ARCH-1: display trust can be derived from the shared relationship state."""
    rel = relationship if isinstance(relationship, dict) else {}
    state = rel.get("state") if isinstance(rel.get("state"), dict) else {}
    base = float(state.get("trust", TRUST_BASE) or TRUST_BASE)
    return {"predictability": round(base, 4), "dependability": round(base, 4),
            "faith": round(base, 4), "overall": round(base, 4)}


def trust_update(trust, regular=False, kept=False, delayed=False, response_rate=0.0):
    """Deprecated: prefer trust_from_relationship; retained for compatibility."""
    data = dict(trust or {"predictability": TRUST_BASE, "dependability": TRUST_BASE, "faith": TRUST_BASE})
    if regular:
        data["predictability"] = clamp(float(data.get("predictability", TRUST_BASE)) + 0.05)
    if kept:
        data["dependability"] = clamp(float(data.get("dependability", TRUST_BASE)) + 0.06)
    if delayed:
        data["dependability"] = clamp(float(data.get("dependability", TRUST_BASE)) - 0.04)
    if response_rate:
        target = clamp(response_rate)
        data["faith"] = clamp(float(data.get("faith", TRUST_BASE)) * 0.9 + target * 0.1)
    for key in ("predictability", "dependability", "faith"):
        data[key] = round(clamp(float(data.get(key, TRUST_BASE))), 4)
    data["overall"] = round(0.4 * data["predictability"] + 0.4 * data["dependability"] + 0.2 * data["faith"], 4)
    return data
