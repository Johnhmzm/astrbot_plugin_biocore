# -*- coding: utf-8 -*-
"""Learned parameters: one vector, versioned, accepted only on held-out data.

The three learning paths (policy table, mushroom body, hill climbing) each adjust
their own thing and nothing can roll any of it back. This module gives them the
shape a training loop has: a parameter vector, a log of (theta, grade) turns, a
held-out split, and accept/reject with rollback.

Model-free by design: replies come from the model, so a new theta cannot be
re-scored offline. What can be done offline is measuring which knobs track the
grade in the log, then moving them only if that relation holds on turns the
proposal has not seen.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

THETA_FILE = "theta.json"
TURN_LOG = "turn_log.jsonl"
LOG_CAP = 2000

DEFAULTS = {
    "push_gain": 0.35,      # how hard one message moves the body
    "replay_learn": 0.06,   # how much one idle recollection moves the baseline
    "anchor_relax": 0.02,   # how fast the baseline drifts back
    "noise_amp": 0.30,      # spontaneous activity amplitude
}
BOUNDS = {
    "push_gain": (0.10, 0.80),
    "replay_learn": (0.01, 0.20),
    "anchor_relax": (0.005, 0.08),
    "noise_amp": (0.05, 0.60),
}
STEP = 0.05          # 5% move per proposal
MIN_VAL_GAIN = 0.004  # a proposal must beat the incumbent by this on validation
                      # (kept below one step's effect, or nothing ever passes)
MIN_ROWS = 20        # below this there is nothing to learn from


def _path(store, name):
    return os.path.join(str(store), name)


def load(store) -> Dict[str, object]:
    try:
        with open(_path(store, THETA_FILE), "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict) or not isinstance(doc.get("values"), dict):
            raise ValueError
        return doc
    except Exception:
        return {"version": 0, "values": dict(DEFAULTS), "history": []}


def save(store, doc) -> bool:
    try:
        tmp = _path(store, THETA_FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        os.replace(tmp, _path(store, THETA_FILE))
        return True
    except Exception:
        return False


def values(store) -> Dict[str, float]:
    doc = load(store)
    out = dict(DEFAULTS)
    for key, val in (doc.get("values") or {}).items():
        if key in BOUNDS:
            try:
                out[key] = float(val)
            except Exception:
                continue
    return out


def log_turn(store, theta: Dict[str, float], grade: Optional[float], state=None) -> bool:
    """One observation: what theta was in force, and how the exchange scored."""
    if grade is None:
        return False
    try:
        row = {"t": round(float(__import__("time").time()), 1),
               "theta": {k: round(float(v), 4) for k, v in (theta or {}).items()
                         if k in BOUNDS},
               "grade": round(float(grade), 4),
               "state": {k: round(float(state.get(k) or 0.0), 4)
                         for k in ("valence", "stress", "action")
                         if isinstance((state or {}).get(k), (int, float))}}
        path = _path(store, TURN_LOG)
        rows = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    rows = [ln for ln in fh.read().splitlines() if ln.strip()]
            except Exception:
                rows = []
        rows.append(json.dumps(row, ensure_ascii=False))
        rows = rows[-LOG_CAP:]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")
        return True
    except Exception:
        return False


def read_log(store) -> List[Dict[str, object]]:
    try:
        with open(_path(store, TURN_LOG), "r", encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]
    except Exception:
        return []


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def iterate(store, min_rows: int = MIN_ROWS) -> Dict[str, object]:
    """Propose one change, accept it only if held-out turns agree."""
    rows = read_log(store)
    if len(rows) < max(min_rows, 8):
        return {"ok": False, "reason": "not_enough_rows", "rows": len(rows)}
    cut = max(4, int(len(rows) * 0.8))
    train, val = rows[:cut], rows[cut:]
    if len(val) < 4:
        return {"ok": False, "reason": "no_holdout", "rows": len(rows)}

    def score(theta, part):
        """Linear stand-in: grade ~ mean + sum(corr_k * delta_k) over the log."""
        base = _mean([float(r.get("grade") or 0.0) for r in part])
        out = []
        for r in part:
            row_theta = r.get("theta") or {}
            pred = base
            for key in BOUNDS:
                delta = float(theta.get(key, DEFAULTS[key])) - float(row_theta.get(key, DEFAULTS[key]))
                pred += corr.get(key, 0.0) * delta
            out.append(pred)
        return _mean(out)

    corr = {}
    for key in BOUNDS:
        xs, ys = [], []
        for r in train:
            tv = (r.get("theta") or {}).get(key)
            if tv is None:
                continue
            xs.append(float(tv))
            ys.append(float(r.get("grade") or 0.0))
        corr[key] = round(_corr(xs, ys), 4)

    doc = load(store)
    cur = dict(DEFAULTS)
    cur.update({k: float(v) for k, v in (doc.get("values") or {}).items() if k in BOUNDS})
    incumb_train, incumb_val = score(cur, train), score(cur, val)

    best = None
    for key in BOUNDS:
        c = corr.get(key, 0.0)
        if abs(c) < 0.15:          # no usable signal on this knob
            continue
        lo, hi = BOUNDS[key]
        cand = dict(cur)
        move = STEP * (1.0 if c > 0 else -1.0)
        cand[key] = round(min(hi, max(lo, cur[key] * (1.0 + move))), 4)
        if cand[key] == cur[key]:
            continue
        gain_val = score(cand, val) - incumb_val
        if gain_val <= MIN_VAL_GAIN:
            continue
        if best is None or gain_val > best["gain_val"]:
            best = {"key": key, "cand": cand, "gain_val": round(gain_val, 4),
                    "gain_train": round(score(cand, train) - incumb_train, 4)}

    if best is None:
        return {"ok": True, "accepted": False, "reason": "no_gain_on_holdout",
                "rows": len(rows), "corr": corr, "theta": cur}

    doc["version"] = int(doc.get("version") or 0) + 1
    doc["values"] = best["cand"]
    doc.setdefault("history", []).append({
        "version": doc["version"], "knob": best["key"],
        "from": round(cur[best["key"]], 4), "to": round(best["cand"][best["key"]], 4),
        "gain_val": best["gain_val"], "gain_train": best["gain_train"],
        "rows": len(rows)})
    doc["history"] = doc["history"][-50:]
    save(store, doc)
    return {"ok": True, "accepted": True, "version": doc["version"],
            "knob": best["key"], "values": best["cand"],
            "gain_val": best["gain_val"], "corr": corr}


def rollback(store, version: Optional[int] = None) -> Dict[str, object]:
    """Undo the last accepted change (or jump to an earlier version)."""
    doc = load(store)
    hist = list(doc.get("history") or [])
    if not hist:
        return {"ok": False, "reason": "no_history"}
    target = hist[-1]
    if version is not None:
        target = next((h for h in reversed(hist) if int(h.get("version")) == int(version)), target)
    cur = dict(doc.get("values") or DEFAULTS)
    cur[target["knob"]] = target["from"]
    doc["values"] = cur
    doc["version"] = int(doc.get("version") or 0) + 1
    hist.append({"version": doc["version"], "knob": target["knob"],
                 "from": target["to"], "to": target["from"], "rolled_back": True})
    doc["history"] = hist[-50:]
    save(store, doc)
    return {"ok": True, "version": doc["version"], "values": cur}
