# -*- coding: utf-8 -*-
"""写入日志、写后回读校验、撤销一批。"""
import sqlite3

import pytest

from biocore_memory.store import sql_store as S


def _store(tmp_path):
    return str(tmp_path)


def test_writes_are_recorded_with_a_batch_id(tmp_path):
    store = _store(tmp_path)
    S.write_doc(store, 's', {'entries': [{'id': 'a', 'turn': 1, 'ts': 1.0,
                                         'role': 'user', 'text': '第一句'}]})
    tail = S.changes_tail(store, 's')
    assert tail and tail[0]['op'] == 'upsert'
    assert tail[0]['batch']


def test_undo_restores_a_deleted_row(tmp_path):
    store = _store(tmp_path)
    doc = {'entries': [{'id': 'a', 'turn': 1, 'ts': 1.0, 'role': 'user', 'text': '第一句'},
                       {'id': 'b', 'turn': 2, 'ts': 2.0, 'role': 'user', 'text': '第二句'}]}
    S.write_doc(store, 's', doc)
    S.write_doc(store, 's', {'entries': []}, deleted=['a'])
    assert len(S.read_entry_rows(store, 's')) == 1
    batch = S.changes_tail(store, 's', limit=1)[0]['batch']
    S.undo_batch(store, 's', batch)
    assert len(S.read_entry_rows(store, 's')) == 2


def test_postcondition_catches_a_missing_row(tmp_path):
    store = _store(tmp_path)
    conn = S.connect(store, 's')
    try:
        S._verify_write(conn, [{'id': 'ghost', 'text': '从未写入'}], [])
    except S.WriteNotVerified as exc:
        assert 'ghost' in str(exc)
    else:
        raise AssertionError('回读校验没有拦住缺失的行')
    finally:
        conn.close()


def test_postcondition_catches_a_text_mismatch(tmp_path):
    store = _store(tmp_path)
    S.write_doc(store, 's', {'entries': [{'id': 'a', 'turn': 1, 'ts': 1.0,
                                         'role': 'user', 'text': '原文'}]})
    conn = S.connect(store, 's')
    try:
        S._verify_write(conn, [{'id': 'a', 'text': '被改过的文本'}], [])
    except S.WriteNotVerified as exc:
        assert '不一致' in str(exc)
    else:
        raise AssertionError('文本不一致没有被拦住')
    finally:
        conn.close()


def test_empty_text_is_rejected_by_the_schema(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        S.write_doc(store, 's', {'entries': [{'id': 'x', 'turn': 1, 'ts': 1.0,
                                             'role': 'user', 'text': ''}]})
