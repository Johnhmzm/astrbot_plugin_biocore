# -*- coding: utf-8 -*-
"""模型看到的时间。

轮号是我们内部的坐标，不是她的经验。她不该知道「第 183 轮」这种事——
人记事用的是「上周三下午」「前天晚上」。所以写给模型看的一律是绝对时间，
轮号只留在排序与去重里。
"""
from __future__ import annotations

import time as _time


def has_time(ts) -> bool:
    try:
        return float(ts or 0.0) > 0
    except Exception:
        return False


def at(ts, seconds=False) -> str:
    """2026-11-07 14:32 ／ 带秒时 2026-11-07 14:32:05。"""
    try:
        value = float(ts or 0.0)
    except Exception:
        return ''
    if value <= 0:
        return ''
    fmt = '%Y-%m-%d %H:%M:%S' if seconds else '%Y-%m-%d %H:%M'
    try:
        return _time.strftime(fmt, _time.localtime(value))
    except Exception:
        return ''


def day(ts) -> str:
    """只要日期：2026-11-07。"""
    try:
        return _time.strftime('%Y-%m-%d', _time.localtime(float(ts or 0.0)))
    except Exception:
        return ''


def label(ts, turn=None) -> str:
    """给模型看的时间标签；没有时间可用时退回轮号（这是最后的退路）。"""
    stamp = at(ts)
    if stamp:
        return stamp
    try:
        n = int(turn or 0)
    except Exception:
        n = 0
    return '第%d轮' % n if n > 0 else '时间未知'


def span(ts_list, seconds=False) -> str:
    """一段时间的写法：同一天只写一次日期。"""
    stamps = sorted(float(t) for t in (ts_list or []) if has_time(t))
    if not stamps:
        return ''
    first, last = stamps[0], stamps[-1]
    if day(first) == day(last):
        a = at(first, seconds)
        b = _time.strftime('%H:%M:%S' if seconds else '%H:%M', _time.localtime(last))
        return a if a == b else '%s ~ %s' % (a, b)
    return '%s ~ %s' % (at(first, seconds), at(last, seconds))
