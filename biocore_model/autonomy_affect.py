# -*- coding: utf-8 -*-
"""Autonomy -> core affect increments, deduped by last_apply_ts."""
from __future__ import annotations

DT_CAP_HOURS = 6.0


def clamp(value, low, high):
    return max(low, min(high, float(value)))


def compute_deltas(dt_hours, phase_weight=0.0, self_blame=0.0):
    dt = max(0.0, min(DT_CAP_HOURS, float(dt_hours or 0.0)))
    weight = clamp(phase_weight, 0.0, 4.0)
    blame = clamp(self_blame, 0.0, 1.0)
    return {"valence": -0.06 * dt / 24.0 * weight - 0.10 * blame,
            "arousal": 0.0,
            "stress": 0.0,
            "lonely": 0.08 * dt / 24.0 * weight,
            "confidence": round(1.0 - 0.5 * blame, 4)}


def apply(core, acc, now, silence_hours=0.0, phase_weight=0.0, self_blame=0.0):
    """Apply one increment per tick (idempotent within the same timestamp)."""
    acc = dict(acc or {})
    try:
        now = float(now)
    except Exception:
        now = 0.0
    last = float(acc.get("last_apply_ts", 0.0) or 0.0)
    if now > 0 and last > 0 and now <= last:
        return {"valence": 0.0, "arousal": 0.0, "stress": 0.0, "lonely": 0.0,
                "confidence": clamp(getattr(core, "confidence", 1.0), 0.0, 1.0)}, acc
    dt = min(DT_CAP_HOURS, max(0.0, (now - last) / 3600.0)) if last > 0 else 0.0
    deltas = compute_deltas(dt, phase_weight, self_blame)
    try:
        core.v = clamp(float(getattr(core, "v", 0.0) or 0.0) + deltas["valence"], -0.6, 1.0)
        core.a = clamp(float(getattr(core, "a", 0.0) or 0.0) + deltas["arousal"], 0.0, 1.0)
        core.stress = clamp(float(getattr(core, "stress", 0.0) or 0.0) + deltas["stress"], 0.0, 1.0)
        if hasattr(core, "social"):
            core.social = clamp(float(getattr(core, "social", 0.0) or 0.0) + deltas["lonely"], 0.0, 1.0)
        core.confidence = deltas["confidence"]
        core.autonomy_affect = {"silence_hours": round(float(silence_hours or 0.0), 3),
                                "self_blame": round(clamp(self_blame, 0.0, 1.0), 4),
                                "frustration": int(acc.get("frustration", 0) or 0),
                                "applied_valence_delta": round(deltas["valence"], 5)}
    except Exception:
        pass
    acc["last_apply_ts"] = now
    acc["affect"] = {key: round(deltas[key], 5) for key in ("valence", "arousal", "stress", "lonely")}
    return deltas, acc
