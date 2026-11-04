# -*- coding: utf-8 -*-
"""CPU-only local int8 ONNX embedder (the fallback path for remote embeddings).

The optional component (task-190) is a bge-small-zh-v1.5 int8 ONNX export:

  models/bge-small-zh-int8/model.onnx   about 23 MB
  inputs   input_ids, attention_mask    int64, dynamic batch / sequence
  output   embedding                    CLS-pooled + L2-normalized, dim 512

Hard rules:
- CPU only: onnxruntime with CPUExecutionProvider; no torch, no CUDA packages,
  no GPU requirement; intra-op threads configurable (default 2).
- Lazy import: importing this module never imports onnxruntime.
- Clear failures: LocalEmbeddingUnavailable when runtime / model / vocab is
  missing, LocalEmbeddingError for bad input or output dimensions. Callers
  (the provider) catch these and stay on the remote path; the process never
  dies because the optional component is absent.
- Tokenizer: a small stdlib BERT WordPiece reader over vocab.txt, so the
  component needs onnxruntime only (no transformers / tokenizers package).

The model directory is an optional, removable component: delete it and the
provider simply keeps using the remote API.
"""
from __future__ import annotations

import json
import os
import threading
import unicodedata
from pathlib import Path

DEFAULT_DIM = 512
DEFAULT_MAX_LENGTH = 512
DEFAULT_THREADS = 2
MAX_THREADS = 8
MAX_WORD_CHARS = 100
SPECIAL_TOKENS = ("[PAD]", "[UNK]", "[CLS]", "[SEP]")
ENV_TOKENIZER = "BIOCORE_EMBEDDING_LOCAL_TOKENIZER"

# Lazy optional deps: imported on first real use, cached for the process, and
# abstracted behind helpers so tests can inject fakes without touching
# sys.modules (replacing sys.modules entries can force numpy to be loaded
# twice in one process, which C extensions reject).
_LAZY_MODULES = {}


def _lazy_import(name):
    module = _LAZY_MODULES.get(name)
    if module is None:
        module = __import__(name)
        _LAZY_MODULES[name] = module
    return module


def _numpy():
    return _lazy_import("numpy")


def _onnxruntime():
    return _lazy_import("onnxruntime")


class LocalEmbeddingUnavailable(RuntimeError):
    """The optional local component cannot be used (missing runtime/model)."""


class LocalEmbeddingError(RuntimeError):
    """The local component was used with bad input or produced bad output."""


def _positive_int(value, default):
    try:
        number = int(value)
    except Exception:
        return int(default)
    return number if number > 0 else int(default)


def _chinese(char):
    code = ord(char)
    return (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF
            or 0x20000 <= code <= 0x2A6DF or 0x2A700 <= code <= 0x2B73F
            or 0x2B740 <= code <= 0x2B81F or 0x2B820 <= code <= 0x2CEAF
            or 0xF900 <= code <= 0xFAFF or 0x2F800 <= code <= 0x2FA1F)


def _control(char):
    category = unicodedata.category(char)
    return category in ("Cc", "Cf") and char not in ("\t", "\n", "\r")


def _whitespace(char):
    if char in ("\t", "\n", "\r"):
        return True
    return unicodedata.category(char) in ("Zs", "Zl", "Zp")


def _punctuation(char):
    code = ord(char)
    if (33 <= code <= 47 or 58 <= code <= 64 or 91 <= code <= 96
            or 123 <= code <= 126):
        return True
    return unicodedata.category(char).startswith("P")


def _clean_text(text, do_lower_case=True):
    out = []
    for char in str(text or ""):
        code = ord(char)
        if code == 0 or code == 0xFFFD:
            continue
        if _control(char):
            continue
        if _whitespace(char):
            out.append(" ")
            continue
        out.append(char.lower() if do_lower_case else char)
    return "".join(out)


def _basic_tokens(text, do_lower_case=True):
    """BERT BasicTokenizer: lowercase, CJK split, whitespace, punctuation."""
    cleaned = _clean_text(text, do_lower_case)
    padded = []
    for char in cleaned:
        if _chinese(char):
            padded.append(" ")
            padded.append(char)
            padded.append(" ")
        else:
            padded.append(char)
    tokens = []
    for word in "".join(padded).split():
        current = []
        for char in word:
            if _punctuation(char):
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(char)
            else:
                current.append(char)
        if current:
            tokens.append("".join(current))
    return tokens


def _wordpiece(token, vocab):
    if len(token) > MAX_WORD_CHARS:
        return [token]
    chars = list(token)
    pieces = []
    start = 0
    while start < len(chars):
        end = len(chars)
        found = None
        while start < end:
            piece = "".join(chars[start:end])
            if start > 0:
                piece = "##" + piece
            if piece in vocab:
                found = piece
                break
            end -= 1
        if found is None:
            return [token]
        pieces.append(found)
        start = end
    return pieces


class _VocabTokenizer:
    """Minimal BERT WordPiece tokenizer over tokenizer.json / vocab.txt.

    tokenizer.json (the fast-tokenizer export) is authoritative and is tried
    first; vocab.txt is only a fallback for components that ship just the
    classic file. Stdlib only.
    """

    def __init__(self, vocab_path, do_lower_case=True):
        path = Path(vocab_path)
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(
                    path.read_text(encoding="utf-8", errors="replace"))
                vocab = payload.get("model", {}).get("vocab")
                if not isinstance(vocab, dict):
                    raise ValueError("tokenizer.json has no model.vocab")
                self.vocab = {}
                for token, index in vocab.items():
                    try:
                        self.vocab[str(token)] = int(index)
                    except (TypeError, ValueError):
                        continue
            else:
                lines = path.read_text(
                    encoding="utf-8", errors="replace").splitlines()
                self.vocab = {}
                for index, line in enumerate(lines):
                    token = line[:-1] if line.endswith("\r") else line
                    if token and token not in self.vocab:
                        self.vocab[token] = index
        except OSError as exc:
            raise LocalEmbeddingUnavailable(
                "cannot read tokenizer vocab: %s (%s)" % (path, exc)) from exc
        except ValueError as exc:
            raise LocalEmbeddingUnavailable(
                "invalid tokenizer vocab %s (%s)" % (path, exc)) from exc
        missing = [token for token in SPECIAL_TOKENS if token not in self.vocab]
        if missing:
            raise LocalEmbeddingUnavailable(
                "tokenizer vocab is missing special tokens: %s"
                % ", ".join(missing))
        self.do_lower_case = bool(do_lower_case)
        self.pad_id = self.vocab["[PAD]"]
        self.unk_id = self.vocab["[UNK]"]
        self.cls_id = self.vocab["[CLS]"]
        self.sep_id = self.vocab["[SEP]"]

    def encode(self, text, max_length=DEFAULT_MAX_LENGTH):
        limit = max(8, _positive_int(max_length, DEFAULT_MAX_LENGTH))
        pieces = []
        for token in _basic_tokens(text, self.do_lower_case):
            pieces.extend(_wordpiece(token, self.vocab))
            if len(pieces) >= limit - 2:
                break
        pieces = pieces[:limit - 2]
        ids = [self.cls_id]
        ids.extend(self.vocab.get(piece, self.unk_id) for piece in pieces)
        ids.append(self.sep_id)
        return ids, [1] * len(ids)

    def encode_batch(self, texts, max_length=DEFAULT_MAX_LENGTH):
        pairs = [self.encode(text, max_length) for text in texts]
        width = max([len(ids) for ids, _ in pairs] or [2])
        ids_rows = []
        mask_rows = []
        for ids, mask in pairs:
            padding = width - len(ids)
            ids_rows.append(ids + [self.pad_id] * padding)
            mask_rows.append(mask + [0] * padding)
        return ids_rows, mask_rows


def _as_texts(texts):
    if texts is None:
        return []
    if isinstance(texts, str):
        texts = [texts]
    if not isinstance(texts, (list, tuple)):
        raise LocalEmbeddingError(
            "texts must be a string or a list of strings")
    rows = []
    for item in texts:
        if item is None:
            rows.append("")
        elif isinstance(item, (dict, list, tuple, set)):
            raise LocalEmbeddingError("text items must be strings")
        else:
            rows.append(str(item))
    return rows


def _normalize(values):
    norm = 0.0
    for value in values:
        norm += value * value
    norm = norm ** 0.5
    if norm <= 1e-12:
        return [0.0] * len(values)
    return [value / norm for value in values]


class LocalEmbedder:
    """Lazy CPU-only int8 ONNX embedder. One instance may be shared."""

    def __init__(self, model_path, dim=DEFAULT_DIM, tokenizer_path=None,
                 max_length=DEFAULT_MAX_LENGTH, threads=DEFAULT_THREADS):
        self.model_path = str(model_path or "").strip()
        self.dim = _positive_int(dim, DEFAULT_DIM)
        self.max_length = _positive_int(max_length, DEFAULT_MAX_LENGTH)
        self.threads = max(1, min(MAX_THREADS,
                                  _positive_int(threads, DEFAULT_THREADS)))
        self.tokenizer_path = str(tokenizer_path or "").strip()
        self._session = None
        self._tokenizer = None
        self._output_name = "embedding"
        self._load_error = None
        self._lock = threading.Lock()

    # -- status -------------------------------------------------------
    def status(self):
        """ok | missing | failed (health string for /health)."""
        if self._session is not None:
            return "ok"
        if self._load_error is not None:
            return "failed"
        if not self.model_path:
            return "missing"
        try:
            self._model_file()
        except LocalEmbeddingUnavailable:
            return "failed"
        return "missing"

    def health(self):
        return {"local_embedding": self.status(),
                "model_path": self.model_path,
                "dim": self.dim,
                "threads": self.threads,
                "load_error": str(self._load_error or "")[:200]}

    # -- load ---------------------------------------------------------
    def _model_file(self):
        if not self.model_path:
            raise LocalEmbeddingUnavailable(
                "embedding_local_model_path is empty")
        path = Path(self.model_path)
        if path.is_dir():
            path = path / "model.onnx"
        if not path.is_file():
            raise LocalEmbeddingUnavailable(
                "local embedding model not found: %s" % path)
        return path

    def _vocab_file(self, model_file):
        candidates = []

        def add(path):
            path = Path(path)
            if path.suffix.lower() in (".json", ".txt"):
                candidates.append(path)
                return
            candidates.append(path / "tokenizer.json")
            candidates.append(path / "vocab.txt")

        if self.tokenizer_path:
            add(self.tokenizer_path)
        env_path = os.environ.get(ENV_TOKENIZER, "").strip()
        if env_path:
            add(env_path)
        add(model_file.parent)
        add(model_file.parent / "tokenizer")
        parent = model_file.parent.parent
        if str(parent) != ".":
            add(parent / "bge-small-zh")
            add(parent / "bge-small-zh" / "tokenizer")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise LocalEmbeddingUnavailable(
            "tokenizer (tokenizer.json or vocab.txt) not found for the local "
            "embedding model; set embedding_local_tokenizer_path")

    def load(self):
        """Load onnxruntime + tokenizer once; raises LocalEmbeddingUnavailable."""
        with self._lock:
            if self._session is not None:
                return self
            if self._load_error is not None:
                raise self._load_error
            model_file = self._model_file()
            vocab_file = self._vocab_file(model_file)
            tokenizer = _VocabTokenizer(vocab_file)
            try:
                ort = _onnxruntime()
            except Exception as exc:
                error = LocalEmbeddingUnavailable(
                    "onnxruntime is not installed; local embedding fallback "
                    "is unavailable (%s)" % exc)
                self._load_error = error
                raise error
            try:
                options = ort.SessionOptions()
                options.intra_op_num_threads = self.threads
                options.inter_op_num_threads = 1
                options.graph_optimization_level = (
                    ort.GraphOptimizationLevel.ORT_ENABLE_ALL)
                options.log_severity_level = 3
                session = ort.InferenceSession(
                    str(model_file), sess_options=options,
                    providers=["CPUExecutionProvider"])
            except Exception as exc:
                error = LocalEmbeddingUnavailable(
                    "failed to load local embedding model %s (%s)"
                    % (model_file, exc))
                self._load_error = error
                raise error
            try:
                names = [item.name for item in session.get_outputs()]
            except Exception:
                names = []
            if "embedding" in names or not names:
                self._output_name = "embedding"
            else:
                self._output_name = names[0]
            self._session = session
            self._tokenizer = tokenizer
            return self

    # -- inference ----------------------------------------------------
    def encode(self, texts):
        """Encode a string or a list of strings into L2-normalized vectors."""
        rows = _as_texts(texts)
        if not rows:
            return []
        self.load()
        ids, mask = self._tokenizer.encode_batch(rows, self.max_length)
        try:
            np = _numpy()
        except Exception as exc:
            raise LocalEmbeddingError(
                "numpy is required for onnxruntime inputs (%s)" % exc)
        feeds = {"input_ids": np.asarray(ids, dtype=np.int64),
                 "attention_mask": np.asarray(mask, dtype=np.int64)}
        try:
            raw = self._session.run([self._output_name], feeds)[0]
        except Exception as exc:
            raise LocalEmbeddingError(
                "local embedding inference failed (%s)" % exc)
        output_rows = raw.tolist() if hasattr(raw, "tolist") else list(raw)
        vectors = []
        for row in output_rows:
            try:
                values = [float(item) for item in row]
            except Exception as exc:
                raise LocalEmbeddingError(
                    "local embedding produced a non-numeric row (%s)" % exc)
            if len(values) != self.dim:
                raise LocalEmbeddingError(
                    "dimension mismatch: expected %d, got %d"
                    % (self.dim, len(values)))
            vectors.append(_normalize(values))
        return vectors

    def warmup(self):
        """Force load + one inference so startup can prove health."""
        self.encode(["warmup"])
        return self


def create_local_embedder(model_path=None, dim=DEFAULT_DIM, tokenizer_path=None,
                          threads=DEFAULT_THREADS, max_length=DEFAULT_MAX_LENGTH):
    """Build an embedder without loading it (caller decides when to load)."""
    return LocalEmbedder(model_path=model_path, dim=dim,
                         tokenizer_path=tokenizer_path, threads=threads,
                         max_length=max_length)
