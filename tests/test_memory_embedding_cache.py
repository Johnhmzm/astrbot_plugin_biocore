# -*- coding: utf-8 -*-
"""Embedding determinism: the disk cache is keyed by text + model.

The same text through the same model returns the same vector (float32-exact in
the db cache, bit for bit in the legacy json cache); the
key carries the model name so a model swap can never be answered with a stale
vector. Writes go through a temp file + os.replace and a corrupt cache is a
miss, not a crash. /state reports {hit, miss, size}.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.recall import embedding as emb  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402

SAVED_ENV = ("BIOCORE_EMBEDDING_CACHE_FILE", "BIOCORE_EMBEDDING_CACHE_DIR")


class FakeProvider:
    """Deterministic stand-in for a remote provider (no network)."""

    def __init__(self, vector, model="m1"):
        self.vector = list(vector)
        self.model = model
        self.calls = 0

    def embed_text(self, text):
        self.calls += 1
        return list(self.vector)


class CacheKeyTest(unittest.TestCase):
    def test_the_key_carries_the_model_name(self):
        self.assertNotEqual(emb.cache_key("你好", "m1"), emb.cache_key("你好", "m2"))
        self.assertEqual(emb.cache_key("你好", "m1"), emb.cache_key("你好", "m1"))
        # a provider without a model name keeps the historical text-only key
        self.assertEqual(emb.cache_key("你好"), emb.cache_key("你好", ""))

    def test_normalization_is_part_of_the_key(self):
        self.assertEqual(emb.cache_key(" 你好 ", "m1"), emb.cache_key("你好", "m1"))
        self.assertNotEqual(emb.cache_key("你好", "m1"), emb.cache_key("你好呀", "m1"))


class DeterminismTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "cache" / "embedding.json")
        emb.embed_stats(reset=True)

    def tearDown(self):
        # the cache pools one writer handle: release it before the temp dir goes
        emb.cache_close()
        self.tmp.cleanup()

    def test_the_same_text_returns_the_same_vector(self):
        provider = FakeProvider([0.1, 0.2, 0.3])
        first = emb.embed("你好", provider, path=self.path)
        second = emb.embed("你好", provider, path=self.path)
        # the db stores float32 (4 KB per 1024-d vector): a round-trip is exact to
        # float32, not to the float64 the json cache happened to keep
        for got, want in zip(second, first):
            self.assertAlmostEqual(got, want, places=6)
        self.assertEqual(provider.calls, 1)          # second call: cache hit
        # the file that exists depends on the backend (json file or sqlite db)
        expected = (emb.sqlite_cache_path(self.path)
                    if emb.cache_backend(self.path) == "sqlite" else self.path)
        self.assertTrue(Path(expected).exists())

    def test_a_second_process_reads_the_disk_cache(self):
        first = emb.embed("你好", FakeProvider([0.1, 0.2, 0.3]), path=self.path)
        other = FakeProvider([9.9, 9.9])            # would differ if it ran
        second = emb.embed("你好", other, path=self.path)
        for got, want in zip(second, first):
            self.assertAlmostEqual(got, want, places=6)
        self.assertEqual(other.calls, 0)
        self.assertEqual(len(emb.read_cache(self.path)), 1)   # backend-agnostic

    def test_write_leaves_no_temp_file(self):
        emb.embed("写入", FakeProvider([1.0]), path=self.path)
        self.assertFalse(Path(self.path + ".tmp").exists())
        self.assertEqual(emb.read_cache(self.path) != {}, True)

    def test_corrupt_cache_degrades_to_a_miss(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        if emb.cache_backend(self.path) == "sqlite":
            # the db is not the json: a corrupt json is simply not consulted
            Path(self.path).write_text("{ this is not json", encoding="utf-8")
            vector = emb.embed("坏掉的缓存", FakeProvider([0.5, 0.5]), path=self.path)
            self.assertEqual(vector, [0.5, 0.5])
            self.assertEqual(len(emb.read_cache(self.path)), 1)
            return
        Path(self.path).write_text("{ this is not json", encoding="utf-8")
        vector = emb.embed("坏掉的缓存", FakeProvider([0.5, 0.5]), path=self.path)
        self.assertEqual(vector, [0.5, 0.5])
        self.assertGreaterEqual(emb.embed_stats()["corrupt"], 1)
        self.assertEqual(len(emb.read_cache(self.path)), 1)   # rewritten healthy

    def test_summary_reports_hit_miss_size(self):
        emb.embed("一", FakeProvider([1.0]), path=self.path)
        emb.embed("一", FakeProvider([1.0]), path=self.path)   # disk hit
        emb.embed("二", FakeProvider([2.0]), path=self.path)   # miss
        info = emb.cache_summary(path=self.path)
        self.assertEqual(info["size"], 2)
        self.assertEqual(info["miss"], 2)
        self.assertEqual(info["hit"], 1)
        self.assertEqual(info["file"],
                         emb.sqlite_cache_path(self.path)
                         if emb.cache_backend(self.path) == "sqlite" else self.path)


class PathTest(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.pop(key, None) for key in SAVED_ENV}

    def tearDown(self):
        for key in SAVED_ENV:
            os.environ.pop(key, None)
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def test_the_default_sits_under_the_data_dir(self):
        with tempfile.TemporaryDirectory() as root:
            expected = str(Path(root) / "cache" / "embedding.json")
            self.assertEqual(emb.default_cache_file(root), expected)
            self.assertEqual(emb.cache_file(None, root), expected)

    def test_the_path_is_configurable(self):
        explicit = str(Path(tempfile.gettempdir()) / "bc-explicit.json")
        self.assertEqual(emb.cache_file({"embedding": {"cache_file": explicit}}),
                         explicit)
        self.assertEqual(emb.cache_file({"cache_path": explicit}), explicit)
        os.environ["BIOCORE_EMBEDDING_CACHE_FILE"] = explicit
        self.assertEqual(emb.cache_file(None, "/ignored"), explicit)
        os.environ["BIOCORE_EMBEDDING_CACHE_FILE"] = tempfile.gettempdir()
        self.assertEqual(emb.cache_file(None, "/ignored"),
                         str(Path(tempfile.gettempdir()) / "embedding.json"))

    def test_no_data_dir_means_no_implicit_file(self):
        self.assertIsNone(emb.cache_file(None, None))


class StateTest(unittest.TestCase):
    def test_state_reports_the_embedding_cache(self):
        with tempfile.TemporaryDirectory() as root:
            emb.embed_stats(reset=True)
            cache = Path(root) / "cache" / "embedding.json"
            emb.embed("统计", FakeProvider([0.3]), path=str(cache))
            out = pipeline.dispatch("state", {"session_id": "s1", "store": root})
            emb.cache_close()          # release the handle before the with-block exits
            info = out["state"]["embedding_cache"]
            for key in ("hit", "miss", "size"):
                self.assertIn(key, info)
            self.assertEqual(info["size"], 1)
            self.assertEqual(info["miss"], 1)


if __name__ == "__main__":
    unittest.main()
