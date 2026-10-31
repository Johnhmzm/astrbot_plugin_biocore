# -*- coding: utf-8 -*-
import json, tempfile, unittest
from pathlib import Path
from biocore_model import plugin_config


class PluginConfigPersistTest(unittest.TestCase):
    def _file(self, tmp, data, bom=False):
        path = Path(tmp) / plugin_config.FILE_NAME
        text = json.dumps(data, ensure_ascii=False)
        path.write_text(text, encoding="utf-8-sig" if bom else "utf-8")
        return path

    def test_persist_updates_and_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._file(tmp, {"reply_split_enabled": False, "reply_split_mode": "punct"})
            old = plugin_config.find_config
            plugin_config.find_config = lambda plugin=None: path
            try:
                result = plugin_config.persist_updates({"reply_split_enabled": True, "reply_split_mode": "astrbot"})
            finally:
                plugin_config.find_config = old
            self.assertTrue(result["ok"])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["reply_split_enabled"]); self.assertEqual(data["reply_split_mode"], "astrbot")

    def test_bom_preserved_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._file(tmp, {"x": 1}, bom=True)
            old = plugin_config.find_config
            plugin_config.find_config = lambda plugin=None: path
            try:
                plugin_config.persist_updates({"y": 2})
            finally:
                plugin_config.find_config = old
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8-sig"))["y"], 2)

    def test_no_bom_written_without_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._file(tmp, {"x": 1})
            old = plugin_config.find_config
            plugin_config.find_config = lambda plugin=None: path
            try:
                plugin_config.persist_updates({"y": 2})
            finally:
                plugin_config.find_config = old
            self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_backup_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._file(tmp, {"x": 1})
            old = plugin_config.find_config
            plugin_config.find_config = lambda plugin=None: path
            try:
                plugin_config.persist_updates({"x": 2})
            finally:
                plugin_config.find_config = old
            self.assertEqual(len(list(Path(tmp).glob(plugin_config.FILE_NAME + ".bak_replysplit_*"))), 1)

    def test_backup_rotation_keeps_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._file(tmp, {"x": 1})
            old = plugin_config.find_config
            plugin_config.find_config = lambda plugin=None: path
            try:
                for index in range(5):
                    plugin_config.persist_updates({"x": index})
            finally:
                plugin_config.find_config = old
            self.assertLessEqual(len(list(Path(tmp).glob(plugin_config.FILE_NAME + ".bak_replysplit_*"))), 3)

    def test_missing_file_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = plugin_config.find_config
            plugin_config.find_config = lambda plugin=None: None
            try:
                result = plugin_config.persist_updates({"x": 1})
            finally:
                plugin_config.find_config = old
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
