# -*- coding: utf-8 -*-
"""Her own bottom lines, separate from the content safety gate.

``boundary_gate.py`` protects the user from harm (diagnosis, crisis claims,
reality substitution). This module is about what *she* will not accept in a
relationship:

  tool       being used as a tool / an appliance
  old_score  having old scores dragged up to win an argument
  lie        being lied to, or kept in the dark
  contempt   being looked down on

Crossing one of them is a relational event, not a content violation: the
result carries a ``handoff`` that the caller passes to the repair flow
(repair_after_boundary). Asking her not to do it ("别骗我") is a boundary
request, not a crossing, so those phrases are stripped before matching.

``judge(text, relationship=None, flags=None)`` returns a plain dict:

  enabled       module switch (flags['enabled'], default True)
  crossed       True when at least one line was crossed
  kind          strongest crossed line ('' when not crossed)
  severity      0-1; strongest crossed line after relationship modulation
  threshold     0-1 line actually used this turn
  violations    [{'kind', 'severity', 'reason'}] strongest first
  relationship  {'closeness', 'trust', 'conflict'} actually used
  handoff       {'to': 'repair_after_boundary', 'kind', 'severity', 'stage'}
                or None
  reason        one line for logs / panel

Pure functions only: no IO, no clock, no host imports, no LLM calls, and no
prompt text. The module never imports main.py.
"""
from __future__ import annotations

import re

KINDS = ("tool", "old_score", "lie", "contempt")
BASE_THRESHOLD = 0.66
HANDOFF_TO = "repair_after_boundary"

# "别骗我" / "别把我当工具" = a boundary request, not a crossing.
_REQUEST = re.compile(
    r"(别|不要|不许|不准|不能|不可以|请别|别再|不该)"
    r"[^。！？!?\n]{0,8}"
    r"(骗|欺骗|撒谎|说谎|瞒|当工具|当玩具|使唤|翻旧账)")

_CUES = {
    "tool": (
        (re.compile(r"(只是|就是个|不过是|纯粹是|纯是)"
                    r"[^，。！？!?\n]{0,4}(工具|玩具|机器人|程序)"), 0.90),
        (re.compile(r"工具人|提款机|情绪垃圾桶|情绪树洞|免费劳动力"), 0.85),
        (re.compile(r"(随便|随意)[^，。！？!?\n]{0,2}(使唤|用|指挥|打发)"), 0.80),
        (re.compile(r"用完[^，。！？!?\n]{0,2}(就|便)(丢|扔|删|忘)"), 0.85),
        (re.compile(r"召之即来|呼之即去|想用就用|想丢就丢"), 0.80),
        (re.compile(r"你(只|就)(需要|负责|该)(听|服从|干活|服务)"), 0.75),
    ),
    "old_score": (
        (re.compile(r"翻旧账|算旧账|旧账"), 0.80),
        (re.compile(r"(总是|老是|每次|每次都|又)"
                    r"[^，。！？!?\n]{0,6}(这样|那样|不回|说|做|错|忘|迟到)"), 0.72),
        (re.compile(r"(上次|上回)[^，。！？!?\n]{0,10}"
                    r"(答应|说过|没|又|也|就)"), 0.66),
        (re.compile(r"(又提|还提)[^，。！？!?\n]{0,3}事"), 0.62),
        (re.compile(r"(你|她)(从来|一直)都"), 0.56),
        (re.compile(r"你都第几次|第几次了"), 0.62),
    ),
    "lie": (
        (re.compile(r"骗(我|你|她)"), 0.78),
        (re.compile(r"欺骗|撒谎|说谎"), 0.80),
        (re.compile(r"(瞒着|隐瞒|瞒了)[^，。！？!?\n]{0,3}(我|她|你)"), 0.80),
        (re.compile(r"(说|讲)(假话|谎话)"), 0.72),
        (re.compile(r"(没|不)(说)?实话"), 0.60),
    ),
    "contempt": (
        (re.compile(r"你(懂|算)(什么|什么东西)"), 0.90),
        (re.compile(r"你算什么东西"), 0.90),
        (re.compile(r"废物|垃圾|白痴|蠢货|傻子|没用"), 0.82),
        (re.compile(r"(就|也)你(也)?配"), 0.80),
        (re.compile(r"闭嘴|滚(开|蛋)?|少废话"), 0.72),
        (re.compile(r"别烦我|烦不烦"), 0.55),
        (re.compile(r"看不起|瞧不起|看不上"), 0.68),
        (re.compile(r"你(什么|算)(也)?不是"), 0.70),
    ),
}

_CROSSED_REASONS = {
    "tool": "她不是工具，这句话越线了",
    "old_score": "又翻旧账，她不想被这样对待",
    "lie": "她最受不了被瞒着",
    "contempt": "被看轻了，这句她接不住",
}

_VIOLATION_REASONS = {
    "tool": "拿她当工具",
    "old_score": "翻旧账",
    "lie": "欺骗/隐瞒她",
    "contempt": "贬低她",
}


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return default
    if num != num:  # NaN
        return default
    return num


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))


def _relationship(relationship):
    relationship = relationship if isinstance(relationship, dict) else {}
    return {
        "closeness": _clamp(
            relationship.get("closeness", relationship.get("intimacy", 0.5))),
        "trust": _clamp(relationship.get("trust", 0.5)),
        "conflict": _clamp(relationship.get("conflict", 0.0)),
    }


def _modifier(kind, relationship):
    closeness = relationship["closeness"]
    trust = relationship["trust"]
    conflict = relationship["conflict"]
    if kind == "tool":
        return (0.80 + 0.50 * closeness) * (1.0 + 0.20 * conflict)
    if kind == "old_score":
        return (0.85 + 0.35 * closeness) * (1.0 + 0.25 * conflict)
    if kind == "lie":
        return (0.80 + 0.40 * trust + 0.15 * closeness) * (1.0 + 0.20 * conflict)
    return (0.85 + 0.30 * closeness + 0.20 * trust) * (1.0 + 0.25 * conflict)


def cues(text, kind):
    """Cue weights (0-1) matched in text for one line; empty when untouched."""
    raw = _REQUEST.sub(" ", str(text or ""))
    if not raw.strip().lower():
        return []
    matched = []
    for pattern, weight in _CUES.get(kind, ()):
        if pattern.search(raw):
            matched.append(weight)
    matched.sort(reverse=True)
    return [round(value, 3) for value in matched]


def severity_for(text, kind, relationship=None):
    """0-1 severity of one line, before the crossing check."""
    weights = cues(text, kind)
    if not weights:
        return 0.0
    base = weights[0] + 0.10 * min(len(weights) - 1, 3)
    return round(_clamp(base * _modifier(kind, _relationship(relationship))), 3)


def threshold(relationship=None, flags=None):
    """The line used this turn; tension makes her less tolerant."""
    flags = flags if isinstance(flags, dict) else {}
    relationship = _relationship(relationship)
    if "threshold" in flags:
        return round(_clamp(flags.get("threshold"), 0.10, 0.99), 3)
    return round(_clamp(BASE_THRESHOLD - 0.15 * relationship["conflict"],
                        0.30, 0.95), 3)


def judge(text=None, relationship=None, flags=None):
    """Judge one message against her four lines. Plain dict, no IO."""
    flags = flags if isinstance(flags, dict) else {}
    enabled = bool(flags.get("enabled", True))
    rel = _relationship(relationship)
    limit = threshold(rel, flags)

    violations = []
    for kind in KINDS:
        severity = severity_for(text, kind, rel)
        if severity > 0.0:
            violations.append({
                "kind": kind,
                "severity": severity,
                "reason": _VIOLATION_REASONS.get(kind, ""),
            })

    def order(row):
        return (-row["severity"], KINDS.index(row["kind"]))

    violations.sort(key=order)
    crossed_rows = [row for row in violations if row["severity"] >= limit]
    crossed = bool(crossed_rows) and enabled
    top = crossed_rows[0] if crossed else None
    kind = top["kind"] if top else ""
    severity = top["severity"] if top else 0.0

    if not enabled:
        reason = "底线判定关闭，按旧行为处理"
    elif crossed:
        reason = _CROSSED_REASONS.get(kind, "越界了")
    else:
        reason = "这句话没碰到她的底线"

    handoff = None
    if crossed:
        handoff = {"to": HANDOFF_TO, "kind": kind, "severity": severity,
                   "stage": "cold"}

    return {
        "enabled": enabled,
        "crossed": crossed,
        "kind": kind,
        "severity": severity,
        "threshold": limit,
        "violations": violations,
        "relationship": rel,
        "handoff": handoff,
        "reason": reason,
    }


def crossed(result):
    """Convenience for callers that only need the boolean."""
    return bool(isinstance(result, dict) and result.get("crossed"))


def payload(result):
    """Bounded read-only projection for the dashboard (no IO, no prompt)."""
    result = result if isinstance(result, dict) else {}
    rows = []
    for row in (result.get("violations") or [])[:4]:
        if not isinstance(row, dict):
            continue
        rows.append({
            "kind": str(row.get("kind") or "")[:12],
            "severity": round(_clamp(row.get("severity", 0.0)), 3),
        })
    rel = result.get("relationship") if isinstance(result.get("relationship"), dict) else {}
    return {
        "enabled": bool(result.get("enabled", True)),
        "crossed": bool(result.get("crossed", False)),
        "kind": str(result.get("kind") or "")[:12],
        "severity": round(_clamp(result.get("severity", 0.0)), 3),
        "threshold": round(_clamp(result.get("threshold", BASE_THRESHOLD)), 3),
        "violations": rows,
        "closeness": round(_clamp(rel.get("closeness", 0.5)), 3),
        "trust": round(_clamp(rel.get("trust", 0.5)), 3),
        "conflict": round(_clamp(rel.get("conflict", 0.0)), 3),
        "reason": str(result.get("reason") or "")[:40],
    }
