import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from biocore_model.core_bridge import CoreBridge
class Fake:
    def __init__(self,**kw): self.calls=[]
    def _call(self,m,p): self.calls.append((m,p)); return {'ok':True}
class T(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.dir=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_primary_summary(self):
        b=CoreBridge({'core_client_enabled':True,'core_client_mode':'primary'},self.dir,core_factory=Fake); self.assertIsNone(b.summary_dry_run({'text':'hello'})); self.assertEqual(b._client.calls[0][0],'summary.daily'); self.assertTrue((self.dir/'summary-dryrun.jsonl').exists())
    def test_off_summary(self):
        calls=[]
        def f(**kw): calls.append(kw); return Fake(**kw)
        b=CoreBridge({'core_client_mode':'off'},self.dir,core_factory=f); self.assertIsNone(b.summary_dry_run({'text':'x'})); self.assertEqual(calls,[]); self.assertFalse((self.dir/'summary-dryrun.jsonl').exists())
