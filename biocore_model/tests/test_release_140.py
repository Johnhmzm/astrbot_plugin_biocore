# -*- coding: utf-8 -*-
"""Release 1.4.0 consistency + autonomy defaults."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUG = ROOT


class VersionTest(unittest.TestCase):
    def test_all_version_sources_140(self):
        meta = (PLUG / "metadata.yaml").read_text(encoding="utf-8")
        self.assertIn("version: 1.4.0", meta)
        main = (PLUG / "main.py").read_text(encoding="utf-8")
        self.assertIn('"1.4.0")', main)
        app = (PLUG / "pages" / "dashboard" / "app.js").read_text(encoding="utf-8")
        self.assertIn('BIO_VERSION = "v1.4.0"', app)
        index = (PLUG / "pages" / "dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertIn('BIO_VERSION = "v1.4.0"', index)
        readme = (PLUG / "README.md").read_text(encoding="utf-8")
        self.assertIn("1.4.0", readme)
        record = json.loads((ROOT.parent / "docs" / "BIOCORE-MARKET-RECORD-v1.json")
                            .read_text(encoding="utf-8"))
        rec = record["Johnhmzm/astrbot_plugin_biocore"]
        self.assertEqual(rec["version"], "1.4.0")
        self.assertTrue(str(rec["updated_at"]).startswith("2026-10-31"))


class AutonomyDefaultTest(unittest.TestCase):
    def test_schema_defaults_false(self):
        schema = json.loads((PLUG / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertIs(schema["proactive_autonomy"]["default"], False)
        self.assertIs(schema["proactive_send"]["default"], False)
        self.assertIs(schema["autonomy_loop_enabled"]["default"], False)

    def test_code_reads_config_with_false_default(self):
        main = (PLUG / "main.py").read_text(encoding="utf-8")
        self.assertIn('self.proactive_autonomy = bool(self.config.get("proactive_autonomy", False))', main)
        self.assertIn('self.proactive_send = bool(self.config.get("proactive_send", False))', main)

    def test_changelog_warnings_and_rollback(self):
        text = (PLUG / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("本版本改动较大", text)
        self.assertIn("自主主动回复默认关闭", text)
        self.assertIn("升级失败可回滚", text)
        self.assertIn("docs/MIGRATION.md", text)


if __name__ == "__main__":
    unittest.main()
