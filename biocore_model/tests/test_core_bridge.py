# -*- coding: utf-8 -*-
import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from biocore_model.core_bridge import CoreBridge
class FakeCore:
    def __init__(self, store=None, enabled=True, timeout=2.0, fail=False):
        self.calls=[]; self.fail=fail; self.store=store
    def remember(self,text,**kw):
        self.calls.append(("remember",text))
        return None if self.fail else {"ok":True,"id":"core1"}
    def recall(self,q,limit=3):
        self.calls.append(("recall",q))
        return None if self.fail else {"ok":True,"results":[{"id":"core1","text":"core result"}]}
    def forget(self,entry_id=None,query=None,limit=5):
        self.calls.append(("forget",entry_id or query))
        return None if self.fail else {"ok":True,"removed":[entry_id]}
class BridgeTest(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.dir=Path(self.tmp.name); self.bridge=CoreBridge({"core_client_mode":"off"},self.dir,core_factory=FakeCore)
    def tearDown(self): self.tmp.cleanup()
    def test_off_no_calls(self): self.assertIsNone(self.bridge.recall("x")); self.assertEqual(self.bridge.calls,0)
    def test_disabled_default(self): self.assertFalse(CoreBridge({},self.dir,core_factory=FakeCore).enabled)
    def test_shadow_recall(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"shadow"},self.dir,core_factory=FakeCore); self.assertTrue(b.enabled); rows=b.recall("q"); self.assertEqual(rows["results"][0]["id"],"core1"); self.assertGreaterEqual(b.calls,1)
    def test_primary_format(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"primary"},self.dir,core_factory=FakeCore); text=b.rows_to_text(b.recall("q")["results"]); self.assertIn("core result",text)
    def test_shadow_record(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"shadow"},self.dir,core_factory=FakeCore); row=b.record_shadow("q",["a","b"],["b","c"],0.1,0.2); self.assertEqual(row["overlap"],1); lines=(self.dir/"shadow_diff.jsonl").read_text(encoding="utf-8").strip().splitlines(); self.assertEqual(len(lines),1); self.assertIn("old_ids",json.loads(lines[0]))
    def test_failure_degrades(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"primary"},self.dir,core_factory=lambda **kw: FakeCore(fail=True)); self.assertIsNone(b.recall("q")); self.assertEqual(b.failures,1)
    def test_circuit_after_five(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"primary"},self.dir,core_factory=lambda **kw: FakeCore(fail=True))
        for _ in range(5): b.recall("q")
        self.assertTrue(b.circuit_open); before=b.calls; self.assertIsNone(b.recall("q")); self.assertEqual(b.calls,before)
    def test_migrated_store_detection(self):
        core=self.dir/"core_store"; core.mkdir(); (core/"memory.json").write_text('{"entries":[]}',encoding="utf-8"); b=CoreBridge({"core_client_enabled":True},self.dir,core_factory=FakeCore); self.assertTrue(b.migrated_available); self.assertTrue(b.store_path().endswith("core_store\\memory.json") or b.store_path().endswith("core_store/memory.json"))
    def test_remember_primary(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"primary"},self.dir,core_factory=FakeCore); self.assertEqual(b.remember("hello")["id"],"core1")
    def test_remember_shadow_not_written(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"shadow"},self.dir,core_factory=FakeCore); self.assertIsNone(b.remember("hello"))
    def test_forget_primary(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"primary"},self.dir,core_factory=FakeCore); self.assertTrue(b.forget(entry_id="a")["ok"])

class TimeoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_core_client_timeout_default_and_set(self):
        from biocore_model.core_client import CoreClient
        client = CoreClient(enabled=False)
        self.assertEqual(client.timeout, 3.0)
        self.assertEqual(client.set_timeout(2.5), 2.5)
        self.assertEqual(client.timeout, 2.5)
        self.assertEqual(client.set_timeout(0.1), 2.5)
        self.assertEqual(client.set_timeout("bad"), 2.5)

    def test_bridge_uses_two_second_timeout(self):
        seen = {}
        def factory(**kw):
            seen.update(kw)
            return FakeCore(**kw)
        b = CoreBridge({"core_client_enabled": True, "core_client_mode": "primary"}, self.dir, core_factory=factory)
        b.recall("q")
        self.assertEqual(seen.get("timeout"), 2.0)

class ShadowRememberTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_shadow_remember_writes_diff(self):
        b = CoreBridge({"core_client_enabled": True, "core_client_mode": "shadow"}, self.dir, core_factory=FakeCore)
        self.assertIsNone(b.remember("hello"))
        lines = (self.dir / "shadow_diff.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        self.assertIn("text_hash", row); self.assertTrue(row["core_ok"])
    def test_primary_remember_no_diff(self):
        b = CoreBridge({"core_client_enabled": True, "core_client_mode": "primary"}, self.dir, core_factory=FakeCore)
        self.assertIsNotNone(b.remember("hello"))
        self.assertFalse((self.dir / "shadow_diff.jsonl").exists())
    def test_off_remember_zero(self):
        calls = []
        def factory(**kw): calls.append(kw); return FakeCore(**kw)
        b = CoreBridge({"core_client_mode": "off"}, self.dir, core_factory=factory)
        self.assertIsNone(b.remember("hello")); self.assertEqual(calls, []); self.assertFalse((self.dir / "shadow_diff.jsonl").exists())