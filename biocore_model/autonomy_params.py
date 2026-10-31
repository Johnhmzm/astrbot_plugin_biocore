# -*- coding: utf-8 -*-
"""Persona-derived autonomy rhythm parameters (no hard-coded theta/cooldown).

Big Five + relationship state + responsiveness/ignore-rate are translated into
the trigger rhythm: threshold, silence time constants and cooldown. Defaults are
literature-guided starting coefficients; ui_settings.autonomy.params can
override any value at runtime.

Literature
  Carver & Scheier 1998 (control loop gains), Powers 1973 (perceptual control),
  Gross 1998 (regulation timing), Bowlby 1969 / Mikulincer & Shaver 2007
  (attachment activation/deactivation), Gross & John 2003 (avoidance), Fraley
  2019 (responsiveness), Porges 2011 (social engagement), Vygotsky-style timing
  is intentionally simple: coefficients are rounded, calibrated by tests.
"""
from __future__ import annotations

PARAM_KEYS = ("theta", "tau_hours", "cooldown_s", "social_tau_hours",
              "silence_tau_hours", "daily_cap")
TRAITS = {"O": "openness", "C": "conscientiousness", "E": "extraversion",
          "A": "agreeableness", "N": "neuroticism"}
# Attachment style -> (activation a_act, avoidance 0/0.5/1, cooldown factor).
ATTACHMENT = {
    "secure": {"a_act": 0.35, "avoid": 0.0, "cooldown": 1.00},
    "anxious": {"a_act": 0.85, "avoid": 0.5, "cooldown": 1.20},
    "avoidant": {"a_act": 0.15, "avoid": 1.0, "cooldown": 1.60},
}


def _clamp(value, low, high):
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _trait(profile, short, default=0.5):
    """Flat O/C/E/A/N wins, then nested traits/big5 (both naming variants)."""
    if not isinstance(profile, dict):
        return float(default)
    long_name = TRAITS.get(short, short).lower()
    for key in (short, short.lower(), long_name):
        if key in profile:
            try:
                return _clamp(profile[key], 0.0, 1.0)
            except Exception:
                return float(default)
    for container in ("traits", "big5"):
        block = profile.get(container)
        if not isinstance(block, dict):
            continue
        for key in (short, short.lower(), long_name, long_name.capitalize()):
            if key in block:
                try:
                    return _clamp(block[key], 0.0, 1.0)
                except Exception:
                    return float(default)
    return float(default)


def _relationship(relationship):
    rel = relationship if isinstance(relationship, dict) else {}
    state = rel.get("state") if isinstance(rel.get("state"), dict) else {}
    closeness = _clamp(state.get("closeness", 0.5), 0.0, 1.0)
    attachment = rel.get("attachment") if isinstance(rel.get("attachment"), dict) else {}
    style = str(rel.get("attachment_style") or rel.get("style")
                or attachment.get("style") or "secure").strip().lower()
    if style not in ATTACHMENT:
        style = "secure"
    return closeness, style


def from_profile(profile, relationship, responsiveness=0.5, ignore_rate=0.0):
    """Return persona-derived {theta, tau_hours, cooldown_s, *_tau_hours, daily_cap}."""
    e = _trait(profile, "E", 0.5)
    n = _trait(profile, "N", 0.5)
    closeness, style = _relationship(relationship)
    info = ATTACHMENT[style]
    a_act = _clamp(0.60 * info["a_act"] + 0.40 * n, 0.0, 1.0)
    avoid = float(info["avoid"])
    r = _clamp(responsiveness, 0.0, 1.0)
    f = _clamp(ignore_rate, 0.0, 1.0)
    e_n = (e - 0.5) / 0.5
    # 0.55 -> 0.61 calibration: the old baseline fired ~45 min for the real
    # high-E persona; +0.06 lands the cadence in the 60-120 min target.
    theta = _clamp(0.61 - 0.10 * e_n - 0.08 * (closeness - 0.5) / 0.5
                   - 0.06 * a_act + 0.10 * avoid + 0.05 * (1.0 - r),
                   0.35, 0.75)
    tau = _clamp(24.0 * (1.0 - 0.35 * closeness)
                 * (1.0 - 0.15 * e_n - 0.15 * a_act)
                 * (1.0 + 0.20 * avoid), 6.0, 36.0)
    cooldown_min = (30.0 * info["cooldown"] * (1.0 + 0.40 * f)
                    * (1.0 - 0.25 * e_n) * (1.0 + 0.30 * (1.0 - r)))
    cooldown_s = 60.0 * _clamp(cooldown_min, 20.0, 180.0)
    social_tau = _clamp(tau, 6.0, 36.0)
    # tau/8 gives the real profile ~2h silence constant -> ~60 min trigger;
    # tau/20 fired around 30 min, faster than the target cadence.
    silence_tau = _clamp(tau / 8.0, 0.5, 3.0)
    daily_cap = int(_clamp(round(4.0 - 2.0 * (closeness - 0.5) - 1.5 * e_n
                                + 1.0 * avoid + 1.0 * (1.0 - r)), 1, 8))
    return {"theta": round(theta, 4),
            "tau_hours": round(tau, 2),
            "cooldown_s": int(round(cooldown_s)),
            "social_tau_hours": round(social_tau, 2),
            "silence_tau_hours": round(silence_tau, 3),
            "daily_cap": daily_cap}


def apply_overrides(params, overrides=None):
    """Merge ui_settings.autonomy.params overrides (debug only), clamped."""
    out = dict(params or {})
    if not isinstance(overrides, dict):
        return out
    limits = {"theta": (0.2, 0.9), "tau_hours": (3.0, 48.0),
              "cooldown_s": (300, 10800), "social_tau_hours": (3.0, 48.0),
              "silence_tau_hours": (0.3, 6.0), "daily_cap": (1, 12)}
    for key in PARAM_KEYS:
        if key not in overrides:
            continue
        try:
            value = float(overrides[key])
        except Exception:
            continue
        low, high = limits[key]
        if key == "daily_cap":
            out[key] = int(_clamp(round(value), low, high))
        elif key == "cooldown_s":
            out[key] = int(round(_clamp(value, low, high)))
        else:
            out[key] = round(_clamp(value, low, high), 4)
    return out
