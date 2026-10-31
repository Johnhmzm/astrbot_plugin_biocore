# -*- coding: utf-8 -*-
"""EXP-4: expression guard (L3). Pure; never writes state."""
from __future__ import annotations

BLOCK = ("不要编造未发生的事；不要复述数值或字段名；"
         "不要用内疚绑架（如「你不理我我就…」）；不要提到系统、模型、触发、限制或权限。")
FORBIDDEN = (
    "系统", "模型", "触发", "限制", "权限",
    "你不理我我就", "我这么难受你也不管",
    "valence", "arousal", "strength=", "字段名",
)


def guard_block():
    return BLOCK


def assert_clean(text):
    """Return (ok, reason); used by tests to detect forbidden phrasing."""
    body = str(text or "")
    for token in FORBIDDEN:
        if token in body:
            return False, "forbidden: " + token
    return True, ""
