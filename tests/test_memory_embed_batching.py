# -*- coding: utf-8 -*-
"""embed_many: N rows must cost ceil(N / batch_size) provider requests.

The failure this pins: a limiter (or a reviewer) treating one embed() call as one
HTTP request. Batching is only real if the request count stays small while the
row count grows, so both are asserted here and reported through EMBED_STATS.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.recall import embedding as emb  # noqa: E402
from biocore_memory.recall import providers as prov  # noqa: E402


def transport(dim=4, calls=None):
    def call(url, payload, timeout, headers):
        if calls is not None:
            calls.append(len(payload.get("input") or []))
        import json
        rows = [{"embedding": [0.1 * (i + 1) for i in range(dim)]}
                for _text in payload.get("input") or []]
        return 200, json.dumps({"data": rows}).encode("utf-8")
    return call


class EmbedManyBatchingTest(unittest.TestCase):
    def setUp(self):
        emb.embed_stats(reset=True)    # the counters are process-wide

    def tearDown(self):
        emb.cache_close()          # drops the connection and the process memo

    def test_128_rows_are_four_requests(self):
        calls = []
        adapter = prov.OpenAICompatEmbeddings(
            {"base_url": "http://x/v1", "model": "m", "dim": 4, "batch_size": 32},
            transport=transport(calls=calls))
        texts = ["第%d条待嵌入的句子" % i for i in range(128)]
        vectors = emb.embed_many(texts, adapter)
        self.assertEqual(len(vectors), 128)
        self.assertEqual(len(calls), 4)               # ceil(128 / 32)
        self.assertEqual(sum(calls), 128)
        self.assertEqual(int(emb.EMBED_STATS.get("requests")), 4)
        self.assertEqual(int(emb.EMBED_STATS.get("rows")), 128)

    def test_a_second_call_is_all_memo_hits(self):
        calls = []
        adapter = prov.OpenAICompatEmbeddings(
            {"base_url": "http://x/v1", "model": "m", "dim": 4, "batch_size": 32},
            transport=transport(calls=calls))
        texts = ["同一批句子 %d" % i for i in range(40)]
        emb.embed_many(texts, adapter)
        first = len(calls)
        self.assertEqual(first, 2)                     # ceil(40 / 32)
        emb.embed_many(texts, adapter)
        self.assertEqual(len(calls), first)           # memo: no new requests
        self.assertEqual(int(emb.EMBED_STATS.get("requests")), first)


if __name__ == "__main__":
    unittest.main()
