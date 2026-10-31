# -*- coding: utf-8 -*-
import unittest
from biocore_model import pipeline as pl


def stage(name, **kw):
    kw.setdefault("run", lambda ctx: {name: True})
    return pl.Stage(name, **kw)


class PipelineTest(unittest.TestCase):
    def test_order(self):
        order = []
        p = pl.Pipeline([stage("a", run=lambda c: order.append("a") or {}), stage("b", run=lambda c: order.append("b") or {})])
        p.run({})
        self.assertEqual(order, ["a", "b"])
    def test_skip_disabled(self):
        p = pl.Pipeline([stage("a"), stage("b")])
        p.set_enabled("a", False)
        ctx = p.run({})
        self.assertEqual(ctx["trace"]["stages"][0]["status"], "skipped")
    def test_required_cannot_disable(self):
        p = pl.Pipeline([stage("perceive")])
        with self.assertRaises(ValueError):
            p.set_enabled("perceive", False)
    def test_exception_continues(self):
        p = pl.Pipeline([stage("a", run=lambda c: 1 / 0), stage("b")])
        ctx = p.run({})
        self.assertEqual(ctx["trace"]["stages"][0]["status"], "failed")
        self.assertEqual(ctx["trace"]["stages"][1]["status"], "ok")
    def test_required_failure_aborts(self):
        p = pl.Pipeline([stage("think", required=True, run=lambda c: 1 / 0)])
        with self.assertRaises(pl.PipelineAbort):
            p.run({})
    def test_timeout_skipped(self):
        import time
        p = pl.Pipeline([stage("slow", timeout_ms=50, run=lambda c: time.sleep(0.2)), stage("b")])
        ctx = p.run({})
        self.assertEqual(ctx["trace"]["stages"][0]["status"], "timeout")
        self.assertEqual(ctx["trace"]["stages"][1]["status"], "ok")
    def test_required_timeout_aborts(self):
        import time
        p = pl.Pipeline([stage("express", timeout_ms=30, run=lambda c: time.sleep(0.15))])
        with self.assertRaises(pl.PipelineAbort):
            p.run({})
    def test_on_error_abort(self):
        p = pl.Pipeline([stage("a", on_error="abort", run=lambda c: 1 / 0)])
        with self.assertRaises(pl.PipelineAbort):
            p.run({})
    def test_trace_fields(self):
        p = pl.Pipeline([stage("a")])
        ctx = p.run({})
        record = ctx["trace"]["stages"][0]
        for key in ("name", "ms", "status", "note"):
            self.assertIn(key, record)
    def test_ring_limit_50(self):
        p = pl.Pipeline([stage("a")])
        for _ in range(60):
            p.run({})
        self.assertEqual(len(p._ring), 50)
    def test_get_status_fields(self):
        p = pl.Pipeline([stage("a"), stage("b")])
        status = p.get_status()
        row = status["stages"][0]
        for key in ("name", "required", "enabled", "last_status", "last_ms"):
            self.assertIn(key, row)
    def test_get_status_after_run(self):
        p = pl.Pipeline([stage("a")])
        p.run({})
        status = p.get_status()
        self.assertEqual(status["stages"][0]["last_status"], "ok")
        self.assertIn("stages", status["last_trace"])
    def test_each_non_required_disabled_still_valid(self):
        names = ["a", "b", "c"]
        for name in names:
            p = pl.Pipeline([stage(n) for n in names])
            p.set_enabled(name, False)
            ctx = p.run({})
            self.assertIn("trace", ctx)
    def test_unknown_set_enabled(self):
        p = pl.Pipeline([stage("a")])
        with self.assertRaises(KeyError):
            p.set_enabled("nope", False)
    def test_ctx_updated_by_stage(self):
        p = pl.Pipeline([stage("a", run=lambda c: {"value": 7})])
        self.assertEqual(p.run({})["value"], 7)
    def test_ctx_input_preserved(self):
        p = pl.Pipeline([stage("a")])
        ctx = p.run({"event": "m1"})
        self.assertEqual(ctx["event"], "m1")
    def test_default_stages_all_required(self):
        stages = pl.default_stages()
        self.assertEqual([s.name for s in stages], ["perceive", "think", "express", "present"])
        self.assertTrue(all(s.required for s in stages))
    def test_no_main_import(self):
        import pathlib
        source = pathlib.Path(__file__).resolve().parent.parent.joinpath("pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("import main", source)


class FakeClock:
    """Injected clock: deterministic seconds, advanced explicitly by a stage."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)
        return self.now


class PipelineContractTest(unittest.TestCase):
    def test_ctx_contract_fields(self):
        ctx = pl.make_ctx()
        self.assertEqual(set(ctx.keys()), set(pl.CTX_FIELDS))
        self.assertEqual(len(pl.CTX_FIELDS), 16)
        self.assertEqual(ctx["trace"]["stages"], [])

    def test_run_fills_all_ctx_fields(self):
        p = pl.Pipeline([stage("a")])
        ctx = p.run({"event": {"text": "hi"}})
        for field in pl.CTX_FIELDS:
            self.assertIn(field, ctx)
        self.assertEqual(ctx["event"], {"text": "hi"})

    def test_run_does_not_mutate_input(self):
        p = pl.Pipeline([stage("a")])
        given = {"event": "m1"}
        p.run(given)
        self.assertEqual(given, {"event": "m1"})

    def test_register_appends(self):
        p = pl.Pipeline([stage("a")])
        p.register(stage("b"))
        self.assertEqual(p.names(), ["a", "b"])

    def test_register_accepts_dict(self):
        p = pl.Pipeline()
        p.register({"name": "a", "run": lambda ctx: None})
        self.assertEqual(p.names(), ["a"])

    def test_register_duplicate_raises(self):
        p = pl.Pipeline([stage("a")])
        with self.assertRaises(ValueError):
            p.register(stage("a"))

    def test_register_bad_type(self):
        p = pl.Pipeline()
        with self.assertRaises(TypeError):
            p.register("nope")

    def test_stage_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            pl.Stage("", lambda ctx: None)

    def test_stage_rejects_non_callable_run(self):
        with self.assertRaises(TypeError):
            pl.Stage("a", "not-callable")

    def test_stage_rejects_negative_timeout(self):
        with self.assertRaises(ValueError):
            pl.Stage("a", lambda ctx: None, timeout_ms=-1)

    def test_invalid_on_error_normalized(self):
        st = pl.Stage("a", lambda ctx: None, on_error="explode")
        self.assertEqual(st.on_error, "skip")

    def test_start_by_name(self):
        order = []
        p = pl.Pipeline([stage("a", run=lambda c: order.append("a") or {}),
                         stage("b", run=lambda c: order.append("b") or {}),
                         stage("c", run=lambda c: order.append("c") or {})])
        ctx = p.run({}, start="b")
        self.assertEqual(order, ["b", "c"])
        self.assertEqual([row["status"] for row in ctx["trace"]["stages"]],
                         ["skipped", "ok", "ok"])
        self.assertEqual(ctx["trace"]["stages"][0]["note"], "before_start")

    def test_start_by_index(self):
        order = []
        p = pl.Pipeline([stage("a", run=lambda c: order.append("a") or {}),
                         stage("b", run=lambda c: order.append("b") or {})])
        p.run({}, start=1)
        self.assertEqual(order, ["b"])

    def test_start_unknown_raises(self):
        p = pl.Pipeline([stage("a")])
        with self.assertRaises(KeyError):
            p.run({}, start="nope")

    def test_start_out_of_range(self):
        p = pl.Pipeline([stage("a")])
        with self.assertRaises(IndexError):
            p.run({}, start=5)

    def test_status_enabled_reflects_toggle(self):
        p = pl.Pipeline([stage("a"), stage("b")])
        p.set_enabled("a", False)
        rows = {row["name"]: row for row in p.get_status()["stages"]}
        self.assertFalse(rows["a"]["enabled"])
        self.assertTrue(rows["b"]["enabled"])
        p.set_enabled("a", True)
        rows = {row["name"]: row for row in p.get_status()["stages"]}
        self.assertTrue(rows["a"]["enabled"])

    def test_all_required_stages_cannot_disable(self):
        for name in pl.REQUIRED_STAGES:
            p = pl.Pipeline([stage(name)])
            with self.assertRaises(ValueError):
                p.set_enabled(name, False)
            self.assertTrue(p.set_enabled(name, True))

    def test_fallback_used_on_error(self):
        p = pl.Pipeline([
            pl.Stage("a", lambda c: 1 / 0, on_error="fallback",
                     fallback=lambda c: {"reply": "fb"}),
            stage("b")])
        ctx = p.run({})
        first = ctx["trace"]["stages"][0]
        self.assertEqual(first["status"], "failed")
        self.assertIn("fallback:ok", first["note"])
        self.assertEqual(ctx["reply"], "fb")
        self.assertEqual(ctx["trace"]["stages"][1]["status"], "ok")

    def test_fallback_failure_keeps_note(self):
        def bad_fallback(ctx):
            raise ValueError("boom")
        p = pl.Pipeline([pl.Stage("a", lambda c: 1 / 0, on_error="fallback",
                                  fallback=bad_fallback)])
        ctx = p.run({})
        self.assertIn("fallback:ValueError", ctx["trace"]["stages"][0]["note"])

    def test_on_error_abort_non_required(self):
        p = pl.Pipeline([pl.Stage("a", lambda c: 1 / 0, on_error="abort")])
        with self.assertRaises(pl.PipelineAbort):
            p.run({})

    def test_clock_injected_ms_is_deterministic(self):
        clock = FakeClock()

        def run(ctx):
            clock.advance(0.012)
            return {}

        p = pl.Pipeline([pl.Stage("a", run, timeout_ms=1000)], clock=clock)
        ctx = p.run({})
        self.assertEqual(ctx["trace"]["stages"][0]["ms"], 12.0)
        self.assertEqual(p.get_status()["stages"][0]["last_ms"], 12.0)

    def test_timeout_with_injected_clock(self):
        clock = FakeClock()

        def run(ctx):
            clock.advance(0.2)
            return {}

        p = pl.Pipeline([pl.Stage("a", run, timeout_ms=50), stage("b")], clock=clock)
        ctx = p.run({})
        self.assertEqual(ctx["trace"]["stages"][0]["status"], "timeout")
        self.assertEqual(ctx["trace"]["stages"][1]["status"], "ok")

    def test_zero_timeout_never_times_out(self):
        clock = FakeClock()

        def run(ctx):
            clock.advance(5.0)
            return {}

        p = pl.Pipeline([pl.Stage("a", run, timeout_ms=0)], clock=clock)
        ctx = p.run({})
        self.assertEqual(ctx["trace"]["stages"][0]["status"], "ok")

    def test_explicit_timeout_error_maps_to_timeout(self):
        def run(ctx):
            raise TimeoutError("stage self-report")

        p = pl.Pipeline([pl.Stage("a", run, timeout_ms=0)])
        ctx = p.run({})
        self.assertEqual(ctx["trace"]["stages"][0]["status"], "timeout")

    def test_ring_keeps_last_50_in_order(self):
        p = pl.Pipeline([stage("a"), stage("b")])
        for _ in range(30):
            p.run({})
        self.assertEqual(len(p._ring), 50)
        self.assertEqual(p._ring[-1]["name"], "b")
        self.assertEqual(p._ring[-2]["name"], "a")

    def test_abort_attaches_trace_and_updates_status(self):
        p = pl.Pipeline([pl.Stage("perceive", lambda c: 1 / 0), stage("b")])
        try:
            p.run({})
        except pl.PipelineAbort as exc:
            self.assertEqual(exc.stage_name, "perceive")
            self.assertEqual(exc.trace["stages"][0]["status"], "failed")
        else:
            self.fail("PipelineAbort not raised")
        status = p.get_status()
        self.assertEqual(status["stages"][0]["last_status"], "failed")
        self.assertEqual(status["last_trace"]["stages"][0]["status"], "failed")

    def test_disable_each_non_required_stage_still_valid(self):
        for name in ("a", "b", "c"):
            p = pl.Pipeline([stage("a"), stage("b"), stage("c")])
            p.set_enabled(name, False)
            ctx = p.run({})
            rows = {row["name"]: row for row in ctx["trace"]["stages"]}
            self.assertEqual(rows[name]["status"], "skipped")
            self.assertEqual(rows[name]["note"], "disabled")
            self.assertEqual(sum(1 for row in rows.values() if row["status"] == "ok"), 2)
            for field in pl.CTX_FIELDS:
                self.assertIn(field, ctx)

    def test_skip_note_and_ms(self):
        p = pl.Pipeline([stage("a")])
        p.set_enabled("a", False)
        ctx = p.run({})
        row = ctx["trace"]["stages"][0]
        self.assertEqual(row["ms"], 0.0)
        self.assertEqual(p.get_status()["stages"][0]["last_status"], "skipped")

    def test_default_stages_run_produces_reply(self):
        p = pl.Pipeline(pl.default_stages())
        ctx = p.run(pl.make_ctx(event={"text": "hi"}))
        self.assertTrue(ctx["reply"])
        self.assertEqual([row["status"] for row in ctx["trace"]["stages"]],
                         ["ok", "ok", "ok", "ok"])

    def test_status_fields_and_trace_contract(self):
        p = pl.Pipeline([stage("a")])
        ctx = p.run({})
        row = ctx["trace"]["stages"][0]
        self.assertEqual(set(row.keys()), {"name", "ms", "status", "note"})
        status = p.get_status()
        self.assertEqual(set(status.keys()), {"stages", "last_trace"})
        self.assertEqual(set(status["stages"][0].keys()),
                         {"name", "required", "enabled", "last_status", "last_ms"})
        self.assertIn("ring", status["last_trace"])


if __name__ == "__main__":
    unittest.main()
