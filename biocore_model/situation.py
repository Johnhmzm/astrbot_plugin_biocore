# -*- coding: utf-8 -*-
"""Deterministic situation summary for the reply prompt (no LLM, no IO).

Answers "现在是什么局面" from the last few turns plus affect and relationship,
in at most three Chinese lines. main.py renders it ahead of the chat history;
the text is never parsed back, so wording changes are safe.

item-2: semantic intent (challenge / praise / hurt) arrives from the model
probe as three bounded numbers; this module never scans words. Every other
signal is numeric too (history roles/timestamps, relationship state).
"""
from __future__ import annotations

MAX_LINES = 3
MAX_CHARS = 200
WINDOW = 6
SILENCE_SECONDS = 6 * 3600.0
UNANSWERED_MIN = 2
TENSION_CONFLICT = 0.45
TENSION_TRUST = 0.35
COLD_STAGES = ("tense", "distant", "cold", "cold_war", "estranged")
SITUATION_KEYS = ("challenge", "praise", "hurt")
SITUATION_THRESHOLD = 0.5
USER_ROLES = ("user", "human")
SELF_ROLES = ("assistant", "bot", "ai", "self")


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _text_of(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("content", "text", "message", "msg"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if isinstance(item, (list, tuple)):
        # (role, text) pairs and provider-style content part lists
        for part in item:
            value = _text_of(part)
            if value:
                return value
    return ""


def _role_of(item):
    if isinstance(item, dict):
        return str(item.get("role") or item.get("sender") or "").strip().lower()
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return str(item[0]).strip().lower()
    return ""


def _ts_of(item):
    if isinstance(item, dict):
        for key in ("ts", "timestamp", "time"):
            if key in item:
                return _num(item.get(key))
    return 0.0


def _rows(history, limit=WINDOW):
    rows = []
    if not isinstance(history, (list, tuple)):
        return rows
    for item in list(history)[-max(1, int(limit)):]:
        text = _text_of(item)
        if not text:
            continue
        rows.append((_role_of(item), text, _ts_of(item)))
    return rows


def _last_user_text(rows):
    for role, text, _ts in reversed(rows):
        if role in USER_ROLES:
            return text
    return ""


def _assistant_after_last_user(rows):
    count = 0
    for role, _text, _ts in reversed(rows):
        if role in USER_ROLES:
            break
        if role in SELF_ROLES:
            count += 1
    return count


def situation_values(situation):
    """Normalise the probe payload to three bounded numbers in 0..1."""
    raw = situation if isinstance(situation, dict) else {}
    values = {}
    for key in SITUATION_KEYS:
        number = _num(raw.get(key))
        values[key] = min(1.0, max(0.0, number))
    return values


def _tone_suffix(core_state):
    state = core_state if isinstance(core_state, dict) else {}
    labels = state.get("labels") if isinstance(state.get("labels"), dict) else {}
    emotion = str(labels.get("emotion") or "").lower()
    valence = _num(state.get("v", state.get("valence", 0.0)))
    stress = _num(state.get("stress", 0.0))
    if (emotion in ("anger", "annoyance", "irritation", "frustration", "sadness")
            or valence <= -0.35 or stress >= 0.6):
        return "，语气不满"
    return ""


def _situation_line(last_user, core_state, situation):
    values = situation_values(situation)
    if values["challenge"] >= SITUATION_THRESHOLD:
        return "局面：对方在质问你" + _tone_suffix(core_state) + "。"
    if values["hurt"] >= SITUATION_THRESHOLD:
        return "局面：对方带着火气，话里有情绪。"
    if values["praise"] >= SITUATION_THRESHOLD:
        return "局面：对方在夸你，气氛不错。"
    state = core_state if isinstance(core_state, dict) else {}
    if (_num(state.get("stress", 0.0)) >= 0.6
            or _num(state.get("intensity", 0.0)) >= 0.8):
        return "局面：气氛偏紧，对方情绪有起伏。"
    return "局面：日常闲聊，没有明显冲突。"


def _topic_of(text):
    cleaned = "".join(ch if ch.isprintable() else " " for ch in str(text or ""))
    cleaned = " ".join(cleaned.split()).strip("，,。.！!？?、~ ")
    if not cleaned:
        return ""
    return cleaned[:18] + ("…" if len(cleaned) > 18 else "")


def _gap_text(seconds):
    seconds = max(0.0, _num(seconds))
    if seconds >= 86400.0:
        return "%.0f 天" % (seconds / 86400.0)
    if seconds >= 3600.0:
        return "%.0f 小时" % (seconds / 3600.0)
    return "%.0f 分钟" % max(1.0, seconds / 60.0)


def _last_activity_ts(rows, events):
    for _role, _text, ts in reversed(rows):
        if ts > 0:
            return ts
    if isinstance(events, (list, tuple)):
        for item in reversed(list(events)):
            ts = _ts_of(item)
            if ts > 0:
                return ts
    return 0.0


def _behaviour_line(rows, events, now):
    unanswered = _assistant_after_last_user(rows)
    if unanswered >= UNANSWERED_MIN:
        return "你刚主动发了 %d 条，对方还没回。" % unanswered
    now_ts = _num(now)
    last_ts = _last_activity_ts(rows, events)
    if now_ts > 0 and last_ts > 0:
        gap = now_ts - last_ts
        if gap >= SILENCE_SECONDS:
            return "已经 %s没说话，对方才回来。" % _gap_text(gap)
    last_user = _last_user_text(rows)
    topic = _topic_of(last_user)
    if topic:
        return "最近话题：%s。" % topic
    return ""


def _pick(mapping, key, default=0.0):
    if isinstance(mapping, dict) and key in mapping:
        return _num(mapping.get(key), default)
    return default


def _relationship_line(relationship):
    rel = relationship if isinstance(relationship, dict) else {}
    state = rel.get("state") if isinstance(rel.get("state"), dict) else rel
    conflict = _pick(state, "conflict", _pick(rel, "conflict", 0.0))
    wary = _pick(state, "wary", conflict)
    trust = _pick(state, "trust", _pick(rel, "trust", 0.5))
    stage = str(state.get("stage") or rel.get("stage") or "").strip().lower()
    repair = rel.get("repair_state") if isinstance(rel.get("repair_state"), dict) else {}
    phase = str(repair.get("phase") or "").strip().lower()
    tense = (conflict >= TENSION_CONFLICT or wary >= TENSION_CONFLICT
             or trust <= TENSION_TRUST or stage in COLD_STAGES
             or (phase and phase != "stable"))
    if tense:
        return "关系：有点紧张，信任%s。" % ("偏低" if trust <= TENSION_TRUST else "中等")
    closeness = _pick(state, "closeness",
                      _pick(state, "affection", _pick(rel, "closeness", 0.5)))
    if closeness >= 0.65:
        near = "亲近"
    elif closeness >= 0.35:
        near = "一般"
    else:
        near = "疏远"
    if trust >= 0.65:
        trust_label = "高"
    elif trust >= 0.35:
        trust_label = "中等"
    else:
        trust_label = "偏低"
    return "关系：%s，信任%s。" % (near, trust_label)


def summarize(history=None, core_state=None, relationship=None, events=None,
              now=None, situation=None) -> str:
    """Return at most three lines describing the current situation.

    Args:
        history: recent turns, each a dict (role/content or role/text) or a
            string or a (role, text) pair; the last WINDOW entries are used.
        core_state: dict-like affect snapshot (v/valence, stress, intensity,
            labels.emotion); missing fields are tolerated.
        relationship: flat relationship dict, or one nested under its
            "state" key: trust / conflict / wary / closeness / affection /
            stage / repair_state.phase.
        events: optional recent events (dicts carrying a ts), used only as a
            fallback clock for silence detection.
        now: current unix timestamp; silence is skipped when missing.
        situation: probe payload with challenge / praise / hurt in 0..1
            (semantic intent strength; absent values count as 0).

    Returns:
        Plain text of up to three lines, or an empty string when there is
        nothing to summarize.
    """
    rows = _rows(history)
    if not rows and not (isinstance(events, (list, tuple)) and len(events) > 0):
        return ""
    last_user = _last_user_text(rows)
    lines = [_situation_line(last_user, core_state, situation)]
    behaviour = _behaviour_line(rows, events, now)
    if behaviour:
        lines.append(behaviour)
    relationship_line = _relationship_line(relationship)
    if relationship_line:
        lines.append(relationship_line)
    text = "\n".join(line.strip() for line in lines[:MAX_LINES] if str(line).strip()).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip()
    return text
