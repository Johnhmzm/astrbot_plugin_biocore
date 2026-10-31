# -*- coding: utf-8 -*-
"""Core mode switch (off/shadow/primary) + one-click rollback.

Reuses the plugin's existing page auth (_page_is_local_admin) and config save path
(_persist_plugin_config); never writes arbitrary flags.
"""
from __future__ import annotations

import time

MODES = ("off", "shadow", "primary")
try:  # AstrBot requires the host logger
    from astrbot.api import logger as LOGGER
except Exception:  # pragma: no cover - offline tests
    class _NullLogger:  # offline fallback: never imports stdlib logging
        def _noop(self, *args, **kwargs):
            return None
        debug = info = warning = error = exception = critical = _noop
    LOGGER = _NullLogger()


class CoreModeError(Exception):
    """HTTP-mapped error: 400 invalid mode, 403 unauthenticated, 500 save failure."""

    def __init__(self, message, status=400):
        self.status = int(status)
        super().__init__(str(message))


def validate_mode(mode) -> str:
    value = str(mode or "").strip().lower()
    if value not in MODES:
        raise CoreModeError("invalid mode: must be off|shadow|primary", 400)
    return value


def authorize(plugin, body) -> None:
    """Auth is enforced by AstrBot's /api layer (JWT). The plugin-level admin token is
    optional hardening only: local requests pass, and remote requests pass when no
    data_admin_token is configured (the historical 403 source)."""
    token = str(getattr(plugin, "data_admin_token", "") or "").strip()
    checker = getattr(plugin, "_page_is_local_admin", None)
    allowed = bool(checker(body)) if callable(checker) else False
    if allowed:
        return
    if not token:
        return  # default: rely on host JWT auth (fixes remote panel 403)
    raise CoreModeError("forbidden", 403)


def updates_for(mode) -> dict:
    value = validate_mode(mode)
    return {"core_client_enabled": value != "off", "core_client_mode": value}


async def apply(plugin, mode, via: str = "page") -> dict:
    """Persist the mode, rebuild the bridge, log from->to, return the payload."""
    value = validate_mode(mode)
    previous = str((getattr(plugin, "config", None) or {}).get("core_client_mode") or "off").lower()
    updates = updates_for(value)
    try:
        await plugin._persist_plugin_config(updates)
    except Exception as error:
        raise CoreModeError("save failed: " + type(error).__name__, 500)
    rebuilt = True
    try:
        rebuilt = bool(plugin._rebuild_core_bridge())
    except Exception:
        rebuilt = False
    try:
        LOGGER.info("[biocore] core_mode_changed from=%s to=%s via=%s ts=%s",
                    previous, value, str(via or "page"), int(time.time()))
    except Exception:
        pass
    return {"ok": True, "mode": value, "pending_restart": not rebuilt}


def http_abort(status: int) -> None:
    """Raise an HTTP error the host understands (Starlette -> real 400/403/500).

    quart.abort raises a werkzeug exception that the dashboard adapter turns into a
    generic 500, so prefer the host asgi runtime's abort when available.
    """
    code = int(status)
    try:
        from astrbot.dashboard.asgi_runtime import abort as host_abort
        host_abort(code)
        return
    except ImportError:
        pass
    except Exception:
        raise
    try:
        from quart import abort as quart_abort
        quart_abort(code)
        return
    except ImportError:
        pass
    raise CoreModeError("http " + str(code), code)


async def rollback(plugin, via: str = "page") -> dict:
    """One-click rollback to the old engine: identical to mode=off."""
    return await apply(plugin, "off", via=via)
