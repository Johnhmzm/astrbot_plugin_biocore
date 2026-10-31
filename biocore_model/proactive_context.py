# -*- coding: utf-8 -*-
"""Proactive-message context: state block, relationship, gap, event hints, prompt."""
from __future__ import annotations

import time

try:
    from .expr_template import PROMPT_OUTPUT_PROTOCOL
except Exception:  # pragma: no cover - package ships with the plugin
    from biocore_model.expr_template import PROMPT_OUTPUT_PROTOCOL
GAP_BANDS = ((1.0, "刚刚"), (6.0, "几小时前"), (24.0, "大半天"),
             (72.0, "两天多"), (float("inf"), "好几天"))


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def gap_text(hours):
    h = max(0.0, _num(hours))
    for limit, label in GAP_BANDS:
        if h < limit:
            return "距上次对话：%d 小时（%s），期间没有收到对方消息。" % (round(h), label)
    return "距上次对话：已经很久了。"


def attachment_gap_hint(style="secure"):
    if style == "anxious":
        return "久别重逢时先对缺席有轻微抗议（别指责）。"
    if style == "avoidant":
        return "久别重逢时不要提间隔。"
    return "久别重逢时先对缺席温和问候。"


def render_state_block(core, relationship=None):
    labels = getattr(core, "labels", None) or {}
    probs = getattr(core, "spectrum_probs", None) or getattr(core, "emotion_probs", None) or {}
    dominant = str(labels.get("emotion") or "neutral")
    intensity = _num(labels.get("intensity", labels.get("i", 0.0)))
    lines = ["主导情绪：%s（强度 %.2f）" % (dominant, intensity)]
    if isinstance(probs, dict) and probs:
        top = sorted(((str(k), _num(v)) for k, v in probs.items()), key=lambda item: item[1], reverse=True)[:3]
        if top:
            lines.append("情绪谱：" + " / ".join("%s %.2f" % (k, v) for k, v in top))
    parts = []
    for key, label in (("v", "效价"), ("a", "唤醒"), ("d", "支配"),
                       ("social", "社交"), ("stress", "压力"), ("energy", "精力")):
        value = getattr(core, key, None)
        if value is not None:
            parts.append("%s %+.2f" % (label, _num(value)))
    if parts:
        lines.append("维度：" + " · ".join(parts))
    try:
        homeo = getattr(core, "homeostasis", None) or {}
        drives = homeo.get("drives") if isinstance(homeo, dict) else None
        if isinstance(drives, dict) and drives:
            need = max(drives.items(), key=lambda item: _num(item[1]))
            lines.append("需求：%s（缺口 %.2f）" % (need[0], _num(need[1])))
        intero = getattr(core, "interoception", None)
        if isinstance(intero, dict) and intero.get("label"):
            lines.append("内感受：%s" % intero.get("label"))
    except Exception:
        pass
    return "\n".join(lines)


def render_relationship(relationship):
    rel = relationship if isinstance(relationship, dict) else {}
    state = rel.get("state") if isinstance(rel.get("state"), dict) else {}
    attachment = rel.get("attachment") if isinstance(rel.get("attachment"), dict) else {}
    return ("关系：亲近 %.2f · 信任 %.2f · 冲突 %.2f · 依恋安全感 %.2f"
            % (_num(state.get("closeness", 0.5)), _num(state.get("trust", 0.5)),
               _num(state.get("conflict", 0.0)), _num(attachment.get("safe", 0.5))))


def _event_ts(event):
    for key in ("next_date_ts", "due_ts"):
        if event.get(key) is not None:
            return _num(event.get(key))
    raw = event.get("next_date")
    if raw:
        try:
            if isinstance(raw, (int, float)):
                return float(raw)
            text = str(raw)
            if len(text) == 10:
                return time.mktime(time.strptime(text, "%Y-%m-%d"))
            return time.mktime(time.strptime(text[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            return 0.0
    return 0.0


def render_event_hints(events, now):
    current = _num(now, time.time())
    hints = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        title = str(event.get("title") or event.get("text") or "").strip()
        if not title or _num(event.get("importance", 0.5), 0.5) < 0.5:
            continue
        due = _event_ts(event)
        if due and -86400 <= (due - current) <= 2 * 86400:
            day = "今天" if (due - current) < 0.5 * 86400 else ("明天" if (due - current) < 1.5 * 86400 else "后天")
            hints.append("他提过「%s」（%s）" % (title[:20], day))
        elif event.get("unresolved") and (current - _num(event.get("ts", 0))) >= 86400:
            hints.append("上次关于「%s」的话题没收尾" % title[:20])
        if len(hints) >= 2:
            break
    return hints


def l1_extra_lines(hours, events, now=None):
    lines = []
    gap = gap_text(hours)
    if len(gap) <= 40:
        lines.append("【间隔】" + gap)
    hints = render_event_hints(events, now if now is not None else time.time())
    if hints:
        text = "；".join(hints)
        if len(text) <= 40:
            lines.append("【你记得】" + text)
    return lines


def build_proactive_prompt(system_persona, speak_style, state_block, relationship_text,
                           gap, event_hints, reason, total_mult=1.0):
    reason = reason if isinstance(reason, dict) else {}
    user = ["你现在想主动找对方说话。", "【当前情绪】", str(state_block or "—"), "",
            "【关系】" + str(relationship_text or "—"), "【间隔】" + str(gap or "—")]
    hints = event_hints or []
    if hints:
        user += ["【你记得】" + "；".join(hints)]
    user += ["【动机】%s（%s，强度 %.2f）· 综合冲动 ×%.2f"
             % (reason.get("text") or "想说话了", reason.get("code") or "lonely",
                _num(reason.get("weight")), _num(total_mult, 1.0)),
             "【要求】一次一句、约 10 字、最多 30 字、可换行；不要解释动机/不要提触发或限制/不要复述数值；严格按系统里的【输出格式】输出情绪标签。"]
    system = "\n".join(part for part in (str(system_persona or "").strip(),
                                         str(speak_style or "").strip(),
                                         PROMPT_OUTPUT_PROTOCOL) if part)
    return {"system": system, "user": "\n".join(user)}


def tone_lines(self_blame):
    lines = []
    try:
        sb = float(self_blame or 0.0)
    except Exception:
        sb = 0.0
    if sb >= 0.4:
        lines.append('你有点不安，句子更短、语气更轻；不要反复道歉、不要自我贬低。')
    if sb >= 0.6:
        lines.append('允许一次轻微试探（如「是不是我说错话了」），但只一次。')
    return lines
