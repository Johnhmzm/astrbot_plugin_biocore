# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path
from biocore_model import reply_limit


class PersistTest(unittest.TestCase):
    def _config(self, tmp, tokens=200):
        path = Path(tmp) / "cmd_config.json"
        path.write_text(json.dumps({"provider": [{"id": "a", "max_tokens": tokens}]}), encoding="utf-8")
        return path

    def test_persist_updates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(tmp)
            self.assertTrue(reply_limit.persist_max_tokens(path, 800))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["provider"][0]["max_tokens"], 800)

    def test_backup_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(tmp)
            reply_limit.persist_max_tokens(path, 512)
            backups = list(Path(tmp).glob("cmd_config.json.bak_replylimit_*"))
            self.assertEqual(len(backups), 1)

    def test_backup_rotation_keeps_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(tmp)
            for index in range(5):
                reply_limit.persist_max_tokens(path, 300 + index)
            backups = list(Path(tmp).glob("cmd_config.json.bak_replylimit_*"))
            self.assertLessEqual(len(backups), 3)

    def test_missing_provider_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cmd_config.json"
            path.write_text(json.dumps({"provider": []}), encoding="utf-8")
            self.assertFalse(reply_limit.persist_max_tokens(path, 800))

    def test_find_active_config_none(self):
        self.assertTrue(reply_limit.find_active_config(None) is None or reply_limit.find_active_config(None).is_file())


if __name__ == "__main__":
    unittest.main()
