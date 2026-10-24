# -*- coding: utf-8 -*-
"""BioCore interpretation layer.

Only this module may construct LLM inputs or parse LLM outputs for the
biological layer. The biological layer must not build prompt strings, and the
LLM may never write biological state directly: every model output is parsed
and validated here (compact <bc> tag, persona profile, event ranking/summary,
insight, memory summary).
"""
from __future__ import annotations

import json
import math
import re


def _one_line(text: str, limit: int = 160) -> str:
    for line in reversed(str(text or "").splitlines()):
        line = line.strip().lstrip("- ").strip()
        if line:
            return line.replace("\n", "；")[:limit]
    return ""


_ALLOWED = {"joy", "sadness", "anger", "fear", "loneliness", "neutral"}
_ALLOWED_NEEDS = {"share", "space", "vent", "be_heard", "talk"}
_ALLOWED_EXPRESSIONS = {"open", "normal", "short"}
# The model may only emit these compact keys. Numeric deltas are derived by
# this module; any delta supplied by the model is ignored (boundary rule).
_ALLOWED_OUTPUT_KEYS = {"e", "emotion", "i", "intensity", "n", "need", "x", "expression"}
_LABEL_DELTAS = {
    "joy": (0.18, 0.06, 0.04, 0.05, 0.02),
    "sadness": (-0.18, -0.04, -0.03, -0.02, -0.01),
    "anger": (-0.16, 0.12, 0.08, -0.05, -0.02),
    "fear": (-0.14, 0.12, -0.10, -0.03, -0.02),
    "loneliness": (-0.12, -0.02, -0.03, -0.10, -0.02),
    "neutral": (0.0, 0.0, 0.0, 0.0, 0.0),
}


def _with_label_deltas(meta: dict) -> dict:
    """Map the compact model output (e/i/n/x) to validated state deltas.


    The LLM never supplies numeric deltas. If a delta key is present it is
    dropped instead of applied, so the model cannot write biological state
    directly; only the label/strength mapping below may change v/a/d/social.
    """
    if not isinstance(meta, dict):
        return {}
    if any(k in meta for k in ("valence_delta", "arousal_delta", "dominance_delta",
                               "social_delta", "trust_delta")):
        return {}
    out = {}
    emo = str(meta.get("emotion") or meta.get("e") or "").strip()
    if emo in _ALLOWED:
        try:
            inten = max(0.0, min(1.0, float(meta.get("intensity", meta.get("i", 0.65)))))
        except Exception:
            inten = 0.65
        out["emotion"] = emo
        out["intensity"] = round(inten, 3)
        out["valence_delta"] = _LABEL_DELTAS[emo][0] * inten
        out["arousal_delta"] = _LABEL_DELTAS[emo][1] * inten
        out["dominance_delta"] = _LABEL_DELTAS[emo][2] * inten
        out["social_delta"] = _LABEL_DELTAS[emo][3] * inten
        out["trust_delta"] = _LABEL_DELTAS[emo][4] * inten
    need = str(meta.get("n") or meta.get("need") or "").strip()
    if need in _ALLOWED_NEEDS:
        out["need"] = need
    expression = str(meta.get("x") or meta.get("expression") or "").strip()
    if expression in _ALLOWED_EXPRESSIONS:
        out["expression"] = expression
    return out


def parse_response(raw: str):
    """Parse LLM output and return (clean_text, validated_update|None).

    This is the only place that interprets the hidden emotion tag. The model
    may only emit compact label keys; numeric deltas in the tag are ignored.
    """
    text = str(raw or "")
    m = re.search(r"<bc>(.*?)</bc>", text, re.S | re.I)
    if not m:
        m = re.search(r"<biocore>(.*?)</biocore>", text, re.S | re.I)
    if not m:
        return text, None
    clean = (text[:m.start()] + text[m.end():]).strip()
    try:
        data = json.loads(m.group(1).strip())
    except Exception:
        return clean, None
    if not isinstance(data, dict):
        return clean, None
    allowed = {key: value for key, value in data.items() if key in _ALLOWED_OUTPUT_KEYS}
    update = _with_label_deltas(allowed)
    return clean, (update or None)


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


def image_caption_prompt(base_prompt: str = "") -> str:
    """Prompt used for the vision model caption request.

    The caller may supply an AstrBot/user configured prompt; the deterministic
    fallback lives here so main.py never assembles prompt text itself.
    """
    text = str(base_prompt or "").strip()
    return text or "请客观描述这张图片，供角色扮演聊天使用。"


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
                   image="", kb="", speaker="", voice="", memory_meta=None,
                   open_loops=None, open_loops_due=0, answer_confidence=None) -> str:
    """Render biological state into the single compact block the LLM sees.

    The interpretation layer owns this string; callers pass raw state/data and
    never build prompt text themselves. Optional fields are rendered only when
    present so the block stays short (prefix-cache friendly).
    """
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
        _ansc = answer_confidence
        if _ansc is None:
            _ansc = mm.get("answer_confidence")
        if _ansc is not None:
            try:
                cp += " ansc=%.2f" % max(0.0, min(1.0, float(_ansc)))
            except Exception:
                pass
        _dests = mm.get("destinations")
        if isinstance(_dests, dict) and _dests:
            cp += " memwho=" + ",".join("%s×%s" % (str(k)[:20], int(v)) for k, v in list(_dests.items())[:3])
    # Prospective memory: open-loop count plus the nearest due item (bounded).
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
           '<bc>{"e":"joy|sadness|anger|fear|loneliness|neutral","i":0.0-1.0}</bc>'
           "（可选 n=share|space|vent|be_heard|talk，x=open|normal|short）；"
           "不解释、不输出任何数值 delta。")
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


# ---------------------------------------------------------------------------
# Model output parsing (the only path from LLM output into biological state)
# ---------------------------------------------------------------------------
_EMOTIONS = {"joy", "sadness", "anger", "fear", "loneliness", "neutral"}

# Compiled-persona numeric ranges. Keys outside this table are ignored so a
# model cannot inject arbitrary fields into the biological layer.
PROFILE_RANGES = {
    "O": (0.0, 1.0), "C": (0.0, 1.0), "E": (0.0, 1.0), "A": (0.0, 1.0), "N": (0.0, 1.0),
    "stress_reactivity": (0.0, 1.0), "recovery_rate": (0.0, 1.0),
    "social_baseline": (0.0, 1.0), "energy_baseline": (0.0, 1.0),
    "curiosity_baseline": (0.0, 1.0), "safety_baseline": (0.0, 1.0),
    "da_baseline": (0.0, 1.0), "oa_baseline": (0.0, 1.0), "ht_baseline": (0.0, 1.0),
    "autonomy_gain": (0.0, 1.5), "baseline_v": (-1.0, 1.0), "baseline_a": (0.0, 1.0),
    "learning_rate": (0.01, 0.12),
}


def _bounded(value, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(float(low), min(float(high), number))


def _clean_text(value, limit: int = 400) -> str:
    return str(value or "").strip()[:max(1, int(limit))]


def _strip_code_fence(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_object(raw: str):
    """Extract one JSON object from possibly noisy model output."""
    text = _strip_code_fence(raw)
    lo, hi = text.find("{"), text.rfind("}")
    if lo < 0 or hi <= lo:
        return None
    try:
        data = json.loads(text[lo:hi + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _extract_json_array(raw: str):
    """Extract one JSON array from possibly noisy model output."""
    text = _strip_code_fence(raw)
    lo, hi = text.find("["), text.rfind("]")
    if lo < 0 or hi <= lo:
        return None
    try:
        data = json.loads(text[lo:hi + 1])
    except Exception:
        return None
    return data if isinstance(data, list) else None


def persona_compile_system() -> str:
    """System prompt for the one-shot persona -> numeric profile compile."""
    return "你是人格参数编译器。只输出 JSON，不要解释。"


def persona_compile_prompt(persona_text: str) -> str:
    """Build the one-shot persona compile prompt (interpretation-layer owned)."""
    return str(persona_text or "") + (
        "\n\n返回 JSON：\n"
        '{"O":0-1,"C":0-1,"E":0-1,"A":0-1,"N":0-1,\n'
        ' "stress_reactivity":0-1,"recovery_rate":0-1,\n'
        ' "social_baseline":0-1,"energy_baseline":0-1,\n'
        ' "curiosity_baseline":0-1,"safety_baseline":0-1,\n'
        ' "da_baseline":0-1,"oa_baseline":0-1,"ht_baseline":0-1,\n'
        ' "autonomy_gain":0-1.5,"baseline_v":-1..1,"baseline_a":0-1,\n'
        ' "learning_rate":0.01-0.12,\n'
        ' "schema":["最多6条，每条不超过40字的自我/关系先验（如：难过时更需要被听见）"]}\n'
        "只输出 JSON。"
    )


def parse_persona_profile(raw: str, defaults: dict) -> dict:
    """Parse + bound a model-compiled persona profile.

    Unknown keys and out-of-range values are dropped/clamped; malformed output
    falls back to the deterministic defaults.
    """
    merged = dict(defaults or {})
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return merged
    for key, (low, high) in PROFILE_RANGES.items():
        if key not in data:
            continue
        default = merged.get(key, 0.0)
        merged[key] = round(_bounded(data.get(key), low, high, float(default or 0.0)), 6)
    return merged


def _clean_schema_list(value) -> list:
    """Bound the self/relationship schema slots proposed by the persona model."""
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = _clean_text(item, 60)
        if not text or text in out:
            continue
        out.append(text)
        if len(out) >= 6:
            break
    return out


def parse_persona_compile(raw: str, defaults: dict) -> dict:
    """Parse the persona-compile payload: numeric profile + schema slots.

    The model proposes schema phrases; this layer bounds them (max 6, <=60
    chars, deduped). It only returns data; the caller decides persistence.
    """
    profile = parse_persona_profile(raw, defaults)
    data = _extract_json_object(raw)
    schema = _clean_schema_list(data.get("schema")) if isinstance(data, dict) else []
    return {"profile": profile, "schema": schema}


def memory_summary_prompt(texts) -> str:
    """Prompt for consolidating memories + proposing bounded write candidates.

    One call does both jobs: the LLM proposes candidates, the biological layer
    decides ADD/UPDATE via its deterministic policy (DELETE is never accepted).
    """
    joined = "\n".join("- " + str(t)[:500] for t in (texts or []) if str(t).strip())
    return ("把下面这些长期记忆整理成一个 JSON 对象，只输出 JSON、不要代码块、不要解释：\n"
            '{"summary":"不超过 180 字的中文摘要，保留人物、关系、偏好、承诺、事件和情绪变化，不要编造",\n'
            ' "candidates":[{"text":"一条长期有用的事实/偏好/承诺，40字以内",'
            '"source":"told|inferred","confidence":0.0-1.0,"kind":"add|update"}]}\n'
            "规则：candidates 最多 3 条；只提取长期有用的信息（偏好、关系、承诺、重要经历），一次性闲聊不要提；\n"
            "已有相似记忆用 update，否则 add；绝对不要输出 delete；没有则输出空数组。\n\n" + joined)


def parse_memory_summary(raw: str, limit: int = 240) -> str:
    """Parse a model summary into bounded plain text for the biological layer."""
    text = _strip_code_fence(raw)
    text = re.sub(r"\s+", " ", text).strip().strip("\"'“”")
    for prefix in ("摘要：", "摘要:", "总结：", "总结:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text[:max(1, int(limit))]


def parse_memory_candidates(raw) -> list:
    """Validate LLM-proposed memory write candidates (proposals only).

    The biological layer never lets a candidate DELETE memory; candidates may
    only be add/update suggestions, carry an inferred/told source, and their
    confidence is capped below direct-user confidence.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        if len(out) >= 3:
            break
        text = _clean_text(item.get("text"), 300)
        if len(text) < 4:
            continue
        source = str(item.get("source") or "inferred").strip().lower()
        if source not in ("told", "inferred"):
            source = "inferred"
        confidence = _bounded(item.get("confidence"), 0.2, 0.7, 0.5)
        kind = str(item.get("kind") or "add").strip().lower()
        if kind not in ("add", "update"):
            kind = "add"
        out.append({"text": text, "source": source,
                    "confidence": round(confidence, 3), "kind": kind})
    return out


def parse_memory_summary_payload(raw: str) -> dict:
    """Parse consolidation output into {summary, candidates}.

    Plain-text summaries (legacy/fake providers) are still accepted; only a
    JSON object with summary/candidates enables the proposed-update path.
    """
    data = _extract_json_object(raw)
    if isinstance(data, dict):
        # Any JSON object is treated as the payload form; a bare "{}" must not
        # become a literal summary entry.
        return {"summary": parse_memory_summary(str(data.get("summary") or "")),
                "candidates": parse_memory_candidates(data.get("candidates"))}
    return {"summary": parse_memory_summary(raw), "candidates": []}


def parse_event_ranking(raw: str) -> list:
    """Parse + validate the ranked-event extraction output."""
    items = _extract_json_array(raw)
    if not isinstance(items, list):
        return []
    out = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        body = _clean_text(item.get("event"), 600)
        if not body:
            continue
        importance = _bounded(item.get("importance"), 0.0, 1.0, 0.0)
        emotion = str(item.get("emotion") or "neutral").strip()
        if emotion not in _EMOTIONS:
            emotion = "neutral"
        centrality = _bounded(item.get("centrality"), 0.0, 1.0, importance)
        out.append({
            "title": _clean_text(item.get("title") or "重要事件", 80),
            "event": body,
            "event_key": _clean_text(item.get("event_key"), 80),
            "centrality": round(centrality, 3),
            "central_details": _clean_text(item.get("central_details") or body, 400),
            "peripheral_details": _clean_text(item.get("peripheral_details"), 300),
            "meaning_to_her": _clean_text(item.get("meaning_to_her"), 400),
            "reflection": _clean_text(item.get("reflection"), 400),
            "emotion": emotion,
            "importance": round(importance, 3),
        })
    return out


def parse_event_summary(raw: str) -> dict:
    """Parse + validate the single-event summary output."""
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return {}
    return {
        "title": _clean_text(data.get("title"), 80),
        "event": _clean_text(data.get("event"), 600),
        "meaning_to_her": _clean_text(data.get("meaning_to_her"), 400),
        "reflection": _clean_text(data.get("reflection"), 400),
    }


def parse_image_caption(raw: str, limit: int = 1600) -> str:
    """Bound a vision-model caption before it enters the biological layer."""
    text = str(raw or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max(1, int(limit))]


def parse_insight(raw: str, limit: int = 500) -> str:
    """Parse + validate the cross-event insight output."""
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return ""
    return _clean_text(data.get("insight"), limit)

