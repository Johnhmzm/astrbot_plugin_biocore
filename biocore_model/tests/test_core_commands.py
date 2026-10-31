class _Recorder:
    """Logger stub so tests never import the stdlib logging module."""

    def __init__(self):
        self.lines = []
        self.level = 0

    def _log(self, msg, *args, **kwargs):
        try:
            self.lines.append(str(msg) % args if args else str(msg))
        except Exception:
            self.lines.append(str(msg))

    def setLevel(self, *_a, **_k):
        return None

    def addHandler(self, *_a, **_k):
        return None

    def removeHandler(self, *_a, **_k):
        return None

    debug = info = warning = error = exception = critical = _log


# -*- coding: utf-8 -*-
"""Chat commands /biocore_core and /biocore_rollback (admin only, thin over core_mode)."""
import unittest

from biocore_model import core_commands
from biocore_model import core_mode, core_mode


class FakeEvent:
    def __init__(self, admin=True, private=True, sender="u1", message=""):
        self.admin = admin
        self.private = private
        self.sender = sender
        self.message_str = message

    def is_admin(self):
        return bool(self.admin)

    def is_private_chat(self):
        return bool(self.private)

    def get_sender_id(self):
        return self.sender


class NoAdminEvent(FakeEvent):
    is_admin = None  # attribute absent path -> private chat + whitelist


class FakePlugin:
    def __init__(self, admin_ids=None):
        self.config = {"core_client_mode": "off", "core_client_enabled": False,
                       "command_admin_ids": list(admin_ids or [])}
        self.data_admin_token = ""
        self.saved = []

    async def _persist_plugin_config(self, updates):
        self.saved.append(dict(updates))
        self.config.update(updates)

    def _rebuild_core_bridge(self):
        return True


class ParseTest(unittest.TestCase):
    def test_three_modes(self):
        for mode in ("off", "shadow", "primary"):
            parsed = core_commands.parse_args("/biocore_core " + mode)
            self.assertTrue(parsed["usable"])
            self.assertEqual(parsed["mode"], mode)

    def test_invalid_usage(self):
        for raw in ("/biocore_core", "/biocore_core bogus", "/biocore_core shadow extra"):
            parsed = core_commands.parse_args(raw)
            self.assertFalse(parsed["usable"])
            self.assertIn("off|shadow|primary", parsed["usage"])


class PermissionTest(unittest.TestCase):
    def test_admin_event_allowed(self):
        self.assertTrue(core_commands.is_admin(FakeEvent(admin=True), {}))

    def test_plain_user_denied(self):
        event = NoAdminEvent(admin=False, private=False)
        self.assertFalse(core_commands.is_admin(event, {}))

    def test_whitelist_allows_group_user(self):
        event = NoAdminEvent(admin=False, private=False, sender="42")
        self.assertTrue(core_commands.is_admin(event, {"command_admin_ids": ["42"]}))

    def test_private_chat_fallback_allows(self):
        event = NoAdminEvent(admin=False, private=True)
        self.assertTrue(core_commands.is_admin(event, {}))


class RunTest(unittest.IsolatedAsyncioTestCase):
    async def test_switch_reply_and_config(self):
        plugin = FakePlugin()
        reply = await core_commands.run_core_command(plugin, "/biocore_core shadow", FakeEvent())
        self.assertEqual(reply, "核心模式已切换：off → shadow（立即生效）")
        self.assertEqual(plugin.config["core_client_mode"], "shadow")
        self.assertTrue(plugin.config["core_client_enabled"])
        self.assertEqual(plugin.saved[-1], {"core_client_enabled": True, "core_client_mode": "shadow"})

    async def test_invalid_argument_reply(self):
        plugin = FakePlugin()
        reply = await core_commands.run_core_command(plugin, "/biocore_core nope", FakeEvent())
        self.assertIn("off|shadow|primary", reply)
        self.assertEqual(plugin.saved, [])

    async def test_non_admin_rejected(self):
        plugin = FakePlugin()
        reply = await core_commands.run_core_command(plugin, "/biocore_core primary", NoAdminEvent(admin=False, private=False))
        self.assertIn("仅管理员可用", reply)
        self.assertEqual(plugin.saved, [])

    async def test_rollback_command(self):
        plugin = FakePlugin()
        plugin.config.update({"core_client_enabled": True, "core_client_mode": "primary"})
        reply = await core_commands.run_rollback_command(plugin, FakeEvent())
        self.assertEqual(reply, "已回退旧版引擎（off）")
        self.assertFalse(plugin.config["core_client_enabled"])
        self.assertEqual(plugin.config["core_client_mode"], "off")

    async def test_log_via_command(self):
        plugin = FakePlugin()
        rec = _Recorder()
        saved = core_mode.LOGGER
        core_mode.LOGGER = rec
        try:
            await core_commands.run_core_command(plugin, "/biocore_core shadow", FakeEvent())
        finally:
            core_mode.LOGGER = saved
        joined = "\n".join(rec.lines)
        self.assertIn("core_mode_changed from=off to=shadow via=command", joined)

    async def test_pending_restart_reply(self):
        plugin = FakePlugin()
        plugin._rebuild_core_bridge = lambda: False
        reply = await core_commands.run_core_command(plugin, "/biocore_core primary", FakeEvent())
        self.assertIn("重启后生效", reply)
