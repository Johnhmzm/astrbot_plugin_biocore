# -*- coding: utf-8 -*-
"""Offline tests for biocore_model.core_client (fake runner; no real service)."""
import os
import unittest

from biocore_model.core_client import CoreClient


class FakeRunner:
    """Transport stub: records requests and returns scripted responses."""

    def __init__(self, responses=None, errors=None):
        self.requests = []
        self.timeouts = []
        self.responses = list(responses or [])
        self.errors = list(errors or [])

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.errors:
            raise self.errors.pop(0)
        if self.responses:
            return self.responses.pop(0)
        return {"id": request.get("id"), "ok": True, "result": {"ok": True, "echo": request.get("method")}}


def ok(result=None):
    return {"id": 0, "ok": True, "result": result if result is not None else {"ok": True}}


def client(runner, **kwargs):
    options = {"store": "C:/tmp/biocore-test-store", "enabled": True, "runner": runner}
    options.update(kwargs)
    return CoreClient(**options)


class CoreClientTest(unittest.TestCase):
    def test_disabled_by_default_returns_none(self):
        os.environ.pop("BIOCORE_CORE_CLIENT", None)
        fake = FakeRunner()
        core = client(fake, enabled=False)
        self.assertFalse(core.enabled)
        self.assertIsNone(core.remember("hello"))
        self.assertIsNone(core.recall("hello"))
        self.assertIsNone(core.forget(entry_id="abc"))
        self.assertIsNone(core.state())
        self.assertIsNone(core.bio_snapshot())
        self.assertIsNone(core.health())
        self.assertEqual(fake.requests, [])

    def test_env_switch_enables_client(self):
        os.environ["BIOCORE_CORE_CLIENT"] = "1"
        try:
            fake = FakeRunner()
            core = CoreClient(store="C:/tmp/biocore-test-store", runner=fake)
            self.assertTrue(core.enabled)
            self.assertEqual(core.health().get("ok"), True)
            self.assertEqual(len(fake.requests), 1)
        finally:
            os.environ.pop("BIOCORE_CORE_CLIENT", None)

    def test_remember_parses_result(self):
        fake = FakeRunner([ok({"ok": True, "entry": {"id": "abc", "text": "hello"}})])
        core = client(fake)
        result = core.remember("hello", tags=["plan"], importance=0.8)
        self.assertEqual(result["entry"]["id"], "abc")
        self.assertEqual(core.last_error, "")
        request = fake.requests[0]
        self.assertEqual(request["method"], "memory.remember")
        self.assertEqual(request["params"]["text"], "hello")
        self.assertEqual(request["params"]["tags"], ["plan"])
        self.assertEqual(request["params"]["importance"], 0.8)
        self.assertEqual(request["params"]["role"], "user")

    def test_id_and_method_passthrough(self):
        fake = FakeRunner([ok({"results": []}), ok({"ok": True})])
        core = client(fake)
        core.recall("friday", limit=4)
        core.health()
        self.assertEqual([request["method"] for request in fake.requests], ["memory.recall", "health.check"])
        self.assertEqual([request["id"] for request in fake.requests], [1, 2])
        self.assertEqual(fake.requests[0]["params"], {"query": "friday", "limit": 4})

    def test_timeout_returns_none_without_raise(self):
        fake = FakeRunner(errors=[TimeoutError("slow")])
        core = client(fake)
        self.assertIsNone(core.recall("anything"))
        self.assertIn("timeout", core.last_error)
        self.assertEqual(len(fake.requests), 1)

    def test_crash_once_restarts_and_succeeds(self):
        fake = FakeRunner(responses=[ok({"ok": True, "entry": {"id": "after-restart"}})], errors=[ChildProcessError("boom")])
        core = client(fake, max_restarts=1)
        result = core.remember("survives a crash")
        self.assertEqual(result["entry"]["id"], "after-restart")
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual([request["method"] for request in fake.requests], ["memory.remember", "memory.remember"])
        self.assertIn("process_error", core.last_error) if False else None
        self.assertEqual(core.last_error, "")

    def test_crash_twice_degrades_to_none(self):
        fake = FakeRunner(errors=[ChildProcessError("boom"), ChildProcessError("boom again")])
        core = client(fake, max_restarts=1)
        self.assertIsNone(core.remember("never succeeds"))
        self.assertEqual(len(fake.requests), 2)
        self.assertIn("process_error", core.last_error)

    def test_error_envelope_returns_none_with_code(self):
        fake = FakeRunner([{"id": 1, "ok": False, "error": {"code": "readonly", "message": "store is read-only"}}])
        core = client(fake)
        self.assertIsNone(core.remember("blocked"))
        self.assertIn("readonly", core.last_error)

    def test_forget_by_id_and_by_query(self):
        fake = FakeRunner([
            ok({"ok": True, "id": "abc", "removed": True}),
            ok({"results": [{"id": "r1"}, {"id": "r2"}]}),
            ok({"ok": True, "id": "r1", "removed": True}),
            ok({"ok": True, "id": "r2", "removed": False}),
        ])
        core = client(fake)
        self.assertTrue(core.forget(entry_id="abc")["removed"])
        result = core.forget(query="friday")
        self.assertEqual(result["removed"], ["r1"])
        self.assertEqual(result["count"], 1)
        methods = [request["method"] for request in fake.requests]
        self.assertEqual(methods, ["memory.forget", "memory.recall", "memory.forget", "memory.forget"])

    def test_state_scope_and_bio_health_method_names(self):
        fake = FakeRunner([ok({"ok": True}), ok({"ok": True}), ok({"ok": True})])
        core = client(fake)
        core.state(limit=5, scope="session:s1")
        core.bio_snapshot()
        core.health()
        self.assertEqual([request["method"] for request in fake.requests], ["memory.state", "bio.snapshot", "health.check"])
        self.assertEqual(fake.requests[0]["params"], {"limit": 5, "scope": "session:s1"})

    def test_timeout_is_configurable_and_forwarded(self):
        fake = FakeRunner()
        core = client(fake, timeout=0.5)
        core.health()
        self.assertEqual(fake.timeouts[0], 0.5)

    def test_close_blocks_later_calls(self):
        fake = FakeRunner()
        core = client(fake)
        self.assertEqual(core.health().get("ok"), True)
        core.close()
        self.assertIsNone(core.recall("after close"))
        self.assertEqual(len(fake.requests), 1)

    def test_missing_service_script_degrades_without_throw(self):
        core = CoreClient(store="C:/tmp/biocore-test-store", enabled=True, service_script="", runner=None)
        self.assertIsNone(core.health())
        self.assertIn("service_script_missing", core.last_error)
