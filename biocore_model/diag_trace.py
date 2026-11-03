# -*- coding: utf-8 -*-
"""Read-only per-turn diagnosis: "why did this turn happen".

The dashboard cannot explain a reply from the final text alone. This module
turns the numbers the turn already computed into one bounded record:

- state_delta   which biological values moved (and by how much)
- intent        who decided what she wants (self layer + candidates order)
- metacog       confidence band / self-correction / convergence
- length        the length constraint and where it came from
- prompt        how the injected block differs from the previous turn

Pure functions only: no IO, no clock, no host imports, no LLM calls. The caller
owns storage (jsonl) and the dashboard endpoint.
"""
from __future__ import annotations

SNAPSHOT_KEYS = (
    "v", "a", "d", "social", "stress", "energy", "trust",
    "boundary_pressure", "conflict_ema", "rumination_ema",
    "attention", "boredom", "novelty_need", "allostatic_load",
    "belonging", "self_esteem", "control", "meaningful_existence",
)
NEED_KEYS = ("belonging", "self_esteem", "control", "meaningful_existence")
MAX_DELTA_KEYS = 18
MAX_ROWS = 50
PREVIEW_CHARS = 160
TEXT_CHARS = 420
SWITCH_KEYS = ("self_intent_enabled", "prospective_enabled", "voice_bank_enabled",
               "metacog_enabled", "diag_trace_enabled")


def _num(value, default=0.0):
    try:
        num = float(value)
    except Exception:
        return float(default)
    if num != num:
        return float(default)
    return num


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _num(value, low)))


def _snap_value(source, key):
    if isinstance(source, dict):
        if key in source:
            return _num(source.get(key), 0.0)
        needs = source.get("needs")
        if isinstance(needs, dict) and key in needs:
            return _num(needs.get(key), 0.0)
        return 0.0
    return _num(getattr(source, key, 0.0), 0.0)


def state_snapshot(core):
    """Bounded numeric snapshot of the values a turn can move."""
    out = {}
    for key in SNAPSHOT_KEYS:
        out[key] = round(_snap_value(core, key), 4)
    return out


def diff_state(before, after):
    """Only the values that actually moved, in snapshot order."""
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    out = {}
    for key in SNAPSHOT_KEYS:
        delta = round(_num(after.get(key), 0.0) - _num(before.get(key), 0.0), 4)
        if abs(delta) >= 0.001:
            out[key] = delta
    return out


def _lines(text):
    return [line for line in str(text or "").splitlines() if line.strip()]


def prompt_diff(prev_prompt, current_prompt):
    """Bounded line-level difference between two injected blocks."""
    prev_text = str(prev_prompt or "")
    current_text = str(current_prompt or "")
    prev_lines = _lines(prev_text)
    current_lines = _lines(current_text)
    added = 0
    removed = 0
    remaining = list(prev_lines)
    for line in current_lines:
        if line in remaining:
            remaining.remove(line)
        else:
            added += 1
    removed = len(remaining)
    changed = bool(added or removed or prev_text != current_text)
    preview = ""
    if changed:
        limit = min(len(prev_text), len(current_text))
        index = 0
        while index < limit and prev_text[index] == current_text[index]:
            index += 1
        preview = current_text[max(0, index - 20):index + PREVIEW_CHARS].strip()
    return {
        "changed": changed,
        "chars": len(current_text),
        "chars_delta": len(current_text) - len(prev_text),
        "lines_added": min(999, added),
        "lines_removed": min(999, removed),
        "preview": preview[:PREVIEW_CHARS],
    }


def _intent_view(result):
    result = result if isinstance(result, dict) else {}
    intents = [item for item in (result.get("intents") or [])
               if isinstance(item, dict)]
    top = result.get("top") or (intents[0].get("kind") if intents else "")
    weight = 0.0
    reason = ""
    for item in intents:
        if str(item.get("kind") or "") == str(top):
            weight = _clamp(item.get("weight", 0.0))
            reason = str(item.get("reason") or "")[:40]
            break
    return {
        "top": str(top or "")[:8],
        "weight": round(weight, 3),
        "reason": reason,
        "motivation": str(result.get("motivation") or "")[:20],
        "self_weight": round(_clamp(result.get("self_weight", 0.5)), 3),
        "drive": round(_clamp(result.get("drive", 0.0)), 3),
        "urge": round(_clamp(result.get("urge", 0.0)), 3),
        "satisfaction": round(max(-1.0, min(1.0, _num(result.get("satisfaction"), 0.0))), 3),
    }


def _candidate_view(result, limit=4):
    rows = []
    for item in (result.get("candidates") if isinstance(result, dict) else []) or []:
        if isinstance(item, dict):
            rows.append({"kind": str(item.get("kind") or "")[:8],
                         "score": round(_clamp(item.get("score", 0.0)), 3)})
    return rows[:limit]


def _metacog_view(result):
    result = result if isinstance(result, dict) else {}
    return {
        "band": str(result.get("band") or "")[:8],
        "confidence": round(_clamp(result.get("confidence", 0.6)), 3),
        "converge": bool(result.get("converge", False)),
        "allow_self_correction": bool(result.get("allow_self_correction", False)),
        "reason": str(result.get("reason") or "")[:40],
    }


def _string_list(values, limit, cap):
    out = []
    for item in (values or [])[:limit] if isinstance(values, (list, tuple)) else []:
        text = str(item or "").strip()[:cap]
        if text:
            out.append(text)
    return out


def _switch_view(switches):
    data = switches if isinstance(switches, dict) else {}
    return {key: bool(data.get(key, False)) for key in SWITCH_KEYS}


def build(*, before=None, after=None, intent=None, metacog=None,
          pending_prompts=None, voice_phrases=None, length=None,
          hints=None, prompt=None, session="", ts=0.0, turn=0,
          latency_ms=0.0, text_chars=0, switches=None):
    """One bounded, JSON-ready turn record (no IO)."""
    length = length if isinstance(length, dict) else {}
    hints = hints if isinstance(hints, dict) else {}
    prompt = prompt if isinstance(prompt, dict) else {}
    prompt_view = {
        "changed": bool(prompt.get("changed", False)),
        "chars": max(0, int(_num(prompt.get("chars"), 0.0))),
        "chars_delta": int(_num(prompt.get("chars_delta"), 0.0)),
        "lines_added": max(0, int(_num(prompt.get("lines_added"), 0.0))),
        "lines_removed": max(0, int(_num(prompt.get("lines_removed"), 0.0))),
        "preview": str(prompt.get("preview") or "")[:PREVIEW_CHARS],
    }
    scale = _clamp(length.get("scale", 1.0), 0.0, 2.0) or 1.0
    return {
        "ts": round(_num(ts, 0.0), 3),
        "session": str(session or "")[:80],
        "turn": max(0, int(_num(turn, 0.0))),
        "latency_ms": round(max(0.0, _num(latency_ms, 0.0)), 1),
        "text_chars": max(0, int(_num(text_chars, 0.0))),
        "state_delta": diff_state(before, after),
        "intent": _intent_view(intent),
        "candidates": _candidate_view(intent),
        "metacog": _metacog_view(metacog),
        "pending_prompts": _string_list(pending_prompts, 3, 60),
        "voice_phrases": _string_list(voice_phrases, 2, 20),
        "length": {
            "scale": round(scale, 3),
            "brevity": str(length.get("brevity") or "normal")[:8],
            "source": str(length.get("source") or "default")[:16],
            "target": max(0, int(_num(length.get("target"), 0.0))),
            "cap": max(0, int(_num(length.get("cap"), 0.0))),
        },
        "hints": {
            "strategy": str(hints.get("strategy") or "")[:140],
            "prospective": str(hints.get("prospective") or "")[:80],
            "voice": str(hints.get("voice") or "")[:80],
            "metacog": str(hints.get("metacog") or "")[:80],
        },
        "prompt": prompt_view,
        "switches": _switch_view(switches),
    }


def render_text(record, limit=TEXT_CHARS):
    """One structured line for the log (bounded, no secrets)."""
    if not isinstance(record, dict):
        return ""
    delta = record.get("state_delta") if isinstance(record.get("state_delta"), dict) else {}
    delta_text = ",".join("%s%+0.3f" % (key, _num(value))
                          for key, value in list(delta.items())[:MAX_DELTA_KEYS])
    intent = record.get("intent") if isinstance(record.get("intent"), dict) else {}
    meta = record.get("metacog") if isinstance(record.get("metacog"), dict) else {}
    length = record.get("length") if isinstance(record.get("length"), dict) else {}
    prompt = record.get("prompt") if isinstance(record.get("prompt"), dict) else {}
    parts = [
        "turn=%d" % int(_num(record.get("turn"), 0)),
        "session=%s" % str(record.get("session") or "")[:32],
        "intent=%s %.2f (%s)" % (str(intent.get("top") or "?"),
                                 _num(intent.get("weight")),
                                 str(intent.get("reason") or "")[:24]),
        "motivation=%s" % str(intent.get("motivation") or ""),
        "self_weight=%.2f" % _num(intent.get("self_weight")),
        "state=%s" % (delta_text or "-"),
        "meta=%s/%.2f%s" % (str(meta.get("band") or "?"),
                            _num(meta.get("confidence")),
                            "/converge" if meta.get("converge") else ""),
        "len=%.2f(%s)/%s" % (_num(length.get("scale"), 1.0),
                             str(length.get("source") or "default"),
                             str(length.get("brevity") or "normal")),
        "prompt=chars%d d%+d +%d/-%d" % (
            int(_num(prompt.get("chars"), 0)),
            int(_num(prompt.get("chars_delta"), 0)),
            int(_num(prompt.get("lines_added"), 0)),
            int(_num(prompt.get("lines_removed"), 0))),
    ]
    return " | ".join(parts)[:int(limit)]


def append(rows, record, limit=MAX_ROWS):
    """Append one record and keep only the newest limit rows (pure)."""
    kept = [row for row in (rows or []) if isinstance(row, dict)]
    if isinstance(record, dict):
        kept.append(record)
    try:
        size = max(1, int(limit))
    except Exception:
        size = MAX_ROWS
    return kept[-size:]


def view(rows, limit=3):
    """Newest-first rows for the read-only panel."""
    kept = [row for row in (rows or []) if isinstance(row, dict)]
    try:
        size = max(1, int(limit))
    except Exception:
        size = 3
    return list(reversed(kept[-size:]))
