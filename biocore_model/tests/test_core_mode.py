# -*- coding: utf-8 -*-
"""Core mode switch: validation, auth, persist, rebuild semantics, rollback."""
import unittest

from biocore_model import core_mode


class FakePlugin:
    def __init__(self, mode="off", admin=True, rebuild=True, token=""):
        self.config = {"core_client_mode": mode, "core_client_enabled": mode != "off"}
        self.admin = admin
        self.rebuild_ok = rebuild
        self.data_admin_token = token
        self.saved = []
        self.rebuilds = 0

    def _page_is_local_admin(self, body=None):
        return bool(self.admin)

    async def _persist_plugin_config(self, updates):
        self.saved.append(dict(updates))
        self.config.update(updates)

    def _rebuild_core_bridge(self):
        self.rebuilds += 1
        return bool(self.rebuild_ok)


class ValidateTest(unittest.TestCase):
    def test_three_modes_valid(self):
        for mode in ("off", "shadow", "primary", " Shadow "):
            self.assertIn(core_mode.validate_mode(mode), core_mode.MODES)

    def test_invalid_mode_400(self):
        with self.assertRaises(core_mode.CoreModeError) as caught:
            core_mode.validate_mode("bogus")
        self.assertEqual(caught.exception.status, 400)

    def test_updates_map(self):
        self.assertEqual(core_mode.updates_for("shadow"), {"core_client_enabled": True, "core_client_mode": "shadow"})
        self.assertEqual(core_mode.updates_for("off"), {"core_client_enabled": False, "core_client_mode": "off"})


class AuthTest(unittest.TestCase):
    def test_403_only_when_token_configured(self):
        # no configured data_admin_token -> host /api JWT is the gate, no plugin 403
        core_mode.authorize(FakePlugin(admin=False, token=""), {})
        with self.assertRaises(core_mode.CoreModeError) as caught:
            core_mode.authorize(FakePlugin(admin=False, token="secret"), {})
        self.assertEqual(caught.exception.status, 403)

    def test_authorized_local_admin(self):
        core_mode.authorize(FakePlugin(admin=True), {})  # no raise

    def test_remote_without_token_passes_by_default(self):
        # remote panel (not local, no configured data_admin_token) must NOT be blocked:
        # AstrBot's /api layer already authenticated the request with JWT.
        core_mode.authorize(FakePlugin(admin=False, token=""), {})  # no raise

    def test_remote_with_configured_token_still_403(self):
        with self.assertRaises(core_mode.CoreModeError) as caught:
            core_mode.authorize(FakePlugin(admin=False, token="secret"), {})
        self.assertEqual(caught.exception.status, 403)


class HttpAbortTest(unittest.TestCase):
    def test_falls_back_to_core_error_when_no_host(self):
        # Outside AstrBot the host module is absent; the code must still preserve status.
        try:
            core_mode.http_abort(400)
        except core_mode.CoreModeError as error:
            self.assertEqual(error.status, 400)
        except Exception as error:  # quart may be installed in the host env
            self.assertTrue(getattr(error, "code", None) == 400 or getattr(error, "status_code", None) == 400)

    def test_invalid_mode_still_400_via_apply(self):
        import asyncio
        plugin = FakePlugin()
        with self.assertRaises(core_mode.CoreModeError) as caught:
            asyncio.run(core_mode.apply(plugin, "bogus"))
        self.assertEqual(caught.exception.status, 400)


class ApplyTest(unittest.IsolatedAsyncioTestCase):
    async def test_apply_shadow_persists_and_rebuilds(self):
        plugin = FakePlugin()
        payload = await core_mode.apply(plugin, "shadow")
        self.assertEqual(payload, {"ok": True, "mode": "shadow", "pending_restart": False})
        self.assertEqual(plugin.saved[-1], {"core_client_enabled": True, "core_client_mode": "shadow"})
        self.assertEqual(plugin.config["core_client_mode"], "shadow")
        self.assertEqual(plugin.rebuilds, 1)

    async def test_apply_off_disables(self):
        plugin = FakePlugin(mode="primary")
        payload = await core_mode.apply(plugin, "off")
        self.assertEqual(payload["mode"], "off")
        self.assertEqual(plugin.config["core_client_enabled"], False)

    async def test_pending_restart_when_rebuild_fails(self):
        plugin = FakePlugin(rebuild=False)
        payload = await core_mode.apply(plugin, "primary")
        self.assertTrue(payload["pending_restart"])

    async def test_rollback_equals_off(self):
        plugin = FakePlugin(mode="primary")
        payload = await core_mode.rollback(plugin)
        self.assertEqual(payload, {"ok": True, "mode": "off", "pending_restart": False})
        self.assertEqual(plugin.config["core_client_enabled"], False)
        self.assertEqual(plugin.config["core_client_mode"], "off")

    async def test_log_records_from_to(self):
        plugin = FakePlugin()
        with self.assertLogs("astrbot", level="INFO") as logs:
            await core_mode.apply(plugin, "shadow")
        joined = "\n".join(logs.output)
        self.assertIn("core_mode_changed from=off to=shadow", joined)
        self.assertNotIn("api_key", joined.lower())

    async def test_invalid_mode_does_not_persist(self):
        plugin = FakePlugin()
        with self.assertRaises(core_mode.CoreModeError):
            await core_mode.apply(plugin, "bogus")
        self.assertEqual(plugin.saved, [])

    async def test_save_failure_maps_500(self):
        class Broken(FakePlugin):
            async def _persist_plugin_config(self, updates):
                raise RuntimeError("boom")
        with self.assertRaises(core_mode.CoreModeError) as caught:
            await core_mode.apply(Broken(), "shadow")
        self.assertEqual(caught.exception.status, 500)
