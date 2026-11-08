# -*- coding: utf-8 -*-
"""Debounced persistence for MemoryStore: batch writes, never lose data."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biocore_memory.store.json_store import MemoryStore  # noqa: E402


def make_store():
    path = Path(tempfile.mkdtemp()) / 'memory.json'
    return MemoryStore(path=path)


class DebounceTest(unittest.TestCase):

    def test_hundred_writes_do_at_most_five_saves(self):
        store = make_store()
        for index in range(100):
            store.add({'id': 'e%d' % index, 'text': '第%d条记忆内容' % index, 'ts': index})
        self.assertLessEqual(store._saves, 5)
        self.assertEqual(len(store.entries), 100)

    def test_flush_writes_everything(self):
        store = make_store()
        for index in range(30):
            store.add({'id': 'e%d' % index, 'text': '记忆内容 %d' % index, 'ts': index})
        store.flush()
        doc = json.loads(store.path.read_text(encoding='utf-8'))
        self.assertEqual(len(doc['entries']), 30)
        self.assertEqual(doc['entries'][-1]['id'], 'e29')

    def test_exception_path_keeps_data_and_flushes(self):
        store = make_store()
        store.add({'id': 'a', 'text': '异常前的记忆', 'ts': 1})
        original = store.save
        calls = {'n': 0}

        def flaky(path=None):
            calls['n'] += 1
            if calls['n'] == 1:
                raise OSError('disk full')
            return original(path)

        store.save = flaky
        store._dirty = 20          # force a flush inside the write path
        with self.assertRaises(OSError):
            store.flush()
        self.assertGreaterEqual(store._dirty, 1)   # still dirty after the failure
        store.flush()                                # a later flush succeeds
        doc = json.loads(store.path.read_text(encoding='utf-8'))
        self.assertEqual(len(doc['entries']), 1)

    def test_context_manager_flushes_on_exit(self):
        path = Path(tempfile.mkdtemp()) / 'memory.json'
        with MemoryStore(path=path) as store:
            store.add({'id': 'x', 'text': '上下文退出时落盘', 'ts': 2})
        doc = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(doc['entries'][0]['id'], 'x')


if __name__ == '__main__':
    unittest.main(verbosity=2)
