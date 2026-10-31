# -*- coding: utf-8 -*-
import unittest
from biocore_model import expr_state as es

FULL = {
    'labels': {'emotion': 'joy', 'intensity': 0.62},
    'spectrum_probs': {'joy': 0.62, 'contentment': 0.23, 'amusement': 0.15},
    'v': 0.42, 'a': 0.66, 'd': 0.52, 'social': 0.61, 'stress': 0.24, 'energy': 0.81,
    'mood': {'valence': -0.15, 'arousal': 0.4, 'label': '偏低'},
    'needs': {'belonging': 0.42, 'control': 0.58, 'meaningful_existence': 0.60},
    'self_esteem': 0.51, 'social_pain': 0.35,
    'attachment': {'activation': 0.42, 'mode': 'hyperactivating'},
    'regulation': {'strategy': 'suppress', 'effort': 0.30},
    'sleep_debt': 1.2,
    'attribution': {'locus': 'external', 'stability': 'unstable'},
}
REL = {'state': {'closeness': 0.61, 'trust': 0.57, 'conflict': 0.22}}

class ExprStateTest(unittest.TestCase):
    def test_full_render_has_sections(self):
        out = es.render_state_block(FULL, REL)
        for key in ('joy', '情绪还挺杂', '心情', '自尊', '被冷落', '依恋', '在忍着', '关系', '觉得是'):
            self.assertIn(key, out['text'])
    def test_empty_returns_empty(self):
        out = es.render_state_block({}, {})
        self.assertEqual(out['text'], ''); self.assertEqual(out['parts_used'], [])
    def test_missing_fields_skip(self):
        out = es.render_state_block({'labels': {'emotion': 'neutral'}}, {})
        self.assertIn('neutral', out['text'])
    def test_budget_truncates_optional(self):
        out = es.render_state_block(FULL, REL, budget_chars=80)
        self.assertTrue(out['truncated']); self.assertLessEqual(len(out['text']), 80)
    def test_mandatory_kept_under_budget(self):
        out = es.render_state_block(FULL, REL, budget_chars=200)
        for key in ('joy', '情绪还挺杂', '心情'):
            self.assertIn(key, out['text'])
    def test_parts_used_lists_present(self):
        out = es.render_state_block(FULL, REL)
        self.assertIn('emotion', out['parts_used']); self.assertIn('relationship', out['parts_used'])
    def test_no_field_names(self):
        out = es.render_state_block(FULL, REL)
        for name in es.FIELD_NAMES:
            self.assertNotIn(name + '=', out['text'])
    def test_adverb_mapping(self):
        self.assertEqual(es.adverb(0.85), '很')
        self.assertEqual(es.adverb(0.65), '有点')
        self.assertEqual(es.adverb(0.45), '略')
        self.assertEqual(es.adverb(0.1), '几乎不')
    def test_self_esteem_note(self):
        self.assertIn('犹豫', es.render_state_block({'self_esteem': 0.3}, {})['text'])
    def test_attachment_modes(self):
        text = es.render_state_block({'attachment': {'activation': 0.5, 'mode': 'deactivating'}}, {})['text']
        self.assertIn('想退开', text)
    def test_sleep_debt_threshold(self):
        self.assertEqual(es.render_state_block({'sleep_debt': 0.1}, {})['text'], '')
        self.assertIn('有点累', es.render_state_block({'sleep_debt': 1.2}, {})['text'])
    def test_relationship_values(self):
        text = es.render_state_block({}, REL)['text']
        self.assertIn('亲近', text); self.assertIn('信任', text)
    def test_attribution_neutral_skipped(self):
        self.assertEqual(es.render_state_block({'attribution': {'locus': 'neutral'}}, {})['text'], '')
    def test_render_is_deterministic(self):
        self.assertEqual(es.render_state_block(FULL, REL), es.render_state_block(FULL, REL))

if __name__ == '__main__':
    unittest.main()
