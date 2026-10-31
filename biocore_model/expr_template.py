# -*- coding: utf-8 -*-
"""EXP-4: deterministic prompt assembly (L3). Pure dependency injection."""
from __future__ import annotations

ORDER_USER = ("状态", "关系", "间隔", "你记得", "意图", "语气")

# Single source of truth for the hidden output contract emitted in SYSTEM.
# Must be strong and explicit: the model previously treated the one-liner as
# optional and never emitted a tag.
PROMPT_OUTPUT_PROTOCOL = (
    "【输出格式 · 必须遵守】\n"
    "正文之后另起一行，输出一个情绪标签，格式：\n"
    '<bc>{"e":"joy","i":0.6}</bc>\n'
    "e 只能取：joy / trust / anxiety / sadness / anger / loneliness / neutral\n"
    "i 是 0 到 1 的小数，表示强度。\n"
    "标签必须输出，不要解释它，不要包在代码块里。"
)


def _join(parts):
    return "\n".join(str(part).strip() for part in parts if part and str(part).strip())


def _system(persona, speak, opts=None):
    opts = opts or {}
    protocol = str(opts.get("output_protocol") or PROMPT_OUTPUT_PROTOCOL).strip()
    legend = str(opts.get("numeric_legend") or "").strip()
    return _join([persona or opts.get("persona"), legend,
                  speak or opts.get("speak_style"), protocol])


def _user_blocks(state_text, relationship_text, gap_text, hints, intent, tone, guard, opts, recent=""):
    opts = opts or {}
    blocks = [("状态", state_text), ("关系", relationship_text), ("间隔", gap_text),
              ("我刚说过", recent), ("你记得", hints), ("意图", intent),
              ("语气", _join([tone, guard]))]
    rows = []
    used = []
    for name, value in blocks:
        if value and str(value).strip():
            rows.append(str(value).strip())
            used.append(name)
    return _join(rows), used


def build_proactive(snapshot=None, relationship=None, state_ctx=None, intent=None,
                    tone=None, guard=None, opts=None):
    opts = dict(opts or {})
    ctx = state_ctx if isinstance(state_ctx, dict) else {}
    opts["numeric_legend"] = str(ctx.get("numeric_legend")
                                or opts.get("numeric_legend") or "").strip()
    state_text = ctx.get("state_block") or opts.get("state_block") or ""
    relationship_text = ctx.get("relationship") or opts.get("relationship") or ""
    gap_text = ctx.get("gap") or opts.get("gap") or ""
    hints = ctx.get("event_hints") or opts.get("event_hints") or ""
    if isinstance(hints, (list, tuple)):
        hints = "；".join(str(item) for item in hints)
    intent_text = ""
    if isinstance(intent, dict):
        intent_text = str(intent.get("text_hint") or intent.get("kind") or "")
    elif intent:
        intent_text = str(intent)
    user, used = _user_blocks(state_text, relationship_text, gap_text, hints,
                              intent_text, tone, guard, opts,
                              recent=ctx.get("recent_proactive") or "")
    return {"system": _system(opts.get("persona"), opts.get("speak_style"), opts),
            "user": user, "order": used}


def build_reply(snapshot=None, relationship=None, state_ctx=None, tone=None,
                guard=None, opts=None, intent=None):
    opts = dict(opts or {})
    ctx = state_ctx if isinstance(state_ctx, dict) else {}
    opts["numeric_legend"] = str(ctx.get("numeric_legend")
                                or opts.get("numeric_legend") or "").strip()
    state_text = ctx.get("state_block") or opts.get("state_block") or ""
    relationship_text = ctx.get("relationship") or opts.get("relationship") or ""
    gap_text = ctx.get("gap") or opts.get("gap") or ""
    hints = ctx.get("event_hints") or opts.get("event_hints") or ""
    if isinstance(hints, (list, tuple)):
        hints = "；".join(str(item) for item in hints)
    intent_text = ""
    if isinstance(intent, dict):
        intent_text = str(intent.get("text_hint") or intent.get("kind") or "")
    elif intent:
        intent_text = str(intent)
    user, used = _user_blocks(state_text, relationship_text, gap_text, hints,
                              intent_text, tone, guard, opts,
                              recent=ctx.get("recent_proactive") or "")
    return {"system": _system(opts.get("persona"), opts.get("speak_style"), opts),
            "user": user, "order": used}
