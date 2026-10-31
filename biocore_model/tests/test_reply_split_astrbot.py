# -*- coding: utf-8 -*-
import re, unittest
from biocore_model import reply_split

BASE = {'enable': True, 'words_count_threshold': 150, 'split_mode': 'words',
        'split_words': ['。', '？', '！'], 'content_cleanup_rule': ''}

def astrbot_reference(text, cfg):
    if not cfg.get('enable'): return [text]
    if len(text) > cfg.get('words_count_threshold', 150): return [text]
    if cfg.get('split_mode') == 'words':
        out, buf = [], ''
        for ch in text:
            buf += ch
            if any(buf.endswith(w) for w in cfg.get('split_words') or []):
                out.append(buf); buf = ''
        if buf.strip(): out.append(buf)
    else:
        out = re.findall(cfg.get('regex') or '[^\\n]+', text, re.DOTALL | re.MULTILINE)
    cleanup = cfg.get('content_cleanup_rule') or ''
    out = [re.sub(cleanup, '', p) if cleanup else p for p in out]
    out = [p for p in out if str(p).strip()]
    return out if len(out) >= 2 else [text]

class AstrbotModeTest(unittest.TestCase):
    def test_default_mode_is_astrbot(self):
        self.assertEqual(reply_split.DEFAULTS['mode'], 'astrbot')
    def test_disabled_returns_single(self):
        cfg = dict(BASE, enable=False)
        self.assertEqual(reply_split.split_reply('一句。两句。', {'enabled': True, 'astrbot': cfg, 'inject_newlines': False}), ['一句。两句。'])
    def test_threshold_exceeded_not_split(self):
        cfg = dict(BASE, words_count_threshold=5)
        self.assertEqual(reply_split.split_reply('一句。两句。', {'enabled': True, 'astrbot': cfg, 'inject_newlines': False}), ['一句。两句。'])
    def test_words_matches_astrbot_reference(self):
        text = '第一句话。第二句话？第三句话！'
        cfg = dict(BASE)
        ours = reply_split.split_reply(text, {'enabled': True, 'astrbot': cfg, 'inject_newlines': False})
        self.assertEqual(ours, astrbot_reference(text, cfg))
    def test_regex_mode_newline(self):
        text = '第一行\n第二行\n第三行'
        cfg = {'enable': True, 'words_count_threshold': 150, 'split_mode': 'regex', 'regex': '[^\\n]+', 'content_cleanup_rule': ''}
        self.assertEqual(reply_split.split_reply(text, {'enabled': True, 'astrbot': cfg, 'inject_newlines': False}), ['第一行', '第二行', '第三行'])
    def test_regex_matches_astrbot_reference(self):
        text = '甲\n乙\n丙'
        cfg = {'enable': True, 'words_count_threshold': 150, 'split_mode': 'regex', 'regex': '[^\\n]+', 'content_cleanup_rule': ''}
        self.assertEqual(reply_split.split_reply(text, {'enabled': True, 'astrbot': cfg, 'inject_newlines': False}), astrbot_reference(text, cfg))
    def test_cleanup_rule_removes_content(self):
        text = '第一句[cut]话。第二句[cut]话？'
        cfg = {'enable': True, 'words_count_threshold': 150, 'split_mode': 'words', 'split_words': ['。', '？'], 'content_cleanup_rule': r'\[cut\]'}
        parts = reply_split.split_reply(text, {'enabled': True, 'astrbot': cfg, 'inject_newlines': False})
        self.assertEqual(parts, ['第一句话。', '第二句话？'])
    def test_below_two_segments_returns_whole(self):
        cfg = dict(BASE)
        self.assertEqual(reply_split.split_reply('只有一句。', {'enabled': True, 'astrbot': cfg, 'inject_newlines': False}), ['只有一句。'])
    def test_empty_text(self):
        self.assertEqual(reply_split.split_reply('', {'enabled': True, 'astrbot': BASE, 'inject_newlines': False}), [])
    def test_effective_shape(self):
        eff = reply_split.effective(None)
        for key in ('enable', 'threshold', 'mode', 'regex_or_words'):
            self.assertIn(key, eff)
    def test_read_astrbot_settings_defaults_no_crash(self):
        settings = reply_split.read_astrbot_settings(None)
        self.assertIn('split_mode', settings)

if __name__ == '__main__':
    unittest.main()
