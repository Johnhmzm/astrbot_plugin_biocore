# -*- coding: utf-8 -*-
"""MD-1 dual-strength memory model (independent module; no main import, no IO).

Paper basis
-----------
1. Bjork & Bjork (1992), "A new theory of disuse and an old theory of stimulus
   fluctuation": storage strength vs retrieval strength are separate; storage
   strength is almost permanent (rarely decays) and grows on successful
   retrieval, while retrieval strength decays fast with disuse.
2. Anderson & Schooler (1991), "Reflections of the environment in memory":
   probability of recall approximates a power-law function of recency and
   frequency of use.
3. Roediger & Karpicke (2006), "Test-enhanced learning"（testing effect）:
   successful retrieval strengthens later retention (storage strength).
4. McGaugh (2000), "Memory -- a century of consolidation": emotional arousal
   at encoding modulates consolidation, giving a stronger initial trace.
5. Tulving (1974), encoding specificity: retrieval depends on cue/context
   match, so context similarity scales the recall probability.
6. Zeigarnik (1927): unfinished tasks stay accessible longer (open-loop bonus).
7. Ebbinghaus (1885) / Linton (1975): retrieval strength follows a power-law
   decay, not exponential.

Implementation notes
--------------------
- pure functions over plain dicts; time is always injected (now / dt hours);
- entry fields are additive on top of the existing memory entry dict:
    storage_s            0..1   storage strength (grows on recall, ~never decays)
    retrieval_s          0..1   retrieval strength (power-law decay)
    access_count         int    successful retrievals
    last_access_ts       float  last successful retrieval (idempotency guard)
    arousal_at_encoding  0..1   encoding arousal (initial storage boost)
    open_loop            bool   unfinished item (Zeigarnik bonus)
    hidden               bool   set by forget() when retrieval_s < threshold
- coexists with feedback_memory / memory_forgetting; this module does not import
  or modify them.
"""
from __future__ import annotations

import math

# -- constants (paper-mapped; all overridable through function kwargs) --------
D_DEFAULT = 0.5              # Ebbinghaus/Linton power-law exponent
TAU_HOURS_DEFAULT = 24.0     # 1 day time constant
STORAGE_GAIN = 0.1           # Roediger & Karpicke testing effect
RETRIEVAL_BOOST = 0.35       # successful retrieval resets retrieval strength
ENCODE_BASE = 0.35           # Bjork baseline storage at zero arousal
ENCODE_AROUSAL_GAIN = 0.35   # McGaugh arousal modulation
FORGET_THRESHOLD = 0.15      # hidden flag threshold (not a delete)
SCORE_RETRIEVAL_EXP = 0.6    # retrieval ** 0.6
ACCESS_WEIGHT = 0.3          # Anderson & Schooler frequency term
CONTEXT_EXP = 0.5            # Tulving encoding specificity term
DEFAULT_OPEN_LOOP_BONUS = 0.15  # Zeigarnik
MIN_SCORE_DEFAULT = 0.12


def _clamp(value, low=0.0, high=1.0):
    try:
        number = float(value)
    except Exception:
        number = low
    return max(low, min(high, number))


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _hours_since(entry, now):
    stamp = 0.0
    for key in ("last_access_ts", "created_ts"):
        try:
            stamp = max(stamp, float(entry.get(key) or 0.0))
        except Exception:
            continue
    try:
        current = float(now)
    except Exception:
        current = stamp
    if stamp <= 0:
        return 0.0
    return max(0.0, (current - stamp) / 3600.0)


def _context_match(context, entry):
    """Context can be a number, a {"match": x} dict, or {entry_id: x}."""
    if context is None:
        return 1.0
    if isinstance(context, (int, float)):
        return _clamp(context)
    if isinstance(context, dict):
        entry_id = str((entry or {}).get("id") or "")
        for key in (entry_id, "match", "default"):
            if key and key in context:
                return _clamp(context[key])
        return 1.0
    return 1.0


# ------------------------------------------------------------------ formulas
def decay(retrieval_s, dt_hours, d=D_DEFAULT, tau_h=TAU_HOURS_DEFAULT):
    """Power-law retrieval decay: retrieval' = retrieval * (1 + t/tau) ** -d."""
    base = _clamp(retrieval_s)
    try:
        hours = max(0.0, float(dt_hours))
    except Exception:
        hours = 0.0
    try:
        tau = float(tau_h) if float(tau_h) > 0 else TAU_HOURS_DEFAULT
    except Exception:
        tau = TAU_HOURS_DEFAULT
    try:
        power = float(d) if float(d) > 0 else D_DEFAULT
    except Exception:
        power = D_DEFAULT
    return base * math.pow(1.0 + hours / tau, -power)


def encode(text, now, arousal=0.0, open_loop=False):
    """Create a new dual-strength entry (initial retrieval == storage)."""
    storage = _clamp(ENCODE_BASE + ENCODE_AROUSAL_GAIN * _clamp(arousal))
    stamp = _num(now, 0.0)
    return {
        "text": str(text or ""),
        "storage_s": round(storage, 4),
        "retrieval_s": round(storage, 4),
        "access_count": 0,
        "last_access_ts": stamp,
        "arousal_at_encoding": round(_clamp(arousal), 4),
        "open_loop": bool(open_loop),
        "hidden": False,
        "created_ts": stamp,
    }


def on_recall(entry, now, context_match=1.0):
    """Testing effect: storage += 0.1*(1-storage); retrieval += 0.35 (cap 1)."""
    row = dict(entry or {})
    stamp = _num(now, 0.0)
    count = max(0, int(row.get("access_count", 0) or 0))
    last = _num(row.get("last_access_ts", 0.0), 0.0)
    if count > 0 and abs(last - stamp) < 1e-9:
        # idempotent: the same entry cannot be re-consolidated at the same now
        return row
    storage = _clamp(row.get("storage_s", 0.0))
    row["storage_s"] = round(min(1.0, storage + STORAGE_GAIN * (1.0 - storage)), 4)
    retrieval = _clamp(row.get("retrieval_s", 0.0))
    row["retrieval_s"] = round(min(1.0, retrieval + RETRIEVAL_BOOST), 4)
    row["access_count"] = count + 1
    row["last_access_ts"] = stamp
    row["last_context_match"] = round(_clamp(context_match), 4)
    return row


def score(entry, now, context_match=1.0, open_loop_bonus=DEFAULT_OPEN_LOOP_BONUS):
    """P(recall) = retrieval^0.6 * (1+0.3*ln(1+access)) * context^0.5 * (1+bonus)."""
    row = entry if isinstance(entry, dict) else {}
    if row.get("hidden"):
        return 0.0
    hours = _hours_since(row, now)
    retrieval = decay(row.get("retrieval_s", 0.0), hours)
    access = max(0, int(row.get("access_count", 0) or 0))
    frequency = 1.0 + ACCESS_WEIGHT * math.log1p(access)
    context = _clamp(context_match)
    bonus = (float(open_loop_bonus) if row.get("open_loop") else 0.0)
    value = (math.pow(max(0.0, retrieval), SCORE_RETRIEVAL_EXP)
             * frequency
             * math.pow(context, CONTEXT_EXP)
             * (1.0 + max(0.0, bonus)))
    return round(value, 6)


def select(entries, now, limit=4, context=None, min_score=MIN_SCORE_DEFAULT):
    """Rank candidates by P(recall); return {picked, skipped} with scores."""
    rows = [entry for entry in (entries or []) if isinstance(entry, dict)]
    ranked = []
    for entry in rows:
        match = _context_match(context, entry)
        value = score(entry, now, context_match=match)
        ranked.append({
            "entry": dict(entry),
            "id": str(entry.get("id") or ""),
            "text": str(entry.get("text") or "")[:80],
            "score": value,
            "retrieval_s": round(decay(entry.get("retrieval_s", 0.0),
                                       _hours_since(entry, now)), 4),
            "storage_s": round(_clamp(entry.get("storage_s", 0.0)), 4),
            "context_match": round(match, 4),
        })
    ranked.sort(key=lambda row: (-row["score"], row["id"]))
    picked = [row for row in ranked if row["score"] >= float(min_score)][:max(0, int(limit))]
    picked_ids = {id(row) for row in picked}
    skipped = []
    for row in ranked:
        if id(row) in picked_ids:
            continue
        if row["entry"].get("hidden"):
            reason = "hidden"
        elif row["score"] < float(min_score):
            reason = "below_min_score"
        else:
            reason = "limit"
        skipped.append({"id": row["id"], "score": row["score"], "reason": reason})
    return {"picked": picked, "skipped": skipped,
            "min_score": float(min_score), "now": float(_num(now, 0.0))}


def forget(entries, now, threshold=FORGET_THRESHOLD):
    """Mark entries whose decayed retrieval < threshold hidden (never delete)."""
    out = []
    forgotten = []
    for entry in entries or []:
        row = dict(entry or {})
        retrieval = decay(row.get("retrieval_s", 0.0), _hours_since(row, now))
        row["retrieval_now"] = round(retrieval, 4)
        if retrieval < float(threshold) and not row.get("hidden"):
            row["hidden"] = True
            row["hidden_ts"] = _num(now, 0.0)
            row["hidden_reason"] = "retrieval_below_threshold"
            forgotten.append(str(row.get("id") or ""))
        out.append(row)
    return {"entries": out, "forgotten_ids": forgotten}
