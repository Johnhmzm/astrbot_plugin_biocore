# -*- coding: utf-8 -*-
"""BioCore interpretation layer.

Only this module may turn biological state into compact LLM input.
The biological layer must not build prompt strings.
"""
from __future__ import annotations

import json
import re


def _one_line(text: str, limit: int = 160) -> str:
    for line in reversed(str(text or "").splitlines()):
        line = line.strip().lstrip("- ").strip()
        if line:
            return line.replace("\n", "；")[:limit]
    return ""


_ALLOWED = {"joy", "sadness", "anger", "fear", "loneliness", "neutral"}
_LABEL_DELTAS = {
    "joy": (0.18, 0.06, 0.04, 0.05, 0.02),
    "sadness": (-0.18, -0.04, -0.03, -0.02, -0.01),
    "anger": (-0.16, 0.12, 0.08, -0.05, -0.02),
    "fear": (-0.14, 0.12, -0.10, -0.03, -0.02),
    "loneliness": (-0.12, -0.02, -0.03, -0.10, -0.02),
    "neutral": (0.0, 0.0, 0.0, 0.0, 0.0),
}


def _with_label_deltas(meta: dict) -> dict:
    if not isinstance(meta, dict):
        return {}
    if any(k in meta for k in ("valence_delta", "arousal_delta", "dominance_delta", "social_delta")):
        return meta
    emo = str(meta.get("emotion") or meta.get("e") or "").strip()
    if emo not in _ALLOWED:
        return meta
    try:
        inten = max(0.0, min(1.0, float(meta.get("intensity", meta.get("i", 0.65)))))
    except Exception:
        inten = 0.65
    out = dict(meta)
    out["emotion"] = emo
    out["valence_delta"] = _LABEL_DELTAS[emo][0] * inten
    out["arousal_delta"] = _LABEL_DELTAS[emo][1] * inten
    out["dominance_delta"] = _LABEL_DELTAS[emo][2] * inten
    out["social_delta"] = _LABEL_DELTAS[emo][3] * inten
    out["trust_delta"] = _LABEL_DELTAS[emo][4] * inten
    return out


def parse_response(raw: str):
    """Parse LLM output and return (clean_text, numeric_update|None).

    This is the only place that interprets the hidden emotion tag.
    """
    text = str(raw or "")
    m = re.search(r"<bc>(.*?)</bc>", text, re.S | re.I)
    tag = "bc"
    if not m:
        m = re.search(r"<biocore>(.*?)</biocore>", text, re.S | re.I)
        tag = "biocore"
    if not m:
        return text, None
    try:
        data = json.loads(m.group(1).strip())
    except Exception:
        return (text[:m.start()] + text[m.end():]).strip(), None
    update = _with_label_deltas(data)
    clean = (text[:m.start()] + text[m.end():]).strip()
    return clean, update


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
    trans = rel.get("transactive_map") if isinstance(rel, dict) else None
    if isinstance(trans, dict) and trans:
        topics = sorted(trans.items(), key=lambda item: (-int(item[1]), str(item[0])))[:3]
        base += "；常谈 " + "、".join(str(k)[:12] for k, _ in topics)
    return base


def memory_block(lines) -> str:
    return "；".join(str(x)[:140] for x in (lines or [])[:3])


def event_block(lines) -> str:
    return "；".join(str(x)[:160] for x in (lines or [])[:2])


def image_block(caption: str) -> str:
    return str(caption or "").strip().replace("\n", "；")[:160]


def event_summary_prompt(texts) -> str:
    joined = "\n".join("- " + str(t)[:400] for t in (texts or [])[:12])
    return ("下面是一段已经发生的事件（来自聊天记录）。请只输出一个 JSON 对象，不要代码块，不要解释：\n"
            '{"title":"短标题","event":"完整事件经过，80字以内","meaning_to_her":"这件事对她意味着什么，60字以内","reflection":"她之后形成的更高层认识或对自己的影响，60字以内"}\n'
            "要求：事件要覆盖整件事，不要只写一句话；意义只写她自己的感受、立场或关系变化；reflection 是从这件事提炼出的反思，不要复述事件；不要编造。\n\n" + joined)


def insight_prompt(events) -> str:
    joined = "\n".join("- " + str(e.get("title") or "") + "：" + str(e.get("event") or "")[:220]
                        for e in (events or [])[:6])
    return ("下面是最近几条重要事件。请只输出一个 JSON 对象，不要解释：\n"
            '{"insight":"从这些事件之间提炼出的一条更高层认识，80字以内，不要复述事件"}\n\n' + joined)


def render_compact(core, memory="", events="", self_model=None, user=None,
                   image="", kb="", speaker="", voice="", memory_meta=None) -> str:
    it = core.intent()
    cp = ("[BC] v=%.2f a=%.2f d=%.2f s=%.2f t=%.2f e=%s c=%s n=%s plan=%s reg=%s" % (
        float(core.v), float(core.a), float(core.d), float(core.social), float(core.trust),
        it.get("emotion") or "neutral", it.get("compound") or "-",
        it.get("need") or "talk", plan(core), it.get("regulation") or "none"))
    mb = memory_block(memory) if isinstance(memory, (list, tuple)) else str(memory or "")[:300]
    eb = event_block(events) if isinstance(events, (list, tuple)) else str(events or "")[:300]
    sb = self_block(self_model)
    ub = user_block(user)
    ib = image_block(image)
    if mb:
        cp += " | mem=" + mb
    mm = memory_meta if isinstance(memory_meta, dict) else {}
    _mm_count = int(mm.get("count", 0) or 0) if mm else 0
    if _mm_count > 0:
        cp += " | memn=%d memc=%.2f memsrc=%s" % (
            _mm_count,
            float(mm.get("confidence", 0.0) or 0.0),
            str(mm.get("source", "unknown") or "unknown")[:12])
        if mm.get("abstain"):
            cp += " mem=uncertain"
        _dests = mm.get("destinations")
        if isinstance(_dests, dict) and _dests:
            cp += " memwho=" + ",".join("%s×%s" % (str(k)[:20], int(v)) for k, v in list(_dests.items())[:3])
    if eb:
        cp += " | ev=" + eb
    if sb:
        cp += " | self=" + sb[:160]
    if ub:
        cp += " | u=" + ub[:100]
    if ib:
        cp += " | img=" + ib
    if kb:
        cp += " | kb=" + str(kb)[:180].replace("\n", "；")
    if speaker:
        cp += " | spk=" + str(speaker)[:80]
    if voice:
        cp += " | voice=" + str(voice)[:160]
    cp += ("\n[BC-Return] 回复末尾只输出一个 "
           '<bc>{"e":"joy|sadness|anger|fear|loneliness|neutral","i":0.0-1.0}</bc>，'
           "不解释、不输出数值 delta。")
    if _mm_count > 0 and mm.get("abstain"):
        cp += "\n[BC-Note] 记忆置信低或来源不明：不要当确定事实，可自然说记不清。"
    return cp


def event_ranking_prompt(texts) -> str:
    joined = "\n".join("- " + str(t)[:400] for t in (texts or [])[:24])
    return ("下面是一段近期会话上下文。请先在心里总结这段上下文，再从中提取最多 3 个"
            "真正重要的情绪事件，按 importance 从高到低排序。只输出 JSON 数组，不要解释：\n"
            '[{"title":"短标题","event":"完整事件经过，80字以内",'
            '"event_key":"稳定的事件键，如 用户-约定-澄清",'
            '"centrality":0.0,'
            '"central_details":"决定这件事意义的核心细节",'
            '"peripheral_details":"外围细节，可省略",'
            '"meaning_to_her":"这件事对她意味着什么，60字以内",'
            '"reflection":"她之后形成的更高层认识，60字以内",'
            '"emotion":"joy|sadness|anger|fear|loneliness|neutral",'
            '"importance":0.0}]\n'
            "规则：importance 0~1；centrality 0~1 表示核心程度；event_key 要能区分同一情绪的不同事件；"
            "只有真正影响关系、承诺、伤害、被理解、重要偏好或情绪转折的事件才给 importance >=0.6；"
            "普通闲聊不要提取；没有重要事件就输出 []；不要编造。\n\n" + joined)
