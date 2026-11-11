# -*- coding: utf-8 -*-
"""副作用回执：每个下游动作是否真的发生了。

turn_end 里有三段副作用：判分、写 turn_log（含学习）、写 learn_log。
任何一段失败都是静默的——日志里看不出来，数据就悄悄少了一截。
这里给每一段留一张回执：kind + fingerprint（这一轮的指纹）+ ts。
下一轮开始时可以按回执判断「上一轮少做了什么」。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Dict, Optional

RECEIPT_FILE = "receipts.json"
KINDS = ("grade", "turn_log", "learn_log")


def _path(store, session_id: str) -> str:
    return os.path.join(str(store), "sessions", str(session_id), RECEIPT_FILE)


def fingerprint(session_id: str, user_text: str, assistant_text: str = "") -> str:
    raw = "%s|%s|%s" % (session_id, str(user_text or "")[:200], str(assistant_text or "")[:200])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _load(store, session_id: str) -> Dict[str, object]:
    try:
        with open(_path(store, session_id), "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def record(store, session_id: str, kind: str, fp: str) -> bool:
    if kind not in KINDS:
        return False
    doc = _load(store, session_id)
    doc[kind] = {"fp": fp, "ts": round(time.time(), 1)}
    try:
        path = _path(store, session_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def missing_kinds(store, session_id: str) -> list:
    doc = _load(store, session_id)
    last = str((doc.get("turn_log") or {}).get("fp") or "")
    if not last:
        return []
    out = []
    for kind in KINDS:
        got = str((doc.get(kind) or {}).get("fp") or "")
        if got != last:
            out.append(kind)
    return out
