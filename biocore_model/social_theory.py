# -*- coding: utf-8 -*-
"""Self-disclosure, question back-passing, theory of mind (GAP-E)."""
from __future__ import annotations

import random

SELF_TEMPLATES = (
    "今天吃到一块好吃的苹果派",
    "下班路上下了点小雨",
    "被同事夸了一句，心情不错",
    "押运任务比平时顺利",
    "路过一家没去过的小店",
    "下午有点困，泡了杯茶",
    "看到一只很胖的猫",
)
QUESTION_TYPES = {
    "state": ("你今天累不累？", "今天状态怎么样？"),
    "event": ("那个事后来怎么样了？", "上次说的那件事有进展吗？"),
    "preference": ("你更喜欢哪个？", "这两种你更偏好哪种？"),
}
MOOD_WORDS = ("开心", "高兴", "累", "烦", "难过", "焦虑", "无聊", "生气", "委屈", "紧张")


def daily_self_life(seed, now, energy=0.7, valence=0.0, count=None):
    """Deterministic self-life events for the day (1-3 events)."""
    rng = random.Random(str(seed))
    if count is None:
        count = rng.randint(1, 3)
    events = []
    for index in range(max(1, min(3, int(count)))):
        template = rng.choice(SELF_TEMPLATES)
        mood = "心情不错" if valence >= 0 else "有点低落"
        events.append({"id": "self:%s:%d" % (seed, index), "owner": "self",
                       "text": template, "ts": float(now) + index,
                       "energy": round(float(energy), 2), "mood": mood})
    return events


def share_probability(responsiveness):
    return round(max(0.0, min(1.0, 0.3 + 0.5 * float(responsiveness or 0.0))), 3)


def share_line(event, responsiveness, rng=None):
    r = rng or random.Random(str((event or {}).get("id", "")))
    if r.random() >= share_probability(responsiveness):
        return ""
    return "今天碰到个事，跟你说——" + str((event or {}).get("text") or "")


def question_probability(responsiveness):
    return round(max(0.0, min(1.0, 0.25 + 0.2 * float(responsiveness or 0.0))), 3)


def pick_question(responsiveness, recent_types=None, rng=None):
    r = rng or random.Random(42)
    if r.random() >= question_probability(responsiveness):
        return None
    recent = list(recent_types or [])[-3:]
    options = [kind for kind in QUESTION_TYPES if kind not in recent]
    if not options:
        options = list(QUESTION_TYPES)
    kind = r.choice(options)
    return {"type": kind, "text": r.choice(QUESTION_TYPES[kind])}


def infer_user_model(recent_messages, now=None):
    """Heuristics: short+slow -> busy, mood words -> mood_hint, follow-ups -> engagement."""
    messages = list(recent_messages or [])
    model = {"mood_hint": "unknown", "busy_hint": "unknown", "last_topic": "", "engagement": 0.5}
    if not messages:
        return model
    short = slow = 0
    mood_hits = 0
    questions = 0
    for item in messages[-5:]:
        text = str((item or {}).get("text") or "")
        delay = float((item or {}).get("delay_s", 0) or 0)
        if len(text) <= 8:
            short += 1
        if delay >= 600:
            slow += 1
        if any(word in text for word in MOOD_WORDS):
            mood_hits += 1
        if "?" in text or "？" in text:
            questions += 1
        if text.strip():
            model["last_topic"] = text.strip()[:20]
    if short >= 2 and slow >= 1:
        model["busy_hint"] = "busy"
    elif short + slow == 0:
        model["busy_hint"] = "free"
    if mood_hits:
        model["mood_hint"] = "low" if any(word in str((messages[-1] or {}).get("text") or "") for word in ("累", "烦", "难过", "焦虑")) else "good"
    model["engagement"] = round(min(1.0, 0.4 + 0.15 * len(messages) + 0.1 * questions), 3)
    return model


def prompt_line(self_life=None, user_model=None):
    parts = []
    events = self_life or []
    if events:
        parts.append("她今天：" + str(events[0].get("text") or ""))
    guess = user_model or {}
    if guess.get("busy_hint") == "busy":
        parts.append("她猜你现在有点忙")
    elif guess.get("mood_hint") == "low":
        parts.append("她猜你心情一般")
    return "；".join(parts)
