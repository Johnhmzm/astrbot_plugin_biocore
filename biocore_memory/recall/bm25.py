# -*- coding: utf-8 -*-
"""Lightweight BM25 scoring (default OFF; stdlib only, single-document mode).

tokenize() splits text into Unicode blocks: Chinese -> bigrams, Japanese
kana -> bigrams, Korean Hangul -> bigrams, Latin/digits -> lowercase words.
tokenize_multi() adds mixed-script/digit sub-tokens and full kana/Hangul runs.
score() keeps its original BM25 math/output; score_multi() uses tokenize_multi.
"""
from __future__ import annotations

import math
import re

enabled = False
ENABLED = False
K1 = 1.2
B = 0.75
AVG_DOC_LEN = 64.0

# Unicode blocks, ordered: CJK, Hiragana, Katakana, Hangul, Latin/digits.
_BLOCK = re.compile(
    r"[\u4e00-\u9fff]+"
    r"|[\u3040-\u309f]+"
    r"|[\u30a0-\u30ff\u31f0-\u31ff]+"
    r"|[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]+"
    r"|[a-z0-9_]+")
_LATIN_WORD = re.compile(r"[a-z]+")
_DIGITS = re.compile(r"\d+")
# Single-document corpus: N=1, df=1 for a present term -> idf > 0.
_IDF = math.log(1.0 + 0.5 / 1.5)


def _bigrams(run):
    if len(run) <= 1:
        return [run]
    return [run[i:i + 2] for i in range(len(run) - 1)]


def _is_cjk(block):
    return "\u4e00" <= block[0] <= "\u9fff"


def _is_kana(block):
    code = ord(block[0])
    return (0x3040 <= code <= 0x309f) or (0x30a0 <= code <= 0x30ff
                                           or 0x31f0 <= code <= 0x31ff)


def _is_hangul(block):
    code = ord(block[0])
    return (0xac00 <= code <= 0xd7af) or (0x1100 <= code <= 0x11ff
                                          or 0x3130 <= code <= 0x318f)


def tokenize(text):
    """Unicode-block tokens: CJK/kana/Hangul bigrams + lowercase Latin/digits."""
    out = []
    for match in _BLOCK.finditer(str(text or "").lower()):
        block = match.group()
        if _is_cjk(block) or _is_kana(block) or _is_hangul(block):
            out.extend(_bigrams(block))
        else:
            out.append(block)
    return out


def tokenize_multi(text):
    """tokenize() plus mixed-script extras (numbers and full kana/Hangul runs)."""
    source = str(text or "").lower()
    out = tokenize(source)
    for match in _BLOCK.finditer(source):
        block = match.group()
        if _is_hangul(block) and len(block) > 1:
            out.append(block)
        elif _is_kana(block) and len(block) > 2:
            out.append(block)
        elif re.fullmatch(r"[a-z0-9_]+", block) and _DIGITS.search(block):
            words = _LATIN_WORD.findall(block)
            digits = _DIGITS.findall(block)
            if words and digits:
                out.extend(words)
                out.extend(digits)
    return out


def _bm25(q_terms, doc, k1, b, avgdl):
    if not q_terms or not doc:
        return 0.0
    try:
        k1 = max(0.0, float(k1))
        b = max(0.0, min(1.0, float(b)))
        avgdl = max(1.0, float(avgdl))
    except Exception:
        k1, b, avgdl = K1, B, AVG_DOC_LEN
    freq = {}
    for term in doc:
        freq[term] = freq.get(term, 0) + 1
    dl = max(1, len(doc))
    total = 0.0
    for term in sorted(q_terms):
        tf = freq.get(term, 0)
        if tf:
            denom = tf + k1 * (1.0 - b + b * dl / avgdl)
            total += _IDF * (tf * (k1 + 1.0)) / denom
    normalizer = _IDF * (k1 + 1.0)
    if normalizer <= 0:
        return 0.0
    return round(max(0.0, min(1.0, total / normalizer)), 6)


def score(query, text, k1=K1, b=B, avgdl=AVG_DOC_LEN):
    """Normalized BM25 score in [0, 1] (original behavior, unchanged math)."""
    return _bm25(set(tokenize(query)), tokenize(text), k1, b, avgdl)


def score_multi(query, text, k1=K1, b=B, avgdl=AVG_DOC_LEN):
    """BM25 over tokenize_multi(): same math, mixed-script token coverage."""
    return _bm25(set(tokenize_multi(query)), tokenize_multi(text), k1, b, avgdl)
