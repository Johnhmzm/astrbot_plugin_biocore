import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from biocore_model.core_bridge import CoreBridge
class Fake:
    def __init__(self,**kw): self.calls=[]; self.last_error='provider_unavailable'
    def _call(self,m,p): self.calls.append((m,p)); return None
class T(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.dir=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_enabled_probe_writes(self):
        b=CoreBridge({'core_client_enabled':True,'core_client_mode':'shadow'},self.dir,core_factory=Fake); r=b.media_probe(); self.assertIsNotNone(r); self.assertTrue((self.dir/'media-probe.jsonl').exists()); row=(self.dir/'media-probe.jsonl').read_text(encoding='utf-8'); self.assertIn('provider_unavailable',row)
    def test_off_probe(self):
        calls=[]
        def f(**kw): calls.append(kw); return Fake(**kw)
        b=CoreBridge({'core_client_mode':'off'},self.dir,core_factory=f); self.assertIsNone(b.media_probe()); self.assertEqual(calls,[]); self.assertFalse((self.dir/'media-probe.jsonl').exists())
