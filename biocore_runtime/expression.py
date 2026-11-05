# -*- coding: utf-8 -*-
"""task-243 段2: the expression policy -- 表层扮演 / 表达抑制 / 展示规则.

The biological layer only decides a wording tendency here. This module never
renders a prompt, never writes a number into one, and never changes a value
back in the dimensions model.

Inputs
    the dimensions model's explicit / implicit channels (11 axes),
    the relationship stage (trust / closeness), the turn intent.

Output
    mode in {authentic, mask, suppress, leak}
    hints {"sentence": short|medium|long, "modifier": sparse|normal|dense,
           "explain": bool, "soften": bool}
    sources [...]   which axes / relationship / intent produced it

Rules
    Hochschild 1983 (surface acting): the explicit line can stay on the outside
    while the implicit one is set aside -- that is mask.
    Gross 1998 (expressive suppression): suppression changes the outside only,
    so suppress shortens and flattens without touching the inner value.
    Ekman 1972 (display rules): the setting decides whether anything may be
    shown, so suppress outranks every other mode.
    leak is the other side of mask: when the relationship is close enough the
    implicit comes through while the explicit is still what gets said.

Switch: expression_policy (default ON). Off -> no policy, no prompt line.
"""
from __future__ import annotations

import math

try:  # same package when imported by the runtime, plain path when run alone
    from . import dimensions as _dimensions
except Exception:  # pragma: no cover
    from biocore_runtime import dimensions as _dimensions

SWITCH_KEY = "expression_policy"
ENV_KEY = "BIOCORE_EXPRESSION_POLICY"
SCHEMA = 1
MODES = ("authentic", "mask", "suppress", "leak")

AMBIVALENCE_GATE = 0.15   # same knob the dimensions rules use
STRESS_SHOW_CAP = 0.80    # [engineering] display rule: too much pressure to show
CLOSE_ENOUGH = 0.55       # [engineering] from here the implicit may leak through
THIN_TRUST = 0.35         # [engineering] below this only the explicit may be shown
SUPPRESS_INTENTS = ("safety", "danger", "crisis", "hostile", "formal", "public")

# 措辞倾向 only. No digits, no axis values, nothing the model could recite.
HINTS = {
    "authentic": {"sentence": "medium", "modifier": "normal",
                  "explain": True, "soften": True},
    "mask": {"sentence": "medium", "modifier": "normal",
             "explain": False, "soften": False},
    "suppress": {"sentence": "short", "modifier": "sparse",
                 "explain": False, "soften": False},
    "leak": {"sentence": "short", "modifier": "sparse",
             "explain": False, "soften": True},
}

# One short line per mode. authentic has nothing to constrain, so it renders
# nothing at all: the prompt stays exactly what it was.
LINES = {
    "mask": "照说得出口的那句说，把心里那点波动留在外面。",
    "suppress": "收着说，句子短一点，不必解释。",
    "leak": "话短一些，情绪会漏出来一点，不必抹平。",
    "authentic": "",
}

MERGE_HINT_LIMIT = 6
MERGE_BUDGET_CHARS = 320


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return default
    if not math.isfinite(number):
        return default
    return number


def _clamp(value, low, high):
    return max(low, min(high, _num(value, low)))


def enabled(flags=None, env=None):
    data = flags if isinstance(flags, dict) else {}
    if isinstance(data.get(SWITCH_KEY), bool):
        return data[SWITCH_KEY]
    switches = data.get("switches") if isinstance(data.get("switches"), dict) else {}
    if isinstance(switches.get(SWITCH_KEY), bool):
        return switches[SWITCH_KEY]
    environ = env if hasattr(env, "get") else None
    if environ is not None and ENV_KEY in environ:
        raw = str(environ.get(ENV_KEY)).strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return True
        if raw in ("0", "false", "off", "no"):
            return False
    return True


def _level(row, channels=("explicit", "implicit"), pick="max"):
    row = row if isinstance(row, dict) else {}
    values = [_num(row.get(channel), 0.0) for channel in channels]
    return (max(values) if pick == "max" else min(values)) if values else 0.0


def facts(model=None, relationship=None, intent="", now=None):
    """Everything the rules read, each axis on its own, nothing added up."""
    model = model if isinstance(model, dict) else _dimensions.initial(now)
    rows = model.get("dims") if isinstance(model.get("dims"), dict) else {}
    rel = relationship if isinstance(relationship, dict) else {}
    best_axis, best = "", 0.0
    for name, row in rows.items():
        value = _num((row or {}).get("ambivalence"), 0.0)
        if value > best:
            best_axis, best = str(name), value
    stress = _level(rows.get("stress"), pick="max")
    trust = rel.get("trust") if isinstance(rel.get("trust"), (int, float)) \
        else _level(rows.get("trust"), pick="max")
    closeness = rel.get("closeness") \
        if isinstance(rel.get("closeness"), (int, float)) \
        else _level(rows.get("closeness"), pick="max")
    return {"ambivalence": round(_clamp(best, 0.0, 1.0), 6),
            "conflict_axis": best_axis,
            "stress": round(_clamp(stress, 0.0, 1.0), 6),
            "trust": round(_clamp(trust, 0.0, 1.0), 6),
            "closeness": round(_clamp(closeness, 0.0, 1.0), 6),
            "intent": str(intent or "").strip().lower()}


def _display_rule(read):
    return (read["stress"] >= STRESS_SHOW_CAP
            or read["intent"] in SUPPRESS_INTENTS)


def _leak_through(read):
    return (read["ambivalence"] >= AMBIVALENCE_GATE
            and read["closeness"] >= CLOSE_ENOUGH
            and read["trust"] >= THIN_TRUST)


def _surface_acting(read):
    return read["ambivalence"] >= AMBIVALENCE_GATE


RULES = (
    {"id": "display_rule", "mode": "suppress", "priority": 90,
     "when": _display_rule},
    {"id": "leak_through", "mode": "leak", "priority": 70,
     "when": _leak_through},
    {"id": "surface_acting", "mode": "mask", "priority": 60,
     "when": _surface_acting},
)


def _sources(read):
    out = []
    if read["conflict_axis"]:
        out.append("dimensions." + read["conflict_axis"])
    if read["stress"] > 0:
        out.append("dimensions.stress")
    if read["trust"] or read["closeness"]:
        out.append("relationship")
    if read["intent"]:
        out.append("intent." + read["intent"])
    return out


def policy(model=None, relationship=None, intent="", now=None,
           enabled_override=None):
    """Decide the mode; hand back hints only. Pure read of the inputs."""
    read = facts(model, relationship, intent, now=now)
    result = {"schema": SCHEMA, "enabled": True, "mode": "authentic",
              "hints": dict(HINTS["authentic"]), "sources": _sources(read),
              "reason": "no_conflict", "readout": dict(read)}
    if enabled_override is False:
        result["enabled"] = False
        result["reason"] = "disabled"
        return result
    for rule in sorted(RULES, key=lambda item: -item["priority"]):
        if rule["when"](read):
            result["mode"] = rule["mode"]
            result["hints"] = dict(HINTS[rule["mode"]])
            result["reason"] = rule["id"]
            break
    return result


def render(policy_row):
    """At most two short lines. No numbers, no axis names, no raw values."""
    row = policy_row if isinstance(policy_row, dict) else {}
    if not row.get("enabled"):
        return []
    mode = str(row.get("mode") or "authentic")
    if mode not in LINES:
        mode = "authentic"
    lines = []
    if LINES[mode]:
        lines.append(LINES[mode])
    hints = row.get("hints") if isinstance(row.get("hints"), dict) else {}
    bits = []
    if hints.get("sentence") == "short" and mode not in ("suppress", "leak"):
        bits.append("句子短一点")   # suppress / leak already say it in their line
    elif hints.get("sentence") == "long":
        bits.append("句子可以长一点")
    if hints.get("modifier") == "sparse":
        bits.append("少用修饰")
    elif hints.get("modifier") == "dense":
        bits.append("修饰可以多一点")
    if hints.get("explain") is False:
        bits.append("不必解释")
    if hints.get("soften") is True and mode != "authentic":
        bits.append("可以示弱一点")
    head = lines[0] if lines else ""
    bits = [bit for bit in bits if bit not in head]   # never repeat the mode line
    if bits:
        lines.append("；".join(bits[:3]) + "。")
    return lines[:2]


def merge_extra(base, policy_row):
    """Merge into a batch_d prompt_extra dict instead of a second seam.

    The base keeps its own tone / length / avoid / sources; the expression rows
    are appended to the same hints list, inside the same caps.
    """
    extra = dict(base) if isinstance(base, dict) else {}
    extra.setdefault("schema", SCHEMA)
    extra.setdefault("enabled", True)
    hints = [dict(item) for item in (extra.get("hints") or [])
             if isinstance(item, dict)]
    source = "expression_policy"
    for line in render(policy_row):
        if any(item.get("text") == line and item.get("source") == source
               for item in hints):
            continue
        hints.append({"source": source, "text": line, "chars": len(line)})
    total = 0
    kept = []
    for item in hints:
        size = int(item.get("chars") or len(str(item.get("text") or "")))
        if len(kept) >= MERGE_HINT_LIMIT or total + size > MERGE_BUDGET_CHARS:
            continue
        kept.append(item)
        total += size
    extra["hints"] = kept
    sources = [str(item) for item in (extra.get("sources") or [])]
    if isinstance(policy_row, dict) and policy_row.get("enabled"):
        extra["expression_policy"] = {
            "mode": str(policy_row.get("mode") or "authentic"),
            "hints": dict(policy_row.get("hints") or {}),
            "sources": list(policy_row.get("sources") or [])}
        if source not in sources:
            sources.append(source)
    extra["sources"] = sources
    return extra
