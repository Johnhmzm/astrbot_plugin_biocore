# -*- coding: utf-8 -*-
import unittest
from biocore_model import reply_limit


class FakeContext:
    def __init__(self, config, fail=False):
        self._config = config
        self.fail = fail
        self.saved = 0
    def get_config(self):
        return self._config
    async def save_config_async(self, config):
        self.saved += 1
        if self.fail:
            raise RuntimeError("save failed")


class FakePlugin:
    def __init__(self, config, fail=False):
        self.context = FakeContext(config, fail)


def cfg(max_tokens=200, enable=True):
    return {"provider": {"default": {"id": "a", "name": "p1", "max_tokens": max_tokens, "enable": enable}}}


class ReplyLimitTest(unittest.IsolatedAsyncioTestCase):
    async def test_read_default_provider(self):
        data = reply_limit.read(FakePlugin(cfg(320)))
        self.assertEqual(data["max_tokens"], 320)
        self.assertEqual(data["provider_id"], "a")
        self.assertEqual(data["source"], "astrbot")

    async def test_apply_ok(self):
        plugin = FakePlugin(cfg(200))
        result = await reply_limit.apply(plugin, {"max_tokens": 512})
        self.assertTrue(result["ok"])
        self.assertEqual(result["applied"]["max_tokens"], 512)
        # restart_required depends on whether an active AstrBot config file exists
        self.assertEqual(plugin.context.saved, 1)

    async def test_apply_writes_file_when_active_config_found(self):
        import json, tempfile
        from pathlib import Path
        from biocore_model import reply_limit as rl
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cmd_config.json"
            path.write_text(json.dumps({"provider": [{"id": "a", "max_tokens": 200}]}), encoding="utf-8")
            old = rl.find_active_config
            rl.find_active_config = lambda plugin=None: path
            try:
                result = await rl.apply(FakePlugin(cfg(200)), {"max_tokens": 800})
            finally:
                rl.find_active_config = old
            self.assertEqual(result["file"], str(path))
            self.assertFalse(result["restart_required"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["provider"][0]["max_tokens"], 800)

    async def test_apply_rejects_low(self):
        with self.assertRaises(reply_limit.ReplyLimitError) as caught:
            await reply_limit.apply(FakePlugin(cfg()), {"max_tokens": 10})
        self.assertEqual(caught.exception.status, 400)

    async def test_apply_rejects_high(self):
        with self.assertRaises(reply_limit.ReplyLimitError):
            await reply_limit.apply(FakePlugin(cfg()), {"max_tokens": 5000})

    async def test_save_failure_sets_restart_required(self):
        result = await reply_limit.apply(FakePlugin(cfg(), fail=True), {"max_tokens": 300})
        self.assertTrue(result["restart_required"])
        self.assertTrue(result["ok"])

    async def test_missing_config_no_crash(self):
        data = reply_limit.read(FakePlugin({}))
        self.assertEqual(data["max_tokens"], 800)
        result = await reply_limit.apply(FakePlugin({}), {"max_tokens": 128})
        self.assertTrue(result["restart_required"])

    async def test_bad_type_rejected(self):
        with self.assertRaises(reply_limit.ReplyLimitError):
            await reply_limit.apply(FakePlugin(cfg()), {"max_tokens": "abc"})


if __name__ == "__main__":
    unittest.main()
