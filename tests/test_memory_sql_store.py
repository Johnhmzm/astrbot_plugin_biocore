# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from biocore_memory.store import sql_store as S


def make_store(root):
    root = Path(root)
    (root / 'sessions' / 's1').mkdir(parents=True, exist_ok=True)
    (root / 'events').mkdir(parents=True, exist_ok=True)
    (root / 'journal').mkdir(parents=True, exist_ok=True)
    (root / 'sessions' / 's1' / 'memory.json').write_text(json.dumps({'entries': [
        {'id': 'e1', 'turn': 1, 'ts': 1.0, 'role': 'user', 'text': '叶楠生日八月十六',
         'vector': [0.1, 0.2], 'hits': 1, 'importance': 0.2},
        {'id': 'e2', 'turn': 2, 'ts': 2.0, 'role': 'user', 'text': '改成八月十八',
         'vector': [0.3, 0.4], 'hits': 2, 'importance': 0.2},
    ]}, ensure_ascii=False), encoding='utf-8')
    (root / 'events' / 's1.json').write_text(json.dumps({'events': [
        {'event_id': 'EV001', 'start': 1, 'end': 2, 'overview': '叶楠生日',
         'text': '...', 'claims': [
             {'subject': '叶楠', 'attr': '生日', 'value': '八月十八', 'status': 'current',
              'source': 'direct', 'confidence': 0.82, 'entity': '叶楠',
              'thread': '叶楠生日', 'turn': 2}]}]}, ensure_ascii=False), encoding='utf-8')
    (root / 'journal' / 's1.jsonl').write_text(
        '{"ts": 1.0, "kind": "inject", "lines": 3}\n', encoding='utf-8')
    return root


class SqlStoreTest(unittest.TestCase):
    def test_imports_old_json_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp)
            conn, info = S.open_or_import(root, 's1')
            self.assertTrue(info['imported'])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM entries').fetchone()[0], 2)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM journal').fetchone()[0], 1)
            conn.close()

    def test_second_open_does_not_reimport(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp)
            S.open_or_import(root, 's1')[0].close()
            conn, info = S.open_or_import(root, 's1')
            self.assertFalse(info['imported'])
            conn.close()

    def test_vectors_roundtrip(self):
        blob = S.pack_vector([0.5, -0.25])
        self.assertEqual([round(x, 4) for x in S.unpack_vector(blob)], [0.5, -0.25])

    def test_claims_by_thread_and_journal_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp)
            conn, _ = S.open_or_import(root, 's1')
            rows = S.claims_by_thread(conn, '叶楠生日')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['value'], '八月十八')
            tail = S.journal_tail(conn, kind='inject')
            self.assertEqual(tail[0]['lines'], 3)
            conn.close()

    def test_export_writes_json_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp)
            conn, _ = S.open_or_import(root, 's1')
            self.assertEqual(S.export_session(conn, root, 's1'), 2)
            data = json.loads((Path(root) / 'sessions' / 's1' / 'memory.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['entries']), 2)
            conn.close()


if __name__ == '__main__':
    unittest.main()
