# -*- coding: utf-8 -*-
"""event_layer switch inside inject_block: on = events, off = old behaviour."""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_runtime import pipeline  # noqa: E402


def entry(entry_id, text, stamp, vector=None):
    row = {'id': entry_id, 'text': text, 'role': 'user', 'ts': stamp, 'scope': 'default'}
    if vector:
        row['vector'] = vector
    return row


def store_with(rows, flags=None):
    root = tempfile.mkdtemp()
    if flags:
        Path(root, 'flags.json').write_text(json.dumps(flags), encoding='utf-8')
    path = Path(root) / 'sessions' / 's1' / 'memory.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'entries': rows}), encoding='utf-8')
    return root


def ts(minute):
    return datetime(2026, 3, 5, 9, minute).timestamp()


ROWS = [entry('a', '叶楠生日是八月十六', ts(0), [1.0, 0.0]),
        entry('b', '今天风挺大', ts(1), [0.0, 1.0]),
        entry('c', '把生日改到八月十八', ts(2), [0.9, 0.1])]


def stub_summarizer(prompt):
    return ('{"state": {"叶楠·生日": {"value": "八月十八", "status": "current", '
            '"note": "改自八月十六"}}, "overview": "叶楠生日八月十八"}')


class EventLayerWiringTest(unittest.TestCase):

    def test_switch_off_keeps_the_old_block(self):
        store = store_with(ROWS)
        one = pipeline.inject_block('s1', store, query='生日是哪天', max_chars=400, top_k=3)
        two = pipeline.inject_block('s1', store, query='生日是哪天', max_chars=400, top_k=3)
        self.assertEqual(one['text'], two['text'])
        self.assertNotIn('事件｜第', one['text'])

    def test_switch_on_returns_event_block(self):
        store = store_with(ROWS, flags={'event_layer': True})
        block = pipeline.inject_block('s1', store, query='生日是哪天', max_chars=800, top_k=3,
                                      payload={'event_summarizer': stub_summarizer})
        self.assertTrue(block['text'])
        self.assertIn('事件｜第', block['text'])
        self.assertTrue(block['ids'])

    def test_missing_summarizer_raises(self):
        store = store_with(ROWS, flags={'event_layer': True})
        with self.assertRaises(RuntimeError):
            pipeline.inject_block('s1', store, query='生日是哪天', max_chars=400, top_k=3)

    def test_failing_summarizer_raises(self):
        store = store_with(ROWS, flags={'event_layer': True})

        def boom(prompt):
            raise RuntimeError('llm down')

        with self.assertRaises(RuntimeError):
            pipeline.inject_block('s1', store, query='生日是哪天', max_chars=400,
                                  top_k=3, payload={'event_summarizer': boom})

    def test_incremental_only_reads_new_entries(self):
        store = store_with(ROWS[:1], flags={'event_layer': True})
        pipeline.inject_block('s1', store, query='生日', max_chars=800, top_k=3,
                              payload={'event_summarizer': stub_summarizer})
        state = pipeline._load_event_state(store, 's1')
        first = len(state.get('events') or [])
        mem = Path(store) / 'sessions' / 's1' / 'memory.json'
        mem.write_text(json.dumps({'entries': ROWS}), encoding='utf-8')
        # the store is sqlite now: the JSON file above is the import format
        pipeline.import_session_json(store, 's1', force=True)
        state = pipeline._load_event_state(store, 's1')
        self.assertEqual(state.get('seen'), 1)
        pipeline.inject_block('s1', store, query='生日', max_chars=800, top_k=3,
                              payload={'event_summarizer': stub_summarizer})
        after = pipeline._load_event_state(store, 's1')
        self.assertGreaterEqual(len(after.get('events') or []), first)
        self.assertEqual(after.get('seen'), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
