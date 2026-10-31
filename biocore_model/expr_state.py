# -*- coding: utf-8 -*-
"""EXP-1: render the whole biological state into human Chinese (expression layer).

Pure: no IO, no state writes. Consumes a core snapshot + relationship only.
"""
from __future__ import annotations

FIELD_NAMES = ("valence", "arousal", "dominance", "social", "stress", "energy",
               "self_esteem", "sleep_debt", "closeness", "trust", "conflict",
               "spectrum_probs", "locus", "stability")


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def adverb(value):
    v = abs(_num(value))
    if v >= 0.8:
        return "很"
    if v >= 0.6:
        return "有点"
    if v >= 0.4:
        return "略"
    if v < 0.2:
        return "几乎不"
    return ""


def _labels(core):
    labels = core.get("labels") if isinstance(core.get("labels"), dict) else {}
    emotion = str(labels.get("emotion") or core.get("emotion") or "")
    intensity = labels.get("intensity", labels.get("i"))
    if intensity is None:
        probs = core.get("spectrum_probs") if isinstance(core.get("spectrum_probs"), dict) else {}
        intensity = max((_num(p) for p in probs.values()), default=None)
    return emotion, intensity


def _section_emotion(core):
    emotion, intensity = _labels(core)
    if not emotion:
        return ""
    if intensity is None:
        return "情绪：%s" % emotion
    return "现在多半是%s，%s" % (emotion, adverb(intensity))


def _section_spectrum(core):
    probs = core.get("spectrum_probs") if isinstance(core.get("spectrum_probs"), dict) else {}
    top = sorted((str(k), _num(v)) for k, v in probs.items())[:0]
    top = sorted(((str(k), _num(v)) for k, v in probs.items()), key=lambda kv: kv[1], reverse=True)[:3]
    if not top:
        return ""
    return "情绪还挺杂：" + "、".join("%s %s" % (k, adverb(v)) for k, v in top)


def _section_dimensions(core):
    pairs = []
    for key, label in (("v", "心情"), ("a", "精神"), ("d", "掌控"),
                       ("social", "社交"), ("stress", "压力"), ("energy", "精力")):
        if core.get(key) is not None:
            value = _num(core.get(key))
            pairs.append("%s%s" % (label, adverb(abs(value)) if key in ("stress", "energy") else ("偏正" if value > 0.15 else ("偏低" if value < -0.15 else "平稳"))))
    return "；".join(pairs)


def _section_mood(core):
    mood = core.get("mood") if isinstance(core.get("mood"), dict) else {}
    if not mood:
        return ""
    label = str(mood.get("label") or "")
    v = _num(mood.get("valence"))
    trend = "仍在回升" if v > 0 else ("还在低谷" if v < -0.1 else "还算平稳")
    return "心情：%s（%s）" % (label or trend, trend)


def _section_needs(core):
    needs = core.get("needs") if isinstance(core.get("needs"), dict) else {}
    if not needs:
        return ""
    names = {"belonging": "归属", "control": "控制", "meaningful_existence": "意义", "self_esteem": "自尊"}
    rows = [(names.get(k, k), _num(v)) for k, v in needs.items() if k in names]
    if not rows:
        return ""
    rows.sort(key=lambda kv: kv[1])
    return "；".join("%s %s" % (name, adverb(value) or "够") for name, value in rows[:3])


def _section_self_esteem(core):
    esteem = core.get("self_esteem")
    if esteem is None:
        return ""
    value = _num(esteem)
    note = "说话会犹豫" if value < 0.45 else ("挺有底气" if value > 0.7 else "还算稳")
    return "自尊 %s（%s）" % (adverb(value), note)


def _section_social_pain(core):
    pain = core.get("social_pain")
    if pain is None:
        return ""
    value = _num(pain)
    if value < 0.15:
        return ""
    return "被冷落的感觉%s" % adverb(value)


def _section_attachment(core):
    attachment = core.get("attachment") if isinstance(core.get("attachment"), dict) else {}
    if not attachment:
        return ""
    activation = _num(attachment.get("activation"))
    mode = str(attachment.get("mode") or "")
    note = {"hyperactivating": "想靠近", "comfort": "想依靠", "deactivating": "想退开"}.get(mode, "")
    return "依恋激活%s%s" % (adverb(activation), ("（%s）" % note) if note else "")


def _section_regulation(core):
    regulation = core.get("regulation") if isinstance(core.get("regulation"), dict) else {}
    if not regulation:
        return ""
    strategy = str(regulation.get("strategy") or "")
    effort = _num(regulation.get("effort"))
    if strategy == "suppress":
        return "在忍着（努力 %s）" % ("%.2f" % effort)
    if strategy == "reappraise":
        return "在试着换个角度想"
    return ""


def _section_sleep(core):
    debt = core.get("sleep_debt")
    if debt is None:
        return ""
    value = _num(debt)
    if value < 0.3:
        return ""
    return "有点累（欠 %sh）" % ("%.1f" % value)


def _section_relationship(relationship):
    rel = relationship if isinstance(relationship, dict) else {}
    state = rel.get("state") if isinstance(rel.get("state"), dict) else {}
    if not state:
        return ""
    return "关系：亲近%s、信任%s、冲突%s" % (
        adverb(state.get("closeness", 0.5)) or "一般",
        adverb(state.get("trust", 0.5)) or "一般",
        adverb(state.get("conflict", 0.0)) or "很少")


def _section_attribution(core):
    attribution = core.get("attribution") if isinstance(core.get("attribution"), dict) else {}
    if not attribution:
        return ""
    locus = str(attribution.get("locus") or "")
    stability = str(attribution.get("stability") or "")
    if not locus or locus == "neutral":
        return ""
    who = "他" if locus == "external" else "自己"
    stable = {"stable": "一直这样", "unstable": "这次而已"}.get(stability, "")
    return "觉得是「%s」%s" % (who, ("（%s）" % stable) if stable else "")


def render_state_block(core_snapshot, relationship=None, now=None, budget_chars=600):
    core = core_snapshot if isinstance(core_snapshot, dict) else {}
    sections = []
    if _labels(core)[0] or core.get("spectrum_probs"):
        sections.append(("emotion", _section_emotion(core)))
    sections.append(("spectrum", _section_spectrum(core)))
    sections.append(("dimensions", _section_dimensions(core)))
    sections.append(("mood", _section_mood(core)))
    sections.append(("needs", _section_needs(core)))
    sections.append(("self_esteem", _section_self_esteem(core)))
    sections.append(("social_pain", _section_social_pain(core)))
    sections.append(("attachment", _section_attachment(core)))
    sections.append(("regulation", _section_regulation(core)))
    sections.append(("sleep", _section_sleep(core)))
    sections.append(("relationship", _section_relationship(relationship)))
    sections.append(("attribution", _section_attribution(core)))
    present = [(name, text) for name, text in sections if text]
    if not present:
        return {"text": "", "parts_used": [], "truncated": False}
    mandatory = present[:4]
    optional = present[4:]
    text = "\n".join(part for _name, part in mandatory)
    used = [name for name, _part in mandatory]
    truncated = False
    budget = max(0, int(budget_chars))
    if len(text) > budget:
        text = text[:budget]
        truncated = True
    for name, part in optional:
        candidate = text + "\n" + part
        if len(candidate) <= int(budget_chars):
            text = candidate
            used.append(name)
        else:
            truncated = True
    return {"text": text, "parts_used": used, "truncated": truncated}
