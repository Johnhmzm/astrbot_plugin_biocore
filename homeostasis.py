# -*- coding: utf-8 -*-
"""Minimal homeostasis / action-control layer for BioCore.

Deterministic, bounded, no LLM and no prompt writing. It only produces
biological state proxies (drives/set-points/L_int/need pyramid/virtual body/
readiness/interoception); the interpretation layer may render at most a few
short status tokens from it.

This is an engineering control loop, not a physiological or clinical model.
"""
from __future__ import annotations

import math
import time
from typing import Any

DRIVE_KEYS = ("energy", "social", "safety", "curiosity")
BODY_KEYS = ("energy", "hydration", "warmth", "fatigue")
NEED_LAYERS = ("physiological", "safety", "belonging", "esteem", "self_actualization")
NEED_WEIGHTS = (1.0, 0.85, 0.65, 0.5, 0.35)
NEED_GAMMA = 0.75
SETPOINT_WARMUP_TICKS = 12
SETPOINT_ETA = 2e-6
MAX_DRIVES = len(DRIVE_KEYS)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return low
        return max(low, min(high, number))
    except Exception:
        return low


def default_state() -> dict[str, Any]:
    return {
        "drives": {key: 0.55 for key in DRIVE_KEYS},
        "set_points": {key: 0.55 for key in DRIVE_KEYS},
        "setpoint_ticks": 0,
        "tick": 0,
        "L_int": 0.0,
        "body": {"energy": 0.70, "hydration": 0.70, "warmth": 0.60, "fatigue": 0.20},
        "need_pyramid": {"deficits": {key: 0.0 for key in NEED_LAYERS},
                         "score": 0.0, "dominant": "physiological"},
        "readiness": 0.60,
        "interoception": {"signal": 0.55, "label": "steady", "expression_hint": "normal"},
        "action": {"mode": "engage", "reason": "baseline", "strength": 0.5},
        "last_metabolic_cost": 0.0,
        "updated_ts": 0.0,
    }


def _ensure_state(state: Any) -> dict[str, Any]:
    base = default_state()
    if not isinstance(state, dict):
        return base
    for key, value in base.items():
        if key not in state:
            state[key] = value
    for group in ("drives", "set_points", "body", "interoception"):
        if not isinstance(state.get(group), dict):
            state[group] = dict(base[group])
    if not isinstance(state.get("need_pyramid"), dict):
        state["need_pyramid"] = dict(base["need_pyramid"])
    return state


def _core(core: Any, name: str, default: float = 0.5) -> float:
    try:
        return _clamp(getattr(core, name, default), 0.0, 1.0)
    except Exception:
        return default


def _drives(core: Any, body: dict, relationship: Any = None) -> dict[str, float]:
    energy = _clamp(0.65 * _core(core, "energy", 0.55) + 0.35 * float(body.get("energy", 0.7)))
    social = _core(core, "social", 0.55)
    safety = _clamp(1.0 - _core(core, "stress", 0.1))
    curiosity = _clamp(0.60 * (1.0 - _core(core, "boredom", 0.0)) +
                       0.40 * _core(core, "novelty_need", 0.5) +
                       0.10 * _core(core, "info_gap", 0.0))
    if isinstance(relationship, dict):
        state = relationship.get("state") if isinstance(relationship.get("state"), dict) else {}
        try:
            safety = _clamp(safety - 0.25 * _clamp(state.get("conflict", 0.0)))
            social = _clamp(social + 0.10 * _clamp(state.get("closeness", 0.5)))
        except Exception:
            pass
    return {"energy": round(energy, 4), "social": round(social, 4),
            "safety": round(safety, 4), "curiosity": round(curiosity, 4)}


def _update_set_points(state: dict, dt: float = 60.0) -> None:
    drive = state.get("drives") or {}
    points = state.get("set_points") or {}
    try:
        ticks = int(state.get("setpoint_ticks", 0) or 0) + 1
    except Exception:
        ticks = 1
    for key in DRIVE_KEYS:
        current = _clamp(points.get(key, 0.55))
        value = _clamp(drive.get(key, 0.55))
        if ticks <= SETPOINT_WARMUP_TICKS:
            points[key] = round(current + (value - current) / max(1, ticks), 6)
        else:
            try:
                step = SETPOINT_ETA * max(0.0, float(dt))
            except Exception:
                step = SETPOINT_ETA * 60.0
            points[key] = round(_clamp(current + step * (value - current)), 6)
    state["set_points"] = points
    state["setpoint_ticks"] = ticks


def _need_pyramid(core: Any, drives: dict, relationship: Any = None) -> dict:
    deficits = {
        "physiological": _clamp(1.0 - float(drives.get("energy", 0.5))),
        "safety": _clamp(1.0 - float(drives.get("safety", 0.5))),
        "belonging": _clamp(1.0 - float(drives.get("social", 0.5))),
        "esteem": 0.5,
        "self_actualization": _clamp(1.0 - float(drives.get("curiosity", 0.5))),
    }
    try:
        esteem = 1.0 - 0.5 * (_core(core, "trust", 0.5) + _clamp(
            (relationship or {}).get("state", {}).get("closeness", 0.5)
            if isinstance(relationship, dict) else 0.5))
        deficits["esteem"] = round(_clamp(esteem), 4)
    except Exception:
        pass
    total_w = 0.0
    score = 0.0
    dominant = "physiological"
    best = -1.0
    for index, layer in enumerate(NEED_LAYERS):
        weight = NEED_WEIGHTS[index] * (NEED_GAMMA ** index)
        deficit = float(deficits.get(layer, 0.0))
        score += weight * deficit
        total_w += weight
        if weight * deficit > best:
            best = weight * deficit
            dominant = layer
    score = _clamp(score / total_w) if total_w > 0 else 0.0
    return {"deficits": {key: round(float(value), 4) for key, value in deficits.items()},
            "score": round(score, 4), "dominant": dominant}


def _readiness(drives: dict, L_int: float, fatigue: float) -> float:
    return round(_clamp(
        0.36 * float(drives.get("energy", 0.5)) +
        0.20 * float(drives.get("social", 0.5)) +
        0.24 * float(drives.get("safety", 0.5)) +
        0.10 * float(drives.get("curiosity", 0.5)) -
        0.30 * _clamp(L_int) -
        0.10 * _clamp(fatigue)), 4)


def _interoception(core: Any, body: dict) -> dict:
    signal = _clamp(0.50 * float(body.get("energy", 0.7)) +
                    0.25 * (1.0 - _core(core, "stress", 0.1)) +
                    0.15 * (1.0 - float(body.get("fatigue", 0.2))) +
                    0.10 * float(body.get("warmth", 0.6)))
    if signal <= 0.35:
        label, hint = "low", "rest"
    elif signal >= 0.72:
        label, hint = "high", "active"
    else:
        label, hint = "steady", "normal"
    return {"signal": round(signal, 4), "label": label, "expression_hint": hint}


ACTION_MODES = ("engage", "rest", "seek_social", "explore", "withdraw", "comfort")


def action_tendency(state: Any, core: Any = None) -> dict[str, Any]:
    """Deterministic drive->action tendency (state token only; no send gate)."""
    s = _ensure_state(state if isinstance(state, dict) else None)
    drives = s.get("drives") or {}
    need = s.get("need_pyramid") if isinstance(s.get("need_pyramid"), dict) else {}
    dominant = str(need.get("dominant") or "physiological")
    readiness = _clamp(s.get("readiness", 0.6))
    L_int = _clamp(s.get("L_int", 0.0))
    energy = _clamp(drives.get("energy", 0.5))
    social = _clamp(drives.get("social", 0.5))
    safety = _clamp(drives.get("safety", 0.5))
    curiosity = _clamp(drives.get("curiosity", 0.5))
    fatigue = _clamp((s.get("body") or {}).get("fatigue", 0.2))
    stress = _core(core, "stress", 0.1) if core is not None else 0.0
    if energy <= 0.35 or fatigue >= 0.72:
        mode, why = "rest", "low_energy_fatigue"
    elif safety <= 0.32 or stress >= 0.75:
        mode, why = "withdraw", "safety_stress"
    elif dominant == "belonging" and social <= 0.45:
        mode, why = "seek_social", "belonging_deficit"
    elif dominant == "self_actualization" and curiosity <= 0.45:
        mode, why = "explore", "curiosity_deficit"
    elif dominant == "esteem" and dominance_low(s):
        mode, why = "comfort", "esteem_deficit"
    elif readiness >= 0.65 and L_int <= 0.25:
        mode, why = "engage", "ready"
    elif L_int >= 0.35:
        mode, why = "comfort", "internal_load"
    else:
        mode, why = "engage", "baseline"
    strength = round(_clamp(0.35 + 0.40 * readiness + 0.25 * L_int), 4)
    return {"mode": mode, "reason": why, "strength": strength}


def dominance_low(state: Any) -> bool:
    # Placeholder-free deterministic check; esteem deficit is represented by need layer.
    need = (state or {}).get("need_pyramid") if isinstance(state, dict) else {}
    deficits = need.get("deficits") if isinstance(need, dict) else {}
    try:
        return float(deficits.get("esteem", 0.0) or 0.0) >= 0.55
    except Exception:
        return False


def normalize_state(state: Any) -> dict[str, Any]:
    """Normalize a persisted homeostasis dict; malformed input falls back safely."""
    base = default_state()
    if not isinstance(state, dict):
        return base
    try:
        for group, keys in (("drives", DRIVE_KEYS), ("set_points", DRIVE_KEYS),
                            ("body", BODY_KEYS)):
            raw = state.get(group) if isinstance(state.get(group), dict) else {}
            for key in keys:
                base[group][key] = round(_clamp(raw.get(key, base[group][key])), 6)
        for key in ("tick", "setpoint_ticks"):
            try:
                base[key] = max(0, min(10 ** 9, int(float(state.get(key, 0) or 0))))
            except Exception:
                base[key] = 0
        base["L_int"] = round(_clamp(state.get("L_int", 0.0)), 6)
        base["readiness"] = round(_clamp(state.get("readiness", 0.6)), 6)
        pyramid = state.get("need_pyramid") if isinstance(state.get("need_pyramid"), dict) else {}
        raw_deficits = pyramid.get("deficits") if isinstance(pyramid.get("deficits"), dict) else {}
        deficits = {}
        for layer in NEED_LAYERS:
            deficits[layer] = round(_clamp(raw_deficits.get(layer, 0.0)), 6)
        base["need_pyramid"] = {
            "deficits": deficits,
            "score": round(_clamp(pyramid.get("score", 0.0)), 6),
            "dominant": str(pyramid.get("dominant") or ""),
        }
        if base["need_pyramid"]["dominant"] not in NEED_LAYERS:
            base["need_pyramid"]["dominant"] = max(deficits, key=lambda k: deficits[k])
        intero = state.get("interoception") if isinstance(state.get("interoception"), dict) else {}
        label = str(intero.get("label") or "steady")
        if label not in ("low", "steady", "high"):
            label = "steady"
        hint = str(intero.get("expression_hint") or "normal")[:24]
        base["interoception"] = {"signal": round(_clamp(intero.get("signal", 0.55)), 6),
                                 "label": label, "expression_hint": hint}
        action = state.get("action") if isinstance(state.get("action"), dict) else {}
        mode = str(action.get("mode") or "engage")
        if mode not in ACTION_MODES:
            mode = "engage"
        base["action"] = {"mode": mode,
                          "reason": str(action.get("reason") or "baseline")[:40],
                          "strength": round(_clamp(action.get("strength", 0.5)), 6)}
        base["last_metabolic_cost"] = round(_clamp(
            state.get("last_metabolic_cost", 0.0), 0.0, 0.10), 6)
        try:
            base["updated_ts"] = round(float(state.get("updated_ts", 0.0) or 0.0), 3)
        except Exception:
            base["updated_ts"] = 0.0
        return base
    except Exception:
        return default_state()


def step(core: Any, dt: float = 60.0, relationship: Any = None) -> dict[str, Any]:
    """One deterministic homeostasis update; attaches and returns the state."""
    state = _ensure_state(getattr(core, "homeostasis", None))
    body = state["body"]
    # Body follows core energy with small inertia; stress raises fatigue.
    body["energy"] = round(_clamp(0.90 * float(body.get("energy", 0.7)) +
                                  0.10 * _core(core, "energy", 0.55)), 4)
    body["fatigue"] = round(_clamp(0.95 * float(body.get("fatigue", 0.2)) +
                                   0.05 * _core(core, "stress", 0.1)), 4)
    # BUG-05: slow recovery balanced against metabolic loss; bounded.
    _stress = _core(core, "stress", 0.1) if core is not None else 0.0
    body["hydration"] = round(_clamp(
        float(body.get("hydration", 0.7)) - 0.001 + 0.0024 * (1.0 - _stress)), 4)
    body["warmth"] = round(_clamp(0.995 * float(body.get("warmth", 0.6)) +
                                  0.005 * (1.0 - _core(core, "stress", 0.1))), 4)
    drives = _drives(core, body, relationship)
    state["drives"] = drives
    _update_set_points(state, dt)
    points = state["set_points"]
    L_int = sum(abs(float(drives.get(key, 0.5)) - float(points.get(key, 0.5)))
                for key in DRIVE_KEYS) / MAX_DRIVES
    state["L_int"] = round(_clamp(L_int), 4)
    # Entry: internal load lightly raises stress (bounded; no runaway).
    try:
        core.stress = _clamp(float(getattr(core, "stress", 0.1)) + 0.01 * state["L_int"], 0.0, 1.0)
    except Exception:
        pass
    state["need_pyramid"] = _need_pyramid(core, drives, relationship)
    state["readiness"] = _readiness(drives, state["L_int"], float(body.get("fatigue", 0.2)))
    state["interoception"] = _interoception(core, body)
    state["action"] = action_tendency(state, core)
    state["tick"] = int(state.get("tick", 0) or 0) + 1
    state["updated_ts"] = round(time.time(), 3)
    try:
        core.homeostasis = state
    except Exception:
        pass
    return state


def metabolize_reply(core: Any, text: str = "") -> float:
    """Reply metabolic cost: body energy drops and next round sees lower energy."""
    state = _ensure_state(getattr(core, "homeostasis", None))
    try:
        length = len(str(text or ""))
    except Exception:
        length = 0
    cost = _clamp(0.015 + 0.0004 * min(120, length), 0.015, 0.06)
    body = state["body"]
    body["energy"] = round(_clamp(float(body.get("energy", 0.7)) - cost), 4)
    body["fatigue"] = round(_clamp(float(body.get("fatigue", 0.2)) + 0.60 * cost), 4)
    body["hydration"] = round(_clamp(float(body.get("hydration", 0.7)) - 0.40 * cost), 4)
    try:
        core.energy = _clamp(float(getattr(core, "energy", 0.55)) - 0.60 * cost, 0.0, 1.0)
        # Persist a decaying energy debt so the next _derive() does not erase it.
        core._metabolic_energy_offset = _clamp(
            float(getattr(core, "_metabolic_energy_offset", 0.0)) + 0.60 * cost, 0.0, 0.20)
    except Exception:
        pass
    state["last_metabolic_cost"] = round(cost, 4)
    state["updated_ts"] = round(time.time(), 3)
    try:
        core.homeostasis = state
    except Exception:
        pass
    return cost


def snapshot(core: Any) -> dict[str, Any]:
    state = getattr(core, "homeostasis", None)
    return dict(state) if isinstance(state, dict) else default_state()
