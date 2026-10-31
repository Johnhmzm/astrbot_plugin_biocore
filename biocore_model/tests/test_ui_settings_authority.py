# -*- coding: utf-8 -*-
"""ui_settings single-authority tests: path, migration, idempotency, roundtrip."""
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from biocore_model import ui_settings as ui

ENV_DIR = "BIOCORE_UI_SETTINGS_DIR"
ENV_LEGACY = "BIOCORE_UI_SETTINGS_LEGACY"


class FakePlugin:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)


class AuthorityPathTest(unittest.TestCase):
    def setUp(self):
        ui._MIGRATED.clear()

    def tearDown(self):
        ui._MIGRATED.clear()

    def test_two_plugin_objects_share_one_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = ui.settings_path(FakePlugin(tmp))
            second = ui.settings_path(FakePlugin(tmp))
            self.assertEqual(first, second)
            self.assertEqual(first, Path(tmp) / ui.FILE_NAME)

    def test_plugins_layout_maps_to_plugin_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "plugins" / "astrbot_plugin_biocore_standalone" / "data"
            legacy.mkdir(parents=True)
            path = ui.settings_path(FakePlugin(legacy))
            self.assertEqual(path, Path(tmp) / "plugin_data" / "astrbot_plugin_biocore" / ui.FILE_NAME)

    def test_env_override_wins_for_every_plugin(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            with mock.patch.dict(os.environ, {ENV_DIR: tmp}):
                a = ui.settings_path(FakePlugin(other))
                b = ui.settings_path(FakePlugin("/somewhere/else"))
            self.assertEqual(a, b)
            self.assertEqual(a, Path(tmp) / ui.FILE_NAME)

    def test_canonical_plugin_data_dir_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            canonical = Path(tmp) / "plugin_data" / "astrbot_plugin_biocore_standalone"
            canonical.mkdir(parents=True)
            path = ui.settings_path(FakePlugin(canonical))
            self.assertEqual(path, Path(tmp) / "plugin_data" / "astrbot_plugin_biocore" / ui.FILE_NAME)


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.authority_dir = Path(self.tmp.name) / "plugin_data"
        self.legacy = Path(self.tmp.name) / "legacy_ui_settings.json"
        self.env = mock.patch.dict(os.environ, {
            ENV_DIR: str(self.authority_dir),
            ENV_LEGACY: str(self.legacy),
        })
        self.env.start()
        ui._MIGRATED.clear()

    def tearDown(self):
        ui._MIGRATED.clear()
        self.env.stop()
        self.tmp.cleanup()

    def _authority_file(self):
        return self.authority_dir / ui.FILE_NAME

    def test_a_to_b_migration_merges_keys(self):
        self.legacy.write_text(json.dumps({"reply_soft": {"max_chars": 77},
                                           "custom": {"x": 1}}), encoding="utf-8")
        data = ui.load(FakePlugin(self.tmp.name))
        self.assertEqual(data["reply_soft"]["max_chars"], 77)
        raw = json.loads(self._authority_file().read_text(encoding="utf-8"))
        self.assertEqual(raw["custom"]["x"], 1)
        self.assertEqual(raw["schema"], 1)

    def test_migration_logged_once(self):
        self.legacy.write_text(json.dumps({"reply_soft": {"max_chars": 40}}), encoding="utf-8")
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        old_level = ui.logger.level
        ui.logger.setLevel(logging.INFO)
        ui.logger.addHandler(handler)
        try:
            ui.load(FakePlugin(self.tmp.name))
            ui.load(FakePlugin(self.tmp.name))
        finally:
            ui.logger.removeHandler(handler)
            ui.logger.setLevel(old_level)
        self.assertEqual(records.count(ui.MIGRATION_LOG), 1)

    def test_migration_idempotent(self):
        self.legacy.write_text(json.dumps({"reply_soft": {"max_chars": 55}}), encoding="utf-8")
        first = ui.load(FakePlugin(self.tmp.name))
        second = ui.load(FakePlugin(self.tmp.name))
        self.assertEqual(first["reply_soft"]["max_chars"], 55)
        self.assertEqual(second["reply_soft"]["max_chars"], 55)

    def test_newer_authority_is_not_overwritten(self):
        self._authority_file().parent.mkdir(parents=True, exist_ok=True)
        self._authority_file().write_text(json.dumps({"reply_soft": {"max_chars": 30}}), encoding="utf-8")
        self.legacy.write_text(json.dumps({"reply_soft": {"max_chars": 77}}), encoding="utf-8")
        os.utime(self._authority_file(), (2_000, 2_000))
        os.utime(self.legacy, (1_000, 1_000))
        data = ui.load(FakePlugin(self.tmp.name))
        self.assertEqual(data["reply_soft"]["max_chars"], 30)

    def test_newer_legacy_is_merged(self):
        self._authority_file().parent.mkdir(parents=True, exist_ok=True)
        self._authority_file().write_text(json.dumps({"reply_soft": {"max_chars": 30},
                                                       "keep": {"k": 1}}), encoding="utf-8")
        self.legacy.write_text(json.dumps({"reply_soft": {"max_chars": 77}}), encoding="utf-8")
        os.utime(self._authority_file(), (1_000, 1_000))
        os.utime(self.legacy, (2_000, 2_000))
        data = ui.load(FakePlugin(self.tmp.name))
        self.assertEqual(data["reply_soft"]["max_chars"], 77)
        raw = json.loads(self._authority_file().read_text(encoding="utf-8"))
        self.assertEqual(raw["keep"]["k"], 1)

    def test_legacy_is_never_read_again(self):
        self.legacy.write_text(json.dumps({"reply_soft": {"max_chars": 44}}), encoding="utf-8")
        ui.load(FakePlugin(self.tmp.name))
        self.legacy.write_text(json.dumps({"reply_soft": {"max_chars": 99}}), encoding="utf-8")
        data = ui.load(FakePlugin(self.tmp.name))
        self.assertEqual(data["reply_soft"]["max_chars"], 44)

    def test_missing_legacy_does_not_crash(self):
        data = ui.load(FakePlugin(self.tmp.name))
        self.assertTrue(data["reply_soft"]["enabled"])
        self.assertFalse(self._authority_file().exists())

    def test_corrupt_legacy_does_not_crash(self):
        self.legacy.write_text("{not json", encoding="utf-8")
        data = ui.load(FakePlugin(self.tmp.name))
        self.assertTrue(data["reply_soft"]["enabled"])

    def test_save_load_roundtrip_two_plugins(self):
        first = FakePlugin(self.tmp.name)
        self.assertTrue(ui.save(first, {"reply_soft": {"max_chars": 25}})["ok"])
        second = FakePlugin("/elsewhere")
        self.assertEqual(ui.load(second)["reply_soft"]["max_chars"], 25)
        self.assertTrue(self._authority_file().is_file())
        self.assertFalse((Path("/elsewhere") / ui.FILE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
