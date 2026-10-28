# -*- coding: utf-8 -*-
"""Multimodal text-derived events (pure; no binaries, no AstrBot).

Only derived text is represented: image caption / audio transcript / file summary.
Raw bytes, EXIF, paths and provider payloads are never stored here.
"""
from __future__ import annotations

import re

enabled = False
MEDIA_ENABLED = enabled

MEDIA_KINDS = ("image", "audio", "file")
IMAGE_CAPTION_MAX = 120
AUDIO_CAPTION_MAX = 120
FILE_CAPTION_MAX = 200
REF_MAX = 128
CHECKSUM_MAX = 64

_SENSITIVE_WORDS = (
    "身份证", "证件", "护照", "银行卡", "手机号", "电话", "住址", "地址",
    "家庭地址", "医院", "病历", "诊断", "处方", "抑郁", "自杀", "自伤",
    "密码", "裸", "私密", "床照", "开房", "工资", "社保号",
)
_PHONE = re.compile(r"(?<!\d)1\d{10}(?!\d)")
_ID18 = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{16,19}(?!\d)")


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _kind(value) -> str:
    kind = str(value or "image").strip().lower()
    return kind if kind in MEDIA_KINDS else "image"


def _limit(kind: str) -> int:
    if kind == "file":
        return FILE_CAPTION_MAX
    return IMAGE_CAPTION_MAX if kind == "image" else AUDIO_CAPTION_MAX


def _prefix(kind: str) -> str:
    return {"image": "图片：", "audio": "语音：", "file": "文件："}.get(kind, "图片：")


def _placeholder(kind: str, sensitive: bool = False) -> str:
    if sensitive:
        return {"image": "（一张敏感图片）", "audio": "（一段敏感语音）",
                "file": "（一份敏感文件）"}.get(kind, "（一条敏感媒体）")
    return {"image": "（一张图片）", "audio": "（一段语音）",
            "file": "（一个文件）"}.get(kind, "（一条媒体）")


def sensitive_caption(caption) -> bool:
    """Conservative deterministic guess: IDs/phones/long digits/privacy words."""
    text = _clean(caption)
    if not text:
        return False
    if _PHONE.search(text) or _ID18.search(text) or _LONG_DIGITS.search(text):
        return True
    return any(word in text for word in _SENSITIVE_WORDS)


def _build(kind: str, caption, ref="", checksum="") -> dict:
    kind = _kind(kind)
    raw = _clean(caption)
    limit = _limit(kind)
    redacted = bool(raw and sensitive_caption(raw))
    if redacted:
        text = _placeholder(kind, sensitive=True)
        stored_caption = ""
    elif raw:
        text = (_prefix(kind) + raw[:limit]).strip()
        stored_caption = raw[:limit]
    else:
        text = _placeholder(kind)
        stored_caption = ""
    media = {"kind": kind,
             "ref": _clean(ref)[:REF_MAX],
             "caption": stored_caption,
             "checksum": _clean(checksum)[:CHECKSUM_MAX]}
    if redacted:
        media["redacted"] = True
    metadata = {"media_kind": kind}
    if redacted:
        metadata["media_redacted"] = True
    return {"text": text, "media": media, "metadata": metadata}


def from_caption(caption, kind="image", ref="", checksum="") -> dict:
    """Build a text-derived image event (caption is never raw pixel data)."""
    return _build(kind, caption, ref=ref, checksum=checksum)


def from_transcript(transcript, ref="", checksum="") -> dict:
    """Build a text-derived audio event from an ASR transcript."""
    return _build("audio", transcript, ref=ref, checksum=checksum)


def from_file(summary, ref="", checksum="") -> dict:
    """Build a text-derived file event from a summary/key fields."""
    return _build("file", summary, ref=ref, checksum=checksum)


__all__ = ["enabled", "MEDIA_ENABLED", "MEDIA_KINDS", "sensitive_caption",
           "from_caption", "from_transcript", "from_file",
           "IMAGE_CAPTION_MAX", "AUDIO_CAPTION_MAX", "FILE_CAPTION_MAX"]
