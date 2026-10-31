# -*- coding: utf-8 -*-
"""Cross-session recall must persist the marked copy into the target doc."""
import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CrossSessionCopyTest(unittest.TestCase):
    def test_copy_persisted_with_fields(self):
        sys.path.insert(0, str(ROOT.parent / "scripts"))
        try:
            e = importlib.import_module("eval_privacy_scope")
        except Exception as exc:  # AstrBot runtime deps are not in system Python
            sys.path.remove(str(ROOT.parent / "scripts"))
            self.skipTest("AstrBot deps unavailable: %s" % type(exc).__name__)
        import main
        names = ("DATA_DIR", "MEMORY_DIR", "STATE_DIR", "EVENT_ARCHIVE_DIR",
                 "EVENT_SESSION_DIR", "EVENT_ARCHIVE_PATH", "INSIGHT_ARCHIVE_PATH",
                 "USER_DIR", "SELF_MODEL_PATH")
        old = {name: getattr(main, name, None) for name in names}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                e.patch_storage(Path(tmp))
                plugin = e.build_plugin()
                s1 = "eval:privacy:session1"
                s2 = "eval:privacy:session2"
                ev1 = e.make_event(s1, "u9")
                ev2 = e.make_event(s2, "u9")

                async def run():
                    await plugin._memory_recall(
                        ev1, "老板最喜欢吃草莓蛋糕，尤其是奶油多的那种", None)
                    plugin._touch_user(ev1, None)
                    plugin._touch_user(ev2, None)
                    plugin.cross_session_memory = True
                    await plugin._memory_recall(ev2, "老板最喜欢吃草莓蛋糕", None)

                asyncio.run(run())
                doc = e.session_doc(plugin, s2)
                copies = [x for x in doc.get("entries") or []
                          if isinstance(x, dict)
                          and x.get("shared_from_session") == s1]
                self.assertEqual(len(copies), 1, doc.get("entries"))
                copy = copies[0]
                self.assertTrue(copy.get("id"))
                self.assertIn("草莓蛋糕", str(copy.get("text") or ""))
                self.assertLessEqual(float(copy.get("memory_confidence", 1)), 0.55)
                self.assertIn(copy.get("memory_source"), ("direct", "inferred"))
                self.assertTrue(any(item.get("reason") == "cross_session"
                                    for item in (doc.get("write_log") or [])))
        finally:
            for name, value in old.items():
                if value is not None:
                    setattr(main, name, value)
            try:
                sys.path.remove(str(ROOT.parent / "scripts"))
            except ValueError:
                pass


if __name__ == "__main__":
    unittest.main()
