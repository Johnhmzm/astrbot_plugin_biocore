# -*- coding: utf-8 -*-
import re, unittest
from biocore_model import reply_split

ENABLED = {'enable': True, 'words_count_threshold': 150, 'split_mode': 'regex', 'regex': '[^\\n]+'}

class InjectNewlinesTest(unittest.TestCase):
    def _inject(self, text, settings=None):
        return reply_split.inject_sentence_newlines(text, settings or ENABLED)

    def test_multi_sentence_one_per_line(self):
        self.assertEqual(self._inject('第一句。第二句？第三句！'), '第一句。\n第二句？\n第三句！')

    def test_punctuation_kept(self):
        out = self._inject('甲。乙！')
        self.assertTrue(out.endswith('甲。\n乙！'))

    def test_existing_newline_not_duplicated(self):
        self.assertEqual(self._inject('第一句。\n第二句。'), '第一句。\n第二句。')

    def test_no_punctuation_unchanged(self):
        self.assertEqual(self._inject('没有标点的句子'), '没有标点的句子')

    def test_over_threshold_no_injection(self):
        text = '一句。两句。'
        self.assertEqual(self._inject(text, dict(ENABLED, words_count_threshold=5)), text)

    def test_disabled_no_injection(self):
        text = '一句。两句。'
        self.assertEqual(self._inject(text, dict(ENABLED, enable=False)), text)

    def test_single_sentence_unchanged(self):
        self.assertEqual(self._inject('只有一句。'), '只有一句。')

    def test_blank_lines_collapsed(self):
        self.assertEqual(self._inject('甲。\n\n乙。'), '甲。\n乙。')

    def test_astrbot_regex_splits_into_sentences(self):
        text = self._inject('第一句。第二句？第三句！')
        self.assertEqual(len(re.findall(r'[^\n]+', text, re.DOTALL | re.MULTILINE)), 3)

    def test_split_reply_returns_single_text_with_newlines(self):
        cfg = {'enabled': True, 'astrbot': ENABLED, 'inject_newlines': True}
        parts = reply_split.split_reply('甲。乙。', cfg)
        self.assertEqual(parts, ['甲。\n乙。'])

    def test_status_has_inject_flag(self):
        self.assertTrue(reply_split.status.__doc__ is not None)
        class P: config = {}
        self.assertTrue(reply_split.status(P())['inject_newlines'])

if __name__ == '__main__':
    unittest.main()
