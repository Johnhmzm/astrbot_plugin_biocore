# -*- coding: utf-8 -*-
"""PIPE-1: one main line pipeline with pluggable / disable-able / isolated / observable stages.

Contract (task-107):
- ctx is a plain dict with the fixed fields in CTX_FIELDS; stages may add
  private keys but must not remove the contract keys.
- one stage is {name, required, enabled(ctx), timeout_ms, on_error, run(ctx)}.
- run(ctx, start=None) walks the stages in order; disabled stages are recorded
  as skipped, exceptions as failed (or timeout), and the configured on_error
  policy decides whether to continue (skip), call the stage fallback and
  continue (fallback), or abort (abort).
- a failed required stage always raises PipelineAbort.
- every stage appends {name, ms, status, note} to ctx["trace"]["stages"] and to
  a ring buffer that keeps the last 50 records.
- no main import and no file I/O: configuration (enabled flags, clock) is
  injected through the constructor, which keeps the executor deterministic and
  unit-testable.

Limits: timeout_ms is enforced cooperatively (elapsed time is measured around
run, so a stage cannot be preempted mid-call); start records the stages before
it as skipped(before_start) without running them.
"""
from __future__ import annotations

import time
from collections import deque

REQUIRED_STAGES = ("perceive", "express", "think", "present")
TRACE_RING_MAX = 50
ON_ERROR_MODES = ("skip", "fallback", "abort")
CTX_FIELDS = (
    "event", "user", "umo", "core", "state", "memory", "decision", "intent",
    "tone", "prompt", "llm_raw", "parsed", "deltas", "reply", "meta", "trace",
)


def make_ctx(**overrides):
    """Fresh ctx carrying every contract field (trace starts empty)."""
    ctx = {field: None for field in CTX_FIELDS}
    ctx["meta"] = {}
    ctx["trace"] = {"stages": [], "ring": []}
    ctx.update(overrides or {})
    return ctx


class PipelineAbort(Exception):
    """Raised when a required stage fails (or a stage uses on_error='abort')."""

    def __init__(self, stage_name, note="", trace=None):
        self.stage_name = str(stage_name)
        self.note = str(note or "")
        self.trace = trace if isinstance(trace, dict) else {"stages": [], "ring": []}
        super().__init__(self.stage_name + ": " + (self.note or "aborted"))


class Stage:
    def __init__(self, name, run, required=False, enabled=None, timeout_ms=2000,
                 on_error="skip", fallback=None):
        self.name = str(name or "").strip()
        if not self.name:
            raise ValueError("stage name required")
        if not callable(run):
            raise TypeError("stage run must be callable")
        if fallback is not None and not callable(fallback):
            raise TypeError("stage fallback must be callable or None")
        self.run = run
        self.fallback = fallback
        self.required = bool(required) or self.name in REQUIRED_STAGES
        self._enabled = enabled
        self.timeout_ms = int(timeout_ms or 0)
        if self.timeout_ms < 0:
            raise ValueError("timeout_ms must be >= 0")
        self.on_error = on_error if on_error in ON_ERROR_MODES else "skip"
        self.last_status = "idle"
        self.last_ms = 0.0
        self.last_note = ""

    def enabled(self, ctx):
        if self._enabled is None:
            return True
        try:
            return bool(self._enabled(ctx))
        except Exception:
            return False

    def describe(self, ctx=None):
        return {"name": self.name, "required": self.required,
                "enabled": self.enabled({} if ctx is None else ctx),
                "last_status": self.last_status,
                "last_ms": round(self.last_ms, 3)}


class Pipeline:
    def __init__(self, stages=None, trace_ring_max=TRACE_RING_MAX, clock=None):
        self._clock = clock if callable(clock) else time.perf_counter
        self.stages = []
        self._ring = deque(maxlen=max(1, int(trace_ring_max)))
        self.last_trace = {"stages": [], "ring": []}
        for stage in (stages or []):
            self.register(stage)

    def _find(self, name):
        for index, stage in enumerate(self.stages):
            if stage.name == name:
                return index, stage
        return -1, None

    def register(self, stage, index=None):
        """Append (or insert) one Stage; duplicate names are rejected."""
        if isinstance(stage, dict):
            stage = Stage(**stage)
        if not isinstance(stage, Stage):
            raise TypeError("register expects a Stage or a dict")
        if self._find(stage.name)[1] is not None:
            raise ValueError("duplicate stage: " + stage.name)
        if index is None:
            self.stages.append(stage)
        else:
            self.stages.insert(max(0, min(len(self.stages), int(index))), stage)
        return stage

    def names(self):
        return [stage.name for stage in self.stages]

    def set_enabled(self, name, enabled):
        """Toggle one stage at runtime; required stages refuse to be disabled."""
        _, stage = self._find(name)
        if stage is None:
            raise KeyError(name)
        if stage.name in REQUIRED_STAGES and not enabled:
            raise ValueError("required stage cannot be disabled: " + stage.name)
        value = bool(enabled)
        stage._enabled = lambda ctx, _value=value: _value
        return True

    def enable(self, name):
        return self.set_enabled(name, True)

    def disable(self, name):
        return self.set_enabled(name, False)

    def get_status(self):
        """Per-stage observability: name/required/enabled/last_status/last_ms."""
        rows = [stage.describe() for stage in self.stages]
        return {"stages": rows, "last_trace": self.last_trace}

    def _start_index(self, start):
        if start is None:
            return 0
        if isinstance(start, int):
            if start < 0 or start > len(self.stages):
                raise IndexError("start index out of range: %d" % start)
            return start
        index, stage = self._find(str(start))
        if stage is None:
            raise KeyError(start)
        return index

    def _record(self, ctx, trace, record):
        trace["stages"].append(record)
        self._ring.append(dict(record))
        ctx["trace"] = trace
        return record

    def _skip(self, ctx, trace, stage, note):
        stage.last_status = "skipped"
        stage.last_ms = 0.0
        stage.last_note = note
        return self._record(ctx, trace, {"name": stage.name, "ms": 0.0,
                                         "status": "skipped", "note": note})

    def _run_stage(self, stage, ctx):
        started = self._clock()
        status, note = "ok", ""
        try:
            result = stage.run(ctx)
            if isinstance(result, dict):
                ctx.update(result)
        except TimeoutError as exc:
            status, note = "timeout", "timeout: " + str(exc)[:100]
        except Exception as exc:
            status, note = "failed", type(exc).__name__ + ": " + str(exc)[:120]
        elapsed_ms = max(0.0, (self._clock() - started) * 1000.0)
        if status == "ok" and stage.timeout_ms and elapsed_ms > stage.timeout_ms:
            status = "timeout"
            note = "exceeded %dms (%.1fms)" % (stage.timeout_ms, elapsed_ms)
        if status != "ok" and stage.on_error == "fallback" and stage.fallback is not None:
            try:
                patch = stage.fallback(ctx)
                if isinstance(patch, dict):
                    ctx.update(patch)
                note = (note + " | fallback:ok").strip(" |")
            except Exception as exc:
                note = (note + " | fallback:" + type(exc).__name__).strip(" |")
        stage.last_ms = elapsed_ms
        stage.last_note = note
        return status, note

    def run(self, ctx=None, start=None):
        """Run every stage in order; start may be a stage name or an index.

        Stages before start are recorded as skipped(before_start) but not run.
        Raises PipelineAbort when a required stage fails or on_error='abort'.
        """
        base = make_ctx()
        base.update(dict(ctx or {}))
        ctx = base
        trace = {"stages": [], "ring": []}
        ctx["trace"] = trace
        start_index = self._start_index(start)
        for position, stage in enumerate(self.stages):
            if position < start_index:
                self._skip(ctx, trace, stage, "before_start")
                continue
            if not stage.enabled(ctx):
                self._skip(ctx, trace, stage, "disabled")
                continue
            status, note = self._run_stage(stage, ctx)
            stage.last_status = status
            self._record(ctx, trace, {"name": stage.name, "ms": round(stage.last_ms, 3),
                                      "status": status, "note": note})
            if status != "ok" and (stage.required or stage.on_error == "abort"):
                trace["ring"] = [dict(item) for item in self._ring]
                ctx["trace"] = trace
                self.last_trace = trace
                raise PipelineAbort(stage.name, note or status, trace)
        trace["ring"] = [dict(item) for item in self._ring]
        ctx["trace"] = trace
        self.last_trace = trace
        return ctx

    def _push(self, record):
        self._ring.append(dict(record))


def default_stages():
    return [Stage("perceive", lambda ctx: {"meta": {"ok": True}}, required=True),
            Stage("think", lambda ctx: {"decision": "reply"}, required=True),
            Stage("express", lambda ctx: {"tone": {"text": "自然"}}, required=True),
            Stage("present", lambda ctx: {"reply": "你好。"}, required=True)]
