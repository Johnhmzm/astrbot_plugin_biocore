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


def image_caption_prompt(base_prompt: str = "") -> str:
    """Prompt used for the vision model caption request.

    The caller may supply an AstrBot/user configured prompt; the deterministic
    fallback lives here so main.py never assembles prompt text itself.
    """
    text = str(base_prompt or "").strip()
    return text or "请客观描述这张图片，供角色扮演聊天使用。"


def event_summary_prompt(texts) -> str:
    joined = "\n".join("- " + str(t)[:400] for t in (texts or [])[:12])
    return ("把下面一段聊天记录总结成一个 JSON 对象，只输出 JSON、不要代码块、不要解释：\n"
            '{"title":"短标题","event":"事件经过≤80字","meaning_to_her":"对她的意义≤60字","reflection":"事件感悟≤60字"}\n'
            "事件覆盖整件事，意义只写她的感受/立场/关系变化；reflection 字段是「事件感悟（单事件）」，不复述事件；不编造。\n\n" + joined)


def insight_prompt(events) -> str:
    joined = "\n".join("- " + str(e.get("title") or "") + "：" + str(e.get("event") or "")[:220]
                        for e in (events or [])[:6])
    return ("下面是最近几条重要事件。请只输出一个 JSON 对象，不要解释：\n"
            '{"insight":"从这些事件之间提炼出的一条长期模式洞察（跨事件，80字以内，不要复述事件）"}\n\n' + joined)


def render_compact(core, memory="", events="", self_model=None, user=None,
                   image="", kb="", speaker="", voice="", memory_meta=None,
                   open_loops=None, open_loops_due=0, answer_confidence=None,
                   strategy_hint="", continuity=None) -> str:
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
    try:
        if float(getattr(core, "boredom", 0.0) or 0.0) >= 0.7:
            cp += " bored"
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
        # Only surface the source when it is actually uncertain; direct input is
        # assumed and does not need extra tokens every turn.
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
                # High confidence is the default; only low values change behavior.
                if _aconf < 0.65:
                    cp += " ansc=%.2f" % _aconf
            except Exception:
                pass
        _dests = mm.get("destinations")
        if isinstance(_dests, dict) and len(_dests) >= 2:
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
    if strategy_hint:
        # L-T02..L-T12: one bounded strategy/cause/receipt token (never a
        # second line; the interpretation layer owns the text).
        cp += " | hint=" + _hint(strategy_hint, 120)
    if continuity:
        # A4 continuity opener: at most one bounded "last talk" fragment on
        # the same [BC] line. No line is added and no empty placeholder is
        # emitted when there is no history data.
        _cont = continuity if isinstance(continuity, str) else continuity_block(continuity)
        if _cont:
            cp += " | cont=" + _hint(_cont, CONTINUITY_LIMIT)
    # Minimal fallback instruction only; full format lives in the
    # biocore-interpretation skill (loaded on demand) to save per-turn tokens.
    cp += ("\n[BC-Return] 末尾只输出一个 <bc>{e,i}</bc>（可选 n/x）；"
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
        ' "schema":["最多6条，每条不超过40字的自我/关系先验（如：难过时更需要被听见）"],\n'
        ' "style":{"intimacy_style":"neutral|playful|gentle|reserved",\n'
        '          "address_terms":["最多3个称呼，每个≤12字"]}}\n'
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
            '{"summary":"≤180字摘要，保留人物/关系/偏好/承诺/事件/情绪变化，不编造",\n'
            ' "candidates":[{"text":"≤40字长期有用事实","source":"told|inferred",\n'
            ' "confidence":0.0-1.0,"kind":"add|update"}]}\n'
            "candidates≤3，只提长期有用信息（偏好/关系/承诺/重要经历）；相似用 update，否则 add；禁止 delete；没有给 []。\n\n" + joined)


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
    """Parse + validate the long-term pattern insight output."""
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return ""
    return _clean_text(data.get("insight"), limit)


# ---------------------------------------------------------------------------
# LLM v2 (L-T01..L-T12): deterministic strategy tokens, prompts, bounded parsers
# ---------------------------------------------------------------------------
HINT_LIMIT = 140
_WE_TYPES = ("nickname", "ritual", "anniversary", "inside_joke", "shared_object")
_REPAIR_TAGS = {"acknowledge", "apologize", "clarify", "commit", "space"}
_EMPATHY_TAGS = {"active_constructive", "supportive", "validate", "neutral"}
_PRAGMATICS_TAGS = {"clarify", "confirm", "hedge", "none"}
_HUMOR_TAGS = {"light", "none"}
_STYLE_TAGS = {"neutral", "playful", "gentle", "reserved"}


def _hint(text, limit=HINT_LIMIT):
    """One bounded single-line hint fragment (never multi-line prompt text)."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:max(1, int(limit))]


def _dict(value):
    return value if isinstance(value, dict) else {}


def _clean_str_list(value, each=80, most=3):
    out = []
    if not isinstance(value, (list, tuple)):
        return out
    for item in value:
        if not isinstance(item, str):
            continue
        text = _hint(item, each)
        if text and text not in out:
            out.append(text)
        if len(out) >= most:
            break
    return out


def _evidence_refs(value, allowed=None, most=8):
    refs = []
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, (str, int)) and str(item).strip():
                refs.append(_hint(item, 80))
    if allowed is not None:
        allowed_set = {str(x) for x in allowed}
        refs = [ref for ref in refs if ref in allowed_set]
    out = []
    for ref in refs:
        if ref not in out:
            out.append(ref)
    return out[:most]


def cause_question(text) -> bool:
    value = str(text or "")
    return any(cue in value for cue in
               ("为什么", "怎么知道", "怎么想到", "你记得", "你还记得", "怎么记得"))


def receipt_question(text) -> bool:
    value = str(text or "")
    return any(cue in value for cue in
               ("记得", "你听谁", "谁告诉", "来源", "怎么知道"))


def repair_strategy_block(repair_state, conflict_event=None) -> str:
    """L-T03 deterministic repair strategy token (no LLM, max one short line)."""
    state = _dict(repair_state)
    phase = str(state.get("phase") or "stable")
    if phase not in ("rupture", "repairing", "repaired"):
        return ""
    mapping = {
        "rupture": ("acknowledge", "先承认感受，不急着辩解"),
        "repairing": ("commit", "只给可执行的小承诺"),
        "repaired": ("acknowledge", "确认已修复，不反复追问"),
    }
    tag, note = mapping[phase]
    return _hint("repair=%s/%s %s" % (phase, tag, note), 90)


def event_polarity(event) -> str:
    """L-T04 deterministic event polarity from stored labels (no LLM)."""
    data = _dict(event)
    emotion = str(data.get("emotion") or "neutral").strip()
    try:
        importance = float(data.get("importance", 0.0) or 0.0)
    except Exception:
        importance = 0.0
    if importance < 0.6:
        return "neutral"
    if emotion == "joy":
        return "positive"
    if emotion in ("sadness", "anger", "fear", "loneliness"):
        return "negative"
    return "neutral"


def response_strategy_block(events, importance_min=0.6) -> str:
    """L-T04 deterministic response strategy (active-constructive/supportive)."""
    rows = [e for e in (events or []) if isinstance(e, dict)]
    rows.sort(key=lambda e: float(e.get("ts", 0) or 0), reverse=True)
    for event in rows[:3]:
        try:
            importance = float(event.get("importance", 0) or 0)
        except Exception:
            importance = 0.0
        if importance < float(importance_min):
            continue
        polarity = event_polarity(event)
        if polarity == "positive":
            return "resp=active_constructive"
        if polarity == "negative":
            emotion = str(event.get("emotion") or "neutral")
            if emotion in ("sadness", "fear", "loneliness"):
                return "resp=supportive"
            return "resp=validate"
    return ""


def grounding_check_block(memory_meta, text="") -> str:
    """L-T05 deterministic grounding/uncertainty hedge token."""
    meta = _dict(memory_meta)
    gate = str(meta.get("gate") or "none")
    if gate in ("semi", "force") or bool(meta.get("abstain")):
        return "ground=hedge"
    return ""


def memory_receipt_block(memory_meta, text="") -> str:
    """L-T09 deterministic memory receipt token; only on explicit receipt cue."""
    if not receipt_question(text):
        return ""
    meta = _dict(memory_meta)
    try:
        count = int(meta.get("count", 0) or 0)
    except Exception:
        count = 0
    if count <= 0:
        return "receipt=none"
    source = str(meta.get("source") or "unknown")[:10]
    try:
        confidence = max(0.0, min(1.0, float(meta.get("confidence", 0.0) or 0.0)))
    except Exception:
        confidence = 0.0
    return _hint("receipt=%s/%.2f" % (source, confidence), 60)


def cause_trace_block(trace, limit=3) -> str:
    """L-T02 deterministic retrieval-contribution trace (never LLM-generated)."""
    rows = [x for x in (trace or []) if isinstance(x, dict)][:max(1, int(limit))]
    parts = []
    for row in rows:
        entry_id = _hint(row.get("entry_id") or row.get("id") or "?", 20)
        try:
            score = float(row.get("score", 0.0) or 0.0)
        except Exception:
            score = 0.0
        parts.append("%s:%.2f" % (entry_id, score))
    if not parts:
        return ""
    return _hint("cause=" + ",".join(parts), 120)


def combine_strategy_hint(*parts) -> str:
    """Merge at most one deterministic fragment + one validated LLM tag."""
    values = [str(x).strip() for x in parts if str(x or "").strip()]
    if not values:
        return ""
    return _hint(" ".join(values), HINT_LIMIT)


# A4 continuity opener ("上次聊到"): deterministic, no LLM, at most one short
# fragment appended to the existing [BC] line. The caller must already have
# decided that history exists (returning after a break); this builder still
# returns "" for empty input so no placeholder can ever be injected.
CONTINUITY_LIMIT = 140
CONTINUITY_SUMMARY_LIMIT = 70
CONTINUITY_LOOP_LIMIT = 30


def continuity_block(continuity, limit=CONTINUITY_LIMIT) -> str:
    """Build the bounded A4 "last talk" fragment.

    Fields (all optional, caller passes raw bio data):
      summary:      last-session summary/title text (<=70 chars used)
      loops:        unfinished open-loop dicts (or strings), max 2 used
      relationship: {"closeness","conflict","repair","phase","absence"}
    Returns "" when every field is empty, so no-history turns stay untouched.
    """
    data = _dict(continuity)
    if not data:
        return ""
    parts = []
    summary = _hint(data.get("summary"), CONTINUITY_SUMMARY_LIMIT)
    if summary:
        parts.append("上次：" + summary)
    loops = []
    raw_loops = data.get("loops")
    if isinstance(raw_loops, (list, tuple)):
        for item in raw_loops[:2]:
            text = _hint(item.get("text") if isinstance(item, dict) else item,
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
    return _hint("；".join(parts), limit)


# ---------------------------------------------------------------------------
# LLM v2 prompts (interpretation layer owns all prompt text)
# ---------------------------------------------------------------------------

def relationship_impression_prompt(events, relationship=None) -> str:
    joined = "\n".join(
        "- id=%s 标题=%s 事件=%s 意义=%s 反思=%s" % (
            _hint(e.get("id") or "", 40), _hint(e.get("title") or "", 60),
            _hint(e.get("event") or "", 160), _hint(e.get("meaning_to_her") or "", 120),
            _hint(e.get("reflection") or "", 120))
        for e in (events or [])[:10] if isinstance(e, dict))
    rel = _dict(relationship)
    state = _dict(rel.get("state"))
    rel_line = "关系=%s" % _hint(
        "信任%.2f 亲近%.2f 冲突%.2f 修复%.2f" % tuple(
            float(state.get(k, 0.5) or 0.5) for k in ("trust", "closeness", "conflict", "repair")),
        100) if state else ""
    return ("下面是她最近的重要事件。请只输出一个 JSON 对象，不要解释：\n"
            '{"traits":["最多3条对她的关系印象，每条≤40字"],\n'
            ' "relation_events":["最多2条关系事件，每条≤60字"],\n'
            ' "we_memory_candidates":[{"type":"nickname|ritual|anniversary|inside_joke|shared_object",'
            '"text":"≤40字","confidence":0.0}],\n'
            ' "confidence":0.0,"evidence_refs":["只能引用下面出现过的 event id"]}\n'
            "规则：traits≤3、relation_events≤2、we_memory_candidates≤2；"
            "evidence_refs 必填且只能来自输入事件；没有足够证据就输出 {}。\n\n"
            + (rel_line + "\n" if rel_line else "") + joined)


def parse_relationship_impression(raw, allowed_refs=None) -> dict:
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return {}
    refs = _evidence_refs(data.get("evidence_refs"), allowed_refs)
    if not refs:
        return {}
    traits = _clean_str_list(data.get("traits"), 60, 3)
    relation_events = _clean_str_list(data.get("relation_events"), 80, 2)
    candidates = []
    for item in data.get("we_memory_candidates") or []:
        if not isinstance(item, dict):
            continue
        mtype = str(item.get("type") or "").strip()
        text = _hint(item.get("text") or "", 40)
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0) or 0)))
        except Exception:
            continue
        if mtype not in _WE_TYPES or not text or confidence < 0.55:
            continue
        candidates.append({"type": mtype, "text": text,
                           "confidence": round(confidence, 3)})
        if len(candidates) >= 2:
            break
    confidence = _bounded(data.get("confidence"), 0.0, 1.0, 0.0)
    return {"traits": traits, "relation_events": relation_events,
            "we_memory_candidates": candidates,
            "confidence": round(confidence, 3), "evidence_refs": refs}


def repair_hint_prompt(repair_state, conflict_event=None) -> str:
    state = _dict(repair_state)
    return ("根据冲突后的修复状态，只输出一个 JSON 对象：\n"
            '{"strategy":"acknowledge|apologize|clarify|commit|space"}\n'
            "规则：stable 不输出；不替用户道歉；space 不等于冷处理；只给策略，不写完整句子。\n"
            "状态：phase=%s attempts=%s\n" % (
                _hint(state.get("phase") or "stable", 20),
                _hint(state.get("repair_attempts") or 0, 8)))


def parse_repair_hint(raw) -> str:
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return ""
    tag = str(data.get("strategy") or "").strip()
    return tag if tag in _REPAIR_TAGS else ""


def empathy_hint_prompt(events) -> str:
    joined = "\n".join(
        "- emotion=%s importance=%.2f meaning=%s" % (
            _hint(e.get("emotion") or "neutral", 20),
            float(e.get("importance", 0) or 0),
            _hint(e.get("meaning_to_her") or "", 100))
        for e in (events or [])[:5] if isinstance(e, dict))
    return ("根据最近事件选择回应策略，只输出 JSON：\n"
            '{"strategy":"active_constructive|supportive|validate|neutral"}\n'
            "规则：好消息用 active_constructive；坏消息用 supportive/validate；不写完整安慰句；不表演。\n\n"
            + joined)


def parse_empathy_hint(raw) -> str:
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return ""
    tag = str(data.get("strategy") or "").strip()
    return tag if tag in _EMPATHY_TAGS else ""


def pragmatics_hint_prompt(memory_meta) -> str:
    meta = _dict(memory_meta)
    return ("根据记忆不确定性选择会话修复提示，只输出 JSON：\n"
            '{"strategy":"clarify|confirm|hedge|none"}\n'
            "规则：不确定就 hedge；指代不清就 clarify；需要确认就 confirm；不要每轮追问。\n"
            "状态：gate=%s abstain=%s count=%s\n" % (
                _hint(meta.get("gate") or "none", 12),
                bool(meta.get("abstain")),
                _hint(meta.get("count") or 0, 8)))


def parse_pragmatics_hint(raw) -> str:
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return ""
    tag = str(data.get("strategy") or "").strip()
    return tag if tag in _PRAGMATICS_TAGS else ""


def humor_hint_prompt(relationship=None) -> str:
    state = _dict(_dict(relationship).get("state"))
    return ("根据关系状态判断本轮是否适合轻幽默，只输出 JSON：\n"
            '{"strategy":"light|none"}\n'
            "规则：冲突/修复阶段/低信任时用 none；不嘲讽、不冒犯；不写句子。\n"
            "状态：信任%.2f 冲突%.2f\n" % (
                float(state.get("trust", 0.5) or 0.5),
                float(state.get("conflict", 0.5) or 0.5)))


def parse_humor_hint(raw) -> str:
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return ""
    tag = str(data.get("strategy") or "").strip()
    return tag if tag in _HUMOR_TAGS else ""


def tom_prompt(user_data, recent_turns=None, memory_lines=None) -> str:
    user = _dict(user_data)
    turns = "\n".join("- " + _hint(x, 100) for x in (recent_turns or [])[:6])
    mem = "\n".join("- id=" + _hint(x, 40) for x in (memory_lines or [])[:6])
    return ("推断用户当前的信念/愿望/意图，只输出 JSON：\n"
            '{"beliefs":["≤3条，每条≤40字"],"desires":["≤3条"],'
            '"intentions":["≤3条"],"confidence":0.0,"evidence_refs":["只能引用输入轮次/记忆 id"]}\n'
            "规则：不确定就不要写；evidence_refs 必填且只能引用下面 memory id；不贴人格标签；不写生物层状态。\n"
            "用户：%s\n%s%s" % (_hint(user.get("sender_name") or user.get("sender_id") or "未知", 40),
                                mem + ("\n" if mem else ""), turns))


def parse_tom_update(raw, allowed_refs=None) -> dict:
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return {}
    refs = _evidence_refs(data.get("evidence_refs"), allowed_refs)
    if not refs:
        return {}
    return {
        "beliefs": _clean_str_list(data.get("beliefs"), 60, 3),
        "desires": _clean_str_list(data.get("desires"), 60, 3),
        "intentions": _clean_str_list(data.get("intentions"), 60, 3),
        "confidence": round(_bounded(data.get("confidence"), 0.0, 1.0, 0.0), 3),
        "evidence_refs": refs,
    }


def diary_prompt(digest, event_titles=None) -> str:
    data = _dict(digest)
    titles = "\n".join("- " + _hint(x, 80) for x in (event_titles or [])[:6])
    return ("根据今天的确定性摘要写一条日记，只输出 JSON：\n"
            '{"diary":"≤120字，只能写摘要里出现过的事","evidence":["只能引用摘要/事件 id"]}\n'
            "规则：不编造未出现的事件；不写用户隐私；只写她的第一人称记录。\n"
            "日期=%s 主情绪=%s 互动=%s 事件=%s\n%s" % (
                _hint(data.get("date") or "", 20),
                _hint(data.get("dominant_emotion") or "neutral", 20),
                _hint(data.get("interaction_count") or 0, 8),
                _hint(",".join(str(x) for x in (data.get("event_ids") or [])[:6]), 160),
                titles))


def parse_diary(raw, allowed_event_ids=None) -> dict:
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return {}
    text = _hint(data.get("diary") or "", 120)
    refs = _evidence_refs(data.get("evidence"), allowed_event_ids)
    if not text or not refs:
        return {}
    return {"diary": text, "evidence": refs}


def relationship_narrative_prompt(relationship) -> str:
    rel = _dict(relationship)
    state = _dict(rel.get("state"))
    marks = [m for m in (rel.get("milestones") or []) if isinstance(m, dict)][:5]
    mark_text = "\n".join("- " + _hint(m.get("key") or m.get("type") or "", 80) for m in marks)
    return ("根据关系状态与里程碑写一段简短关系叙述，只输出 JSON：\n"
            '{"narrative":"≤200字","evidence_refs":["只能引用里程碑/事件 id"]}\n'
            "规则：只写确定性字段与里程碑；不编造未发生的事；不宣称真人感情。\n"
            "状态：信任%.2f 亲近%.2f 冲突%.2f 修复%.2f\n%s" % (
                float(state.get("trust", 0.5) or 0.5),
                float(state.get("closeness", 0.5) or 0.5),
                float(state.get("conflict", 0.5) or 0.5),
                float(state.get("repair", 0.0) or 0.0), mark_text))


def parse_relationship_narrative(raw, allowed_refs=None) -> dict:
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return {}
    text = _hint(data.get("narrative") or "", 200)
    refs = _evidence_refs(data.get("evidence_refs"), allowed_refs)
    if not text or not refs:
        return {}
    return {"narrative": text, "evidence_refs": refs}


def _bounded_style(data) -> dict:
    style = _dict(data)
    tag = str(style.get("intimacy_style") or "neutral").strip()
    if tag not in _STYLE_TAGS:
        tag = "neutral"
    terms = _clean_str_list(style.get("address_terms"), 12, 3)
    return {"intimacy_style": tag, "address_terms": terms}


def parse_persona_compile(raw, defaults) -> dict:
    """Parse persona-compile payload: numeric profile + schema slots + style."""
    profile = parse_persona_profile(raw, defaults)
    data = _extract_json_object(raw)
    schema = _clean_schema_list(data.get("schema")) if isinstance(data, dict) else []
    style = _bounded_style(data.get("style")) if isinstance(data, dict) else _bounded_style({})
    return {"profile": profile, "schema": schema, "style": style}

