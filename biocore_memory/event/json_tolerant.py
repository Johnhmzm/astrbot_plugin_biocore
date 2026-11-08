# -*- coding: utf-8 -*-
"""One tolerant JSON reader for every model answer in the event layer.

Models fence their JSON, wrap it in prose, and leave trailing commas. All three
were separate failure modes in three places (claims, note, compaction); this is
the single implementation they share.
"""
from __future__ import annotations

import json

FENCE = "```"


class ParseError(ValueError):
    """The text could not be read as JSON after every repair attempt."""


def strip_fence(text):
    body = str(text or "").strip()
    if body.startswith(FENCE):
        body = body.split(chr(10), 1)[-1] if chr(10) in body else body
        if body.rstrip().endswith(FENCE):
            body = body.rstrip()[:-3]
    return body.strip(chr(96)).strip()


def cut_json(body, prefer="{"):
    """First opening bracket to the last matching close, prose dropped."""
    order = (("{", "}"), ("[", "]")) if prefer == "{" else (("[", "]"), ("{", "}"))
    for left, right in order:
        start, end = body.find(left), body.rfind(right)
        if 0 <= start < end:
            return body[start:end + 1]
    return ""


def drop_trailing_commas(body):
    out = []
    index, length = 0, len(body)
    while index < length:
        ch = body[index]
        if ch == ",":
            look = index + 1
            while look < length and body[look] in " \t\r\n":
                look += 1
            if look < length and body[look] in "]}":
                index += 1
                continue
        out.append(ch)
        index += 1
    return "".join(out)


def loads(text, prefer="{"):
    """Parsed JSON, with the three repairs applied in order. Raises ParseError."""
    body = strip_fence(text)
    candidates = []
    if body:
        candidates.append(body)
    cut = cut_json(body, prefer=prefer)
    if cut and cut != body:
        candidates.append(cut)
    for candidate in list(candidates):
        fixed = drop_trailing_commas(candidate)
        if fixed != candidate:
            candidates.append(fixed)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    raise ParseError("unparseable model answer: %r" % str(text or "")[:120])
