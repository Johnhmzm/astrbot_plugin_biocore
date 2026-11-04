# -*- coding: utf-8 -*-
"""task-192 本地 int8 ONNX embedder 单测（CPU-only、懒加载、明确异常）。

不依赖真实模型/onnxruntime：用临时 tokenizer.json + 假 session/fake onnxruntime
模块验证加载、池化/归一化、维度校验、异常与 tokenizer 行为。
"""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from biocore_memory import embedding_local as el

VOCAB = {
    "[PAD]": 0, "[UNK]": 100, "[CLS]": 101, "[SEP]": 102,
    "你": 200, "好": 201, "，": 202, "世": 203, "界": 204,
    "今": 205, "天": 206, "abc": 207,
}


def _write_tokenizer(directory, vocab=None):
    path = Path(directory) / "tokenizer.json"
    payload = {"model": {"type": "WordPiece", "vocab": vocab or VOCAB,
                         "unk_token": "[UNK]",
                         "continuing_subword_prefix": "##"}}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class FakeSession:
    def __init__(self, output):
        self.output = output
        self.calls = 0
        self.feeds = None

    def run(self, names, feeds):
        self.calls += 1
        self.feeds = feeds
        return [self.output]


class FakeOptions:
    intra_op_num_threads = 0
    inter_op_num_threads = 0
    graph_optimization_level = 0
    log_severity_level = 0


class FakeOrtModule:
    captured = {}

    class GraphOptimizationLevel:
        ORT_ENABLE_ALL = 99

    @staticmethod
    def SessionOptions():
        return FakeOptions()

    class InferenceSession:
        def __init__(self, path, sess_options=None, providers=None):
            FakeOrtModule.captured = {
                "path": str(path), "threads": getattr(
                    sess_options, "intra_op_num_threads", None),
                "providers": list(providers or []),
            }
            self.batch_size = 0

        def get_outputs(self):
            return [types.SimpleNamespace(name="embedding")]

        def run(self, names, feeds):
            size = len(feeds["input_ids"])
            return [[[0.0, 1.0, 0.0, 0.0] for _ in range(size)]]


class LocalEmbedderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.model = self.root / "model.onnx"
        self.model.write_bytes(b"fake-onnx")
        self.tokenizer = _write_tokenizer(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _embedder(self, **kwargs):
        return el.LocalEmbedder(self.model, dim=4,
                                tokenizer_path=self.tokenizer, **kwargs)

    def test_status_missing_before_load(self):
        embedder = self._embedder()
        self.assertEqual(embedder.status(), "missing")
        self.assertEqual(embedder.health()["local_embedding"], "missing")

    def test_status_ok_after_injected_session(self):
        embedder = self._embedder()
        embedder._session = FakeSession([[3.0, 4.0, 0.0, 0.0]])
        embedder._tokenizer = el._VocabTokenizer(self.tokenizer)
        self.assertEqual(embedder.status(), "ok")

    def test_encode_cls_and_l2_normalize(self):
        embedder = self._embedder()
        embedder._session = FakeSession([[3.0, 4.0, 0.0, 0.0]])
        embedder._tokenizer = el._VocabTokenizer(self.tokenizer)
        vectors = embedder.encode("你好")
        self.assertEqual(len(vectors), 1)
        self.assertAlmostEqual(vectors[0][0], 0.6, places=5)
        self.assertAlmostEqual(vectors[0][1], 0.8, places=5)
        norm = sum(value * value for value in vectors[0]) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_batch_order_and_padding(self):
        embedder = self._embedder()
        embedder._session = FakeSession([[1.0, 0.0, 0.0, 0.0],
                                         [0.0, 1.0, 0.0, 0.0]])
        embedder._tokenizer = el._VocabTokenizer(self.tokenizer)
        vectors = embedder.encode(["你好", "今天，世界"])
        self.assertEqual(len(vectors), 2)
        self.assertAlmostEqual(vectors[0][0], 1.0)
        self.assertAlmostEqual(vectors[1][1], 1.0)
        feeds = embedder._session.feeds
        self.assertEqual(len(feeds["input_ids"]), 2)
        self.assertEqual(feeds["input_ids"].shape[0], 2)
        self.assertIn(0, feeds["attention_mask"][0])

    def test_dimension_mismatch_raises(self):
        embedder = self._embedder()
        embedder._session = FakeSession([[1.0, 0.0, 0.0]])
        embedder._tokenizer = el._VocabTokenizer(self.tokenizer)
        with self.assertRaises(el.LocalEmbeddingError):
            embedder.encode("你好")

    def test_non_numeric_output_raises(self):
        embedder = self._embedder()
        embedder._session = FakeSession([["x", 0.0, 0.0, 0.0]])
        embedder._tokenizer = el._VocabTokenizer(self.tokenizer)
        with self.assertRaises(el.LocalEmbeddingError):
            embedder.encode("你好")

    def test_malformed_texts(self):
        embedder = self._embedder()
        embedder._session = FakeSession([[1.0, 0.0, 0.0, 0.0]])
        embedder._tokenizer = el._VocabTokenizer(self.tokenizer)
        self.assertEqual(embedder.encode(None), [])
        self.assertEqual(embedder.encode([]), [])
        with self.assertRaises(el.LocalEmbeddingError):
            embedder.encode(123)
        with self.assertRaises(el.LocalEmbeddingError):
            embedder.encode({"a": 1})

    def test_threads_default_and_clamped(self):
        self.assertEqual(el.LocalEmbedder(self.model).threads, 2)
        self.assertEqual(el.LocalEmbedder(self.model, threads=99).threads, 8)
        self.assertEqual(el.LocalEmbedder(self.model, threads=0).threads, 2)


class LoadFailureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tokenizer = _write_tokenizer(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_model_path(self):
        embedder = el.LocalEmbedder("", tokenizer_path=self.tokenizer)
        self.assertEqual(embedder.status(), "missing")
        with self.assertRaises(el.LocalEmbeddingUnavailable):
            embedder.encode(["x"])

    def test_model_file_absent(self):
        embedder = el.LocalEmbedder(self.root / "nope.onnx",
                                    tokenizer_path=self.tokenizer)
        with self.assertRaises(el.LocalEmbeddingUnavailable) as ctx:
            embedder.load()
        self.assertIn("not found", str(ctx.exception))
        self.assertEqual(embedder.status(), "failed")

    def test_missing_onnxruntime(self):
        model = self.root / "model.onnx"
        model.write_bytes(b"fake")
        embedder = el.LocalEmbedder(model, tokenizer_path=self.tokenizer)
        with mock.patch.object(el, "_onnxruntime",
                               side_effect=ImportError("no onnxruntime")):
            with self.assertRaises(el.LocalEmbeddingUnavailable) as ctx:
                embedder.load()
        self.assertIn("onnxruntime", str(ctx.exception))
        self.assertEqual(embedder.status(), "failed")

    def test_missing_tokenizer(self):
        isolated = self.root / "isolated"
        isolated.mkdir()
        model = isolated / "model.onnx"
        model.write_bytes(b"fake")
        with mock.patch.dict("os.environ",
                             {el.ENV_TOKENIZER: ""}):
            embedder = el.LocalEmbedder(model)
            with self.assertRaises(el.LocalEmbeddingUnavailable) as ctx:
                embedder.load()
        self.assertIn("tokenizer", str(ctx.exception))

    def test_cpu_only_session_options(self):
        model = self.root / "model.onnx"
        model.write_bytes(b"fake")
        embedder = el.LocalEmbedder(model, dim=4,
                                    tokenizer_path=self.tokenizer, threads=3)
        fake_numpy = types.SimpleNamespace(
            asarray=lambda seq, dtype=None: seq, int64=object)
        with mock.patch.object(el, "_onnxruntime",
                               return_value=FakeOrtModule), \
                mock.patch.object(el, "_numpy", return_value=fake_numpy):
            vectors = embedder.encode(["你好"])
        self.assertEqual(len(vectors), 1)
        captured = FakeOrtModule.captured
        self.assertEqual(captured["providers"], ["CPUExecutionProvider"])
        self.assertEqual(captured["threads"], 3)
        self.assertNotIn("CUDAExecutionProvider",
                         " ".join(captured["providers"]))

    def test_no_torch_or_cuda_source_dependency(self):
        source = Path(el.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import torch", source)
        self.assertNotIn("CUDAExecutionProvider", source)


class TokenizerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tokenizer = _write_tokenizer(self._tmp.name)
        self.vocab = el._VocabTokenizer(self.tokenizer)

    def tearDown(self):
        self._tmp.cleanup()

    def test_chinese_char_split(self):
        ids, mask = self.vocab.encode("你好")
        self.assertEqual(ids, [101, 200, 201, 102])
        self.assertEqual(mask, [1, 1, 1, 1])

    def test_punctuation_split(self):
        ids, _ = self.vocab.encode("你好，天")
        self.assertEqual(ids, [101, 200, 201, 202, 206, 102])

    def test_batch_padding_masks(self):
        ids_rows, mask_rows = self.vocab.encode_batch(["你好", "你好，天"])
        self.assertEqual(len(ids_rows), 2)
        self.assertEqual(len(ids_rows[0]), len(ids_rows[1]))
        self.assertEqual(len(ids_rows[1]), 6)
        self.assertEqual(mask_rows[0][:4], [1, 1, 1, 1])
        self.assertEqual(mask_rows[0][-2:], [0, 0])
        self.assertTrue(all(value == 1 for value in mask_rows[1]))

    def test_max_length_truncation(self):
        ids, _ = self.vocab.encode("今天世界" * 20, max_length=8)
        self.assertLessEqual(len(ids), 8)
        self.assertEqual(ids[0], 101)
        self.assertEqual(ids[-1], 102)

    def test_vocab_txt_fallback(self):
        txt = Path(self._tmp.name) / "vocab.txt"
        lines = ["[PAD]", "[UNK]", "[CLS]", "[SEP]"] + ["你", "好"]
        txt.write_text("\n".join(lines), encoding="utf-8")
        vocab = el._VocabTokenizer(txt)
        self.assertEqual(vocab.encode("你好")[0], [2, 4, 5, 3])

    def test_missing_specials_rejected(self):
        path = Path(self._tmp.name) / "bad.json"
        path.write_text(json.dumps({"model": {"vocab": {"a": 0}}}),
                        encoding="utf-8")
        with self.assertRaises(el.LocalEmbeddingUnavailable):
            el._VocabTokenizer(path)


if __name__ == "__main__":
    unittest.main()
