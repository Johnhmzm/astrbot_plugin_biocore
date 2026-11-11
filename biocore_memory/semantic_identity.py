# -*- coding: utf-8 -*-
"""逻辑身份与物理身份分离。

物理身份（storage id）是 SQLite 主键：重排、重新导入、换库都会变。
逻辑身份（semantic id）只由内容决定：同一句话在同一会话里永远是同一个身份。

两者不许互相推导——从 storage id 推不出语义，从语义也推不出主键。
用处：去重、跨库合并、以及「这条记忆是不是我认识的那条」。
"""
from __future__ import annotations

import hashlib
import re

_SPACE = re.compile(r"\s+")


def normalize(text) -> str:
    return _SPACE.sub(" ", str(text or "").strip())


def semantic_id(session_id, ts, role, text) -> str:
    """内容决定的身份：会话 + 时间 + 角色 + 归一化文本。"""
    try:
        stamp = "%.1f" % float(ts or 0.0)
    except Exception:
        stamp = "0.0"
    body = "%s|%s|%s|%s" % (str(session_id or ""), stamp,
                              str(role or "").strip().lower(), normalize(text))
    return "S" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:15]


def storage_id_of(row) -> str:
    """物理身份只在存储层有意义；缺了就是空串，不要拿语义去凑。"""
    return str((row or {}).get("id") or "") if isinstance(row, dict) else ""


def identity_of(session_id, row) -> dict:
    if not isinstance(row, dict):
        return {"storage_id": "", "semantic_id": ""}
    return {
        "storage_id": storage_id_of(row),
        "semantic_id": semantic_id(session_id, row.get("ts"), row.get("role"),
                                     row.get("text")),
    }


def same_memory(session_id, a, b) -> bool:
    """两条记录是不是同一条记忆（看内容，不看主键）。"""
    return (identity_of(session_id, a)["semantic_id"]
            == identity_of(session_id, b)["semantic_id"])
