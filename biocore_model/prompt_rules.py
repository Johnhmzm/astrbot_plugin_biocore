# -*- coding: utf-8 -*-
"""Deterministic behaviour rules for the system prompt (no LLM, no memory writes).

Rendered from affect / relation / certainty at prompt-build time; 4-6 short lines.
The goal is one LLM call per reply: these rules replace per-turn enhancement calls.
"""
from __future__ import annotations

MAX_RULES_CHARS = 400


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def render_rules(affect=None, relation=None, certainty=0.7, soft_target=0, soft_max=0) -> str:
    """Return 4-6 Chinese rule lines (<= MAX_RULES_CHARS characters)."""
    a = affect if isinstance(affect, dict) else {}
    r = relation if isinstance(relation, dict) else {}
    valence = _num(a.get("valence", a.get("v", 0.0)))
    trust = _num(r.get("trust", a.get("trust", 0.5)))
    conflict = _num(r.get("conflict", a.get("conflict", 0.0)))
    wary = _num(r.get("wary", a.get("wary", conflict)))
    cert = max(0.0, min(1.0, _num(certainty, 0.7)))
    lines = []
    if valence < 0.35:
        lines.append("先接住情绪，再谈事情；句子短一点、语气放软。")
    elif valence > 0.65:
        lines.append("气氛不错，可以更放松地回应，但别过度热闹。")
    else:
        lines.append("语气保持自然平稳，先回应对方在意的事。")
    if cert < 0.5:
        lines.append("不确定时用问句确认，不要编造具体细节。")
    elif cert > 0.8:
        lines.append("信息足够，可以直接回答，不必反复确认。")
    if max(conflict, wary) > 0.45:
        lines.append("先缓和，不急着解释；承认对方感受。")
    if trust >= 0.6 and conflict <= 0.3 and valence >= 0.6:
        lines.append("关系亲近且气氛轻松，可以轻轻开个玩笑，但别抢话。")
    if len(lines) < 4:
        lines.append("先回应对方在意的事，再补充细节。")
    if len(lines) < 4:
        lines.append("不编造未发生的事，拿不准就说不确定。")
    text = "\n".join("- " + line for line in lines[:8])
    return text[:MAX_RULES_CHARS]



def render_length_rule(target=10, max_chars=30):
    """Soft length rule: speak like the group chat (one short message at a time)."""
    def _n(value, default):
        try:
            return int(value)
        except Exception:
            return default
    target = max(1, min(30, _n(target, 10)))
    max_chars = max(1, min(30, _n(max_chars, 30)))
    if target > max_chars:
        target = max_chars
    return ("【说话方式 · 最重要】\n"
            "像在群里回消息那样：一次只说一句，通常 %d 字以内，最多不超过 %d 字。\n"
            "宁可分成多条短句，也不要合并成一大段。\n"
            "需要停顿、转折或换气时用换行；不要用逗号把多个意思硬连。" % (target, max_chars))



def render_speak_style(target=10, max_chars=30):
    """The speak-style paragraph (goes right after the persona prompt)."""
    return render_length_rule(target, max_chars)


def compose_prompt(persona, speak, rest, protocol):
    """Fixed order: persona -> speak style -> rest -> output protocol."""
    parts = []
    if persona:
        parts.append(str(persona).strip())
    if speak:
        parts.append(str(speak).strip())
    if rest:
        parts.append(str(rest).strip())
    if protocol:
        parts.append(str(protocol).strip())
    text = "\n".join(part for part in parts if part)
    if len(text) > 400 and speak:
        keep = str(speak).strip()
        text = (keep + "\n" + str(rest or "").strip())[:400] if persona else text[:400]
    return text
