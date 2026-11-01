# -*- coding: utf-8 -*-
"""SillyTavern-style prompt preset: structured injection blocks (pure, no IO).

Every injected prompt fragment is one record (id/name/role/position/depth/
order/enabled/condition/content). The host plugin renders them with
template_expr and places them into req.contexts before / inside / after the
chat history instead of appending an unstructured pile of strings. This module
never imports the host and performs no IO.
"""
from __future__ import annotations

import re

try:
    from . import template_expr as _tpl
except Exception:  # pragma: no cover
    try:
        import template_expr as _tpl  # type: ignore
    except Exception:
        _tpl = None

POSITIONS = ("before_history", "depth", "after_history")

_EXPR_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SKIP_NAMES = {"true", "false", "none", "and", "or", "not", "in",
               "len", "min", "max", "abs", "round", "if", "elif", "else",
               "endif", "for", "endfor"}


def _template_var_names(template):
    """Plain variable names referenced inside {{ ... }} expressions."""
    names = set()
    for expr in _EXPR_RE.findall(str(template or "")):
        for name in _ID_RE.findall(expr):
            if name.lower() not in _SKIP_NAMES:
                names.add(name)
    return names


def _has_signal(content, variables):
    """A block rendered only from its static scaffolding is treated as empty."""
    names = _template_var_names(content)
    if not names:
        return True
    for name in names:
        value = variables.get(name)
        if value is None:
            continue
        if str(value).strip():
            return True
    return False

# Default block list. content is a template_expr template; an empty rendered
# body is skipped by assemble(), so callers may pass only the variables they
# have in this turn.
PRESET = [
    {"id": "situation", "name": "局面摘要", "role": "system",
     "position": "before_history", "depth": 4, "order": 100, "enabled": True,
     "condition": "", "content": "[局面摘要]\n{{situation}}"},
    {"id": "layered_memory", "name": "分层记忆", "role": "system",
     "position": "before_history", "depth": 4, "order": 110, "enabled": True,
     "condition": "layered_memory",
     "content": "{{layered_memory}}"},
    {"id": "graph_memory", "name": "你知道的", "role": "system",
     "position": "before_history", "depth": 4, "order": 115, "enabled": True,
     "condition": "graph_memory", "content": "{{graph_memory}}"},
    {"id": "state_block", "name": "状态块", "role": "system",
     "position": "before_history", "depth": 4, "order": 120, "enabled": True,
     "condition": "state_block", "content": "{{state_block}}"},
    {"id": "relationship", "name": "关系", "role": "system",
     "position": "before_history", "depth": 4, "order": 130, "enabled": True,
     "condition": "relationship", "content": "{{relationship}}"},
    {"id": "gap", "name": "间隔", "role": "system",
     "position": "before_history", "depth": 4, "order": 140, "enabled": True,
     "condition": "gap", "content": "{{gap}}"},
    {"id": "speak_style", "name": "说话方式建议", "role": "system",
     "position": "depth", "depth": 2, "order": 150, "enabled": True,
     "condition": "speak_style", "content": "{{speak_style}}"},
    {"id": "numeric_legend", "name": "情绪图例", "role": "system",
     "position": "after_history", "depth": 4, "order": 160, "enabled": True,
     "condition": "numeric_legend", "content": "{{numeric_legend}}"},
]


def _clamp_depth(value, history_len):
    try:
        depth = int(value)
    except Exception:
        depth = 4
    if depth < 0:
        depth = 0
    try:
        limit = max(0, int(history_len))
    except Exception:
        limit = 0
    return min(depth, limit)


def _render(template, variables):
    text = str(template or "")
    if _tpl is None:
        return text
    try:
        return str(_tpl.render(text, variables) or "")
    except Exception:
        return text


def _condition_ok(condition, variables):
    """Empty condition passes; falsy/empty renders exclude; errors fail closed."""
    raw = str(condition or "").strip()
    if not raw:
        return True
    rendered = _render("{{ " + raw + " }}", variables).strip()
    if not rendered:
        return False
    return rendered.lower() not in ("false", "0", "0.0", "none", "null",
                                    "[]", "{}", "()")


def _blocks(records, variables, history_len):
    out = []
    for record in records:
        if not isinstance(record, dict) or not record.get("enabled", True):
            continue
        position = str(record.get("position") or "before_history")
        if position not in POSITIONS:
            continue
        try:
            if not _condition_ok(record.get("condition"), variables):
                continue
        except Exception:
            continue
        rendered = _render(record.get("content"), variables)
        if not _has_signal(record.get("content"), variables):
            rendered = ""
        content = "\n".join(line for line in rendered.strip().splitlines()
                             if line.strip())
        if not content:
            continue
        block = {"id": str(record.get("id") or ""),
                 "name": str(record.get("name") or ""),
                 "role": str(record.get("role") or "system"),
                 "order": int(record.get("order", 100) or 100),
                 "position": position,
                 "depth": _clamp_depth(record.get("depth", 4), history_len),
                 "content": content}
        out.append(block)
    out.sort(key=lambda row: (row["order"], row["id"]))
    return out


def assemble(variables=None, history_len=0):
    """Render PRESET into the three prompt positions.

    Returns {"before_history": [block...], "depth": [{"depth": N, "blocks":
    [block...]}...], "after_history": [block...]}. Blocks are ordered by
    "order"; empty/false-condition blocks are dropped; depth is clamped to
    history_len so a depth block can never point past the available history.
    """
    variables = variables if isinstance(variables, dict) else {}
    world = dict(variables)
    blocks = _blocks(PRESET, world, history_len)
    before = [b for b in blocks if b["position"] == "before_history"]
    after = [b for b in blocks if b["position"] == "after_history"]
    groups = {}
    for block in blocks:
        if block["position"] != "depth":
            continue
        groups.setdefault(block["depth"], []).append(block)
    depth = [{"depth": key, "blocks": groups[key]} for key in sorted(groups)]
    return {"before_history": before, "depth": depth, "after_history": after}


def depth_index(history_len, depth):
    """Insertion index for a depth block: right after the Nth newest message."""
    try:
        length = max(0, int(history_len))
    except Exception:
        length = 0
    try:
        value = max(0, int(depth))
    except Exception:
        value = 0
    if value <= 0:
        return 0
    if value >= length:
        return 0
    return max(0, length - value + 1)

def render_texts(assembled):
    """Flatten an assembled result to [(position, depth, role, content)]."""
    out = []
    if not isinstance(assembled, dict):
        return out
    for block in assembled.get("before_history") or []:
        out.append(("before_history", 0, block["role"], block["content"]))
    for group in assembled.get("depth") or []:
        for block in group.get("blocks") or []:
            out.append(("depth", int(group.get("depth", 0)), block["role"],
                        block["content"]))
    for block in assembled.get("after_history") or []:
        out.append(("after_history", 0, block["role"], block["content"]))
    return out
