# -*- coding: utf-8 -*-
"""Gratitude, boundaries, empathy channels, conversational repair, time sense."""
from __future__ import annotations


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def gratitude_event(current=0.0, kindness=False):
    try:
        value = clamp(current)
    except Exception:
        value = 0.0
    if kindness:
        value = clamp(value + 0.15)
    return round(value, 4)


def gratitude_message(events, gratitude):
    """find-remind-bind: reference a real user event when grateful."""
    if float(gratitude or 0.0) < 0.5:
        return ""
    for event in events or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("owner") or "") == "user" and float(event.get("valence", 0.0) or 0.0) > 0:
            text = str(event.get("text") or event.get("title") or "")[:30]
            if text:
                return "想起上次你%s，谢了——今天还好吗？" % text
    return ""


def boundaries(stage="stranger", trust=0.5, blocked=None):
    depth = {"stranger": 0.2, "acquaintance": 0.4, "friend": 0.65, "close": 0.85}.get(stage, 0.2)
    depth = clamp(depth * 0.7 + 0.3 * clamp(trust))
    return {"topics_blocked": list(blocked or []), "disclosure_depth": round(depth, 3)}


def boundary_reply(topic, blocked_topics):
    if str(topic) in (blocked_topics or []):
        return "这个先不说。"
    return ""


def empathy(own_valence, user_mood="unknown", cognitive_accuracy=0.5):
    own = float(own_valence or 0.0)
    affective = clamp(abs(own))
    cognitive = clamp(cognitive_accuracy)
    if affective >= 0.5 and cognitive >= 0.5:
        mode = "comfort"
    elif cognitive >= 0.5:
        mode = "reason"
    elif affective >= 0.5:
        mode = "resonance"
    else:
        mode = "cold"
    return {"affective": round(affective, 3), "cognitive": round(cognitive, 3), "mode": mode,
            "valence_shift": round(own * 0.3, 4)}


def repair_check(user_text, previous_reply="", clarify_failures=0):
    text = str(user_text or "")
    confusion = any(word in text for word in ("你说什么", "没懂", "没听懂", "？", "?"))
    if not confusion or len(str(previous_reply or "")) < 12:
        return {"needed": False, "text": ""}
    if clarify_failures >= 2:
        return {"needed": True, "text": "我简单点说："}
    guess = str(previous_reply or "").strip()[:16]
    return {"needed": True, "text": "你是说「%s」？" % guess}


def time_gap_text(hours):
    try:
        h = max(0.0, float(hours))
    except Exception:
        h = 0.0
    if h < 1:
        return "刚刚"
    if h < 6:
        return "几小时前"
    if h < 24:
        return "大半天"
    if h < 72:
        return "两天多"
    if h < 24 * 7:
        return "好几天前"
    return "一周前"


def future_text(days):
    try:
        value = float(days)
    except Exception:
        value = 0.0
    if value <= 0:
        return "已经过了"
    if value < 1:
        return "还有几小时"
    return "还有 %d 天" % int(round(value))


def memory_time_label(hours_ago):
    label = time_gap_text(hours_ago)
    return "你说过（%s）：" % label


def view(gratitude=0.0, bounds=None, empathy_info=None, repair=None, time_sense=None):
    return {"gratitude": round(float(gratitude or 0.0), 3), "boundaries": dict(bounds or {}),
            "empathy": dict(empathy_info or {}), "repair": dict(repair or {}),
            "time_sense": dict(time_sense or {})}
