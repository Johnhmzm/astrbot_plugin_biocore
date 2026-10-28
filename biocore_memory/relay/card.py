# -*- coding: utf-8 -*-
"""Relay card: exactly five fields (who/relationship/recent/promises/loops)."""
from __future__ import annotations

_PROMISE_CUES = ("承诺", "答应", "保证", "约定", "约好", "说好", "会一直", "不会离开")
_CHANGE_KEYS = ("identity_weight", "previous_versions", "identity_history",
                "relationship", "trust", "closeness")


def _text(entry, limit=120):
    return str(entry.get("text") or "").strip()[:limit]


def relay_card(entries, now=0.0, open_loops=None, due_enabled=False):
    rows = [e for e in (entries or []) if isinstance(e, dict)]
    identity = [e for e in rows if e.get("self_defining") or e.get("identity")]
    relationship = [e for e in rows if isinstance(e.get("relationship"), dict)
                    or e.get("relationship") or e.get("trust") is not None]
    recent = sorted(rows, key=lambda e: float(e.get("ts", 0.0) or 0.0), reverse=True)
    changes = [e for e in rows if any(k in e for k in _CHANGE_KEYS)]
    promises = [e for e in rows if any(c in _text(e) for c in _PROMISE_CUES)
                or e.get("promise")]
    loops = list(open_loops or [])
    loops += [e for e in rows if e.get("open_loop") or e.get("unresolved")
              or str(e.get("status") or "") in ("open", "open_loop")]
    def _cards(items):
        out = []
        for e in items[:5]:
            out.append({"id": str(e.get("id") or ""), "text": _text(e, 90)})
        return out
    card = {
        "identity": _cards(identity)[:3],
        "relationship": _cards(relationship)[:3],
        "recent_changes": _cards(changes or recent)[:3],
        "promises": _cards(promises)[:3],
        "open_loops": [str(x.get("topic") or x.get("text") or x.get("id") or x)[:90]
                       if isinstance(x, dict) else str(x)[:90] for x in loops][:5],
    }
    if due_enabled:
        hints = []
        for loop in loops:
            if not isinstance(loop, dict):
                continue
            due = loop.get("due") or loop.get("due_ts") or loop.get("deadline")
            text = str(loop.get("topic") or loop.get("text") or "").strip()
            if due and text:
                hints.append(text[:140])
            if hints:
                break
        card["due_hints"] = hints[:1]
    return card
