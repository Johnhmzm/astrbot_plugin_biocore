# -*- coding: utf-8 -*-
"""Tiny safe template engine for prompt fragments.

Borrowed idea: SillyTavern's Prompt Template extension lets world info and
character prompts carry conditions/loops. We only need the read-only half
(substitute + if/elif/else + for) and we evaluate expressions with a
whitelisted AST instead of running JavaScript.

Syntax
------
{{ expr }}                    -> value of a simple expression
{% if expr %} .. {% elif expr %} .. {% else %} .. {% endif %}
{% for name in list %} .. {% endfor %}

Expressions support: numbers, strings, True/False/None, variables from the
provided mapping, arithmetic (+ - * / %), comparisons, and/or/not, in,
plus a few safe helpers (len, min, max, abs, round).
"""
from __future__ import annotations

import ast
import re

_MAX_DEPTH = 12
_ALLOWED_FUNCS = {"len": len, "min": min, "max": max, "abs": abs, "round": round}
_TOKEN = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.S)


class TemplateError(ValueError):
    pass


def _eval(expr, vars):
    expr = str(expr or "").strip()
    if not expr:
        return ""
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError:
        return ""
    return _eval_node(node.body, vars)


def _eval_node(node, vars):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return vars.get(node.id, "")
    if isinstance(node, ast.List):
        return [_eval_node(x, vars) for x in node.elts]
    if isinstance(node, ast.UnaryOp):
        val = _eval_node(node.operand, vars)
        if isinstance(node.op, ast.Not):
            return not _truthy(val)
        if isinstance(node.op, ast.USub):
            return -_num(val)
        if isinstance(node.op, ast.UAdd):
            return _num(val)
        raise TemplateError("unsupported unary op")
    if isinstance(node, ast.BoolOp):
        values = [_truthy(_eval_node(v, vars)) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        return any(values)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, vars)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, vars)
            if not _compare(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BinOp):
        left, right = _eval_node(node.left, vars), _eval_node(node.right, vars)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return _num(left) - _num(right)
        if isinstance(node.op, ast.Mult):
            return _num(left) * _num(right)
        if isinstance(node.op, ast.Div):
            right = _num(right)
            return (_num(left) / right) if right else 0
        if isinstance(node.op, ast.Mod):
            right = _num(right)
            return (_num(left) % right) if right else 0
        raise TemplateError("unsupported binary op")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise TemplateError("function not allowed")
        args = [_eval_node(a, vars) for a in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)
    if isinstance(node, ast.Attribute):
        raise TemplateError("attribute access not allowed")
    if isinstance(node, ast.Subscript):
        base = _eval_node(node.value, vars)
        key = _eval_node(node.slice, vars)
        try:
            return base[key]
        except Exception:
            return ""
    raise TemplateError("unsupported expression")


def _compare(op, left, right):
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    if isinstance(op, ast.Gt):
        return _num(left) > _num(right)
    if isinstance(op, ast.GtE):
        return _num(left) >= _num(right)
    if isinstance(op, ast.Lt):
        return _num(left) < _num(right)
    if isinstance(op, ast.LtE):
        return _num(left) <= _num(right)
    if isinstance(op, ast.In):
        try:
            return left in right
        except Exception:
            return False
    if isinstance(op, ast.NotIn):
        try:
            return left not in right
        except Exception:
            return True
    if isinstance(op, ast.Is):
        return left is right
    if isinstance(op, ast.IsNot):
        return left is not right
    raise TemplateError("unsupported comparison")


def _num(value):
    try:
        return float(value)
    except Exception:
        return 0.0


def _truthy(value):
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _parse(template):
    """Turn the template into a flat token list: ('text', s) / ('expr', s) / ('tag', s)."""
    out, pos = [], 0
    for match in _TOKEN.finditer(template):
        if match.start() > pos:
            out.append(("text", template[pos:match.start()]))
        if match.group(1) is not None:
            out.append(("expr", match.group(1)))
        else:
            out.append(("tag", (match.group(2) or "").strip()))
        pos = match.end()
    if pos < len(template):
        out.append(("text", template[pos:]))
    return out


def _render_tokens(tokens, idx, vars, stop, depth=0):
    if depth > _MAX_DEPTH:
        raise TemplateError("template nesting too deep")
    chunks = []
    while idx < len(tokens):
        kind, value = tokens[idx]
        if kind == "text":
            chunks.append(value)
            idx += 1
            continue
        if kind == "expr":
            try:
                chunks.append(str(_eval(value, vars)))
            except TemplateError:
                chunks.append("")
            idx += 1
            continue
        head = value.split(None, 1)[0] if value else ""
        if head in stop:
            return "".join(chunks), idx
        if head == "if":
            cond = value[2:].strip()
            body, idx = _render_tokens(tokens, idx + 1, vars, {"elif", "else", "endif"}, depth + 1)
            taken = _truthy(_eval_safe(cond, vars))
            branch = body if taken else ""
            while idx < len(tokens) and tokens[idx][0] == "tag":
                tag = tokens[idx][1]
                word = tag.split(None, 1)[0]
                if word == "elif":
                    inner, idx = _render_tokens(tokens, idx + 1, vars, {"elif", "else", "endif"}, depth + 1)
                    if not taken and _truthy(_eval_safe(tag[4:].strip(), vars)):
                        branch, taken = inner, True
                    continue
                if word == "else":
                    inner, idx = _render_tokens(tokens, idx + 1, vars, {"endif"}, depth + 1)
                    if not taken:
                        branch = inner
                    continue
                if word == "endif":
                    idx += 1
                    break
                break
            chunks.append(branch)
            continue
        if head == "for":
            spec = value[3:].strip()
            if " in " not in spec:
                idx += 1
                continue
            name, expr = spec.split(" in ", 1)
            name = name.strip()
            items = _eval_safe(expr, vars)
            body_tokens = tokens[idx + 1:]
            # find matching endfor to capture the body once
            body, after = _render_tokens(body_tokens, 0, dict(vars), {"endfor"}, depth + 1)
            idx = idx + 1 + after + 1
            try:
                seq = list(items) if isinstance(items, (list, tuple, str, dict)) else []
            except Exception:
                seq = []
            for item in seq:
                scoped = dict(vars)
                scoped[name] = item
                try:
                    chunks.append(_render_tokens(body_tokens, 0, scoped, {"endfor"}, depth + 1)[0])
                except TemplateError:
                    continue
            continue
        # unknown tag: drop it
        idx += 1
    return "".join(chunks), idx


def _eval_safe(expr, vars):
    try:
        return _eval(expr, vars)
    except TemplateError:
        return ""


def render(template, variables=None):
    """Render a template string; returns the input unchanged when it has no tags."""
    text = str(template or "")
    if "{{" not in text and "{%" not in text:
        return text
    vars = dict(variables or {})
    tokens = _parse(text)
    out, idx = _render_tokens(tokens, 0, vars, set())
    return out
