# -*- coding: utf-8 -*-
"""模型看到的是时间，不是轮号。"""
from biocore_memory import timefmt as T
from biocore_memory.event import keynorm as K


def test_label_prefers_time_over_turn():
    assert T.label(1794000000.0, 183).startswith("2026-")
    assert "轮" not in T.label(1794000000.0, 183)


def test_label_falls_back_to_turn_when_time_is_missing():
    assert T.label(0.0, 183) == "第183轮"


def test_span_collapses_the_day_when_it_is_the_same():
    span = T.span([1794000000.0, 1794005000.0])
    assert span.count("2026-") == 1, "同一天只写一次日期"
    assert "~" in span


def test_state_line_uses_the_given_clock():
    item = {"values": [{"value": "浅灰色", "turn": 183, "ts": 0},
                       {"value": "米色", "turn": 317, "ts": 0}]}
    line = K.state_line("客厅地板·颜色", item,
                        turn_dates={183: "2026-09-14 20:03", 317: "2026-10-02 09:11"})
    assert "2026-09-14 20:03" in line and "2026-10-02 09:11" in line
    assert "第183轮" not in line


def test_seconds_are_available_when_asked():
    assert len(T.at(1794000000.0, seconds=True)) == len("2026-11-07 05:20:00")
