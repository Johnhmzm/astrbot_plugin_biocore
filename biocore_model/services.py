# -*- coding: utf-8 -*-
"""BioCore model layer: external/long-running service gateway (Phase 1).

Placeholder interface for the future route layer. It centralises the three
external call shapes the plugin already has so Phase 4 (route.py) can add
failover/persistence in one place:

- embed  : embedding provider HTTP call
- rerank : rerank provider call
- llm    : text LLM call (chat/summary/insight)

Phase 1 only wraps the calls that already exist, preserving the exact
timeout/exception behaviour. Policy work (sensitive skip, cache keys, daily
budget, failover) stays in main.py until route.py lands; the hooks
sensitive/cache_hint are accepted but intentionally unused here.

Standard library only: importable without AstrBot for tests.
"""
from __future__ import annotations

import asyncio
import time

SERVICE_KINDS = ("embedding", "rerank", "llm")


class ServiceStats:
    """Bounded, read-only counters for external calls (never decision input)."""

    def __init__(self):
        self.counters = {}
        self.last_ms = {}

    def record(self, kind, outcome, elapsed_ms=0.0):
        key = "%s:%s" % (str(kind or "call")[:16], str(outcome or "?")[:12])
        self.counters[key] = min(10 ** 6, int(self.counters.get(key, 0) or 0) + 1)
        try:
            self.last_ms[str(kind or "call")[:16]] = round(float(elapsed_ms), 1)
        except Exception:
            pass

    def snapshot(self):
        return {"counters": dict(self.counters), "last_ms": dict(self.last_ms)}


class Services:
    """Thin timeout/counting gateway; one shared instance per plugin."""

    def __init__(self, stats=None):
        self.stats = stats if isinstance(stats, ServiceStats) else ServiceStats()

    async def wait(self, awaitable, timeout_s, kind="call"):
        """Await one external call with the caller's timeout (same exceptions)."""
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(awaitable, timeout=timeout_s)
        except asyncio.TimeoutError:
            self.stats.record(kind, "timeout", (time.monotonic() - started) * 1000.0)
            raise
        except Exception:
            self.stats.record(kind, "error", (time.monotonic() - started) * 1000.0)
            raise
        self.stats.record(kind, "ok", (time.monotonic() - started) * 1000.0)
        return result

    async def embed(self, awaitable, timeout_s, *, sensitive=False, cache_hint=""):
        """Embedding call. sensitive/cache_hint are policy hooks (Phase 4)."""
        _ = (sensitive, cache_hint)
        return await self.wait(awaitable, timeout_s, "embedding")

    async def rerank(self, awaitable, timeout_s, *, kind="rerank"):
        return await self.wait(awaitable, timeout_s, kind)

    async def llm(self, awaitable, timeout_s, *, kind="llm"):
        return await self.wait(awaitable, timeout_s, kind)


SERVICES = Services()
