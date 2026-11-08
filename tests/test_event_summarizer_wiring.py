# -*- coding: utf-8 -*-
"""The event layer only closes events when capture is handed a summariser.

Regression: the real DSH plugin path never passed one, so no event was ever
generated in production while bench builds (which do pass one) had events.
"""
import json
import tempfile
from pathlib import Path

from biocore_runtime import pipeline as P


def _store(tmp):
    root = Path(tmp)
    (root / "flags.json").write_text(json.dumps({"event_layer": True}), encoding="utf-8")
    return str(root)


def _feed(store, summarizer, turns=6):
    for i in range(turns):
        cfg = {"enabled": True, "now": 1777800000 + i * 600, "hourly_cap": 0, "min_chars": 0}
        if summarizer is not None:
            cfg["event_summarizer"] = summarizer
        P.capture("s1", "user", "第%d轮：我明天去苏州，记得带双份奶。" % i, store, config=cfg)


def test_capture_without_summarizer_does_not_raise_and_makes_no_events():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        _feed(store, None)
        assert (P._load_event_state(store, "s1").get("events") or []) == []


def test_capture_hands_the_summarizer_to_the_event_layer():
    """The wiring itself: capture must reach the event layer *with* a summariser."""
    seen = {"summarizer": "unset", "calls": 0}
    original = P._event_layer_block

    def spy(session_id, store, query="", *args, **kwargs):
        seen["summarizer"] = kwargs.get("summarizer")
        seen["calls"] += 1
        return original(session_id, store, query, *args, **kwargs)

    def summarizer(prompt):
        return json.dumps({"overview": "用户在安排苏州出差。", "claims": [],
                           "threads": []}, ensure_ascii=False)

    P._event_layer_block = spy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _feed(_store(tmp), summarizer)
    finally:
        P._event_layer_block = original

    assert seen["calls"] > 0, "capture must touch the event layer"
    assert seen["summarizer"] is summarizer, "the caller's summariser must reach the event layer"
