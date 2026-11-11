# -*- coding: utf-8 -*-
"""状态根健康检查：一个会话只该有一套可信的状态。

现在同一会话的状态散在几个文件里：body、clock、prev、norm、theta、receipts。
它们本该互相一致；一旦有人只改了一部分（手工编辑、旧版本残留、并发写），
就会同时存在两个「真」，而下游读到的可能是错的那一个。

这里做三件事：
  1  列出会话的全部状态根（哪个存在、多大、多久没动）
  2  找出互相矛盾的地方（时钟在未来、prev 比 body 新、body 缺失但 norm 在）
  3  能修的修（时钟回拨到当前），不能修的报出来，绝不假装一致
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List

ROOTS = {
    "body": "mindbase_body.json",
    "clock": "mindbase_clock.json",
    "prev": "mindbase_prev.json",
    "norm": "mindbase_norm.json",
    "theta": "theta.json",
    "receipts": "receipts.json",
}


def _dir(store, session_id) -> str:
    return os.path.join(str(store), "sessions", str(session_id))


def inventory(store, session_id, now=None) -> Dict[str, dict]:
    """每个状态根是否存在、大小、上次修改距今多少秒。"""
    now = float(now if now is not None else time.time())
    out = {}
    base = _dir(store, session_id)
    for name, filename in ROOTS.items():
        path = os.path.join(base, filename)
        try:
            stat = os.stat(path)
            out[name] = {"exists": True, "bytes": stat.st_size,
                         "age_s": round(max(0.0, now - stat.st_mtime), 1)}
        except Exception:
            out[name] = {"exists": False, "bytes": 0, "age_s": None}
    return out


def contradictions(store, session_id, now=None) -> List[str]:
    """找出互相矛盾的组合，返回人话描述（空列表表示没发现问题）。"""
    now = float(now if now is not None else time.time())
    inv = inventory(store, session_id, now)
    issues: List[str] = []
    if inv["norm"]["exists"] and not inv["body"]["exists"]:
        issues.append("norm 存在但 body 不在：z 值没有参照物")
    if inv["prev"]["exists"] and not inv["body"]["exists"]:
        issues.append("prev 存在但 body 不在：KL 基线没有落点")
    if inv["clock"]["exists"]:
        try:
            with open(os.path.join(_dir(store, session_id), ROOTS["clock"]),
                      "r", encoding="utf-8") as fh:
                last = float(json.load(fh).get("last") or 0.0)
            if last > now + 60:
                issues.append("时钟在未来（%.0fs）：上次记录比现在还晚" % (last - now))
        except Exception:
            issues.append("时钟文件读不出来")
    if inv["body"]["exists"] and inv["norm"]["exists"]:
        if (inv["norm"]["age_s"] or 0) + 1 < (inv["body"]["age_s"] or 0):
            issues.append("norm 比 body 旧：归一化没有跟上状态")
    return issues


def repair_clock(store, session_id, now=None) -> bool:
    """把跑飞的时钟拉回当前时间。只修这一种，其余只报不修。"""
    now = float(now if now is not None else time.time())
    path = os.path.join(_dir(store, session_id), ROOTS["clock"])
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        last = float(doc.get("last") or 0.0)
        if last <= now + 60:
            return False
        doc["last"] = round(now, 1)
        doc["repaired_at"] = round(now, 1)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        return True
    except Exception:
        return False
