# -*- coding: utf-8 -*-
"""Config errors must fail loudly: no silent fallback to a degraded path.

Two silent failures cost a day each: a store stamped with a model that did not
produce its vectors, and an embedder that quietly became lexical matching. Both
are asserted here.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.recall import embedding as emb  # noqa: E402
from biocore_runtime import pipeline  # noqa: E402


class LoudConfigTest(unittest.TestCase):
    def test_reembed_refuses_to_stamp_a_model_it_cannot_prove(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            store = tmp.name
            Path(store, "core_config.json").write_text(json.dumps(
                {"embedding": {"model": "m-768", "dim": 768,
                               "base_url": "http://x/v1"}}), encoding="utf-8")
            class Liar:
                model = "BAAI/bge-m3"          # not what the config says
                def embed(self, texts):
                    return [[0.1] * 768 for _ in texts]
            with self.assertRaises(ValueError) as caught:
                pipeline.reembed_store(store, "s1", provider=Liar())
            message = str(caught.exception)
            self.assertIn("BAAI/bge-m3", message)
            self.assertIn("m-768", message)
        finally:
            tmp.cleanup()

    def test_reembed_without_a_config_is_an_error_not_a_default(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            with self.assertRaises(ValueError) as caught:
                pipeline.reembed_store(tmp.name, "s1", provider=None)
            self.assertIn("core_config.json", str(caught.exception))
        finally:
            tmp.cleanup()

    def test_a_provider_without_a_model_name_is_refused(self):
        class Nameless:
            model = ""
            mode = "remote"        # a remote provider must name its model
            def embed_text(self, text):
                return [0.1, 0.2]
        with self.assertRaises(ValueError) as caught:
            emb.embed("任意文本", Nameless())
        self.assertIn("model", str(caught.exception))

    def test_the_new_embedding_block_builds_an_embedder(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            fn = pipeline._event_embed_fn(tmp.name, {},
                                          {"embedding": {"base_url": "http://127.0.0.1:9/v1",
                                                         "model": "m-new", "dim": 8}})
            # a provider object is built even though the endpoint is dead: the
            # call itself would fail loudly, but construction must not fall back
            self.assertTrue(callable(fn))
        finally:
            tmp.cleanup()

    def test_embedding_enabled_without_a_provider_raises(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            # a config that asks for embeddings but cannot produce a provider:
            # no base_url anywhere, so load_provider returns None
            with self.assertRaises(RuntimeError) as caught:
                pipeline._event_embed_fn(tmp.name, {"embedding": {"model": "m"}},
                                         {"embedding": {"model": "m"}})
            self.assertIn("embedding", str(caught.exception).lower())
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
