# -*- coding: utf-8 -*-
"""Media attachment/scrubbing helpers (pure derived text; no binaries).

MEDIA is only an opaque ref plus derived caption/checksum. Module is disabled by
default; callers MUST check `enabled` before wiring it.
"""
from __future__ import annotations

import hashlib
import re

from ..event.media import (FILE_CAPTION_MAX, IMAGE_CAPTION_MAX, MEDIA_KINDS,
                           sensitive_caption)
from ..index.entities import cues

enabled = False
MEDIA_STORE_ENABLED = enabled

REF_MAX = 128
CHECKSUM_HEX = 16
_URL_OR_PATH = re.compile(r"^(?:https?|file|data|ftp):|^[A-Za-z]:[\\/]|^[\\/]")


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _kind(value) -> str:
    kind = str(value or "image").strip().lower()
    return kind if kind in MEDIA_KINDS else "image"


def _limit(kind: str) -> int:
    if kind == "file":
        return FILE_CAPTION_MAX
    return IMAGE_CAPTION_MAX


def _sha16(ref, caption) -> str:
    raw = (str(ref or "") + str(caption or "")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:CHECKSUM_HEX]


def _opaque_ref(ref) -> str:
    """Keep only an opaque id; drop URLs/local paths (never store an address)."""
    value = _clean(ref)[:REF_MAX]
    if not value:
        return ""
    if _URL_OR_PATH.search(value) or ".." in value:
        return ""
    return value


def _media_of(entry):
    if isinstance(entry, dict):
        media = entry.get("media")
        return media if isinstance(media, dict) else {}
    return {}


def attach(entry, media=None) -> dict:
    """Return a copy of entry with a bounded/scrubbed media dict attached."""
    base = dict(entry) if isinstance(entry, dict) else {}
    raw = media if isinstance(media, dict) else _media_of(base)
    if not raw:
        return base
    kind = _kind(raw.get("kind"))
    ref_raw = _clean(raw.get("ref"))[:REF_MAX]
    ref = _opaque_ref(ref_raw)
    caption_raw = _clean(raw.get("caption") or raw.get("text"))
    # checksum is the deterministic sha256(ref+caption)[:16] for the stored row
    checksum = (_sha16(ref_raw, caption_raw) if (ref_raw or caption_raw)
                else _clean(raw.get("checksum"))[:64])
    redacted = bool(raw.get("redacted")) or sensitive_caption(caption_raw)
    caption = "" if redacted else caption_raw[:_limit(kind)]
    out = {"kind": kind, "ref": ref, "caption": caption, "checksum": checksum}
    if redacted:
        out["redacted"] = True
    if ref_raw and not ref:
        out["ref_omitted"] = True
    base["media"] = out
    return base


def scrub(entry) -> dict:
    """Redact a sensitive caption in place (returned copy); ref/kind preserved."""
    base = dict(entry) if isinstance(entry, dict) else {}
    media = _media_of(base)
    if not media:
        return base
    caption = _clean(media.get("caption") or "")
    if bool(media.get("redacted")) or sensitive_caption(caption):
        out = dict(media)
        out["caption"] = ""
        out["redacted"] = True
        base["media"] = out
    return base


def remove_media(entry) -> dict:
    """Remove derived media text/ref but keep a tombstone marker (no hard delete)."""
    base = dict(entry) if isinstance(entry, dict) else {}
    media = _media_of(base)
    if not media:
        return base
    kind = _kind(media.get("kind"))
    base["media"] = {"kind": kind, "ref": "", "caption": "",
                     "checksum": "", "removed": True}
    base["media_removed"] = True
    text = _clean(base.get("text") or "")
    if text.startswith(("图片：", "语音：", "文件：", "（一张", "（一段", "（一份")):
        base["text"] = "（媒体记忆已删除）"
    return base


def media_cues(caption_or_entry, ref_ts=None) -> dict:
    """Extract deterministic entities/place/time from a media caption.

    ref_ts anchors relative time words; when absent, epoch 0 is used so the same
    caption always yields the same time_coarse (no wall-clock dependency).
    """
    anchor = ref_ts
    if isinstance(caption_or_entry, dict):
        media = _media_of(caption_or_entry)
        text = _clean(media.get("caption") or "")
        if anchor is None:
            anchor = caption_or_entry.get("ts")
    else:
        text = _clean(caption_or_entry)
    if not text:
        return {"entities": [], "place": [], "time_coarse": ""}
    try:
        anchor = float(anchor if anchor is not None else 0.0)
    except Exception:
        anchor = 0.0
    if anchor <= 0:
        anchor = 1.0  # cues() treats 0 as "now"; 1.0 is a deterministic epoch
    c = cues(text, ref_ts=anchor)
    return {"entities": list(c.get("entities") or []),
            "place": list(c.get("place") or []),
            "time_coarse": str(c.get("time_coarse") or "")}


__all__ = ["enabled", "MEDIA_STORE_ENABLED", "attach", "scrub", "remove_media",
           "media_cues", "CHECKSUM_HEX"]
