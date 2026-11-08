# -*- coding: utf-8 -*-
"""The event layer must not depend on the caller remembering a callable.

Production capture is JSON over stdin, so a Python callable cannot travel with
it. The core therefore builds the summariser from core_config.json when the
layer is on; a missing block is an error, not a silent no-op.
"""
import json
import tempfile
from pathlib import Path

from biocore_runtime import pipeline as P


def _store(tmp, summarizer=None):
    root = Path(tmp)
    (root / "flags.json").write_text(json.dumps({"event_layer": True}), encoding="utf-8")
    if summarizer is not None:
        (root / "core_config.json").write_text(
            json.dumps({"summarizer": summarizer}), encoding="utf-8")
    return str(root)


def _feed(store, summarizer, turns=6):
    for i in range(turns):
        cfg = {"enabled": True, "now": 1777800000 + i * 600, "hourly_cap": 0, "min_chars": 0}
        if summarizer is not None:
            cfg["event_summarizer"] = summarizer
        P.capture("s1", "user", "第%d轮：我明天去苏州，记得带双份奶。" % i, store, config=cfg)


def test_the_core_builds_a_summariser_from_config():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp, {"base_url": "http://127.0.0.1:9/v1", "model": "m"})
        fn = P.summarizer_from_config(store)
        assert callable(fn)
        # the same config must not build a second object per capture
        assert P.summarizer_from_config(store) is fn


def test_event_layer_on_without_a_summariser_block_raises():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)          # event_layer on, no summarizer block
        try:
            _feed(store, None, turns=2)
        except RuntimeError as exc:
            assert "summarizer" in str(exc)
        else:
            raise AssertionError("a missing summarizer block must raise")


def test_capture_reaches_the_event_layer_with_a_built_summariser():
    seen = {"summarizer": "unset", "calls": 0}
    original = P._event_layer_block

    def spy(session_id, store, query="", *args, **kwargs):
        seen["summarizer"] = kwargs.get("summarizer")
        seen["calls"] += 1
        return None                  # do not actually run the maintenance

    P._event_layer_block = spy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, {"base_url": "http://127.0.0.1:9/v1", "model": "m"})
            _feed(store, None, turns=3)
    finally:
        P._event_layer_block = original

    assert seen["calls"] > 0, "capture must touch the event layer"
    assert callable(seen["summarizer"]), "the core must build one from config"


def test_the_host_callable_still_wins():
    seen = {}
    original = P._event_layer_block

    def spy(session_id, store, query="", *args, **kwargs):
        seen["summarizer"] = kwargs.get("summarizer")
        return None

    def host_summarizer(prompt):
        return json.dumps({"overview": "x", "claims": [], "threads": []},
                          ensure_ascii=False)

    P._event_layer_block = spy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _feed(_store(tmp, {"base_url": "http://127.0.0.1:9/v1", "model": "m"}),
                  host_summarizer, turns=2)
    finally:
        P._event_layer_block = original
    assert seen["summarizer"] is host_summarizer
