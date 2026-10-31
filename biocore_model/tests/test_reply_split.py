# -*- coding: utf-8 -*-
import unittest
from biocore_model import reply_split

CFG = {'enabled': True, 'mode': 'punct', 'max_chars': 400, 'min_chars': 12}

class ReplySplitTest(unittest.TestCase):
    def test_punct_keeps_punctuation(self):
        parts = reply_split.split_reply('今天真的挺不错的。你那边怎么样呢？我这边一切顺利。', dict(CFG, min_chars=1))
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(parts[0].endswith('。')); self.assertTrue(parts[1].endswith('？'))

    def test_newline_mode(self):
        cfg = {'enabled': True, 'mode': 'newline', 'min_chars': 1}
        self.assertEqual(reply_split.split_reply('一行\n二行\n三行', cfg), ['一行', '二行', '三行'])

    def test_words_mode(self):
        cfg = {'enabled': True, 'mode': 'words', 'words': ['好的', '结束'], 'min_chars': 1}
        parts = reply_split.split_reply('好的开始结束', cfg)
        self.assertEqual(len(parts), 2)

    def test_short_piece_merged(self):
        parts = reply_split.split_reply('这是第一句比较长的话。嗯。后面还有一句比较长的话。', CFG)
        self.assertFalse(any(len(p) < 12 for p in parts[:-1]))

    def test_over_max_chars_not_split(self):
        cfg = dict(CFG, max_chars=10)
        text = '很长很长很长很长很长。很长很长很长很长很长。'
        self.assertEqual(reply_split.split_reply(text, cfg), [text])

    def test_at_most_six_segments(self):
        text = ''.join('第%d句比较长的话说三遍。' % i for i in range(10))
        self.assertLessEqual(len(reply_split.split_reply(text, CFG)), 6)

    def test_disabled_returns_single(self):
        text = '一句。两句。'
        self.assertEqual(reply_split.split_reply(text, dict(CFG, enabled=False)), [text])

    def test_empty_text(self):
        self.assertEqual(reply_split.split_reply('', CFG), [])

    def test_single_sentence_not_split(self):
        self.assertEqual(reply_split.split_reply('只有一句话。', CFG), ['只有一句话。'])

    def test_plain_text_without_punctuation(self):
        self.assertEqual(reply_split.split_reply('没有标点的句子', CFG), ['没有标点的句子'])

    def test_invalid_mode_falls_back(self):
        self.assertIn(reply_split.split_reply('甲。乙。丙。', {'enabled': True, 'mode': 'bogus', 'min_chars': 1}), [['甲。乙。丙。'], ['甲。', '乙。', '丙。']])

if __name__ == '__main__':
    unittest.main()
