# -*- coding: utf-8 -*-
"""SQLite store: the structured half of a session (entries, events, claims, journal).

JSON stays the export/compat format; this module is the working store. Opening a
store that only has JSON imports it once, so old installs keep working.
"""
from __future__ import annotations

import atexit
import contextlib
import json
import weakref
import os
import sqlite3
import struct
import time
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS entries (
  id TEXT PRIMARY KEY,
  -- 业务键：人能读、能引用、能当世界书/提示词里的触发词（借自 shujuku 的 code_index）
  code TEXT,
  -- 逻辑身份：只由内容决定，重排/换库/重新导入都不变
  semantic_id TEXT,
  turn INTEGER CHECK(turn IS NULL OR turn >= 0),
  ts REAL CHECK(ts IS NULL OR ts >= 0),
  role TEXT CHECK(role IS NULL OR role IN ('user', 'assistant', 'system')),
  -- 空条目没有意义：库这一层直接拒，不靠调用方自觉
  text TEXT NOT NULL CHECK(length(text) > 0),
  vector BLOB, hits INTEGER DEFAULT 1, importance REAL DEFAULT 0.2,
  deleted INTEGER DEFAULT 0, raw TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, start INTEGER, end INTEGER, overview TEXT,
  text TEXT, closed_ts REAL, payload TEXT, centroid BLOB
);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, subject TEXT, attr TEXT,
  value TEXT, canon TEXT, status TEXT, source TEXT, confidence REAL,
  entity TEXT, thread TEXT, turn INTEGER, event_id TEXT
);
CREATE TABLE IF NOT EXISTS event_state (
  session TEXT PRIMARY KEY, seen INTEGER, global_state TEXT, open_buf TEXT, updated REAL
);
CREATE TABLE IF NOT EXISTS changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, batch TEXT, op TEXT, entry_id TEXT, before TEXT, after TEXT
);
CREATE INDEX IF NOT EXISTS idx_changes_batch ON changes(batch);
CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS meta (
  k TEXT PRIMARY KEY, v TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_key ON claims(key);
CREATE INDEX IF NOT EXISTS idx_claims_thread ON claims(thread);
CREATE INDEX IF NOT EXISTS idx_journal_kind ON journal(kind);
CREATE INDEX IF NOT EXISTS idx_entries_turn ON entries(turn);
'''


def pack_vector(vec):
    if not vec:
        return None
    try:
        return struct.pack('<%df' % len(vec), *[float(x) for x in vec])
    except Exception:
        return None


def unpack_vector(blob):
    if not blob:
        return []
    try:
        return list(struct.unpack('<%df' % (len(blob) // 4), blob))
    except Exception:
        return []


def db_path(root, session_id):
    return Path(root) / 'sessions' / str(session_id) / 'memory.db'


_OPEN_CONNS = []          # weak refs only: a forgotten handle must not survive
                          # (a strong list would keep the file undeletable forever)


def _ensure_entries_schema(conn):
    """老库补 code 列并回填业务键（M0001 起）。

    约束（CHECK）只对新库生效——SQLite 不能给已有表加 CHECK，
    所以老库靠这条唯一索引 + 这里的一次回填保证不重号。
    """
    try:
        cols = [row[1] for row in conn.execute('PRAGMA table_info(entries)')]
        if 'code' not in cols:
            conn.execute('ALTER TABLE entries ADD COLUMN code TEXT')
        if 'semantic_id' not in cols:
            conn.execute('ALTER TABLE entries ADD COLUMN semantic_id TEXT')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_semantic'
                     ' ON entries(semantic_id) WHERE semantic_id IS NOT NULL')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_code'
                     ' ON entries(code) WHERE code IS NOT NULL')
        missing = conn.execute('SELECT id FROM entries WHERE code IS NULL'
                               ' ORDER BY rowid').fetchall()
        if missing:
            cur = conn.execute('SELECT COALESCE(MAX(CAST(SUBSTR(code, 2) AS INTEGER)), 0)'
                               ' FROM entries WHERE code LIKE \'M%\'').fetchone()
            n = int((cur or [0])[0] or 0)
            for row in missing:
                n += 1
                conn.execute('UPDATE entries SET code=? WHERE id=?',
                             ('M%04d' % n, row[0]))
        conn.commit()
    except Exception:
        pass


def connect(root, session_id):
    """A fresh connection per call; registered so store_close() can release it.

    Pooling was tried and removed: a held handle makes the temporary store
    directory undeletable on Windows (WinError 32). A registry is not pooling --
    it exists because a *forgotten* close is exactly the same bug, and callers
    that legitimately hold a handle (a test, a worker shutdown) need one way to
    let go of all of them.
    """
    path = db_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(SCHEMA)
    conn.commit()
    _ensure_entries_schema(conn)
    try:
        _OPEN_CONNS.append(weakref.ref(conn))
    except TypeError:       # a backend without weakref support: nothing to track
        pass
    return conn


def store_close(path=None):
    """Close every registered connection (or only those of one database).

    Safe to call from anywhere, any number of times: a closed handle is dropped
    from the registry, so the next connect() starts clean.
    """
    root = None
    if path is not None:
        root = str(Path(path).resolve())
    closed = 0
    keep = []
    for ref in list(_OPEN_CONNS):
        conn = ref() if callable(ref) else ref
        if conn is None:
            continue                  # already collected and closed by CPython
        if False:
            pass
        target = ""
        try:
            target = str(Path(conn.execute("PRAGMA database_list").fetchone()[2]))
        except Exception:
            target = ""
        if root is not None and target and Path(target).resolve().as_posix() != Path(root).as_posix():
            keep.append(conn)
            continue
        try:
            conn.commit()
        except Exception:
            pass
        try:
            conn.close()
            closed += 1
        except Exception:
            pass
    _OPEN_CONNS[:] = keep
    return closed


@contextlib.contextmanager
def store_open(root, session_id):
    """Hold one store connection for a block and release it on the way out."""
    conn = connect(root, session_id)
    try:
        yield conn
    finally:
        try:
            conn.commit()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        _OPEN_CONNS[:] = [ref for ref in _OPEN_CONNS
                          if (ref() if callable(ref) else ref) not in (None, conn)]


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default


def import_session(root, session_id, force=False, events_path=None):
    """Load sessions/<sid>/memory.json, events/<sid>.json, journal/<sid>.jsonl.

    events_path lets the caller keep its own event-file rule: the pipeline puts
    events under <dataDir>/events even when the store root is <dataDir>/memory.
    """
    root = Path(root)
    conn = connect(root, session_id)
    done = conn.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
    if done and not force:
        return conn, {'imported': False, 'entries': done}
    memory = _read_json(root / 'sessions' / session_id / 'memory.json', {})
    rows = memory.get('entries') if isinstance(memory, dict) else memory
    count = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        conn.execute(
            'INSERT OR REPLACE INTO entries (id,turn,ts,role,text,vector,hits,importance,deleted,raw)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?)',
            (str(row.get('id') or ''), int(row.get('turn') or 0), float(row.get('ts') or 0.0),
             str(row.get('role') or 'user'), str(row.get('text') or ''),
             pack_vector(row.get('vector')), int(row.get('hits') or 1),
             float(row.get('importance') or 0.2), 1 if row.get('deleted') else 0,
             json.dumps(row, ensure_ascii=False)))
        count += 1
    event_file = Path(events_path) if events_path is not None \
        else root / 'events' / (session_id + '.json')
    events = _read_json(event_file, {})
    for ev in (events.get('events') if isinstance(events, dict) else events) or []:
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get('event_id') or '')
        conn.execute(
            'INSERT OR REPLACE INTO events (id,start,end,overview,text,closed_ts,payload)'
            ' VALUES (?,?,?,?,?,?,?)',
            (eid, int(ev.get('start') or 0), int(ev.get('end') or 0),
             str(ev.get('overview') or ''), str(ev.get('text') or ''),
             float(ev.get('closed_ts') or 0.0), json.dumps(ev, ensure_ascii=False)))
        for claim in ev.get('claims') or []:
            if not isinstance(claim, dict):
                continue
            subject = str(claim.get('subject') or '')
            attr = str(claim.get('attr') or '')
            conn.execute(
                'INSERT INTO claims (key,subject,attr,value,canon,status,source,confidence,entity,thread,turn,event_id)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                ('%s·%s' % (subject, attr), subject, attr, str(claim.get('value') or ''),
                 str(claim.get('canon') or claim.get('value') or ''), str(claim.get('status') or 'current'),
                 str(claim.get('source') or 'unknown'), float(claim.get('confidence') or 0.0),
                 str(claim.get('entity') or ''), str(claim.get('thread') or ''),
                 int(claim.get('turn') or 0), eid))
    try:   # the event rows are the only place these vectors existed
        harvested = harvest_event_vectors(
            (events.get('events') if isinstance(events, dict) else events) or [])
        for entry_id, vector in harvested.items():
            blob = pack_vector(vector)
            if blob:
                conn.execute('UPDATE entries SET vector=? WHERE id=? AND vector IS NULL',
                             (blob, entry_id))
    except Exception:
        pass
    journal = root / 'journal' / (session_id + '.jsonl')
    if journal.exists():
        for line in journal.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            conn.execute('INSERT INTO journal (ts,kind,payload) VALUES (?,?,?)',
                         (float(row.get('ts') or 0.0), str(row.get('kind') or ''),
                          json.dumps(row, ensure_ascii=False)))
    conn.commit()
    return conn, {'imported': True, 'entries': count}


def export_session(conn, root, session_id):
    """Write the JSON files back so old readers keep working."""
    root = Path(root)
    rows = conn.execute('SELECT raw FROM entries ORDER BY turn').fetchall()
    entries = []
    for (raw,) in rows:
        try:
            entries.append(json.loads(raw))
        except Exception:
            continue
    path = root / 'sessions' / session_id / 'memory.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'entries': entries}, ensure_ascii=False), encoding='utf-8')
    return len(entries)


def harvest_event_vectors(events, open_buf=None):
    """Per-entry vectors carried by event rows: {entry_id: [floats]}.

    In the event-layer mode the only copy of a row's vector lives in the event
    that quotes it, so migrating to sqlite has to lift them into entries.vector
    or the two-stage recall loses its coordinates.
    """
    out = {}
    rows = list(events or []) + list(open_buf or [])
    for ev in rows:
        if not isinstance(ev, dict):
            continue
        for item in ev.get("entries") or []:
            if not isinstance(item, dict):
                continue
            entry_id = str(item.get("id") or "")
            vector = item.get("vector")
            if entry_id and isinstance(vector, (list, tuple)) and vector:
                out[entry_id] = list(vector)
    return out


def update_entry_vectors(root, session_id, vectors):
    """Write per-entry vectors into entries.vector (BLOB); unknown ids are skipped."""
    if not vectors:
        return 0
    root = Path(root)
    conn = connect(root, session_id)
    try:
        written = 0
        for entry_id, vector in vectors.items():
            blob = pack_vector(vector)
            if not blob:
                continue
            cur = conn.execute('UPDATE entries SET vector=? WHERE id=? AND vector IS NULL',
                               (blob, str(entry_id)))
            written += cur.rowcount or 0
        conn.commit()
        return written
    finally:
        conn.close()


def read_entry_vectors(root, session_id):
    """{entry_id: vector} for every row that has one (the recall coordinates)."""
    root = Path(root)
    conn = connect(root, session_id)
    try:
        out = {}
        for entry_id, blob in conn.execute(
                'SELECT id, vector FROM entries WHERE vector IS NOT NULL').fetchall():
            vector = unpack_vector(blob)
            if vector:
                out[str(entry_id)] = vector
        return out
    finally:
        conn.close()


class WriteNotVerified(RuntimeError):
    """写完回读对不上：库里的内容和要写的不是一回事。"""


def _verify_write(conn, changed, deleted):
    """写后回读校验：条数与文本都要对上，否则抛。

    「宿主保存成功」不等于「数据正确」——上一层的 ok 与这一层的事实是两件事。
    """
    for row in changed or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get('id') or '')
        got = conn.execute('SELECT text, deleted FROM entries WHERE id=?',
                           (rid,)).fetchone()
        want_text = str(row.get('text') or '')
        if row.get('deleted'):
            if not got or not got[1]:
                raise WriteNotVerified('删除标记没有落库: %s' % rid)
            continue
        if not got:
            raise WriteNotVerified('写入后读不到: %s' % rid)
        if str(got[0]) != want_text:
            raise WriteNotVerified('文本不一致: %s' % rid)
    for entry_id in deleted or []:
        got = conn.execute('SELECT 1 FROM entries WHERE id=?',
                           (str(entry_id),)).fetchone()
        if got:
            raise WriteNotVerified('删除没有生效: %s' % entry_id)


def _reinsert_from_raw(conn, entry_id, raw):
    """按 raw 里的完整字段把一行插回去（只写 id/raw 会撞 NOT NULL）。"""
    try:
        row = json.loads(raw) if raw else {}
    except Exception:
        row = {}
    conn.execute(
        'INSERT OR REPLACE INTO entries'
        ' (id,code,turn,ts,role,text,vector,hits,importance,deleted,raw)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (entry_id, row.get('code'), int(row.get('turn') or 0),
         float(row.get('ts') or 0.0), str(row.get('role') or 'user'),
         str(row.get('text') or '(恢复时缺失)'),
         pack_vector(row.get('vector')), int(row.get('hits') or 1),
         float(row.get('importance') or 0.2), 0, raw))


def changes_tail(root, session_id, limit=50):
    conn = connect(root, session_id)
    try:
        rows = conn.execute('SELECT ts,batch,op,entry_id FROM changes'
                            ' ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
        return [{'ts': r[0], 'batch': r[1], 'op': r[2], 'entry_id': r[3]} for r in rows]
    finally:
        conn.close()


def undo_batch(root, session_id, batch):
    """把某一批变更撤回去（删除的恢复、写入的还原或删掉）。"""
    conn = connect(root, session_id)
    try:
        rows = conn.execute('SELECT op,entry_id,before,after FROM changes'
                            ' WHERE batch=? ORDER BY id DESC', (str(batch),)).fetchall()
        for op, entry_id, before, after in rows:
            if op == 'delete':
                if before:
                    _reinsert_from_raw(conn, str(entry_id), before)
            else:
                if before:
                    conn.execute('UPDATE entries SET raw=? WHERE id=?',
                                 (before, str(entry_id)))
                else:
                    conn.execute('DELETE FROM entries WHERE id=?', (str(entry_id),))
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def read_doc(root, session_id, with_vectors=False):
    """The session document as the JSON file used to hold it.

    Insert order is rowid order, which is exactly the order the old file kept,
    so an export round-trips byte for byte.
    """
    root = Path(root)
    conn = connect(root, session_id)
    try:
        meta = {}
        try:
            for key, value in conn.execute('SELECT k, v FROM meta').fetchall():
                meta[str(key)] = value
        except Exception:
            meta = {}
        entries = []
        # the vector lives in its own BLOB column, not in `raw`: reading only
        # `raw` is why recall saw vector=None on every row
        columns = 'raw, vector, code, semantic_id' if with_vectors else 'raw, code, semantic_id'
        for row in conn.execute('SELECT %s FROM entries ORDER BY rowid' % columns).fetchall():
            raw = row[0]
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            # 业务键以列为准（老库是迁移回填的，raw 里没有）
            code = row[-2] if len(row) > 1 else None
            if code:
                entry['code'] = str(code)
            sid = row[-1]
            if sid:
                entry['semantic_id'] = str(sid)
            if with_vectors:
                blob = row[1] if len(row) > 1 else None
                entry['vector'] = unpack_vector(blob)
            entries.append(entry)
        try:
            schema_version = int(meta.get('schema_version') or 1)
        except Exception:
            schema_version = 1
        return {'schema_version': schema_version,
                'session_id': str(meta.get('session_id') or session_id),
                'entries': entries}
    finally:
        conn.close()


def read_entry_rows(root, session_id):
    """id -> raw JSON, in insertion order (the diff baseline for incremental writes)."""
    root = Path(root)
    conn = connect(root, session_id)
    try:
        rows = conn.execute('SELECT id, raw FROM entries ORDER BY rowid').fetchall()
        return [(str(rid or ''), raw or '') for rid, raw in rows]
    finally:
        conn.close()


def write_doc(root, session_id, doc, changed=None, deleted=None, stamp_meta=True):
    """Upsert only the entries that changed; never rewrite the whole table.

    changed: iterable of entry dicts (or None to mean "everything in doc")
    deleted: iterable of ids to drop
    """
    root = Path(root)
    conn = connect(root, session_id)
    try:
        if stamp_meta:
            for key, value in (('schema_version', doc.get('schema_version', 1)),
                               ('session_id', doc.get('session_id', session_id))):
                conn.execute('INSERT INTO meta (k, v) VALUES (?, ?)'
                             ' ON CONFLICT(k) DO UPDATE SET v=excluded.v',
                             (key, str(value)))
        batch = '%d' % int(time.time() * 1000)
        rows = doc.get('entries') if isinstance(doc.get('entries'), list) else []
        if changed is None:
            changed = rows
        for row in changed:
            if not isinstance(row, dict):
                continue
            _sid = str(row.get('semantic_id') or '')
            if not _sid:
                try:
                    from biocore_memory import semantic_identity as _si
                    _sid = _si.semantic_id(session_id, row.get('ts'),
                                           row.get('role'), row.get('text'))
                except Exception:
                    _sid = ''
            code = str(row.get('code') or '')
            if not code:
                cur = conn.execute('SELECT COALESCE(MAX(CAST(SUBSTR(code, 2) AS INTEGER)), 0)'
                                   ' FROM entries WHERE code LIKE \'M%\'').fetchone()
                code = 'M%04d' % (int((cur or [0])[0] or 0) + 1)
                row['code'] = code
            _prev = conn.execute('SELECT raw FROM entries WHERE id=?',
                                 (str(row.get('id') or ''),)).fetchone()
            conn.execute(
                'INSERT INTO entries (id,code,semantic_id,turn,ts,role,text,vector,hits,importance,deleted,raw)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET'
                ' code=COALESCE(entries.code, excluded.code),'
                ' semantic_id=COALESCE(entries.semantic_id, excluded.semantic_id), turn=excluded.turn,'
                ' ts=excluded.ts, role=excluded.role, text=excluded.text,'
                ' vector=excluded.vector, hits=excluded.hits, importance=excluded.importance,'
                ' deleted=excluded.deleted, raw=excluded.raw',
                (str(row.get('id') or ''), code, _sid, int(row.get('turn') or 0),
                 float(row.get('ts') or 0.0), str(row.get('role') or 'user'),
                 str(row.get('text') or ''), pack_vector(row.get('vector')),
                 int(row.get('hits') or 1), float(row.get('importance') or 0.2),
                 1 if row.get('deleted') else 0,
                 json.dumps(row, ensure_ascii=False)))
            conn.execute('INSERT INTO changes (ts,batch,op,entry_id,before,after)'
                         ' VALUES (?,?,?,?,?,?)',
                         (time.time(), batch, 'upsert', str(row.get('id') or ''),
                          _prev[0] if _prev else None,
                          json.dumps(row, ensure_ascii=False)))
        for entry_id in deleted or []:
            prev = conn.execute('SELECT raw FROM entries WHERE id=?',
                                (str(entry_id),)).fetchone()
            conn.execute('INSERT INTO changes (ts,batch,op,entry_id,before,after)'
                         ' VALUES (?,?,?,?,?,?)',
                         (time.time(), batch, 'delete', str(entry_id),
                          prev[0] if prev else None, None))
            conn.execute('DELETE FROM entries WHERE id=?', (str(entry_id),))
        conn.commit()
        _verify_write(conn, changed, deleted)
        return True
    finally:
        conn.close()


def export_doc_json(root, session_id, path=None):
    """Write the session document back out as JSON (export/debug only)."""
    doc = read_doc(root, session_id)
    if path is None:
        path = Path(root) / 'sessions' / session_id / 'memory.json'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path


def export_events_json(root, session_id, path=None):
    """The event table as the old events/<sid>.json payload (export/debug only)."""
    state = load_event_state(root, session_id) or {'seen': 0, 'events': [], 'state': {}, 'open': []}
    payload = {'seen': int(state.get('seen') or 0), 'events': state.get('events') or [],
               'state': state.get('state') or {}, 'open': state.get('open') or []}
    if path is None:
        path = Path(root) / 'events' / (session_id + '.json')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path


def claims_by_thread(conn, thread=None, limit=50):
    if thread:
        rows = conn.execute('SELECT key,value,status,confidence,thread,turn FROM claims'
                            ' WHERE thread=? ORDER BY turn DESC LIMIT ?', (thread, limit)).fetchall()
    else:
        rows = conn.execute('SELECT key,value,status,confidence,thread,turn FROM claims'
                            ' ORDER BY turn DESC LIMIT ?', (limit,)).fetchall()
    return [{'key': r[0], 'value': r[1], 'status': r[2], 'confidence': r[3],
             'thread': r[4], 'turn': r[5]} for r in rows]


def journal_tail(conn, limit=50, kind=None):
    if kind:
        rows = conn.execute('SELECT ts,kind,payload FROM journal WHERE kind=?'
                            ' ORDER BY id DESC LIMIT ?', (kind, limit)).fetchall()
    else:
        rows = conn.execute('SELECT ts,kind,payload FROM journal ORDER BY id DESC LIMIT ?',
                            (limit,)).fetchall()
    out = []
    for ts, kind_, payload in rows:
        try:
            out.append(json.loads(payload))
        except Exception:
            out.append({'ts': ts, 'kind': kind_})
    return out


def close_connections(path=None):
    """Alias kept for the test helper: every store handle is released."""
    return store_close(path)


def backfill_vectors(root, session_id, events_path=None):
    """One-time: lift per-entry vectors out of the legacy event file.

    Databases written before the cutover stored event payloads without vectors,
    so a run that finds rows lacking coordinates repairs them from the JSON the
    events were originally built from. Idempotent: a fully populated table is a
    single COUNT.
    """
    root = Path(root)
    conn = connect(root, session_id)
    try:
        done = conn.execute(
            "SELECT v FROM meta WHERE k='vector_backfill'").fetchone()
        if done is not None:
            return 0          # one-shot: new rows get their vector from the save path
        missing = conn.execute(
            'SELECT COUNT(*) FROM entries WHERE vector IS NULL').fetchone()[0]
        if not missing:
            conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('vector_backfill','1')")
            conn.commit()
            return 0
        event_file = Path(events_path) if events_path is not None \
            else root / 'events' / (session_id + '.json')
        legacy = _read_json(event_file, {})
        rows = legacy.get('events') if isinstance(legacy, dict) else legacy
        vectors = harvest_event_vectors(rows or [])
        written = 0
        for entry_id, vector in vectors.items():
            blob = pack_vector(vector)
            if not blob:
                continue
            cur = conn.execute(
                'UPDATE entries SET vector=? WHERE id=? AND vector IS NULL',
                (blob, str(entry_id)))
            written += cur.rowcount or 0
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('vector_backfill','1')")
        conn.commit()
        return written
    except Exception:
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def open_or_import(root, session_id, events_path=None):
    """Never break an old install: import JSON when the db is missing."""
    root = Path(root)
    fresh = not db_path(root, session_id).exists()
    conn, info = import_session(root, session_id, force=False, events_path=events_path)
    # the caller owns the connection (legacy contract): never close it here
    info['vectors'] = backfill_vectors(root, session_id, events_path=events_path)
    info['fresh'] = fresh
    return conn, info


atexit.register(store_close)


def _ensure_events_centroid(conn):
    """Old databases predate the centroid column; add it in place."""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        if "centroid" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN centroid BLOB")
    except Exception:
        pass


def pack_vector(vector):
    """float32 BLOB: an event centroid costs 4 KB instead of ~20 KB of JSON text."""
    try:
        import struct
        rows = [float(x) for x in (vector or [])]
        if not rows:
            return None
        return struct.pack("<%df" % len(rows), *rows)
    except Exception:
        return None


def unpack_vector(blob):
    try:
        import struct
        if not blob:
            return []
        return list(struct.unpack("<%df" % (len(blob) // 4), blob))
    except Exception:
        return []


def _event_payload(ev):
    """The event row minus the per-entry vectors, which hydrate from the cache."""
    out = dict(ev or {})
    rows = []
    for item in ev.get("entries") or []:
        if not isinstance(item, dict):
            continue
        rows.append({key: item.get(key) for key in
                     ("id", "turn", "ts", "role", "text")})
    out["entries"] = rows
    out.pop("vector", None)
    return out


def save_event_state(root, session_id, seen, events, global_state, open_buf):
    """Incrementally upsert the session's events; no whole-table rewrite."""
    conn = connect(root, session_id)
    try:
        _ensure_events_centroid(conn)
        live = {str(ev.get("event_id") or "") for ev in (events or [])
                if isinstance(ev, dict)}
        # cheap fingerprint of what is already on disk: one small SELECT, then
        # only the rows that actually changed are written (a closed event never
        # changes again, so a turn that closes one event writes one row)
        existing = {}
        try:
            for row in conn.execute(
                    "SELECT id, start, end, overview, length(text) FROM events").fetchall():
                existing[str(row[0])] = (int(row[1] or 0), int(row[2] or 0),
                                         str(row[3] or ""), int(row[4] or 0))
        except Exception:
            existing = {}
        for (eid,) in conn.execute("SELECT id FROM events").fetchall():
            if str(eid) not in live:
                conn.execute("DELETE FROM events WHERE id=?", (eid,))
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            key = (str(ev.get("event_id") or ""), int(ev.get("start") or 0),
                   int(ev.get("end") or 0), str(ev.get("overview") or ""),
                   len(str(ev.get("text") or "")))
            if existing.get(key[0]) == key[1:]:
                continue
            conn.execute(
                "INSERT INTO events (id,start,end,overview,text,closed_ts,payload,centroid)"
                " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET"
                " start=excluded.start, end=excluded.end, overview=excluded.overview,"
                " text=excluded.text, closed_ts=excluded.closed_ts,"
                " payload=excluded.payload, centroid=excluded.centroid",
                (str(ev.get("event_id") or ""), int(ev.get("start") or 0),
                 int(ev.get("end") or 0), str(ev.get("overview") or ""),
                 str(ev.get("text") or ""), float(ev.get("closed_ts") or 0.0),
                 json.dumps(_event_payload(ev), ensure_ascii=False),
                 pack_vector(ev.get("vector"))))
        conn.execute(
            "INSERT INTO event_state (session,seen,global_state,open_buf,updated)"
            " VALUES (?,?,?,?,?) ON CONFLICT(session) DO UPDATE SET"
            " seen=excluded.seen, global_state=excluded.global_state,"
            " open_buf=excluded.open_buf, updated=excluded.updated",
            (session_id, int(seen or 0), json.dumps(global_state or {}, ensure_ascii=False),
             json.dumps(open_buf or [], ensure_ascii=False), time.time()))
        conn.commit()
        return True
    finally:
        conn.close()


def load_event_state(root, session_id):
    """Read back what save_event_state wrote; None when the session is new."""
    import os as _os
    if not db_path(root, session_id).exists() and not _os.environ.get("BIOCORE_SQL_FIRST"):
        return None
    conn = connect(root, session_id)
    try:
        row = conn.execute("SELECT seen, global_state, open_buf FROM event_state WHERE session=?",
                           (session_id,)).fetchone()
        events = []
        try:
            rows = conn.execute(
                "SELECT payload, centroid FROM events ORDER BY start").fetchall()
        except Exception:
            rows = [(p, None) for (p,) in conn.execute(
                "SELECT payload FROM events ORDER BY start").fetchall()]
        for payload, centroid in rows:
            try:
                ev = json.loads(payload)
            except Exception:
                continue
            if centroid:
                ev["vector"] = unpack_vector(centroid)
            events.append(ev)
        if row is None and not events:
            return None
        seen = int((row or [0])[0] or 0)
        try:
            state = json.loads((row or [0, "{}"])[1] or "{}")
        except Exception:
            state = {}
        try:
            open_buf = json.loads((row or [0, "{}", "[]"])[2] or "[]")
        except Exception:
            open_buf = []
        return {"seen": seen, "events": events, "state": state, "open": open_buf}
    finally:
        conn.close()