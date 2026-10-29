# -*- coding: utf-8 -*-
"""BioCore model layer: final reply presentation guard (stdlib-only).

Architecture follows the popular plugin pattern: one presentation-boundary
sanitizer with declarative pattern lists, protected literal ranges (URLs /
media tags / code blocks), idempotent cleaning, fixed empty/traceback
fallbacks and per-rule counters. It never returns the raw unsanitized text.
"""
from __future__ import annotations

import json
import re

FALLBACK_EMPTY = "（这条回复没有正常生成，已跳过。）"
FALLBACK_ERROR = "（这条回复没有正常生成，按安全策略不予展示。）"

_BARE_KEYS = ('e', 'emotion', 'i', 'intensity', 'n', 'need', 'x', 'expression')
_BARE_KEY_RE = re.compile(r"(?:^|[{,]\s*)['\"]?(?:%s)['\"]?\s*:" % '|'.join(_BARE_KEYS))


class ReplySanitizer:
    """Declarative, idempotent output guard (one presentation boundary)."""

    CONTROL_TAG_PATTERNS = [
        re.compile(r"<\s*(?:bc|biocore)\b[^>]*>.*?</\s*(?:bc|biocore)\s*>", re.I | re.S),
        re.compile(r"<\s*(?:bc|biocore)\b[^>]*>[^\n]*", re.I),
        re.compile(r"<\s*(?:thinking|think|thought|reasoning|analysis)\b[^>]*>.*?</\s*(?:thinking|think|thought|reasoning|analysis)\s*>", re.I | re.S),
        re.compile(r"<\s*(?:thinking|think|thought|reasoning|analysis)\b[^>]*>[^\n]*", re.I),
        re.compile(r"<\s*(?:思考|分析|推理|内心独白)\s*>.*?</\s*(?:思考|分析|推理|内心独白)\s*>", re.S),
        re.compile(r"<\s*(?:思考|分析|推理|内心独白)\s*>[^\n]*", re.S),
    ]
    PREFIX_PATTERNS = [
        re.compile(r"^\s*(?:情绪|状态|JSON|输出|标签|回答|结论)\s*[：:]\s*", re.I | re.M),
    ]
    FENCE_RE = re.compile(r"`{3}([A-Za-z0-9_-]*)\s*\n?(.*?)`{3}", re.S)
    DOUBLE_TAG_RE = re.compile(r"\[\[[^\]]*\]\]")
    URL_RE = re.compile(r"https?://[^\s<>]+")
    MEDIA_RE = re.compile(r"<\s*(?:image|voice|video|audio|file)\b[^>]*>.*?</\s*(?:image|voice|video|audio|file)\s*>", re.I | re.S)
    ZW_RE = re.compile("[\u200b\u200c\u200d\ufeff\u2060]")
    TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\)|File \"[^\"]+\", line \d+")
    EDGE_PUNCT = '：:，,、；; \t\r\n'

    def __init__(self):
        self.stats = {k: 0 for k in ('tag_stripped', 'json_stripped',
                                     'fenced_stripped', 'empty_fallback',
                                     'traceback_guard', 'repair_ok')}

    # -- protected literals -------------------------------------------------
    def _protect(self, text):
        store = []
        def _mask(match):
            store.append(match.group(0))
            return '\x00P%d\x00' % (len(store) - 1)

        value = self.URL_RE.sub(_mask, text)
        value = self.MEDIA_RE.sub(_mask, value)
        # protect non-json fenced code blocks (content only; fences removed later)
        def _code(match):
            lang = (match.group(1) or '').lower()
            if lang == 'json':
                return match.group(0)
            store.append(match.group(2))
            return '`{3}' + match.group(1) + '\n\x00P%d\x00\n`{3}' % (len(store) - 1)
        value = self.FENCE_RE.sub(_code, value)
        return value, store

    @staticmethod
    def _restore(text, store):
        for i, original in enumerate(store):
            text = text.replace('\x00P%d\x00' % i, original)
        return text

    # -- protocol stripping -------------------------------------------------
    def _strip_protocol(self, text):
        # fenced blocks: ```json with label keys -> remove; others -> keep body
        def _fence(match):
            body = match.group(2)
            if _BARE_KEY_RE.search(body):
                candidate = self._payload(body)
                if candidate is not None:
                    self.stats['fenced_stripped'] += 1
                    self.stats['json_stripped'] += 1
                    self._pending_payload = candidate
                    return ' '
                self.stats['fenced_stripped'] += 1
                self._pending_payload = body
                return ' '
            return body
        text = self.FENCE_RE.sub(_fence, text)
        # declarative control tags, in order; debug log only if changed
        for pat in self.CONTROL_TAG_PATTERNS:
            new = pat.sub('', text)
            if new != text:
                self.stats['tag_stripped'] += 1
            text = new
        # line prefixes
        for pat in self.PREFIX_PATTERNS:
            new = pat.sub('', text)
            if new != text:
                self.stats['tag_stripped'] += 1
            text = new
        text = self.DOUBLE_TAG_RE.sub(' ', text)
        return text

    # -- bare JSON ---------------------------------------------------------
    def _payload(self, text):
        raw = str(text or '').strip()
        if not _BARE_KEY_RE.search(raw):
            return None
        try:
            data = json.loads(raw)
        except Exception:
            fixed = re.sub(r",\s*([}\]\])", r"\1", raw)
            fixed = re.sub(r"'([^']*)'", r'"\1"', fixed)
            try:
                data = json.loads(fixed)
                if isinstance(data, dict):
                    self.stats['repair_ok'] += 1
            except Exception:
                return None
        return json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else None

    def _strip_bare_json(self, text):
        keep = []
        def _bare(match):
            candidate = match.group(0)
            parsed = self._payload(candidate)
            if parsed is None and not _BARE_KEY_RE.search(candidate):
                return candidate
            self.stats['json_stripped'] += 1
            if parsed is not None and self._pending_payload is None:
                self._pending_payload = parsed
            return ' '
        return re.sub(r'\{[^{}]*\}', _bare, text)

    # -- public API ---------------------------------------------------------
    def extract(self, text):
        """Return (visible_text, payload_json|None), removing protocol blocks."""
        self._pending_payload = None
        value = self.ZW_RE.sub('', str(text or ''))
        # capture <bc>/<biocore> payloads before the declarative tag stripper
        for m in re.finditer(r"<\s*(?:bc|biocore)\b[^>]*>(.*?)</\s*(?:bc|biocore)\s*>",
                             value, re.I | re.S):
            inner = str(m.group(1) or '').strip()
            if inner.startswith('{') and inner.endswith('}'):
                try:
                    parsed = json.loads(inner)
                    if isinstance(parsed, dict):
                        self._pending_payload = json.dumps(parsed, ensure_ascii=False)
                    else:
                        self._pending_payload = inner
                except Exception:
                    self._pending_payload = inner
        for m in re.finditer(r"<\s*(?:bc|biocore)\b[^>]*>(.*)$", value, re.I | re.S):
            tail = str(m.group(1) or '').strip()
            if tail.startswith('{') and tail.endswith('}'):
                try:
                    parsed = json.loads(tail)
                    if isinstance(parsed, dict):
                        self._pending_payload = json.dumps(parsed, ensure_ascii=False)
                    else:
                        self._pending_payload = tail
                except Exception:
                    self._pending_payload = tail
        value, protected = self._protect(value)
        value = self._strip_protocol(value)
        value = self._strip_bare_json(value)
        value = self._restore(value, protected)
        value = re.sub(r'\s+', ' ', value).strip()
        value = value.strip(self.EDGE_PUNCT).strip()
        return value, self._pending_payload

    def clean(self, text) -> str:
        if self.TRACEBACK_RE.search(str(text or '')):
            self.stats['traceback_guard'] += 1
            return FALLBACK_ERROR
        value, _ = self.extract(text)
        if not value.strip():
            self.stats['empty_fallback'] += 1
            return FALLBACK_EMPTY
        return value

    def reset_stats(self):
        for key in self.stats:
            self.stats[key] = 0


SANITIZER = ReplySanitizer()
STATS = SANITIZER.stats


def clean(text) -> str:
    return SANITIZER.clean(text)


def extract(text):
    return SANITIZER.extract(text)


def reset_stats():
    SANITIZER.reset_stats()
