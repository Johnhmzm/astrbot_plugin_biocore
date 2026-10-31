# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_mode

class FakePlugin:
    def __init__(self):
        self.config = {"proactive_autonomy": False, "proactive_send": False,
                       "proactive_autonomy_threshold": 0.6, "proactive_autonomy_max_chars": 120}
        self.saved = []
    async def _persist_plugin_config(self, updates):
        self.saved.append(dict(updates)); self.config.update(updates)

class AutonomyRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_save(self):
        plugin = FakePlugin()
        result = await autonomy_mode.apply(plugin, {"enabled": True, "send": True, "threshold": 0.7, "max_chars": 200})
        self.assertTrue(result["ok"]); self.assertEqual(plugin.saved[-1]["proactive_autonomy"], True)
        self.assertEqual(result["values"]["threshold"], 0.7); self.assertEqual(result["values"]["max_chars"], 200)
    async def test_invalid_threshold(self):
        with self.assertRaises(autonomy_mode.AutonomyError) as caught:
            await autonomy_mode.apply(FakePlugin(), {"threshold": 1.7})
        self.assertEqual(caught.exception.status, 400)
    async def test_invalid_max_chars(self):
        with self.assertRaises(autonomy_mode.AutonomyError):
            await autonomy_mode.apply(FakePlugin(), {"max_chars": 5})
    async def test_bad_bool_type(self):
        with self.assertRaises(autonomy_mode.AutonomyError):
            await autonomy_mode.apply(FakePlugin(), {"enabled": "yes"})
    async def test_partial_update_only(self):
        plugin = FakePlugin()
        await autonomy_mode.apply(plugin, {"send": True})
        self.assertEqual(list(plugin.saved[-1].keys()), ["proactive_send"])
    async def test_returns_current(self):
        plugin = FakePlugin()
        result = await autonomy_mode.apply(plugin, {})
        self.assertEqual(result["values"]["threshold"], 0.6)
if __name__ == "__main__": unittest.main()
