# -*- coding: utf-8 -*-
"""Autonomy drive + expected-utility gate (docs/AUTONOMY-MODEL.md).

drive = w_social*social_gap + w_lonely*lonely + w_stress*stress_load
      + w_drive*drive_dev + w_echo*echo + w_noise*noise
gate  = P_ready * B - C_fp   (Horvitz 1999 expected utility)
"""
from __future__ import annotations

import math

DEFAULTS = {
    "tau_hours": 18.0, "w_social": 0.25, "w_lonely": 0.12, "w_anxiety": 0.12,
    "w_sadness": 0.10, "w_joy": 0.08, "w_anger": 0.08, "w_boredom": 0.05,
    "w_stress": 0.10, "w_drive": 0.10, "gate_c0": 0.35,
    "quiet_start": 23, "quiet_end": 8, "noise_sigma": 0.08,
    "leak": 0.15, "theta": 0.55, "sigma": 0.06, "memory_cooldown_days": 7,
}
EMOTION_PARTS = ("lonely", "anxiety_fear", "sadness", "joy", "anger_conflict", "boredom")
WEIGHT_KEYS = ("w_social", "w_lonely", "w_anxiety", "w_sadness", "w_joy",
               "w_anger", "w_boredom", "w_stress", "w_drive")
CONFIG_KEYS = {
    "tau_hours": "autonomy_tau_hours", "w_social": "autonomy_w_social",
    "w_lonely": "autonomy_w_lonely", "w_stress": "autonomy_w_stress",
    "w_drive": "autonomy_w_drive", "w_echo": "autonomy_w_echo",
    "w_anxiety": "autonomy_w_anxiety", "w_sadness": "autonomy_w_sadness",
    "w_joy": "autonomy_w_joy", "w_anger": "autonomy_w_anger",
    "w_boredom": "autonomy_w_boredom", "w_distress": "autonomy_w_distress",
    "w_activity": "autonomy_w_activity", "w_open_loops": "autonomy_w_open_loops",
    "w_nostalgia": "autonomy_w_nostalgia", "w_repair": "autonomy_w_repair",
    "gate_c0": "autonomy_gate_c0",
}


def clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def social_gap(gap_hours, tau_hours=18.0, social_baseline=0.5, closeness=0.5):
    try:
        gap = max(0.0, float(gap_hours))
    except Exception:
        gap = 0.0
    tau = max(0.1, float(tau_hours or 18.0))
    base = 1.0 - math.exp(-gap / tau)
    return clamp(base * clamp(social_baseline, 0.0, 1.0) * (0.6 + 0.4 * clamp(closeness)))


def lonely(prob=0.0, intensity=0.0):
    return clamp(float(prob or 0.0) * clamp(intensity))


def sigmoid(x):
    try:
        return 1.0 / (1.0 + math.exp(-float(x)))
    except Exception:
        return 0.0


def drive(parts, weights=None):
    w = dict(DEFAULTS)
    w.update(weights or {})
    total = sum(float(w[k]) for k in WEIGHT_KEYS) or 1.0
    p = parts or {}
    value = (float(w["w_social"]) * clamp(p.get("social_gap"))
             + float(w["w_lonely"]) * clamp(p.get("lonely"))
             + float(w["w_anxiety"]) * clamp(p.get("anxiety_fear"))
             + float(w["w_sadness"]) * clamp(p.get("sadness"))
             + float(w["w_joy"]) * clamp(p.get("joy"))
             + float(w["w_anger"]) * clamp(p.get("anger_conflict"))
             + float(w["w_boredom"]) * clamp(p.get("boredom"))
             + float(w["w_stress"]) * clamp(p.get("stress_load"))
             + float(w["w_drive"]) * clamp(p.get("drive_dev")))
    return clamp(value / total)


def gate(drive_value, threshold, closeness=0.5, cost0=0.35, quiet=False,
         recent_user_active=False, lonely_value=0.0, anxiety=0.0, anger=0.0, joy=0.0):
    p_ready = sigmoid((clamp(drive_value) - clamp(threshold)) / 0.08)
    benefit = 0.5 + 0.5 * clamp(closeness)
    cost = (float(cost0) + (0.25 if quiet else 0.0) - (0.15 if recent_user_active else 0.0)
            - 0.10 * clamp(lonely_value) - 0.08 * clamp(anxiety)
            + 0.10 * clamp(anger) - 0.05 * clamp(joy))
    cost = clamp(cost, 0.05, 1.0)
    expected = p_ready * benefit - cost
    return {"p_ready": round(p_ready, 4), "benefit": round(benefit, 4),
            "cost": round(cost, 4), "expected": round(expected, 4),
            "allowed": bool(expected > 0)}


def habit(drive_value, unanswered=0):
    try:
        count = max(0, int(unanswered or 0))
    except Exception:
        count = 0
    return clamp(clamp(drive_value) * (0.7 ** count))


def compute(parts, threshold, closeness=0.5, weights=None, unanswered=0,
            quiet=False, recent_user_active=False, cost0=0.35, lonely_value=0.0):
    base_drive = drive(parts, weights)
    effective_drive = habit(base_drive, unanswered)
    p = parts or {}
    g = gate(effective_drive, threshold, closeness, cost0, quiet, recent_user_active,
             lonely_value if lonely_value is not None else p.get("lonely", 0.0),
             p.get("anxiety_fear", 0.0), p.get("anger_conflict", 0.0), p.get("joy", 0.0))
    return {"drive": round(effective_drive, 4), "drive_base": round(base_drive, 4),
            "parts": {k: round(clamp(p.get(k)), 4) for k in
                      ("social_gap", "lonely", "anxiety_fear", "sadness", "distress",
                       "joy", "anger_conflict", "boredom", "activity", "user_busy",
                       "stress_load", "drive_dev", "open_loops", "nostalgia",
                       "repair_urge", "contact_mult", "guilt", "gratitude")},
            "gate": g, "ready": bool(g["allowed"] and effective_drive >= clamp(threshold))}


# ---------------------------------------------------------------- v3 accumulator
# Evidence accumulation (DDM / LIF): noise is the TRIGGER mechanism, not a weight.
V3_DEFAULTS = {"leak": 0.15, "theta": 0.55, "sigma": 0.06, "tick_seconds": 300,
               "refractory_seconds": 1800, "daily_cap": 3}

DRIFT_WEIGHTS = {"social_gap": 0.16, "lonely": 0.08, "anxiety_fear": 0.13,
                 "sadness": 0.07, "distress": 0.04, "joy": 0.06,
                 "anger_conflict": 0.06, "boredom": 0.03, "activity": 0.03,
                 "stress_load": 0.07, "drive_dev": 0.06, "open_loops": 0.04,
                 "nostalgia": 0.02, "repair_urge": 0.02, "memory_due": 0.10,
                 "guilt": 0.02, "gratitude": 0.01}


def distress_value(sadness, anger, valence=0.0):
    v = clamp((float(valence) + 1.0) / 2.0)  # -1..1 -> 0..1
    return clamp(0.6 * max(clamp(sadness), clamp(anger)) + 0.4 * (1.0 - v))


def activity_value(energy=0.0, curiosity=0.0, extraversion=0.0):
    return clamp(0.5 * clamp(energy) + 0.3 * clamp(curiosity) + 0.2 * clamp(extraversion))


def user_busy_value(recent_reply_ratio=1.0, short_gap_min=0.0):
    try:
        ratio = float(recent_reply_ratio)
    except Exception:
        ratio = 1.0
    try:
        gap = float(short_gap_min or 0.0)
    except Exception:
        gap = 0.0
    busy = 0.5 * (1.0 - clamp(ratio, 0.0, 2.0)) + 0.5 * (min(max(0.0, gap), 30.0) / 30.0)
    return clamp(busy)


def nostalgia_value(hours_since_shared, tau_hours=6.0):
    try:
        hours = max(0.0, float(hours_since_shared))
    except Exception:
        hours = 0.0
    return clamp(math.exp(-hours / max(0.1, float(tau_hours or 6.0))))


def repair_urge_value(conflict=0.0, guilt=0.0):
    return clamp(0.7 * clamp(conflict) + 0.3 * clamp(guilt))


def contact_mult(attachment_safe=0.5):
    return 1.0 + 0.6 * (1.0 - clamp(attachment_safe))


def parts_from_state(core, relationship=None, now=None, acc=None,
                     params=None, social_baseline=None):
    """Build L4 motive parts from a live core + relationship record.

    The autonomy tick previously read snapshot["parts"], but core.snapshot()
    does not expose a parts dict -> drift_value({}) was always 0 and V could
    never accumulate. This adapter is the single source of those parts.
    """
    def _num(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    snap = {}
    try:
        snap = core.snapshot() if callable(getattr(core, "snapshot", None)) else {}
    except Exception:
        snap = {}
    snap = snap if isinstance(snap, dict) else {}
    acc = acc if isinstance(acc, dict) else {}
    params = params if isinstance(params, dict) else {}
    rel = relationship if isinstance(relationship, dict) else {}
    rel_state = rel.get("state") if isinstance(rel.get("state"), dict) else {}
    closeness = clamp(rel_state.get("closeness", 0.5))
    conflict = clamp(rel_state.get("conflict", 0.5))
    repair = clamp(rel_state.get("repair", 0.0))
    attachment = rel.get("attachment") if isinstance(rel.get("attachment"), dict) else {}
    attachment_safe = clamp(attachment.get("safe", 0.5))
    labels = getattr(core, "labels", {}) or {}
    emotion = str(labels.get("emotion") or "neutral")
    intensity = clamp(labels.get("intensity", 0.0))
    by_emotion = {"sadness": "sadness", "anger": "anger_conflict",
                  "fear": "anxiety_fear", "joy": "joy",
                  "loneliness": "lonely"}
    parts = {key: 0.0 for key in (
        "social_gap", "lonely", "anxiety_fear", "sadness", "distress", "joy",
        "anger_conflict", "boredom", "activity", "user_busy", "stress_load",
        "drive_dev", "attachment_safe", "open_loops", "memory_due",
        "nostalgia", "repair_urge", "guilt", "gratitude", "contact_mult")}
    for emo, key in by_emotion.items():
        if emotion == emo:
            parts[key] = max(parts[key], intensity)
    try:
        if now is not None and float(acc.get("last_user_msg_ts", 0.0) or 0.0) > 0:
            gap_hours = max(0.0, (float(now) - float(acc["last_user_msg_ts"])) / 3600.0)
        else:
            gap_hours = 0.0
    except Exception:
        gap_hours = 0.0
    social_tau = max(0.5, _num(params.get("social_tau_hours", 18.0), 18.0))
    social_base = clamp(0.5 if social_baseline is None else social_baseline)
    parts["social_gap"] = round(social_gap(
        gap_hours, tau_hours=social_tau, social_baseline=social_base,
        closeness=closeness), 4)
    # Silence itself is a missing-social signal: with tau=2h this crosses the
    # V threshold (theta*leak) around 1-2h of silence even in a calm state,
    # instead of staying under the leak floor for ~12h.
    silence_tau = max(0.1, _num(params.get("silence_tau_hours", 2.0), 2.0))
    silence_lonely = 1.0 - math.exp(-gap_hours / silence_tau)
    parts["lonely"] = round(max(parts["lonely"], 0.6 * (1.0 - closeness),
                               silence_lonely), 4)
    stress = clamp(snap.get("stress", 0.0))
    allostatic = clamp(snap.get("allostatic_load", 0.0))
    parts["stress_load"] = round(clamp(0.6 * stress + 0.4 * allostatic), 4)
    homeo = snap.get("homeostasis") if isinstance(snap.get("homeostasis"), dict) else {}
    parts["drive_dev"] = round(clamp(homeo.get("L_int", 0.0)), 4)
    energy = clamp(snap.get("energy", 0.5))
    arousal = clamp(snap.get("a", 0.5))
    parts["activity"] = round(clamp(0.6 * energy + 0.4 * arousal), 4)
    parts["boredom"] = round(clamp(snap.get("boredom", 0.0)), 4)
    parts["distress"] = round(clamp(0.5 * stress + 0.5 * parts["sadness"]), 4)
    loops = snap.get("open_loops") if isinstance(snap.get("open_loops"), list) else []
    parts["open_loops"] = round(clamp(len(loops) / 5.0), 4)
    due = _num(snap.get("open_loops_due", 0.0))
    parts["memory_due"] = round(clamp(due / 3.0), 4)
    parts["attachment_safe"] = round(attachment_safe, 4)
    parts["contact_mult"] = round(1.0 + 0.6 * (1.0 - attachment_safe), 4)
    parts["repair_urge"] = round(clamp(conflict * (1.0 - repair)), 4)
    parts["user_busy"] = 0.0
    return {key: round(clamp(value), 4) for key, value in parts.items()}


def drift_value(parts, weights=None, traits=None):
    w = dict(DRIFT_WEIGHTS); w.update(weights or {})
    p = parts or {}
    t = traits or {}
    mult = contact_mult(p.get("attachment_safe", 0.5)) if "attachment_safe" in p else float(p.get("contact_mult", 1.0) or 1.0)
    social_raw = clamp(p.get("social_gap")) * (1.0 + 0.5 * clamp(p.get("user_busy"))) * mult
    social_term = clamp(float(w["social_gap"]) * social_raw)
    lonely_term = clamp(float(w["lonely"]) * clamp(p.get("lonely")) * mult)
    open_term = clamp(float(w["open_loops"]) * clamp(p.get("open_loops")) * mult)
    memory = clamp(p.get("memory_due")) * (0.6 + 0.8 * clamp(t.get("conscientiousness", 0.5), 0.0, 1.5))
    activity = clamp(p.get("activity")) * (0.7 + 0.6 * clamp(t.get("extraversion", 0.5), 0.0, 1.5))
    value = (social_term
             + lonely_term
             + float(w["anxiety_fear"]) * clamp(p.get("anxiety_fear"))
             + float(w["sadness"]) * clamp(p.get("sadness"))
             + float(w["distress"]) * clamp(p.get("distress"))
             + float(w["joy"]) * clamp(p.get("joy"))
             + float(w["anger_conflict"]) * clamp(p.get("anger_conflict"))
             + float(w["boredom"]) * clamp(p.get("boredom"))
             + float(w["activity"]) * clamp(activity)
             + float(w["stress_load"]) * clamp(p.get("stress_load"))
             + float(w["drive_dev"]) * clamp(p.get("drive_dev"))
             + open_term
             + float(w["nostalgia"]) * clamp(p.get("nostalgia"))
             + float(w["repair_urge"]) * clamp(p.get("repair_urge"))
             + float(w["memory_due"]) * clamp(memory, 0.0, 1.0)
             + float(w["guilt"]) * clamp(p.get("guilt"))
             + float(w["gratitude"]) * clamp(p.get("gratitude")))
    return clamp(value)


def step(V, drift, leak=0.15, sigma=0.06, theta=0.55, xi=None, rng=None):
    """One tick: V = V*(1-leak) + drift + xi; fire when V >= theta."""
    import random
    r = rng or random
    noise = float(xi) if xi is not None else (r.gauss(0.0, float(sigma)) if float(sigma) > 0 else 0.0)
    raw = float(V) * (1.0 - clamp(leak, 0.0, 0.5)) + float(drift) + noise
    # V is accumulated evidence: it lives in [0, +inf) and can never go
    # negative. A negative drift just floors at 0 until the next positive
    # evidence arrives (the threshold clears it separately).
    value = max(0.0, raw)
    fire = value >= float(theta)
    return {"V": 0.0 if fire else value, "V_raw": raw, "fire": bool(fire),
            "xi": round(noise, 4), "theta": round(float(theta), 4),
            "drift": round(float(drift), 4),
            "to_threshold": round(max(0.0, float(theta) - value), 4)}


def on_user_reply(V):
    return clamp(float(V) * 0.3, 0.0, 10.0)


def memory_due(events, now_ts, triggered=None, cooldown_days=7, weights=None):
    """Event due pulses: today=1.0, tomorrow=0.7, day-after=0.4; commitments bonus."""
    w = {"today": 1.0, "tomorrow": 0.7, "after": 0.4, "commitment_bonus": 0.2}
    w.update(weights or {})
    triggered = triggered if isinstance(triggered, dict) else {}
    now = float(now_ts)
    best = 0.0
    fired = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        key = str(event.get("id") or event.get("title") or "")
        if not key or key in triggered:
            continue
        due = event.get("due_ts") or event.get("due_at_ts") or 0
        try:
            due = float(due)
        except Exception:
            continue
        days = (due - now) / 86400.0
        if days < -0.5 or days > 2.5:
            continue
        weight = w["today"] if days < 0.5 else (w["tomorrow"] if days < 1.5 else w["after"])
        text = str(event.get("title") or event.get("text") or "")
        if any(word in text for word in ("答应", "承诺", "别忘", "记得")):
            weight = min(1.0, weight + w["commitment_bonus"])
        if weight > best:
            best = weight
            fired = [key]
    return {"memory_due": best, "events": fired}


def accumulator_snapshot(acc, theta=0.55):
    acc = acc if isinstance(acc, dict) else {}
    value = float(acc.get("V", 0.0) or 0.0)
    return {"V": round(value, 4), "theta": round(float(theta), 4),
            "drift": round(float(acc.get("drift", 0.0) or 0.0), 4),
            "leak": round(float(acc.get("leak", 0.15) or 0.15), 4),
            "sigma": round(float(acc.get("sigma", 0.06) or 0.06), 4),
            "ticks_since_fire": int(acc.get("ticks_since_fire", 0) or 0),
            "to_threshold": round(max(0.0, float(theta) - value), 4)}


def test_trigger(acc, reset=False, arm=False):
    """Force one near-threshold tick (0.9*theta) or reset the accumulator."""
    acc = dict(acc or {})
    theta = clamp(acc.get("theta", 0.55) or 0.55, 0.0, 10.0)
    if reset:
        acc.update({"V": 0.0, "ticks_since_fire": 0})
        return {"ok": True, "V_set": 0.0, "theta": round(theta, 4), "reset": True,
                "note": "V reset to 0"}
    value = round((1.05 if arm else 0.9) * theta, 4)
    acc.update({"V": value, "ticks_since_fire": 0})
    return {"ok": True, "V_set": value, "theta": round(theta, 4), "reset": False,
            "note": "V set to " + ("1.05" if arm else "0.9") + "*theta; next tick may fire"}


def status_snapshot(acc, parts=None, tick_seconds=300, block_reason="", gate_allowed=False):
    """Read-only projection for /page/status (never advances a tick)."""
    src = dict(acc or {})
    value = float(src.get("V", 0.0) or 0.0)
    theta = clamp(src.get("theta", 0.55) or 0.55, 0.0, 10.0)
    drift = float(src.get("drift", 0.0) or 0.0)
    to_threshold = max(0.0, theta - value)
    try:
        eta_hours = round(to_threshold / max(drift, 1e-6) * float(tick_seconds or 300) / 3600.0, 2) if drift > 0 else None
    except Exception:
        eta_hours = None
    return {"V": round(value, 4), "theta": round(theta, 4), "drift": round(drift, 4),
            "leak": round(float(src.get("leak", 0.15) or 0.15), 4),
            "sigma": round(float(src.get("sigma", 0.06) or 0.06), 4),
            "ticks_since_fire": int(src.get("ticks_since_fire", 0) or 0),
            "to_threshold": round(to_threshold, 4),
            "eta_hours": eta_hours,
            "parts": {k: round(clamp((parts or {}).get(k)), 4) for k in DRIFT_WEIGHTS},
            "gate_allowed": bool(gate_allowed), "block_reason": str(block_reason or ""),
            "last_tick_ts": float(src.get("last_tick_ts", 0.0) or 0.0),
            "silence": dict(src.get("silence") or {}),
            "affect": dict(src.get("affect") or {}),
            "limit": limit_view(src, int(src.get("hourly_cap", HOURLY_CAP_DEFAULT) or HOURLY_CAP_DEFAULT),
                                daily_cap=int(src.get("daily_cap", 5) or 5))}


def send_gate(state, private=True, now=None, quiet_start=23, quiet_end=8,
              cooldown_seconds=1800, daily_cap=3, send_enabled=True):
    """Safety gates for a v3 fire; returns (allowed, reason)."""
    import time
    state = state if isinstance(state, dict) else {}
    if not private:
        return False, "not_private"
    if not send_enabled:
        return False, "send_disabled"
    current = float(now if now is not None else time.time())
    hour = time.localtime(current).tm_hour
    if (quiet_start <= hour < quiet_end) if quiet_start <= quiet_end else (hour >= quiet_start or hour < quiet_end):
        return False, "quiet_hours"
    try:
        last_ts = float(state.get("last_sent_ts", 0.0) or 0.0)
        cooldown = float(state.get("cooldown_seconds", cooldown_seconds) or cooldown_seconds)
    except Exception:
        last_ts, cooldown = 0.0, float(cooldown_seconds)
    if last_ts > 0 and cooldown > 0 and (current - last_ts) < cooldown:
        return False, "cooldown"
    day = time.strftime("%Y-%m-%d", time.localtime(current))
    try:
        sent_count = int(state.get("sent_count", 0) or 0)
    except Exception:
        sent_count = 0
    if str(state.get("sent_day") or "") == day and sent_count >= int(daily_cap):
        return False, "daily_cap"
    return True, "fired"


def apply_fire(acc, theta=0.55, now=None, text_len=0):
    """Post-send accumulator update: V=0, counter reset, sent bookkeeping."""
    import time
    acc = dict(acc or {})
    acc.update({"V": 0.0, "ticks_since_fire": 0, "last_sent_ts": float(now or time.time()),
                "last_sent_chars": int(text_len or 0)})
    return acc


# ------------------------------------------------------------------ v6 silence
SILENCE_PHASES = (("expect", 0.0, 2.0, 1.00, 0.0),
                  ("protest", 2.0, 6.0, 1.20, None),
                  ("loss", 6.0, 24.0, 0.80, None),
                  ("withdraw", 24.0, None, 0.35, None))


def silence_hours(last_proactive_ts, last_user_msg_ts, now):
    """Hours since she reached out without a reply; 0 if user replied after."""
    try:
        proactive = float(last_proactive_ts or 0.0)
        user = float(last_user_msg_ts or 0.0)
        current = float(now)
    except Exception:
        return 0.0
    if proactive <= 0 or user >= proactive:
        return 0.0
    return max(0.0, (current - proactive) / 3600.0)


def silence_phase(hours, clingy=True):
    """Return {phase, drive_mult, phase_weight} for the 4-phase model."""
    try:
        h = max(0.0, float(hours))
    except Exception:
        h = 0.0
    if h < 2.0:
        return {"phase": "expect", "drive_mult": 1.00, "phase_weight": 0.0}
    if h < 6.0:
        return {"phase": "protest", "drive_mult": 1.20, "phase_weight": 0.8 * (h - 2.0) / 4.0}
    if h < 24.0:
        return {"phase": "loss", "drive_mult": 0.80, "phase_weight": 0.8 + 0.7 * (h - 6.0) / 18.0}
    return {"phase": "withdraw", "drive_mult": 0.90 if clingy else 0.35, "phase_weight": 2.5 + 1.0}


def silence_nudges(dt_hours, phase, phase_weight=None):
    """Per-tick emotional nudges (dt capped at 6h)."""
    try:
        dt = max(0.0, min(6.0, float(dt_hours)))
    except Exception:
        dt = 0.0
    info = silence_phase(0.0) if not isinstance(phase, str) else None
    if info is None:
        current = {"expect": 0.0, "protest": 0.0, "loss": 0.0, "withdraw": 0.0}.get(phase, 0.0)
        weight = current if phase_weight is None else float(phase_weight)
    else:
        weight = info["phase_weight"]
    lonely_mult = 1.2 if phase == "protest" else 1.0
    # v7: silence only touches lonely + valence (stress/arousal belong to rate limiting)
    return {"valence": -0.60 * dt / 24.0 * weight,
            "arousal": 0.0,
            "stress": 0.0,
            "lonely": 0.50 * dt / 24.0 * weight * lonely_mult,
            "dt_hours": dt}


def clingy_burst(rng=None, p=0.20):
    import random
    r = rng or random
    return bool(r.random() < float(p))


def withdraw_retry_allowed(last_proactive_ts, now, min_hours=6.0, clingy=False):
    try:
        last = float(last_proactive_ts or 0.0)
        current = float(now)
    except Exception:
        return True
    if clingy:
        return True
    if last <= 0:
        return True
    return (current - last) / 3600.0 >= float(min_hours)


def silence_view(last_proactive_ts, last_user_msg_ts, now, clingy=True, rng=None):
    hours = silence_hours(last_proactive_ts, last_user_msg_ts, now)
    info = silence_phase(hours, clingy)
    burst = False
    if info['phase'] == 'withdraw' and clingy:
        burst = clingy_burst(rng)
    mult = info['drive_mult'] * (1.5 if burst else 1.0)
    return {'hours': round(hours, 3), 'phase': info['phase'],
            'drive_mult': round(info['drive_mult'], 4), 'burst': burst,
            'effective_mult': round(mult, 4), 'clingy': bool(clingy),
            'phase_weight': round(info['phase_weight'], 4)}


# ------------------------------------------------------- hourly rate limiting
HOURLY_CAP_DEFAULT = 3


def hourly_window(acc, now):
    """Roll the hourly window forward; returns a mutable copy."""
    import time
    acc = dict(acc or {})
    try:
        current = float(now)
    except Exception:
        current = time.time()
    try:
        start = float(acc.get("hour_window_start", 0.0) or 0.0)
    except Exception:
        start = 0.0
    if start <= 0:
        acc["hour_window_start"] = current
    elif (current - start) >= 3600.0:
        acc.update({"hour_window_start": current, "hour_sent_count": 0,
                    "hour_blocked_count": 0, "frustration": 0, "drive_mult": 1.0})
    return acc


def hourly_allowed(acc, now, cap=HOURLY_CAP_DEFAULT):
    acc2 = hourly_window(acc, now)
    try:
        cap = max(1, min(12, int(cap)))
    except Exception:
        cap = HOURLY_CAP_DEFAULT
    sent = int(acc2.get("hour_sent_count", 0) or 0)
    return sent < cap, acc2, cap


def block_feedback(acc, now, reason="hourly_cap"):
    """Frustration -> invigorated responding (Amsel 1958; Brehm 1966), capped."""
    import time
    acc = dict(acc or {})
    acc["blocked_count"] = int(acc.get("blocked_count", 0) or 0) + 1
    acc["hour_blocked_count"] = int(acc.get("hour_blocked_count", 0) or 0) + 1
    acc["last_block_reason"] = str(reason or "hourly_cap")
    acc["last_block_ts"] = float(now or time.time())
    frustration = min(10, int(acc.get("frustration", 0) or 0) + 1)
    acc["frustration"] = frustration
    acc["drive_mult"] = round(min(1.30, 1.0 + 0.04 * frustration), 4)
    return {"acc": acc, "stress": 0.03, "arousal": 0.02, "valence": 0.0,
            "drive_mult": acc["drive_mult"], "total_blocked": acc["blocked_count"]}


def clear_frustration(acc):
    acc = dict(acc or {})
    acc["frustration"] = 0
    acc["drive_mult"] = 1.0
    return acc


def limit_view(acc, hourly_cap=HOURLY_CAP_DEFAULT, now=None, daily_cap=5):
    import time
    current = float(now if now is not None else time.time())
    start = float((acc or {}).get("hour_window_start", 0.0) or 0.0)
    reset_in = max(0.0, 3600.0 - (current - start)) if start > 0 else 0.0
    return {"hourly_cap": int(hourly_cap or HOURLY_CAP_DEFAULT),
            "daily_cap": int(daily_cap or 5),
            "hour_sent": int((acc or {}).get("hour_sent_count", 0) or 0),
            "hour_blocked": int((acc or {}).get("hour_blocked_count", 0) or 0),
            "total_blocked": int((acc or {}).get("blocked_count", 0) or 0),
            "window_reset_in": round(reset_in, 1),
            "frustration": int((acc or {}).get("frustration", 0) or 0),
            "drive_mult": round(float((acc or {}).get("drive_mult", 1.0) or 1.0), 3)}


# ------------------------------------------------- v7 attachment / single line
ATTACHMENT_STYLES = ("secure", "anxious", "avoidant")
ATTACHMENT_MODS = {
    "secure": {"protest": 1.0, "withdraw": 1.0},
    "anxious": {"protest": 1.4, "withdraw": 0.9},
    "avoidant": {"protest": 0.8, "withdraw": 0.2},
}
MULT_CAP = 1.6
MULT_FLOOR = 0.35


def silence_mult(hours, clingy=True, attachment_style="secure"):
    info = silence_phase(hours, clingy)
    mult = float(info["drive_mult"])
    style = attachment_style if attachment_style in ATTACHMENT_STYLES else "secure"
    mods = ATTACHMENT_MODS[style]
    if info["phase"] == "protest":
        mult *= mods["protest"]
    elif info["phase"] == "withdraw":
        mult *= mods["withdraw"]
    return round(mult, 4)


def frust_mult(frustration):
    try:
        count = max(0, min(10, int(frustration or 0)))
    except Exception:
        count = 0
    return round(min(1.30, 1.0 + 0.04 * count), 4)


def guilt_value(conflict_unresolved=0.0, guilt_emotion=0.0):
    return clamp(0.7 * clamp(conflict_unresolved) + 0.3 * clamp(guilt_emotion))


def gratitude_value(gratitude_emotion=0.0, recent_positive=0.0):
    return clamp(0.6 * clamp(gratitude_emotion) + 0.4 * clamp(recent_positive))


def emotion_effects(parts):
    """v7 division of labour: each channel only touches its own affect."""
    p = parts if isinstance(parts, dict) else {}
    return {"valence": -0.02 * clamp(p.get("guilt")) + 0.02 * clamp(p.get("gratitude")),
            "repair_urge": 0.02 * clamp(p.get("guilt"))}

# ---------------------------------------------------------------- v8 self-blame
BLAME_CAP = 0.7
ATTACH_COEF = {'anxious': 1.3, 'secure': 1.0, 'avoidant': 0.5}


def self_blame_value(silence_hours, rejection_sensitivity=0.4, attachment_style='secure'):
    style = attachment_style if attachment_style in ATTACHMENT_STYLES else 'secure'
    try:
        hours = max(0.0, float(silence_hours))
        rs = clamp(rejection_sensitivity, 0.0, 1.0)
    except Exception:
        hours, rs = 0.0, 0.4
    return round(clamp((hours / 24.0) * rs * ATTACH_COEF[style], 0.0, BLAME_CAP), 4)


def self_blame_decay(self_blame, hours_since_reply):
    try:
        hours = max(0.0, float(hours_since_reply))
        sb = clamp(self_blame, 0.0, 1.0)
    except Exception:
        return 0.0
    if hours >= 4.0:
        return 0.0
    return round(sb * (1.0 - hours / 4.0), 4)


def blame_mult(style='secure', self_blame=0.0):
    sb = clamp(self_blame, 0.0, 1.0)
    if style == 'anxious':
        return round(1.0 + 0.15 * sb, 4)
    if style == 'avoidant':
        return round(1.0 - 0.30 * sb, 4)
    return 1.0


def blame_effects(self_blame):
    sb = clamp(self_blame, 0.0, 1.0)
    return {'valence': -0.10 * sb, 'confidence': round(1.0 - 0.5 * sb, 4)}


def compose_mult(silence_value, frustration, blame_value=1.0):
    total = (clamp(float(silence_value or 1.0), 0.0, 2.0)
             * clamp(frust_mult(frustration), 0.0, 1.3)
             * clamp(float(blame_value or 1.0), 0.0, 2.0))
    return round(clamp(total, 0.20, 1.8), 4)


def motive_view(hours, frustration=0, clingy=True, attachment_style='secure',
                self_blame=0.0, rejection_sensitivity=0.4):
    sil = silence_mult(hours, clingy, attachment_style)
    mul = frust_mult(frustration)
    bmul = blame_mult(attachment_style, self_blame)
    total = compose_mult(sil, frustration, bmul)
    return {'silence_mult': sil, 'frust_mult': mul, 'blame_mult': bmul,
            'total_mult': total, 'hours': round(float(hours or 0.0), 3),
            'attachment_style': attachment_style,
            'self_blame': round(clamp(self_blame), 4),
            'confidence': blame_effects(self_blame)['confidence']}


# --------------------------------------------- single daily cap -> hourly cap
DAILY_CAP_DEFAULT = 5
DAILY_CAP_MIN = 1
DAILY_CAP_MAX = 20
HOURLY_CAP_MIN = 1
HOURLY_CAP_MAX = 12


def daily_cap_value(value=DAILY_CAP_DEFAULT):
    try:
        return max(DAILY_CAP_MIN, min(DAILY_CAP_MAX, int(value)))
    except Exception:
        return DAILY_CAP_DEFAULT


def derive_hourly_cap(daily_cap=DAILY_CAP_DEFAULT):
    """hourly = clamp(ceil(daily/3), 1, 12): 3->1, 5->2, 9->3, 20->7."""
    import math
    daily = daily_cap_value(daily_cap)
    return max(HOURLY_CAP_MIN, min(HOURLY_CAP_MAX, math.ceil(daily / 3.0)))


def effective_caps(daily_cap=DAILY_CAP_DEFAULT, legacy_hourly=None):
    daily = daily_cap_value(daily_cap)
    if legacy_hourly is not None:
        try:
            hourly = max(HOURLY_CAP_MIN, min(HOURLY_CAP_MAX, int(legacy_hourly)))
        except Exception:
            hourly = derive_hourly_cap(daily)
    else:
        hourly = derive_hourly_cap(daily)
    return {"daily_cap": daily, "hourly_cap": hourly}
