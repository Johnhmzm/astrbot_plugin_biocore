# -*- coding: utf-8 -*-
import re, unittest
from pathlib import Path
from biocore_model import appraisal_action as aa, needs_esteem as ne, needs_sleep as ns
from biocore_model import attachment_regulation as ar, attachment_state as ast
from biocore_model import connection_bids as cb, sleep_circadian as sc, memory_forgetting as mf

class ConvergenceTest(unittest.TestCase):
    def test_appraisal_delegates(self):
        self.assertEqual(aa.appraisal(0.5, 0.6, 0.7, 0.8, 0.9), aa._bio_appraisal.appraisal(0.5, 0.6, 0.7, 0.8, 0.9))
    def test_appraise_delegates(self):
        self.assertEqual(aa.appraise(-0.5, 0.8, 0.2, 0.6), aa._bio_appraisal.appraise(-0.5, 0.8, 0.2, 0.6))
    def test_needs_esteem_delegates_to_needs_sleep(self):
        old = ne.apply_silence(ne.defaults(), 10)
        new = ns.need_step(ns.defaults(0), {'silence_hours': 10}, dt=0, now=1)
        self.assertAlmostEqual(old['belonging'], new['belonging'], places=3)
    def test_attachment_wrapper_delegates(self):
        wrapped = ar.activation('anxious', threat=0.4, current=0.3, hours=1)
        raised = ast.threat(0.3, 0.4); expected = ast.decay(raised, False, 1)
        self.assertAlmostEqual(wrapped['activation'], expected, places=3)
    def test_trust_derived_from_relationship(self):
        derived = cb.trust_from_relationship({'state': {'trust': 0.7}})
        self.assertAlmostEqual(derived['overall'], 0.7)
    def test_circadian_reads_snapshot(self):
        self.assertAlmostEqual(sc.circadian_from_snapshot({'circadian_alertness': 0.42}), 0.42)
    def test_rumination_single_module_no_core_write(self):
        source = Path(__file__).resolve().parent.parent.joinpath('memory_forgetting.py').read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'core\.[A-Za-z_]+\s*=', source))
    def test_no_core_assignment_in_appraisal(self):
        for name in ('appraisal_action.py', 'bio_appraisal.py'):
            source = Path(__file__).resolve().parent.parent.joinpath(name).read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'core\.[A-Za-z_]+\s*=', source), name)

if __name__ == '__main__':
    unittest.main()
