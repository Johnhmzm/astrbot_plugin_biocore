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


# task-39: deterministic parse telemetry (read-only; never feeds prompts).
PARSE_STATS = {"calls": 0, "bad_json": 0, "repaired": 0, "dropped": 0,
               "unknown_keys": 0, "unknown_labels": 0, "residual_stripped": 0,
               "whitelist_rejects": 0}

_BC_TAG_RE = re.compile(r"<(?:bc|biocore)\b[^>]*>(.*?)</(?:bc|biocore)>",
                        re.S | re.I)
_BC_RESIDUE_RE = re.compile(r"</?(?:bc|biocore)\b[^>]*>", re.I)


def _repair_json_payload(payload) -> dict | None:
    """One deterministic repair attempt for a malformed <bc> JSON payload."""
    text = str(payload or "").strip()
    text = re.sub(r"^\s*```(?:json)?|\`\`\`\s*$", "", text,
                  flags=re.I | re.M).strip()
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for cand in list(candidates):
        candidates.append(re.sub(r",\s*([}\]])", r"\1", cand))
        candidates.append(re.sub(r"'([^']*)'", r'"\1"', cand))
    for cand in candidates:
        try:
            data = json.loads(cand)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def parse_response(raw: str, whitelist=None):
    """Parse LLM output and return (clean_text, validated_update|None).

    task-39 hardening: one deterministic repair attempt for bad JSON; unknown
    keys/labels are counted; residual <bc> variants are always stripped from the
    visible reply (parse failure must not leak the hidden tag). A configurable
    whitelist defaults to the unchanged legacy key set.
    """
    text = str(raw or "")
    PARSE_STATS["calls"] += 1
    m = _BC_TAG_RE.search(text)
    if not m:
        if _BC_RESIDUE_RE.search(text):
            PARSE_STATS["residual_stripped"] += 1
            text = _BC_RESIDUE_RE.sub("", text).strip()
        return text, None
    clean = (text[:m.start()] + text[m.end():]).strip()
    payload = str(m.group(1) or "").strip()
    data = None
    try:
        data = json.loads(payload)
    except Exception:
        PARSE_STATS["bad_json"] += 1
        data = _repair_json_payload(payload)
        if data is None:
            PARSE_STATS["dropped"] += 1
            clean = _BC_RESIDUE_RE.sub("", clean).strip()
            return clean, None
        PARSE_STATS["repaired"] += 1
    if not isinstance(data, dict):
        PARSE_STATS["dropped"] += 1
        return clean, None
    keys = whitelist if isinstance(whitelist, (set, list, tuple)) and whitelist \
        else _ALLOWED_OUTPUT_KEYS
    allowed = {}
    for key, value in data.items():
        if key in keys:
            allowed[key] = value
        else:
            PARSE_STATS["unknown_keys"] += 1
            PARSE_STATS["whitelist_rejects"] += 1
    update = _with_label_deltas(allowed)
    for label_key in ("emotion", "e", "need", "n", "expression", "x"):
        if label_key not in allowed:
            continue
        raw_label = str(allowed.get(label_key) or "").strip()
        if label_key in ("emotion", "e") and raw_label not in _ALLOWED:
            PARSE_STATS["unknown_labels"] += 1
        elif label_key in ("need", "n") and raw_label not in _ALLOWED_NEEDS:
            PARSE_STATS["unknown_labels"] += 1
        elif label_key in ("expression", "x") and raw_label not in _ALLOWED_EXPRESSIONS:
            PARSE_STATS["unknown_labels"] += 1
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
            '{"title":"短标题","event":"完整事件经过","meaning_to_her":"对她的意义","reflection":"事件感悟",'
            '"big_summary":"完整总结（不设固定字数上限）","small_summary":"≤80字 tooltip 短总结",'
            '"emotion_nuance":["0-3个隐含/复合情绪中文标签，如 遗憾/难过/失落/释然/心动；没有就空数组，不要重复主情绪/次情绪"],'
            '"emotion_layers":[{"emotion":"joy","intensity":0.80,"confidence":0.90,"centrality":0.70,"evidence":"老板把喜欢限定为干员喜欢"},{"emotion":"sadness","intensity":0.45,"confidence":0.80,"centrality":0.60,"evidence":"她笑着但语气低下去"}]}\n'
            "基于提供的聊天事件完整总结整件事，不设固定字数上限；big_summary 是完整总结，small_summary 是给 tooltip 的≤80字短总结；"
            "只总结事件本身，不要把原始聊天上下文原样拼进摘要；意义只写她的感受/立场/关系变化；"
            "reflection 字段是「事件感悟（单事件）」，不复述事件；不编造。"
            "emotion_layers 必须基于总结出的事件给出全部识别到的情绪（0-6 个，含主情绪，emotion 用 EMOTION_SPECTRUM 英文 key）；"
            "每个情绪给四个独立信号：intensity 0-1（该情绪强度）、confidence 0-1（判断置信）、centrality 0-1（对该事件核心程度）、evidence（文本依据短句）；"
            "不要把强度归一化为总和 1、不要为了凑总和而虚增/压小，也不要只取 top3；"
            "没有依据就给空数组，不要用固定权重凑数；emotion_nuance 的标签只是候选，emotion_layers 的 p 由你按事件实际给出。"
            "emotion_nuance 只提取主情绪/次情绪之外隐含或复合的情绪层次（0-3 个中文短标签），没有就输出空数组，不能编造。"
            "遇到表白/期待被降级、关系边界回退、心意被限定为玩笑等场景，如果文本里确有难过/失落的依据，"
            "emotion_nuance 要考虑 遗憾/难过/失落 等词；依据不足时不要为了凑数编造。\n\n" + joined)


def insight_prompt(events) -> str:
    joined = "\n".join("- " + str(e.get("title") or "") + "：" + str(e.get("event") or "")[:220]
                        for e in (events or [])[:6])
    return ("下面是最近几条重要事件。请只输出一个 JSON 对象，不要解释：\n"
            '{"insight":"从这些事件之间提炼出的一条长期模式洞察（跨事件，80字以内，不要复述事件）"}\n\n' + joined)


def _brief_clean(text, limit=30):
    value = str(text or "").strip()
    value = value.lstrip("- ")
    for prefix in ("用户：", "用户:", "你(已总结)：", "你："):
        if value.startswith(prefix):
            value = value[len(prefix):]
    value = __import__("re").sub(r"\d+\.\d+", "", value)
    value = __import__("re").sub(r"\s+", " ", value).strip("；;，。 ")
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
    # Relationship stance.
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
    # One high-confidence memory, else one recent event.
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
    # Continuity.
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
    brief = __import__("re").sub(r"\s+", " ", brief).strip()
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


def render_compact(core, memory="", events="", self_model=None, user=None,
                   image="", kb="", speaker="", voice="", memory_meta=None,
                   open_loops=None, open_loops_due=0, answer_confidence=None,
                   strategy_hint="", continuity=None, prompt_mode="telemetry",
                   workspace_token="", brevity="normal") -> str:
    """Render biological state into the single compact block the LLM sees.

    The interpretation layer owns this string; callers pass raw state/data and
    never build prompt text themselves. Optional fields are rendered only when
    present so the block stays short (prefix-cache friendly).
    """
    if str(prompt_mode or "telemetry").lower() == "semantic":
        try:
            _sem = render_semantic(core, memory=memory, events=events, user=user,
                                    continuity=continuity, memory_meta=memory_meta,
                                    open_loops=open_loops)
            if 40 <= len(_sem) <= 300:
                return _sem + _return_contract(memory_meta)
        except Exception:
            pass
    it = core.intent()
    cp = ("[BC] v=%.2f a=%.2f d=%.2f s=%.2f t=%.2f e=%s c=%s n=%s plan=%s reg=%s" % (
        float(core.v), float(core.a), float(core.d), float(core.social), float(core.trust),
        it.get("emotion") or "neutral", it.get("compound") or "-",
        it.get("need") or "talk", plan(core), it.get("regulation") or "none"))
    try:
        # task-35: workspace token from the minimal autonomy loop. Only the
        # caller passes it when autonomy_loop_enabled (default OFF => "").
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
    _brevity = str(brevity or "normal").strip().lower()
    _hint_cap = 120
    if _brevity == "short":
        _hint_cap = 60
    elif _brevity == "medium":
        _hint_cap = 90
    if strategy_hint:
        # L-T02..L-T12: one bounded strategy/cause/receipt token (never a
        # second line; the interpretation layer owns the text). task-35:
        # refusal posture may shorten the hint cap (default "normal" = 120).
        cp += " | hint=" + _hint(strategy_hint, _hint_cap)
    _btok = brevity_token(_brevity)
    if _btok:
        cp += " | " + _btok
    if continuity:
        # A4 continuity opener: at most one bounded "last talk" fragment on
        # the same [BC] line. No line is added and no empty placeholder is
        # emitted when there is no history data.
        _cont = continuity if isinstance(continuity, str) else continuity_block(continuity)
        if _cont:
            cp += " | cont=" + _hint(_cont, CONTINUITY_LIMIT)
    # Minimal fallback instruction only; full format lives in the
    # biocore-interpretation skill (loaded on demand) to save per-turn tokens.
    cp += _return_contract(mm)
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
}


def _bounded(value, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(float(low), min(float(high), number))


def _summary_text(value, max_chars: int = 0) -> str:
    text = str(value or "").strip()
    try:
        cap = int(max_chars or 0)
    except Exception:
        cap = 0
    return text[:cap] if cap > 0 else text


def _clean_text(value, limit: int = 400) -> str:
    return str(value or "").strip()[:max(1, int(limit))]


def clean_event_title(value, limit: int = 32, fallback: str = "") -> str:
    """Turn a raw event first sentence into a short, readable event title.

    Deterministic fallback titles used to be the ugly raw first sentence. This
    strips speaker prefixes, parenthetical actions, quotes and the stray "在。",
    prefers the first sentence, and bounds the result (default <=32 chars).
    Empty input returns fallback (caller usually passes 对话事件).
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return str(fallback or "")
    # speaker prefix: 老板说： / 她说， / 对方表示:
    text = re.sub(
        r"^(?:[\u4e00-\u9fa5A-Za-z0-9_]{1,12})"
        r"(?:说|说道|讲|问|答|回复|表示|提到|补充)(?:[:：,，]|\s)+",
        "", text)
    # parenthetical actions: （在走廊里）/ (笑) / 【动作】
    text = re.sub(r"[（(【\[][^）)】\]]{0,40}[）)】\]]", "", text)
    # quote marks and stray "在。"
    text = re.sub(r"[“”\"'‘’「」『』]", "", text)
    text = text.replace("在。", "")
    text = text.strip(" ，,。.;；:：!?！？、")
    # first sentence only
    match = re.search(r"[。！？!?；;]", text)
    if match:
        text = text[:match.start()]
    text = text.strip(" ，,。.;；:!?！？、").strip()
    if not text:
        return str(fallback or "")
    lim = max(1, int(limit or 32))
    if len(text) > lim:
        text = text[:max(1, lim - 1)].rstrip() + "…"
    return text


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
            '{"summary":"完整摘要，保留人物/关系/偏好/承诺/事件/情绪变化，不编造",\n'
            ' "candidates":[{"text":"≤40字长期有用事实","source":"told|inferred",\n'
            ' "confidence":0.0-1.0,"kind":"add|update"}]}\n'
            "summary 按提供的记忆上下文完整总结，不设固定字数上限；只总结记忆本身，不要把原始上下文原样拼进摘要；"
            "candidates≤3，只提长期有用信息（偏好/关系/承诺/重要经历）；相似用 update，否则 add；禁止 delete；没有给 []。\n\n" + joined)


def parse_memory_summary(raw: str, limit: int = 0) -> str:
    """Parse a model summary into bounded plain text for the biological layer."""
    text = _strip_code_fence(raw)
    text = re.sub(r"\s+", " ", text).strip().strip("\"'“”")
    for prefix in ("摘要：", "摘要:", "总结：", "总结:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return _summary_text(text, limit)


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


def parse_memory_summary_payload(raw: str, limit: int = 0) -> dict:
    """Parse consolidation output into {summary, candidates}.

    Plain-text summaries (legacy/fake providers) are still accepted; only a
    JSON object with summary/candidates enables the proposed-update path.
    """
    data = _extract_json_object(raw)
    if isinstance(data, dict):
        # Any JSON object is treated as the payload form; a bare "{}" must not
        # become a literal summary entry.
        return {"summary": parse_memory_summary(str(data.get("summary") or ""), limit),
                "candidates": parse_memory_candidates(data.get("candidates"))}
    return {"summary": parse_memory_summary(raw, limit), "candidates": []}


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


_NUANCE_EMOTION_MAP = {
    "遗憾": "disappointment",
    "失望": "disappointment",
    "失落": "sadness",
    "难受": "sadness",
    "难过": "sadness",
    "委屈": "sadness",
    "心痛": "sadness",
    "尴尬": "awkwardness",
    "释然": "contentment",
    "松口气": "contentment",
    "心动": "adoration",
    "害怕": "fear",
    "担心": "anxiety",
    "生气": "anger",
    "不甘": "anger",
    "内疚": "guilt",
    "怀念": "nostalgia",
    "孤独": "loneliness",
}


def nuance_emotion_key(label) -> str:
    """Map a Chinese emotion-nuance label to an EMOTION_SPECTRUM key (task-68).

    Used only to build fallback emotion_layers for OLD events (layers missing)
    on regenerate; unknown labels return "" so no ring is fabricated.
    """
    text = re.sub(r"\s+", "", str(label or ""))
    if not text:
        return ""
    direct = _NUANCE_EMOTION_MAP.get(text)
    if direct:
        return direct
    for word, key in _NUANCE_EMOTION_MAP.items():
        if word and word in text:
            return key
    return ""


def clean_emotion_nuance(value, limit: int = 3) -> list:
    """Normalize the hidden/composite emotion layer (task-64).

    Only short Chinese-ish labels are kept (max limit, deduped, no empty
    entries). Missing/garbage input returns [] -- the deterministic fallback
    never fabricates a nuance layer. A plain string is tolerated by splitting
    common separators so an older model's output still parses.
    """
    if isinstance(value, str):
        raw = re.split(r"[/、,，;；·|]+", value)
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        return []
    out = []
    for item in raw:
        text = re.sub(r"\s+", "", str(item or ""))
        text = text.strip(" \t\r\n，。；、,.!?！？:：;\"'“”‘’()（）[]【】")
        if not text or len(text) > 12:
            continue
        if not re.search(r"[\u4e00-\u9fff]", text):
            continue
        if text in out:
            continue
        out.append(text)
        if len(out) >= max(1, int(limit or 0)):
            break
    return out[:max(0, int(limit or 0))]


def clean_emotion_layers(value, limit: int = 6) -> list:
    """Validate summary-provided emotion proportions (task-68 correction).

    The event summary returns ALL recognized emotions (0-6), each with an
    INDEPENDENT 0-1 intensity in p (no requirement to sum to 1, no global
    normalization). Entries need a non-empty emotion key and p>0; the list is
    deduped, sorted by intensity and capped at 6. Missing/garbage -> [].
    """
    if not isinstance(value, (list, tuple)):
        return []
    def _clamp_signal(raw) -> float:
        try:
            value_f = float(raw)
        except Exception:
            return 0.0
        return round(max(0.0, min(1.0, value_f)), 4)

    out = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get("emotion") or "").strip().lower()
        intensity = item.get("intensity")
        if intensity is None:
            intensity = item.get("p")   # backward compatibility
        intensity = _clamp_signal(intensity)
        confidence = (0.5 if item.get("confidence") is None
                      else _clamp_signal(item.get("confidence")))
        centrality = (0.5 if item.get("centrality") is None
                      else _clamp_signal(item.get("centrality")))
        evidence = str(item.get("evidence") or "").strip()[:120]
        if not key or intensity <= 0 or key in seen:
            continue
        seen.add(key)
        out.append({"emotion": key, "intensity": intensity,
                    "confidence": confidence, "centrality": centrality,
                    "evidence": evidence})
        if len(out) >= max(1, int(limit or 0)):
            break
    # task-68 final: these are independent signals, NOT shares. Do not
    # normalize to 1; keep the four signals for the ring scorer.
    out.sort(key=lambda item: item["intensity"], reverse=True)
    return out


def parse_event_summary(raw: str, max_chars: int = 0) -> dict:
    """Parse the single-event summary; summary fields are uncapped by default."""
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        return {}
    title_text = _clean_text(data.get("title"), 80)
    event_text = _summary_text(data.get("event"), max_chars)
    big_text = _summary_text(data.get("big_summary") or event_text or title_text, max_chars)
    small_seed = str(data.get("small_summary") or big_text or event_text or title_text).strip()
    small_text = _clean_text(small_seed, 80)
    return {
        "title": title_text,
        "event": event_text,
        "meaning_to_her": _summary_text(data.get("meaning_to_her"), max_chars),
        "reflection": _summary_text(data.get("reflection"), max_chars),
        "big_summary": big_text,
        "small_summary": small_text,
        "emotion_nuance": clean_emotion_nuance(data.get("emotion_nuance")),
        "emotion_layers": clean_emotion_layers(data.get("emotion_layers")),
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


def refusal_strategy_block(protocol) -> str:
    """G2/L9: bounded refusal-posture token from refusal_protocol (no LLM).

    Emits only the posture label; it never decides whether to reply, never
    carries a policy sentence, and renders nothing below the pressure
    threshold (protocol mode "comply"). Callers pass the raw protocol dict.
    """
    mode = str(_dict(protocol).get("mode") or "comply")
    if mode not in ("negotiate", "decline"):
        return ""
    return _hint("refuse=" + mode, 40)


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


def proposal_hint_block(impression=None, tom=None, diary=None,
                        narrative=None) -> str:
    """task-35: deterministic [BC] consumer for proposal-only outputs.

    Only called when the corresponding per-function switch is ON, so the
    default (all proposal functions OFF) renders nothing and the [BC] line is
    byte-identical to 1.2.99. No LLM, bounded (<=140 chars), never a second line.
    """
    parts = []
    imp = _dict(impression)
    traits = []
    for item in (imp.get("annotations") or []):
        if isinstance(item, dict) and str(item.get("kind") or "") == "trait":
            text = str(item.get("text") or "").strip()[:24]
            if text and text not in traits:
                traits.append(text)
    if traits:
        parts.append("imp=" + "|".join(traits[:2]))
    tom_data = _dict(tom)
    beliefs = [str(x).strip()[:24] for x in (tom_data.get("beliefs") or [])
               if str(x or "").strip()]
    if beliefs:
        parts.append("tom=" + beliefs[-1])
    if diary:
        parts.append("diary=" + str(diary).strip()[:12])
    if narrative:
        parts.append("narr=" + str(narrative).strip()[:40])
    if not parts:
        return ""
    return _hint(" ".join(parts), 140)


def brevity_token(brevity) -> str:
    """task-35: bounded refusal-brevity token (only when the switch is on)."""
    mode = str(brevity or "normal").strip().lower()
    if mode not in ("short", "medium"):
        return ""
    return _hint("brevity=" + mode, 24)


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


def relationship_impression_template(relationship, evidence_count: int = 0) -> dict:
    """A3: deterministic relationship-impression proposal (no LLM, bounded).

    Used when the relationship_impression LLM function is off (the default).
    Maps relation numbers to at most three short enum-style traits; the caller
    adds evidence refs and validates through relationship_meta before storage.
    """
    rel = _dict(relationship)
    state = _dict(rel.get("state"))
    repair = _dict(rel.get("repair_state"))
    absence = _dict(rel.get("absence"))

    def _num(key, default=0.5):
        try:
            return max(0.0, min(1.0, float(state.get(key, default) or default)))
        except Exception:
            return default

    traits = []
    closeness = _num("closeness")
    conflict = _num("conflict")
    trust = _num("trust")
    phase = str(repair.get("phase") or "stable")
    bucket = str(absence.get("bucket") or "")
    if closeness >= 0.62:
        traits.append("关系偏亲近，愿意主动分享近况")
    elif closeness <= 0.35:
        traits.append("关系偏疏远，互动需要更主动")
    if conflict >= 0.50:
        traits.append("近期有未解决的冲突，先确认再推进")
    elif phase in ("repairing", "repaired"):
        traits.append("冲突后有修复动作，不反复追问")
    if bucket in ("medium", "long"):
        traits.append("有间隔后重逢，先接住近况")
    if not traits and trust >= 0.55:
        traits.append("信任在累积，保持稳定回应")
    try:
        refs = max(0, int(evidence_count))
    except Exception:
        refs = 0
    confidence = round(min(0.72, 0.50 + 0.05 * len(traits) + 0.02 * min(3, refs)), 3)
    return {"traits": traits[:3], "relation_events": [],
            "we_memory_candidates": [], "confidence": confidence}


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


def empathy_strategy_block(core) -> str:
    """A4: deterministic empathy strategy token from core affect (no LLM).

    Only strong, bounded conditions emit a token; neutral state stays silent so
    the default hint path does not add noise. Mirrors the optional LLM labels
    (active_constructive/supportive/validate) without a model call.
    """
    try:
        v = float(getattr(core, "v", 0.0))
        a = float(getattr(core, "a", 0.5))
        stress = float(getattr(core, "stress", 0.0))
    except Exception:
        return ""
    if v <= -0.25 and a >= 0.55:
        return "empathy=supportive"
    if v >= 0.30 and a >= 0.50:
        return "empathy=active_constructive"
    if stress >= 0.60:
        return "empathy=validate"
    return ""


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


# ---------------------------------------------------------------------------
# task-39/37: [BC] budget, reverse check (F1), repeat guard (F3), thought note,
# path-dependence metrics. All deterministic, no LLM, read-only.
# ---------------------------------------------------------------------------
BC_FORMAT_VERSION = "1.3.1"
BC_TOKEN_CHARS = 2.5     # task-39: default token estimate = chars / 2.5
TOKEN_CHARS_EST = 2.2    # task-37: conservative fallback estimate = chars / 2.2


def estimate_bc_tokens(text, chars_per_token: float = BC_TOKEN_CHARS) -> int:
    try:
        ratio = max(1.0, float(chars_per_token))
    except Exception:
        ratio = BC_TOKEN_CHARS
    value = str(text or "")
    if not value:
        return 0
    return int(math.ceil(len(value) / ratio))


def estimate_text_tokens(text, chars_per_token: float = TOKEN_CHARS_EST) -> int:
    return estimate_bc_tokens(text, chars_per_token)


_BC_MEMORY_KEYS = {"mem", "memn", "memc", "memsrc", "ansc", "memwho", "loops",
                   "due", "soon", "ev", "self", "u", "img", "kb", "spk",
                   "voice", "cont"}
_BC_HINT_KEYS = {"hint", "ws", "brevity"}


def _bc_segment_kind(segment) -> str:
    token = str(segment or "").strip().split("=", 1)[0].strip()
    if token in _BC_HINT_KEYS:
        return "hint"
    if token in _BC_MEMORY_KEYS:
        return "memory"
    return "other"


# ATTENTION-THINKING-LIT §6: drop from the tail by ascending salience; never
# drop the [BC] head or the memory evidence keys.
_BC_PROTECTED_KEYS = {"mem", "memn", "memsrc", "ansc", "memwho"}
_BC_DROP_ORDER = ("cont", "loops", "due", "soon", "ev",
                  "hint", "ws", "brevity",
                  "self", "u", "img", "kb", "spk", "voice")


def _bc_key(segment) -> str:
    return str(segment or "").strip().split("=", 1)[0].strip()


def apply_bc_budget(text, budget_tokens=0, budget_chars=0, history=None,
                    dedupe=True, hints_enabled=True):
    """task-39/37 + ATTENTION-THINKING-LIT §6 budget/order.

    Single block, order: head(intent/emotion/action) → memory evidence →
    other state → events → loops → hint/continuity last. Truncation walks the
    tail in ascending salience (cont → loops → ev → hint → other state), never
    dropping the head or memory evidence keys. Budget is expressed in chars
    (480–800 engineering) or legacy tokens (×2.5). Empty input returns "".
    """
    raw = str(text or "")
    try:
        tok_budget = max(0, int(budget_tokens or 0))
    except Exception:
        tok_budget = 0
    try:
        char_budget = max(0, int(budget_chars or 0))
    except Exception:
        char_budget = 0
    if not char_budget and tok_budget:
        char_budget = int(tok_budget * BC_TOKEN_CHARS)
    if not raw.strip():
        return "", {"chars": 0, "tokens_estimate": 0,
                    "budget_tokens": tok_budget, "budget_chars": char_budget,
                    "truncated": [], "dropped_duplicates": [],
                    "format_version": BC_FORMAT_VERSION, "hints_disabled": not hints_enabled,
                    "segments": 0}
    parts = raw.split(" | ")
    head = parts[0]
    segments = [s for s in parts[1:] if str(s).strip()]
    seen = set()
    if dedupe and history:
        for old in history:
            for seg in str(old or "").split(" | ")[1:]:
                if seg.strip():
                    seen.add(seg.strip())
    dropped = []
    kept = []
    for seg in segments:
        if dedupe and seg.strip() in seen:
            dropped.append(seg)
            continue
        if not hints_enabled and _bc_segment_kind(seg) == "hint":
            dropped.append(seg)
            continue
        kept.append(seg)
    # §6 block order: evidence/memory + state first, events, loops, hints last.
    early, events, loops, hints, late = [], [], [], [], []
    for seg in kept:
        key = _bc_key(seg)
        if key in _BC_PROTECTED_KEYS or key in ("self", "u", "img", "kb", "spk", "voice"):
            early.append(seg)
        elif key == "ev":
            events.append(seg)
        elif key in ("loops", "due", "soon"):
            loops.append(seg)
        elif key in ("hint", "ws", "brevity"):
            hints.append(seg)
        else:
            late.append(seg)
    ordered = early + events + loops + hints + late
    truncated = []
    if char_budget > 0:
        while ordered and len(" | ".join([head] + ordered)) > char_budget:
            # drop by explicit tail salience order; protected rows are skipped.
            _idx = None
            for key in _BC_DROP_ORDER:
                for pos in range(len(ordered) - 1, -1, -1):
                    if _bc_key(ordered[pos]) == key:
                        _idx = pos
                        break
                if _idx is not None:
                    break
            if _idx is None:
                _idx = len(ordered) - 1
            seg = ordered[_idx]
            if _bc_key(seg) in _BC_PROTECTED_KEYS:
                break
            truncated.append(ordered.pop(_idx))
    out = " | ".join([head] + ordered)
    return out, {"chars": len(out), "tokens_estimate": estimate_bc_tokens(out),
                 "budget_tokens": tok_budget, "budget_chars": char_budget,
                 "truncated": truncated, "dropped_duplicates": dropped,
                 "hints_disabled": not hints_enabled,
                 "head_over_budget": bool(char_budget > 0 and len(head) > char_budget),
                 "format_version": BC_FORMAT_VERSION,
                 "segments": len(ordered) + 1}


def extract_hint_line(text):
    """§6: hint goes after the [BC] block (<=140 chars, at most one per round)."""
    raw = str(text or "")
    parts = raw.split(" | ")
    hint = ""
    kept = [parts[0]]
    for seg in parts[1:]:
        if _bc_key(seg) == "hint" and not hint:
            hint = seg.split("=", 1)[1].strip() if "=" in seg else seg.strip()
        else:
            kept.append(seg)
    return " | ".join([p for p in kept if p.strip()]), hint[:140]


def _ngrams(text, n: int = 4) -> set:
    value = "".join(str(text or "").split())
    if len(value) < n:
        return {value} if value else set()
    return {value[i:i + n] for i in range(len(value) - n + 1)}


def _char_bigrams(text) -> set:
    value = "".join(str(text or "").split())
    if len(value) < 2:
        return {value} if value else set()
    return {value[i:i + 2] for i in range(len(value) - 1)}


def _jaccard(a, b) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def _cosine_bigrams(a, b) -> float:
    ga, gb = _char_bigrams(a), _char_bigrams(b)
    if not ga or not gb:
        return 0.0
    dot = len(ga & gb)
    return dot / math.sqrt(len(ga) * len(gb)) if ga and gb else 0.0


def _sentence_cosine(a, b) -> float:
    sa = [s for s in re.split(r"[。！？；!?;\n]", str(a or "")) if s.strip()]
    sb = [s for s in re.split(r"[。！？；!?;\n]", str(b or "")) if s.strip()]
    if not sa or not sb:
        return 0.0
    return max(_cosine_bigrams(x, y) for x in sa for y in sb)


def repeat_guard(reply, previous_replies, *, jaccard_threshold=0.60,
                 cosine_threshold=0.85) -> dict:
    """task-39 F3: mark (never rewrite) repeat/template degeneration."""
    current = str(reply or "")
    previous = [str(x) for x in (previous_replies or []) if str(x).strip()][-3:]
    if not current.strip() or not previous:
        return {"flag": "none", "jaccard": 0.0, "sentence_cosine": 0.0,
                "reason": "insufficient_history"}
    grams = _ngrams(current, 4)
    best_j = max(_jaccard(grams, _ngrams(prev, 4)) for prev in previous)
    best_c = max(_sentence_cosine(current, prev) for prev in previous)
    # ATTENTION-THINKING-LIT §6: same 20-char prefix is also a repeat signal.
    _cur_prefix = "".join(current.split())[:20]
    prefix_hit = bool(len(_cur_prefix) >= 20 and any(
        "".join(prev.split())[:20] == _cur_prefix for prev in previous))
    flag = "repeat" if (best_j >= float(jaccard_threshold)
                        or best_c >= float(cosine_threshold)
                        or prefix_hit) else "none"
    return {"flag": flag, "jaccard": round(best_j, 4),
            "sentence_cosine": round(best_c, 4), "prefix": bool(prefix_hit),
            "thresholds": {"jaccard": float(jaccard_threshold),
                           "sentence_cosine": float(cosine_threshold)},
            "compared": len(previous)}


_ABSOLUTE_PROMISE_RE = re.compile(r"(我保证|保证|发誓|永远|一辈子|绝不|说到做到|一定会的|答应你)")
_NEGATED_FEELING_RE = re.compile(r"(我没生气|我不生气|我不难过|我没难过|我不在乎|我才不在乎|我没事|我不委屈|我没关系|我不介意)")
_OVERREACH_RE = re.compile(r"(你应该|你必须|听我的|赶紧分手|分手吧|辞职|拉黑|别理他|必须原谅)")


def reverse_check(reply, *, core_state=None, previous_replies=None,
                  low_confidence=False, boundary_pressure=0.0) -> dict:
    """task-39 F1: deterministic evidence-based self check (no LLM, read-only).

    Checks absolute promises / negated feelings (only when L1 arousal is high) /
    overreach advice / repeat of the previous line / template repetition.
    Never rewrites the reply; the hint is at most 140 chars.
    """
    text = str(reply or "")
    state = core_state if isinstance(core_state, dict) else {}
    try:
        intensity = max(0.0, min(1.0, float(state.get("intensity", 0.0) or 0.0)))
    except Exception:
        intensity = 0.0
    previous = [str(x) for x in (previous_replies or []) if str(x).strip()]
    checks = []
    violations = []

    def _add(name, hit, evidence=""):
        checks.append({"name": name, "ok": not hit,
                       "evidence": str(evidence or "")[:80]})
        if hit:
            violations.append(name)

    m = _ABSOLUTE_PROMISE_RE.search(text)
    _add("absolute_promise", bool(m), m.group(0) if m else "")
    # evidence-based promise mismatch: a commitment/答应 + an explicit "没做到" cue
    _mismatch = (("答应" in text or "承诺" in text or "说好" in text)
                 and any(w in text for w in ("没做到", "忘了", "食言", "没兑现", "做不到")))
    _add("promise_mismatch", bool(_mismatch), "答应/承诺+未兑现" if _mismatch else "")
    # low-confidence citation flag is passed in from the recall metadata (T4)
    _add("low_conf", bool(low_confidence), "answer_confidence<0.40" if low_confidence else "")
    m = _NEGATED_FEELING_RE.search(text)
    _add("negated_feeling", bool(m) and intensity >= 0.50,
         (m.group(0) if m else "") + ("/I=%.2f" % intensity if m else ""))
    m = _OVERREACH_RE.search(text)
    _add("overreach_advice", bool(m), m.group(0) if m else "")
    rep = repeat_guard(text, previous) if previous else {"flag": "none"}
    _add("repeat_previous", rep.get("flag") == "repeat", rep.get("flag", ""))
    sentences = [s.strip() for s in re.split(r"[。！？；!?;\n]", text) if s.strip()]
    dup_sentence = any(sentences.count(s) >= 2 for s in sentences if len(s) >= 6)
    template = dup_sentence
    if not template and len(sentences) >= 2:
        template = _sentence_cosine(sentences[0], sentences[-1]) >= 0.85
    _add("template_repeat", bool(template), "duplicate_sentence" if dup_sentence else "")
    labels = {"absolute_promise": "绝对承诺", "negated_feeling": "否定感受",
              "overreach_advice": "越界建议", "repeat_previous": "重复上一句",
              "template_repeat": "模板重复", "promise_mismatch": "承诺不一致",
              "low_conf": "低置信引用"}
    hint = ""
    if violations:
        names = [labels.get(v, v) for v in violations[:3]]
        hint = ("避免" + "/".join(names))[:140]
    score = round(max(0.0, 1.0 - 0.25 * len(violations)), 4)
    return {"checks": checks, "violations": violations, "score": score,
            "hint": hint, "low_confidence": bool(low_confidence),
            "boundary_pressure": round(max(0.0, min(1.0, float(boundary_pressure or 0.0))), 4)}


def thought_note(core_state=None, *, memory_count=0, hint="", now=None) -> dict:
    """task-39: per-turn deterministic thinking note (never persisted/refed)."""
    state = core_state if isinstance(core_state, dict) else {}
    labels = state.get("labels") if isinstance(state.get("labels"), dict) else {}
    parts = []
    emo = str(labels.get("emotion") or "neutral")[:12]
    need = str(labels.get("need") or "talk")[:12]
    parts.append("情绪=%s 需要=%s" % (emo, need))
    try:
        intensity = float(state.get("intensity", 0.0) or 0.0)
    except Exception:
        intensity = 0.0
    parts.append("强度=%.2f" % max(0.0, min(1.0, intensity)))
    try:
        count = int(memory_count or 0)
    except Exception:
        count = 0
    if count:
        parts.append("记忆=%d条" % count)
    if hint:
        parts.append(str(hint)[:40])
    text = ("；".join(parts))[:120]
    try:
        stamp = float(now if now is not None else 0.0)
    except Exception:
        stamp = 0.0
    return {"text": text, "ts": round(stamp, 3)}


def path_dependence_metrics(replies, labels, summaries) -> dict:
    """task-39/40: read-only path-dependence monitors (deterministic)."""
    rows = [str(x) for x in (replies or []) if str(x).strip()][-5:]
    sims = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            sims.append(_cosine_bigrams(rows[i], rows[j]))
    self_similarity = round(sum(sims) / len(sims), 4) if sims else 0.0
    labs = [str(x) for x in (labels or []) if str(x).strip()][-8:]
    same = 0
    for a, b in zip(labs, labs[1:]):
        if a == b:
            same += 1
    label_autocorr = round(same / max(1, len(labs) - 1), 4)
    sums = [str(x) for x in (summaries or []) if str(x).strip()][-2:]
    drift = 0.0
    if len(sums) >= 2:
        drift = round(max(0.0, min(1.0, 1.0 - _cosine_bigrams(sums[-2], sums[-1]))), 4)
    warning = bool(self_similarity >= 0.60 or label_autocorr >= 0.80 or drift >= 0.50)
    return {"self_similarity": self_similarity, "label_autocorr": label_autocorr,
            "summary_drift": drift, "samples": len(rows), "warning": warning}


# ATTENTION-THINKING-LIT §6: read-only sycophancy / risky-agreement detection.
_SYCO_AGREE = ("你说得对", "完全同意", "听你的", "都依你", "你没错",
               "你说什么都对", "必须的", "当然可以", "没问题")
_SYCO_RISKY = ("分手", "辞职", "借", "打", "删", "报复", "离家", "绝交", "拉黑")
_SYCO_HEDGE = ("但是", "不过", "如果", "建议", "或者", "先别", "要不要")


def sycophancy_check(reply, core_state=None, *, risky=False) -> dict:
    """task-43/§6: high-intensity agreement / risky agreement (trace only)."""
    text = str(reply or "")
    state = core_state if isinstance(core_state, dict) else {}
    try:
        intensity = max(0.0, min(1.0, float(state.get("intensity", 0.0) or 0.0)))
    except Exception:
        intensity = 0.0
    agree = [w for w in _SYCO_AGREE if w in text]
    risky_hit = [w for w in _SYCO_RISKY if w in text] if risky else []
    hedge = any(w in text for w in _SYCO_HEDGE)
    flag = bool(agree and (risky_hit or intensity >= 0.70) and not hedge)
    return {"flag": flag, "agree": agree[:3], "risky": risky_hit[:3],
            "hedged": bool(hedge), "intensity": round(intensity, 4)}



