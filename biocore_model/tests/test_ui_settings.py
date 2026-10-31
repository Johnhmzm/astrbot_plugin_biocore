# -*- coding: utf-8 -*-
import json, tempfile, unittest
from pathlib import Path
from biocore_model import ui_settings


class FakePlugin:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.reply_soft_limit_enabled = None
        self.reply_soft_target_chars = None
        self.reply_soft_max_chars = None
        self.reply_split_enabled = None
        self.reply_split_mode = None
        self.reply_split_max_chars = None
        self.proactive_autonomy = None
        self.proactive_send = None


class UiSettingsTest(unittest.TestCase):
    def test_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = ui_settings.load(FakePlugin(tmp))
            self.assertTrue(data["reply_soft"]["enabled"]); self.assertEqual(data["reply_split"]["mode"], "astrbot")

    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = FakePlugin(tmp)
            result = ui_settings.save(plugin, {"reply_split": {"enabled": True, "mode": "astrbot"}, "reply_soft": {"target_chars": 10, "max_chars": 30}})
            self.assertTrue(result["ok"])
            data = ui_settings.load(plugin)
            self.assertTrue(data["reply_split"]["enabled"]); self.assertEqual(data["reply_split"]["mode"], "astrbot")
            self.assertEqual(data["reply_soft"]["max_chars"], 30)

    def test_apply_to_plugin_overrides_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = FakePlugin(tmp)
            ui_settings.save(plugin, {"reply_split": {"enabled": True, "mode": "astrbot"}, "autonomy": {"enabled": True, "send": True}})
            ui_settings.apply_to_plugin(plugin)
            self.assertTrue(plugin.reply_split_enabled); self.assertEqual(plugin.reply_split_mode, "astrbot")
            self.assertTrue(plugin.proactive_autonomy); self.assertTrue(plugin.proactive_send)

    def test_survives_simulated_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = FakePlugin(tmp)
            ui_settings.save(first, {"reply_split": {"enabled": True, "mode": "astrbot"}, "reply_soft": {"target_chars": 10, "max_chars": 30}})
            second = FakePlugin(tmp)  # fresh instance = restart
            ui_settings.apply_to_plugin(second)
            self.assertTrue(second.reply_split_enabled); self.assertEqual(second.reply_split_mode, "astrbot")
            self.assertEqual(second.reply_soft_target_chars, 10); self.assertEqual(second.reply_soft_max_chars, 30)

    def test_corrupt_file_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = FakePlugin(tmp)
            ui_settings.settings_path(plugin).write_text("{not json", encoding="utf-8")
            data = ui_settings.load(plugin)
            self.assertTrue(data["reply_soft"]["enabled"])

    def test_backups_rotated_to_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = FakePlugin(tmp)
            for index in range(6):
                ui_settings.save(plugin, {"reply_split": {"max_chars": 200 + index}})
            backups = list(Path(tmp).glob("ui_settings.json.bak_*"))
            self.assertLessEqual(len(backups), 3)

    def test_accumulator_v_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = FakePlugin(tmp)
            ui_settings.save(first, {"autonomy": {"accumulator": {"V": 0.42, "ticks_since_fire": 7}}})
            data = ui_settings.load(FakePlugin(tmp))
            self.assertAlmostEqual(data["autonomy"]["accumulator"]["V"], 0.42)
            self.assertEqual(data["autonomy"]["accumulator"]["ticks_since_fire"], 7)

    def test_schema_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = FakePlugin(tmp)
            ui_settings.save(plugin, {"autonomy": {"enabled": True}})
            raw = json.loads(ui_settings.settings_path(plugin).read_text(encoding="utf-8"))
            self.assertEqual(raw["schema"], 1)


if __name__ == "__main__":
    unittest.main()
