# -*- coding: utf-8 -*-
"""HUMAN-6 intent rendering: feeling -> tendency constraint, no raw signals.

Turns an internal action/feeling into one short tendency line for the
interpretation layer. Hard constraints: no digits, no emotion words, no
diagnostic labels -- only a behavioural inclination plus optional tone/guard
fragments that are themselves sanitized.

Literature
  Barrett 2017 (language constrains constructed emotion), Craig 2009
  (interoception precedes words), Seth 2013 (prediction -> action tendency),
  Powers 1973 (perceptual control error becomes action), Carver & Scheier 1998
  (approach/withdraw tendencies), Gross 1998 (regulation strategy phrasing),
  Garfinkel 2015 (sensibility vs accuracy), Sterling 2012 (allostatic action).

Constraints: pure functions, stdlib only, no IO, no main import.
"""
from __future__ import annotations

import re

PHRASES = {
    "approach": "想靠近一点",
    "share": "想和你说说话",
    "question": "想先问清楚",
    "withdraw": "想先退开一点",
    "repair": "想把气氛缓一缓",
    "rest": "想安静一会儿",
}
FALLBACK = "想待一会儿"
FORBIDDEN_EMOTION_WORDS = (
    "开心", "高兴", "快乐", "难过", "伤心", "悲伤", "生气", "愤怒", "恼火",
    "害怕", "恐惧", "焦虑", "紧张", "孤独", "寂寞", "压力", "情绪", "心情",
    "抑郁", "烦躁", "崩溃", "委屈", "内疚", "羞耻",
)
DIGIT_RE = re.compile(r"[0-9０-９]+")
PUNCT_RE = re.compile(r"[，,。；;、\s]+")


def _clean_fragment(value):
    text = str(value or "")
    text = DIGIT_RE.sub("", text)
    for word in FORBIDDEN_EMOTION_WORDS:
        text = text.replace(word, "")
    return PUNCT_RE.sub(" ", text).strip(" ，,。；;、")


def check(text):
    """Return {ok, digits, emotion_words} for one candidate line."""
    value = str(text or "")
    digits = DIGIT_RE.findall(value)
    words = [word for word in FORBIDDEN_EMOTION_WORDS if word in value]
    return {"ok": not digits and not words, "digits": digits, "emotion_words": words}


def sanitize(text, fallback=FALLBACK):
    value = _clean_fragment(text)
    if not value:
        value = fallback
    return value


def render(intent, tone=None, guard=None):
    """Render one tendency line: action phrase + optional tone/guard."""
    action = ""
    if isinstance(intent, dict):
        action = str(intent.get("action") or "")
    elif intent:
        action = str(intent)
    phrase = PHRASES.get(action, FALLBACK)
    parts = [phrase]
    tone_text = _clean_fragment(tone)
    if tone_text:
        parts.append(tone_text)
    guard_text = _clean_fragment(guard)
    if guard_text:
        parts.append(guard_text)
    text = "，".join(parts)
    text = sanitize(text)
    result = check(text)
    return text if result["ok"] else sanitize(text)


def tendency(intent):
    """Coarse approach/withdraw label for downstream stages (no words)."""
    action = ""
    if isinstance(intent, dict):
        action = str(intent.get("action") or "")
    return {"approach": "approach", "share": "approach", "question": "approach",
            "repair": "approach", "withdraw": "withdraw", "rest": "withdraw"}.get(
                action, "neutral")
