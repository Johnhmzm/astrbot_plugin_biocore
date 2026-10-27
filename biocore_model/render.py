# -*- coding: utf-8 -*-
"""BioCore model layer: deterministic rendering (Phase 1).

Owns the text the interpretation layer injects. Three modes:

- ``telemetry``: legacy compact [BC] numeric telemetry (byte-identical to 1.3.0)
- ``semantic``: 60-150 char natural-language brief (prototype, unchanged)
- ``text``: numbers rendered as tier words, labels preserved, fixed order
  (她此刻 -> 对你 -> 这一轮), <= 150 chars

Design rules:

- no clock/random inside the renderers (callers pass ``now`` when day words are
  needed for event links, so golden tests stay reproducible);
- the package imports only the standard library, so tests can import it
  without AstrBot;
- text mode never emits the legend (the legend lives in the fixed system
  prompt, once per request, through :func:`text_legend`).
"""
from __future__ import annotations

import math
import re

HINT_LIMIT = 140
CONTINUITY_LIMIT = 140
CONTINUITY_SUMMARY_LIMIT = 70
CONTINUITY_LOOP_LIMIT = 30
TEXT_LIMIT = 150


def _dict(value):
    return value if isinstance(value, dict) else {}


def hint(text, limit=HINT_LIMIT):
    """One bounded single-line hint fragment."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:max(1, int(limit))]


# ---------------------------------------------------------------------------
# Shared deterministic fragments (moved from interpretation.py)
# ---------------------------------------------------------------------------

def plan(core) -> str:
    labels = dict(getattr(core, "labels", {}) or {})
    need = labels.get("need", "talk")
    if need == "be_heard":
        return "先接住情绪"
    if need == "space":
        return "留出空间"
    if need == "vent":
        return "先听，不急着讲道理"
    if need == "share":
        return "顺着分享接话"
    return "自然回应"


def self_block(model: dict) -> str:
    d = model or {}
    parts = []
    if d.get("who_am_i"):
        parts.append("我是：" + str(d["who_am_i"]))
    if d.get("boundaries"):
        parts.append("边界：" + "；".join(str(x) for x in d["boundaries"][:5]))
    if d.get("consistency"):
        parts.append("一致性：" + "；".join(str(x) for x in d["consistency"][:5]))
    if d.get("narrative"):
        parts.append("最近：" + str(d["narrative"])[:500])
    return "；".join(parts)


def user_block(user: dict) -> str:
    d = user or {}
    if not d:
        return ""
    name = str(d.get("sender_name") or d.get("sender_id") or "").strip()
    base = "%s；互动 %s；信任 %.2f" % (
        name or "未知", int(d.get("interactions", 0) or 0),
        float(d.get("trust", 0.5) or 0.5))
    rel = d.get("relationship")
    state = rel.get("state") if isinstance(rel, dict) else None
    if isinstance(state, dict) and state:
        base += "；关系 亲近%.2f 冲突%.2f 修复%.2f 可预测%.2f" % (
            float(state.get("closeness", 0.5) or 0.5),
            float(state.get("conflict", 0.5) or 0.5),
            float(state.get("repair", 0.0) or 0.0),
            float(state.get("predictability", 0.5) or 0.5))
    repair_state = rel.get("repair_state") if isinstance(rel, dict) else None
    if isinstance(repair_state, dict):
        phase = str(repair_state.get("phase") or "stable")
        if phase != "stable":
            base += "；修复=" + phase[:16]
    absence = d.get("absence") if isinstance(d.get("absence"), dict) else (
        rel.get("absence") if isinstance(rel, dict) else None)
    if isinstance(absence, dict):
        bucket = str(absence.get("bucket") or "same_day")
        if bucket != "same_day":
            base += "；回归=" + bucket[:16]
    trans = rel.get("transactive_map") if isinstance(rel, dict) else None
    if isinstance(trans, dict) and trans:
        topics = sorted(trans.items(), key=lambda item: (-int(item[1]), str(item[0])))[:3]
        base += "；常谈 " + "、".join(str(k)[:12] for k, _ in topics)
    we_items = rel.get("we_memory") if isinstance(rel, dict) else None
    if isinstance(we_items, list) and we_items:
        first = we_items[0] if isinstance(we_items[0], dict) else {}
        we_text = str(first.get("text") or "").strip()[:24]
        if we_text:
            base += "；共同记忆：" + we_text
    try:
        commitment = float(rel.get("commitment", 0.0) or 0.0)
    except Exception:
        commitment = 0.0
    if commitment >= 0.2:
        base += "；承诺%.2f" % commitment
    return base


def memory_block(lines) -> str:
    return "；".join(str(x)[:140] for x in (lines or [])[:3])


def event_block(lines) -> str:
    return "；".join(str(x)[:160] for x in (lines or [])[:2])


def image_block(caption: str) -> str:
    return str(caption or "").strip().replace("\n", "；")[:160]


def continuity_block(continuity, limit=CONTINUITY_LIMIT) -> str:
    data = _dict(continuity)
    if not data:
        return ""
    parts = []
    summary = hint(data.get("summary"), CONTINUITY_SUMMARY_LIMIT)
    if summary:
        parts.append("上次：" + summary)
    loops = []
    raw_loops = data.get("loops")
    if isinstance(raw_loops, (list, tuple)):
        for item in raw_loops[:2]:
            text = hint(item.get("text") if isinstance(item, dict) else item,
                        CONTINUITY_LOOP_LIMIT)
            if text and text not in loops:
                loops.append(text)
    if loops:
        parts.append("未完成：" + "、".join(loops))
    rel = _dict(data.get("relationship"))
    if rel:
        try:
            closeness = max(0.0, min(1.0, float(rel.get("closeness", 0.5) or 0.5)))
            conflict = max(0.0, min(1.0, float(rel.get("conflict", 0.5) or 0.5)))
            repair = max(0.0, min(1.0, float(rel.get("repair", 0.0) or 0.0)))
        except Exception:
            closeness, conflict, repair = 0.5, 0.5, 0.0
        rel_parts = ["关系 近%.2f/冲突%.2f" % (closeness, conflict)]
        if repair > 0.05:
            rel_parts.append("修复%.2f" % repair)
        phase = str(rel.get("phase") or "stable")
        if phase and phase != "stable":
            rel_parts.append("修复阶段=" + phase[:12])
        absence = str(rel.get("absence") or "")
        if absence and absence != "same_day":
            rel_parts.append("回归=" + absence[:12])
        parts.append("；".join(rel_parts))
    if not parts:
        return ""
    return hint("；".join(parts), limit)


def brevity_token(brevity) -> str:
    mode = str(brevity or "normal").strip().lower()
    if mode not in ("short", "medium"):
        return ""
    return hint("brevity=" + mode, 24)


def _return_contract(memory_meta) -> str:
    """Shared [BC-Return]/[BC-Note] suffix for telemetry and semantic modes."""
    mm = memory_meta if isinstance(memory_meta, dict) else {}
    suffix = ("\n[BC-Return] 末尾只输出一个 <bc>{e,i}</bc>（可选 n/x）；"
              "不解释、不输出任何数值 delta。")
    try:
        _count = int(mm.get("count", 0) or 0)
    except Exception:
        _count = 0
    if _count > 0 and mm.get("abstain"):
        suffix += "\n[BC-Note] 记忆置信低或来源不明：不要当确定事实，可自然说记不清。"
    return suffix


def _brief_clean(text, limit=30):
    value = str(text or "").strip()
    value = value.lstrip("- ")
    for prefix in ("用户：", "用户:", "你(已总结)：", "你："):
        if value.startswith(prefix):
            value = value[len(prefix):]
    value = re.sub(r"\d+\.\d+", "", value)
    value = re.sub(r"\s+", " ", value).strip("；;，。 ")
    return value[:limit]


def render_semantic(core, memory="", events="", user=None, continuity=None,
                    memory_meta=None, open_loops=None) -> str:
    """Prototype 60-150 char natural-language brief; no raw telemetry/field names."""
    if core is None:
        return ""
    parts = []
    try:
        v = float(getattr(core, "v", 0.0) or 0.0)
        stress = float(getattr(core, "stress", 0.2) or 0.2)
        energy = float(getattr(core, "energy", 0.55) or 0.55)
        social = float(getattr(core, "social", 0.5) or 0.5)
        if v <= -0.35:
            mood = "心里有点沉"
        elif v <= -0.12:
            mood = "心里有点发紧"
        elif v >= 0.40:
            mood = "心情不错"
        else:
            mood = "整体偏平静"
        if energy <= 0.35:
            body = "身体有点累"
        elif stress >= 0.60:
            body = "还带着点压力"
        else:
            body = "状态还算稳"
        if social <= 0.35:
            soc = "不太想说话"
        elif social >= 0.65:
            soc = "愿意靠近人"
        else:
            soc = "社交一般"
        parts.append("%s，%s，%s" % (mood, body, soc))
    except Exception:
        parts.append("现在整体偏平静，状态还算稳，社交一般")
    stance = "关系一般，先按平常方式接"
    try:
        rel = (user or {}).get("relationship") if isinstance(user, dict) else None
        state = rel.get("state") if isinstance(rel, dict) else {}
        repair = rel.get("repair_state") if isinstance(rel, dict) else {}
        absence = (user or {}).get("absence") if isinstance(user, dict) else {}
        if not isinstance(absence, dict) and isinstance(rel, dict):
            absence = rel.get("absence") if isinstance(rel.get("absence"), dict) else {}
        phase = str((repair or {}).get("phase") or "stable")
        bucket = str((absence or {}).get("bucket") or "same_day")
        trust = float((state or {}).get("trust", 0.5) or 0.5)
        closeness = float((state or {}).get("closeness", 0.5) or 0.5)
        conflict = float((state or {}).get("conflict", 0.0) or 0.0)
        if phase != "stable":
            stance = "关系还在修复中，先别急着讲道理"
        elif bucket in ("long", "medium"):
            stance = "很久没聊了，先从近况接上"
        elif conflict >= 0.45:
            stance = "关系有点紧，先轻轻接"
        elif trust >= 0.60 and closeness >= 0.60:
            stance = "关系挺稳，信任还在慢慢长"
        elif trust >= 0.55:
            stance = "关系还算稳，别太用力"
    except Exception:
        pass
    parts.append(stance)
    try:
        conf = 0.0
        if isinstance(memory_meta, dict):
            conf = float(memory_meta.get("confidence", 0.0) or 0.0)
        snippet = ""
        if conf >= 0.60:
            for line in str(memory or "").splitlines():
                cleaned = _brief_clean(line, 26)
                if cleaned:
                    snippet = cleaned
                    break
            if snippet:
                parts.append("记得：" + snippet)
        if not snippet:
            for line in str(events or "").splitlines():
                cleaned = _brief_clean(line, 24)
                if cleaned:
                    parts.append("最近：" + cleaned)
                    break
    except Exception:
        pass
    try:
        if isinstance(continuity, dict):
            summary = _brief_clean(continuity.get("summary"), 24)
            if summary:
                for _prefix in ("上次：", "上次:", "上次"):
                    if summary.startswith(_prefix):
                        summary = summary[len(_prefix):].lstrip("：:，, ")
                        break
                if summary:
                    parts.append("上次：" + summary)
    except Exception:
        pass
    parts.append("回复自然一点，别解释内部状态，也别报数值")
    brief = "；".join(part for part in parts if part)
    brief = re.sub(r"\s+", " ", brief).strip()
    if len(brief) > 150:
        cut = brief[:150]
        if "；" in cut:
            cut = cut[:cut.rfind("；")]
        brief = cut.strip("； ")
    if len(brief) < 60:
        brief = (brief + "；像平常聊天那样接就好").strip("； ")
    return brief[:150]


def semantic_brief(*args, **kwargs):
    """Compatibility alias for the task-33 prototype name."""
    return render_semantic(*args, **kwargs)
# ---------------------------------------------------------------------------
# text mode: numbers -> tier words, labels preserved, fixed section order
# ---------------------------------------------------------------------------

_EMO_ZH = {
    "joy": "开心", "sadness": "难过", "anger": "生气", "fear": "害怕",
    "loneliness": "孤单", "neutral": "平静", "trust": "信任",
    "surprise": "意外", "anticipation": "期待", "disgust": "别扭",
}

_NEED_ZH = {"talk": "想聊聊", "be_heard": "想被听见", "space": "想有点空间",
            "vent": "想倒一倒", "share": "想分享"}

# axis -> (tier boundaries, tier words)
_AXES = {
    "v": ([-0.35, -0.12, 0.12, 0.40],
          ["心里沉", "有点发紧", "还算平", "还不错", "心情好"]),
    "a": ([0.30, 0.55, 0.75], ["很松弛", "不紧不慢", "有点绷", "绷得紧"]),
    "d": ([0.30, 0.55], ["没底", "拿捏一般", "拿得住"]),
    "s": ([0.35, 0.65], ["不想说话", "愿意搭话", "想靠近"]),
    "stress": ([0.25, 0.50, 0.70], ["没压力", "有点压", "压着", "扛不住"]),
    "energy": ([0.35, 0.60], ["累", "还撑得住", "有精神"]),
}
_DECIMAL_BOUNDS = {
    "v": [-0.5, 0.0, 0.5],
    "a": [0.5, 0.75],
    "d": [0.5],
    "s": [0.5],
    "stress": [0.5],
    "energy": [0.5],
}


def _as_float(value, default=0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(out):
        return float(default)
    return out


def _tier(axis, value) -> str:
    bounds, words = _AXES[axis]
    for i, bound in enumerate(bounds):
        if value < bound:
            return words[i]
    return words[len(bounds)]


def _tier_with_decimal(axis, value) -> str:
    """Tier word; append one decimal only near a threshold (or 0.5/0.75)."""
    word = _tier(axis, value)
    bounds = list(_AXES[axis][0]) + list(_DECIMAL_BOUNDS.get(axis, ()))
    near = any(abs(value - b) <= 0.05 + 1e-9 for b in bounds)
    if near:
        return word + ("(%.1f)" % value)
    return word


_REL_AXES = {
    "trust": ([0.35, 0.60], ["还没起来", "在慢慢长", "挺稳"]),
    "closeness": ([0.35, 0.65], ["还远", "不算远", "挺近"]),
    "conflict": ([0.30, 0.55], ["没冲突", "有点别扭", "还在拧着"]),
}


def _rel_phrase(axis, value) -> str:
    bounds, words = _REL_AXES[axis]
    for i, bound in enumerate(bounds):
        if value < bound:
            return words[i]
    return words[len(bounds)]


def _rel_with_decimal(axis, value) -> str:
    """Relationship tier word + one decimal near a boundary (or 0.5/0.75)."""
    word = _rel_phrase(axis, value)
    bounds = list(_REL_AXES[axis][0]) + [0.5, 0.75]
    if any(abs(value - b) <= 0.05 + 1e-9 for b in bounds):
        return word + ("(%.1f)" % value)
    return word


def _emotion_sentence(core, it) -> str:
    primary = str(it.get("emotion") or "neutral")
    p_zh = _EMO_ZH.get(primary, primary)
    secondary = ""
    compound = str(it.get("compound") or "").strip()
    if compound:
        secondary = compound
    else:
        spectrum = it.get("spectrum")
        best = None
        if isinstance(spectrum, (list, tuple)):
            for item in spectrum:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "")
                if key == primary:
                    continue
                p = _as_float(item.get("p"), 0.0)
                if p >= 0.15 and (best is None or p > best[0]):
                    best = (p, str(item.get("name") or _EMO_ZH.get(key, key)))
        if best:
            secondary = best[1]
    level = "中"
    try:
        intensity = float(core._intensity())
        if intensity <= 0.33:
            level = "低"
        elif intensity > 0.66:
            level = "高"
    except Exception:
        level = "中"
    out = "情绪%s为主" % p_zh
    if secondary:
        out += "，也带点" + secondary
    out += "，强度" + level
    return out


def _short_event(event) -> str:
    e = event if isinstance(event, dict) else {}
    text = (str(e.get("title") or "").strip()
            or str(e.get("small_summary") or "").strip()
            or str(e.get("event") or "").strip())
    text = re.sub(r"\s+", " ", text)
    return text[:14]


def _day_word(ts, now) -> str:
    """Relative day word for an event link (deterministic given now)."""
    if now is None:
        return ""
    try:
        delta = float(now) - float(ts)
    except Exception:
        return ""
    if delta < 0:
        return ""
    days = int(delta // 86400.0)
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    if days == 2:
        return "前天"
    return "之前"


def derive_event_links(events, now=None, limit=2) -> list:
    """Strongest 1-2 event links, as bounded render-ready dicts.

    Uses persisted chain_links first (memory_chain_enabled); when the archive
    carries no explicit edges it falls back to adjacent same-session events
    within 1800 s, mirroring the write-side edge rule. No clock is read here:
    now is only used to label the day (今天/昨天/前天/之前).
    """
    if not isinstance(events, (list, tuple)):
        return []
    evs = [e for e in events if isinstance(e, dict)]
    by_id = {str(e.get("id")): e for e in evs if e.get("id")}
    pairs = []
    for src in evs:
        links = src.get("chain_links")
        if not isinstance(links, (list, tuple)):
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            tgt = by_id.get(str(link.get("id") or ""))
            if tgt is None:
                continue
            weight = _as_float(link.get("weight"), 0.0)
            pairs.append((weight, src, tgt))
    if not pairs:
        ordered = sorted(evs, key=lambda e: _as_float(e.get("ts"), 0.0))
        for left, right in zip(ordered, ordered[1:]):
            if str(left.get("session") or "") != str(right.get("session") or ""):
                continue
            gap = abs(_as_float(right.get("ts"), 0.0) - _as_float(left.get("ts"), 0.0))
            if gap > 1800.0:
                continue
            weight = max(0.5, 1.0 - 0.5 * gap / 1800.0)
            pairs.append((round(weight, 3), left, right))
    out = []
    seen = set()
    for weight, left, right in sorted(
            pairs, key=lambda row: (-row[0], _as_float(row[1].get("ts"), 0.0))):
        key = frozenset((str(left.get("id") or id(left)),
                         str(right.get("id") or id(right))))
        if key in seen:
            continue
        seen.add(key)
        # Chronological reading: earlier event on the left.
        if _as_float(left.get("ts"), 0.0) > _as_float(right.get("ts"), 0.0):
            left, right = right, left
        item = {"left": _short_event(left), "right": _short_event(right),
                "left_time": _day_word(left.get("ts"), now),
                "right_time": _day_word(right.get("ts"), now),
                "weight": round(weight, 3)}
        if not item["left"] or not item["right"]:
            continue
        out.append(item)
        if len(out) >= max(1, int(limit)):
            break
    return out


_TIME_WORDS = ("今天", "昨晚", "昨天", "前天", "之前", "最近")


def _time_label(day, label) -> str:
    """Avoid duplicated time words when the event title already carries one."""
    label = str(label or "")
    day = str(day or "")
    if not day:
        return label
    if any(word in label for word in _TIME_WORDS):
        return label
    return day + label


def _link_text(event_links) -> str:
    if not isinstance(event_links, (list, tuple)):
        return ""
    parts = []
    for item in event_links[:2]:
        if not isinstance(item, dict):
            continue
        left = str(item.get("left") or "").strip()
        right = str(item.get("right") or "").strip()
        if not left or not right:
            continue
        parts.append("%s → %s，她读成同一件事" % (
            _time_label(item.get("left_time"), left),
            _time_label(item.get("right_time"), right)))
    if not parts:
        return ""
    return "联系：" + "；".join(parts)


TEXT_LEGEND_LINES = (
    "[BC-Legend] 档位词：效价=沉/紧/平/好；唤醒=松弛/不紧/绷/紧；压力=无/有/压着/扛不住；信任=没信/在信/挺信。",
    "[BC-Legend] 阈值：0.5 与 0.75 是档位分界；数值只在阈值±0.05 内才带 1 位小数，其余只给词。",
)


def text_legend() -> str:
    """<=2 line legend for the fixed system-prompt prefix (never per turn)."""
    return "\n".join(TEXT_LEGEND_LINES)


def _status_labels(core) -> str:
    out = []
    try:
        alert = float(getattr(core, "circadian_alertness", 0.5) or 0.5)
        if alert <= 0.33:
            out.append("alert=low")
        elif alert >= 0.80:
            out.append("alert=high")
    except Exception:
        pass
    try:
        if float(getattr(core, "allostatic_load", 0.0) or 0.0) >= 0.6:
            out.append("load=high")
    except Exception:
        pass
    try:
        homeo = getattr(core, "homeostasis", None)
        if isinstance(homeo, dict):
            ready = float(homeo.get("readiness", 0.6) or 0.6)
            if ready <= 0.35:
                out.append("ready=low")
            elif ready >= 0.75:
                out.append("ready=high")
            intero = homeo.get("interoception") if isinstance(
                homeo.get("interoception"), dict) else {}
            ilabel = str(intero.get("label") or "")
            if ilabel in ("low", "high"):
                out.append("intero=" + ilabel)
    except Exception:
        pass
    try:
        trace = getattr(core, "_last_memory_trace", None)
        if isinstance(trace, dict):
            tv = float(trace.get("valence", 0.0) or 0.0)
            if tv >= 0.3:
                out.append("mtrace=warm")
            elif tv <= -0.3:
                out.append("mtrace=heavy")
    except Exception:
        pass
    return " ".join(out)


def _relationship_text(core, user, full=True) -> str:
    rel = (user or {}).get("relationship") if isinstance(user, dict) else None
    state = rel.get("state") if isinstance(rel, dict) else {}
    if not isinstance(state, dict):
        state = {}
    trust = _as_float(state.get("trust", getattr(core, "trust", 0.5)), 0.5)
    closeness = _as_float(state.get("closeness", 0.5), 0.5)
    conflict = _as_float(state.get("conflict", 0.5), 0.5)
    bits = ["信任" + _rel_with_decimal("trust", trust),
            "亲近" + _rel_with_decimal("closeness", closeness)]
    if full:
        bits.append("冲突" + _rel_with_decimal("conflict", conflict))
    repair_state = rel.get("repair_state") if isinstance(rel, dict) else None
    phase = str((repair_state or {}).get("phase") or "stable") if isinstance(
        repair_state, dict) else "stable"
    absence = (user or {}).get("absence") if isinstance(user, dict) else None
    if not isinstance(absence, dict) and isinstance(rel, dict):
        absence = rel.get("absence") if isinstance(rel.get("absence"), dict) else None
    bucket = str((absence or {}).get("bucket") or "same_day")
    if phase and phase != "stable":
        bits.append("还在修复")
    elif bucket in ("medium", "long"):
        bits.append("很久没聊")
    return "、".join(bits)


def _first_line(text) -> str:
    for line in str(text or "").splitlines():
        cleaned = _brief_clean(line, 18)
        if cleaned:
            return cleaned
    return ""


def render_text(core, memory="", events="", self_model=None, user=None,
                image="", kb="", speaker="", voice="", memory_meta=None,
                open_loops=None, open_loops_due=0, answer_confidence=None,
                strategy_hint="", continuity=None, workspace_token="",
                brevity="normal", event_links=None) -> str:
    """Render the text mode block: tier words, labels, fixed order, <=150 chars."""
    if core is None:
        return ""
    it = core.intent() if hasattr(core, "intent") else {}
    v = _as_float(getattr(core, "v", 0.0), 0.0)
    a = _as_float(getattr(core, "a", 0.5), 0.5)
    stress = _as_float(getattr(core, "stress", 0.2), 0.2)
    energy = _as_float(getattr(core, "energy", 0.55), 0.55)
    mood = "、".join([_tier_with_decimal("v", v),
                      _tier_with_decimal("a", a),
                      _tier_with_decimal("energy", energy),
                      _tier_with_decimal("stress", stress)])
    s1 = "她此刻：" + mood + "，" + _emotion_sentence(core, it)
    s1 += "（e=%s c=%s）" % (str(it.get("emotion") or "neutral"),
                            str(it.get("compound") or "-"))
    need = str(it.get("need") or "talk")
    plan_text = plan(core)
    reg = str(it.get("regulation") or "none")
    labels_req = ["n=" + need, "plan=" + plan_text, "reg=" + reg]
    labels_opt = _status_labels(core).split()
    labels_full = labels_req + labels_opt

    def _compose(rel_text, extra, labels):
        tail = ("，" + "，".join(extra)) if extra else ""
        return ("[BC] " + s1 + "；对你：" + rel_text + "；这一轮：" +
                _NEED_ZH.get(need, need) + tail +
                "（" + " ".join(labels) + "）")

    candidates = []
    link = _link_text(event_links)
    if link:
        candidates.append(link)
    loops = [x for x in (open_loops or []) if isinstance(x, dict)] if isinstance(
        open_loops, (list, tuple)) else []
    open_count = sum(1 for x in loops if str(x.get("status") or "open") == "open")
    if open_count:
        candidates.append("还有%d件没落定" % open_count)
    if isinstance(continuity, dict):
        cont_text = _first_line(continuity.get("summary"))
        if cont_text:
            candidates.append("上次：" + cont_text)
    mem_text = _first_line(memory)
    if mem_text:
        candidates.append("记得：" + mem_text)
    ev_text = _first_line(events)
    if ev_text:
        candidates.append("最近：" + ev_text)

    rel_full = _relationship_text(core, user, full=True)
    rel_core = _relationship_text(core, user, full=False)
    rel = rel_full
    extra = []
    for item in candidates:
        trial = extra + [item]
        if len(_compose(rel, trial, labels_full)) <= TEXT_LIMIT:
            extra = trial
        elif rel == rel_full and len(_compose(rel_core, trial, labels_full)) <= TEXT_LIMIT:
            rel = rel_core
            extra = trial
    out = _compose(rel, extra, labels_full)
    if len(out) <= TEXT_LIMIT:
        return out
    out = _compose(rel_core, extra, labels_req)
    if len(out) <= TEXT_LIMIT:
        return out
    # Last resort: drop the secondary-emotion clause, keep primary+intensity+req labels.
    shortened = s1
    if "，也带点" in shortened:
        head, tail = shortened.split("，也带点", 1)
        tail_parts = tail.split("，强度", 1)
        shortened = head + "，强度" + (tail_parts[1] if len(tail_parts) > 1 else "中")
    saved_s1 = s1
    try:
        s1 = shortened
        out = _compose(rel_core, extra, labels_req)
    finally:
        s1 = saved_s1
    return out[:TEXT_LIMIT]


# ---------------------------------------------------------------------------
# Unified entry: render_compact dispatches telemetry/semantic/text
# ---------------------------------------------------------------------------

def render_compact(core, memory="", events="", self_model=None, user=None,
                   image="", kb="", speaker="", voice="", memory_meta=None,
                   open_loops=None, open_loops_due=0, answer_confidence=None,
                   strategy_hint="", continuity=None, prompt_mode="telemetry",
                   workspace_token="", brevity="normal", event_links=None) -> str:
    """Render biological state into the single compact block the LLM sees.

    The interpretation layer owns this string; callers pass raw state/data and
    never build prompt text themselves. Optional fields are rendered only when
    present so the block stays short (prefix-cache friendly).
    """
    mode = str(prompt_mode or "telemetry").strip().lower()
    if mode == "semantic":
        try:
            _sem = render_semantic(core, memory=memory, events=events, user=user,
                                   continuity=continuity, memory_meta=memory_meta,
                                   open_loops=open_loops)
            if 40 <= len(_sem) <= 300:
                return _sem + _return_contract(memory_meta)
        except Exception:
            pass
    if mode == "text":
        try:
            _txt = render_text(core, memory=memory, events=events,
                               self_model=self_model, user=user, image=image,
                               kb=kb, speaker=speaker, voice=voice,
                               memory_meta=memory_meta, open_loops=open_loops,
                               open_loops_due=open_loops_due,
                               answer_confidence=answer_confidence,
                               strategy_hint=strategy_hint,
                               continuity=continuity,
                               workspace_token=workspace_token,
                               brevity=brevity, event_links=event_links)
            if _txt:
                return _txt + _return_contract(memory_meta)
        except Exception:
            pass
    it = core.intent()
    cp = ("[BC] v=%.2f a=%.2f d=%.2f s=%.2f t=%.2f e=%s c=%s n=%s plan=%s reg=%s" % (
        float(core.v), float(core.a), float(core.d), float(core.social), float(core.trust),
        it.get("emotion") or "neutral", it.get("compound") or "-",
        it.get("need") or "talk", plan(core), it.get("regulation") or "none"))
    try:
        _ws = str(workspace_token or "").strip()[:16]
        if _ws and all(ch.isalnum() or ch == "_" for ch in _ws):
            cp += " ws=" + _ws
    except Exception:
        pass
    try:
        if float(getattr(core, "boredom", 0.0) or 0.0) >= 0.7:
            cp += " bored"
    except Exception:
        pass
    try:
        _alert = float(getattr(core, "circadian_alertness", 0.5) or 0.5)
        if _alert <= 0.33:
            cp += " alert=low"
        elif _alert >= 0.80:
            cp += " alert=high"
    except Exception:
        pass
    try:
        if float(getattr(core, "allostatic_load", 0.0) or 0.0) >= 0.6:
            cp += " load=high"
    except Exception:
        pass
    try:
        _h = getattr(core, "homeostasis", None)
        if isinstance(_h, dict):
            _ready = float(_h.get("readiness", 0.6) or 0.6)
            if _ready <= 0.35:
                cp += " ready=low"
            elif _ready >= 0.75:
                cp += " ready=high"
            _intero = _h.get("interoception") if isinstance(_h.get("interoception"), dict) else {}
            _ilabel = str(_intero.get("label") or "")
            if _ilabel in ("low", "high"):
                cp += " intero=" + _ilabel
            _need = _h.get("need_pyramid") if isinstance(_h.get("need_pyramid"), dict) else {}
            _dom = str(_need.get("dominant") or "")
            if _dom:
                cp += " need=" + _dom[:20]
            _action = _h.get("action") if isinstance(_h.get("action"), dict) else {}
            _amode = str(_action.get("mode") or "")
            if _amode:
                cp += " action=" + _amode[:16]
    except Exception:
        pass
    try:
        _trace = getattr(core, "_last_memory_trace", None)
        if isinstance(_trace, dict):
            _tv = float(_trace.get("valence", 0.0) or 0.0)
            if _tv >= 0.3:
                cp += " mtrace=warm"
            elif _tv <= -0.3:
                cp += " mtrace=heavy"
    except Exception:
        pass
    mb = memory_block(memory) if isinstance(memory, (list, tuple)) else str(memory or "")[:220]
    eb = event_block(events) if isinstance(events, (list, tuple)) else str(events or "")[:220]
    sb = self_block(self_model)
    ub = user_block(user)
    ib = image_block(image)
    if mb:
        cp += " | mem=" + mb
    mm = memory_meta if isinstance(memory_meta, dict) else {}
    _mm_count = int(mm.get("count", 0) or 0) if mm else 0
    if _mm_count > 0:
        cp += " | memn=%d memc=%.2f" % (
            _mm_count,
            float(mm.get("confidence", 0.0) or 0.0))
        _msrc = str(mm.get("source", "unknown") or "unknown")[:12]
        if _msrc in ("inferred", "unknown"):
            cp += " memsrc=" + _msrc
        if mm.get("abstain"):
            cp += " mem=uncertain"
        _ansc = answer_confidence
        if _ansc is None:
            _ansc = mm.get("answer_confidence")
        if _ansc is not None:
            try:
                _aconf = max(0.0, min(1.0, float(_ansc)))
                if _aconf < 0.65:
                    cp += " ansc=%.2f" % _aconf
            except Exception:
                pass
        _dests = mm.get("destinations")
        if isinstance(_dests, dict) and len(_dests) >= 2:
            cp += " memwho=" + ",".join("%s×%s" % (str(k)[:20], int(v)) for k, v in list(_dests.items())[:3])
    _loops = [x for x in (open_loops or []) if isinstance(x, dict)] if isinstance(open_loops, (list, tuple)) else []
    _open_loops = [x for x in _loops if str(x.get("status") or "open") == "open"]
    if _open_loops:
        cp += " | loops=%d" % len(_open_loops)
        try:
            _due = int(open_loops_due or 0)
        except Exception:
            _due = 0
        if _due:
            cp += " due=%d" % _due
        for _loop in _open_loops:
            if str(_loop.get("due_hint") or "") in ("soon", "tomorrow"):
                _text = str(_loop.get("text") or "").strip()[:40]
                if _text:
                    cp += " soon=" + _text
                break
    if eb:
        cp += " | ev=" + eb
    if sb:
        cp += " | self=" + sb[:120]
    if ub:
        cp += " | u=" + ub[:80]
    if ib:
        cp += " | img=" + ib
    if kb:
        cp += " | kb=" + str(kb)[:140].replace("\n", "；")
    if speaker:
        cp += " | spk=" + str(speaker)[:60]
    if voice:
        cp += " | voice=" + str(voice)[:120]
    _brevity = str(brevity or "normal").strip().lower()
    _hint_cap = 120
    if _brevity == "short":
        _hint_cap = 60
    elif _brevity == "medium":
        _hint_cap = 90
    if strategy_hint:
        cp += " | hint=" + hint(strategy_hint, _hint_cap)
    _btok = brevity_token(_brevity)
    if _btok:
        cp += " | " + _btok
    if continuity:
        _cont = continuity if isinstance(continuity, str) else continuity_block(continuity)
        if _cont:
            cp += " | cont=" + hint(_cont, CONTINUITY_LIMIT)
    cp += _return_contract(mm)
    return cp
