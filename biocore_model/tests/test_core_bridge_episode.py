import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from biocore_model.core_bridge import CoreBridge
class EpisodeTest(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.dir=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_record_episode_local_once(self):
        b=CoreBridge({'core_client_enabled':True,'core_client_mode':'shadow'},self.dir,core_factory=lambda **kw: None)
        self.assertIsNotNone(b.record_episode('guard:refusal','blocked',0.0,{'reason':'x'}))
        lines=(self.dir/'episodes-local.jsonl').read_text(encoding='utf-8').strip().splitlines(); self.assertEqual(len(lines),1); self.assertIn('guard:refusal',lines[0])
    def test_off_no_episode(self):
        b=CoreBridge({'core_client_mode':'off'},self.dir,core_factory=lambda **kw: None); self.assertIsNone(b.record_episode('guard:refusal','blocked'))
