# -*- coding: utf-8 -*-
import unittest
import interpretation


class ProtocolEchoStripTest(unittest.TestCase):
    def setUp(self):
        interpretation.LEAK_GUARD.update({'protocol_echo_stripped': 0, 'prompt_rule_echo': 0, 'protocol_echo_seen': 0})

    def test_echo_sentence_at_end_is_removed(self):
        visible, _ = interpretation.parse_response('今天天气不错。标签必须隐藏，不要解释。')
        self.assertNotIn('必须隐藏', visible)
        self.assertIn('今天天气不错', visible)
        self.assertEqual(interpretation.LEAK_GUARD['protocol_echo_stripped'], 1)

    def test_echo_sentence_in_middle_keeps_neighbours(self):
        visible, _ = interpretation.parse_response('我明白你的意思。标签只出现一次，必须隐藏。我们继续聊。')
        self.assertNotIn('标签只出现一次', visible)
        self.assertIn('我明白', visible)
        self.assertIn('我们继续聊', visible)

    def test_multiple_echo_sentences_all_removed(self):
        visible, _ = interpretation.parse_response('标签格式说明。不要解释。正常内容。')
        self.assertNotIn('<bc>', visible)
        self.assertNotIn('不要解释', visible)
        self.assertIn('正常内容', visible)

    def test_normal_hidden_word_not_stripped(self):
        visible, _ = interpretation.parse_response('这件事我一直隐藏着没说。')
        self.assertEqual(visible.strip(), '这件事我一直隐藏着没说。')

    def test_rule_echo_kept_but_counted(self):
        visible, _ = interpretation.parse_response('先接住情绪，再谈事情；今天想聊什么？')
        self.assertIn('先接住情绪', visible)
        self.assertEqual(interpretation.LEAK_GUARD['prompt_rule_echo'], 1)

    def test_normal_reply_no_metrics(self):
        visible, _ = interpretation.parse_response('晚安，做个好梦。')
        self.assertEqual(visible.strip(), '晚安，做个好梦。')
        self.assertEqual(interpretation.LEAK_GUARD['prompt_rule_echo'], 0)

    def test_tag_plus_json_plus_fence_no_leak(self):
        visible, _ = interpretation.parse_response('你好。\n```json\n{"e":"sad","i":0.5}\n```\n<bc>{"e":"sad","i":0.5}</bc>\n必须隐藏。')
        self.assertNotIn('<bc>', visible)
        self.assertNotIn('"e"', visible)
        self.assertNotIn('```', visible)
        self.assertIn('你好', visible)

    def test_unclosed_tag_removed(self):
        visible, _ = interpretation.parse_response('在的。<bc>{"e":"joy","i":0.4}')
        self.assertNotIn('<bc>', visible)
        self.assertIn('在的', visible)

    def test_bad_json_label_not_crash(self):
        visible, _ = interpretation.parse_response('嗯。<bc>not json</bc>')
        self.assertNotIn('<bc>', visible)

    def test_echo_only_reply_becomes_empty(self):
        visible, _ = interpretation.parse_response('标签必须隐藏，不要解释。')
        self.assertEqual(visible.strip(), '')

    def test_leak_guard_snapshot_shape(self):
        interpretation.parse_response('标签必须隐藏。开心吗？')
        snap = interpretation.leak_guard_snapshot()
        for key in ('protocol_echo', 'prompt_rule_echo', 'tag_missing', 'tag_invalid'):
            self.assertIn(key, snap)
        self.assertGreaterEqual(snap['protocol_echo'], 1)

    def test_prompt_rule_multiple_occurrences_counted_once(self):
        interpretation.parse_response('先接住情绪。先缓和。')
        self.assertEqual(interpretation.LEAK_GUARD['prompt_rule_echo'], 1)


if __name__ == '__main__':
    unittest.main()
