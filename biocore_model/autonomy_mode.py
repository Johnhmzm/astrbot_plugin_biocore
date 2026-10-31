# -*- coding: utf-8 -*-
"""Autonomy settings (page/autonomy): validate + persist plugin config."""
from __future__ import annotations


class AutonomyError(Exception):
    def __init__(self, message, status=400):
        self.status = int(status)
        super().__init__(str(message))


def normalize(body) -> dict:
    data = body if isinstance(body, dict) else {}
    enabled = data.get("enabled", None)
    send = data.get("send", None)
    clingy = data.get("clingy", None)
    attachment_style = data.get("attachment_style", None)
    rejection_sensitivity = data.get("rejection_sensitivity", None)
    daily_cap = data.get("daily_cap", None)
    tick_engine = data.get("tick_engine", None)
    if tick_engine is not None and tick_engine not in ("legacy", "module"):
        raise AutonomyError("tick_engine invalid", 400)
    if daily_cap is not None:
        try:
            daily_cap = int(daily_cap)
        except Exception:
            raise AutonomyError("daily_cap invalid", 400)
        if not 1 <= daily_cap <= 20:
            raise AutonomyError("daily_cap out of range", 400)
    if rejection_sensitivity is not None:
        try:
            rejection_sensitivity = float(rejection_sensitivity)
        except Exception:
            raise AutonomyError("rejection_sensitivity invalid", 400)
        if not 0.0 <= rejection_sensitivity <= 1.0:
            raise AutonomyError("rejection_sensitivity out of range", 400)
    if attachment_style is not None and attachment_style not in ("secure", "anxious", "avoidant"):
        raise AutonomyError("attachment_style invalid", 400)
    if clingy is not None and not isinstance(clingy, bool):
        raise AutonomyError("clingy must be boolean", 400)
    if enabled is not None and not isinstance(enabled, bool):
        raise AutonomyError("enabled must be boolean", 400)
    if send is not None and not isinstance(send, bool):
        raise AutonomyError("send must be boolean", 400)
    threshold = data.get("threshold", None)
    if threshold is not None:
        try:
            threshold = float(threshold)
        except Exception:
            raise AutonomyError("threshold must be number", 400)
        if not (0.0 <= threshold <= 1.0):
            raise AutonomyError("threshold out of range", 400)
    max_chars = data.get("max_chars", None)
    if max_chars is not None:
        try:
            max_chars = int(max_chars)
        except Exception:
            raise AutonomyError("max_chars must be int", 400)
        if not (20 <= max_chars <= 4000):
            raise AutonomyError("max_chars out of range", 400)
    return {"enabled": enabled, "send": send, "threshold": threshold, "max_chars": max_chars, "clingy": clingy, "attachment_style": attachment_style, "rejection_sensitivity": rejection_sensitivity, "daily_cap": daily_cap, "tick_engine": tick_engine}


async def apply(plugin, body) -> dict:
    values = normalize(body)
    updates = {}
    if values["enabled"] is not None:
        updates["proactive_autonomy"] = bool(values["enabled"])
        try: plugin.proactive_autonomy = bool(values["enabled"])
        except Exception: pass
    if values["tick_engine"] is not None:
        updates["autonomy_tick_engine"] = str(values["tick_engine"])
        try: plugin.autonomy_tick_engine = str(values["tick_engine"])
        except Exception: pass
    if values["daily_cap"] is not None:
        updates["autonomy_daily_cap"] = int(values["daily_cap"])
        try:
            plugin.autonomy_daily_cap = int(values["daily_cap"])
            import math as _math
            plugin.autonomy_hourly_cap = max(1, min(12, _math.ceil(plugin.autonomy_daily_cap / 3.0)))
        except Exception:
            pass
    if values["rejection_sensitivity"] is not None:
        updates["rejection_sensitivity"] = float(values["rejection_sensitivity"])
        try: plugin.rejection_sensitivity = float(values["rejection_sensitivity"])
        except Exception: pass
    if values["attachment_style"] is not None:
        updates["attachment_style"] = str(values["attachment_style"])
        try: plugin.attachment_style = str(values["attachment_style"])
        except Exception: pass
    if values["clingy"] is not None:
        updates["autonomy_clingy"] = bool(values["clingy"])
        try: plugin.autonomy_clingy = bool(values["clingy"])
        except Exception: pass
    if values["send"] is not None:
        updates["proactive_send"] = bool(values["send"])
        try: plugin.proactive_send = bool(values["send"])
        except Exception: pass
    if values["threshold"] is not None:
        updates["proactive_autonomy_threshold"] = float(values["threshold"])
    if values["max_chars"] is not None:
        updates["proactive_autonomy_max_chars"] = int(values["max_chars"])
    if updates:
        try:
            await plugin._persist_plugin_config(updates)
        except Exception as error:
            raise AutonomyError("save failed: " + type(error).__name__, 500)
    cfg = getattr(plugin, "config", None) or {}
    return {"ok": True, "values": {
        "enabled": bool(getattr(plugin, "proactive_autonomy", cfg.get("proactive_autonomy", False))),
        "send": bool(getattr(plugin, "proactive_send", cfg.get("proactive_send", False))),
        "threshold": float(cfg.get("proactive_autonomy_threshold", 0.6) or 0.6),
        "max_chars": int(cfg.get("proactive_autonomy_max_chars", 120) or 120),
    }}
