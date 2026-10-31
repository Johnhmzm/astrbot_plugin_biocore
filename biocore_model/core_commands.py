# -*- coding: utf-8 -*-
"""Chat commands for the core mode switch (thin: parse + permission + reply only).

Reuses biocore_model.core_mode for validate/apply/rollback; no duplicated logic.
"""
from __future__ import annotations

from . import core_mode

COMMAND = "biocore_core"
ROLLBACK_COMMAND = "biocore_rollback"
USAGE = "用法：/biocore_core off|shadow|primary"
ROLLBACK_USAGE = "用法：/biocore_rollback"
DENY = "仅管理员可用（或私聊 + 配置白名单）"


def parse_args(raw_text) -> dict:
    """Parse 'biocore_core shadow' / '/biocore_core shadow' -> {'mode': 'shadow'}."""
    text = str(raw_text or "").strip()
    tokens = text.split()
    if tokens and tokens[0].lstrip("/").strip().lower() == COMMAND:
        tokens = tokens[1:]
    if len(tokens) != 1:
        return {"usable": False, "usage": USAGE}
    value = tokens[0].strip().lower()
    try:
        return {"usable": True, "mode": core_mode.validate_mode(value)}
    except core_mode.CoreModeError:
        return {"usable": False, "usage": USAGE}


def _sender_id(event) -> str:
    for getter in ("get_sender_id",):
        fn = getattr(event, getter, None)
        if callable(fn):
            try:
                value = fn()
                if value:
                    return str(value)
            except Exception:
                continue
    for attr in ("sender_id", "get_sender_id"):
        value = getattr(event, attr, None)
        if value and not callable(value):
            return str(value)
    try:
        return str(getattr(getattr(event, "message_obj", None), "sender_id", "") or "")
    except Exception:
        return ""


def is_private(event) -> bool:
    for getter in ("is_private_chat", "is_private"):
        fn = getattr(event, getter, None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                continue
    return False


def is_admin(event, config) -> bool:
    """Use AstrBot's event.is_admin when available; otherwise private chat + whitelist."""
    checker = getattr(event, "is_admin", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            pass
    elif checker is not None:
        return bool(checker)
    cfg = config if isinstance(config, dict) else {}
    whitelist = cfg.get("command_admin_ids") or cfg.get("admin_ids") or []
    sender = _sender_id(event)
    if sender and str(sender) in {str(item) for item in whitelist if str(item).strip()}:
        return True
    return is_private(event)


def switch_reply(payload) -> str:
    mode = str(payload.get("mode") or "off")
    if payload.get("pending_restart"):
        return "核心模式已切换：off → %s（重启后生效）" % mode
    return "核心模式已切换：off → %s（立即生效）" % mode


async def run_core_command(plugin, raw_text, event, via="command") -> str:
    if not is_admin(event, getattr(plugin, "config", {})):
        return DENY + "，" + USAGE
    parsed = parse_args(raw_text)
    if not parsed.get("usable"):
        return parsed.get("usage") or USAGE
    try:
        payload = await core_mode.apply(plugin, parsed["mode"], via=via)
    except core_mode.CoreModeError as error:
        return "切换失败：" + str(error)
    except Exception as error:
        return "切换失败：" + type(error).__name__
    return switch_reply(payload)


async def run_rollback_command(plugin, event, via="command") -> str:
    if not is_admin(event, getattr(plugin, "config", {})):
        return DENY + "，" + ROLLBACK_USAGE
    try:
        await core_mode.rollback(plugin, via=via)
    except core_mode.CoreModeError as error:
        return "回退失败：" + str(error)
    except Exception as error:
        return "回退失败：" + type(error).__name__
    return "已回退旧版引擎（off）"
