# -*- coding: utf-8 -*-
"""记忆写入的版本戳与写集。

现在的写入是「读-改-写」，两个调用方并发时后写的会静默覆盖先写的。
这里给一个最小契约：

    rev = current_revision(store, sid)
    assert_fresh(store, sid, rev)      别人动过就抛 StaleWrite
    ... 改数据 ...
    bump_revision(store, sid, write_set=...)   提交后 +1

写集只声明「这次动了哪些键」，供冲突文案与日志使用；锁的粒度不在这里实现，先把语义立住。
"""
from __future__ import annotations

import json
import os
from typing import Dict, Iterable, Optional

REVISION_FILE = "memory_revision.json"


class StaleWrite(RuntimeError):
    """写入基线过期：期间有别的写入提交过。"""


def _path(store, session_id: str) -> str:
    return os.path.join(str(store), "sessions", str(session_id), REVISION_FILE)


def _load(store, session_id: str) -> Dict[str, object]:
    try:
        with open(_path(store, session_id), "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def current_revision(store, session_id: str) -> int:
    return int(_load(store, session_id).get("revision") or 0)


def bump_revision(store, session_id: str, write_set: Optional[Iterable[str]] = None) -> int:
    doc = _load(store, session_id)
    rev = int(doc.get("revision") or 0) + 1
    doc["revision"] = rev
    if write_set:
        doc["last_write_set"] = sorted({str(k) for k in write_set})[:50]
    try:
        path = _path(store, session_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass
    return rev


def assert_fresh(store, session_id: str, expected: int) -> None:
    actual = current_revision(store, session_id)
    if int(expected) != actual:
        raise StaleWrite(
            "记忆已被其他写入更新（期望 revision=%s，实际=%s），请重新读取后重试"
            % (expected, actual))


def write_set_of(*keys) -> list:
    return sorted({str(k) for k in keys if k})
