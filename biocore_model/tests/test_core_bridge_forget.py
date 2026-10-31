import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from biocore_model.core_bridge import CoreBridge
class FakeCore:
    def __init__(self,store=None,enabled=True,timeout=2.0,fail=False,**kw): self.calls=[]; self.fail=fail
    def forget(self,entry_id=None,query=None,limit=5): self.calls.append(1); return None if self.fail else {"ok":True,"removed":[entry_id]}
class T(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.dir=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_ok(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"primary"},self.dir,core_factory=FakeCore); self.assertTrue(b.forget_via_core(entry_id="a")["used_core"])
    def test_fail(self):
        b=CoreBridge({"core_client_enabled":True,"core_client_mode":"primary"},self.dir,core_factory=lambda **kw: FakeCore(fail=True)); self.assertFalse(b.forget_via_core(entry_id="a")["used_core"])
    def test_off(self):
        b=CoreBridge({"core_client_mode":"off"},self.dir,core_factory=FakeCore); self.assertFalse(b.forget_via_core(entry_id="a")["used_core"]); self.assertEqual(b.calls,0)
