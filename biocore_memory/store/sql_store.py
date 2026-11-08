# -*- coding: utf-8 -*-
"""SQLite store: the structured half of a session (entries, events, claims, journal).

JSON stays the export/compat format; this module is the working store. Opening a
store that only has JSON imports it once, so old installs keep working.
"""
from __future__ import annotations

import json
import os
import sqlite3
import struct
import time
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS entries (
  id TEXT PRIMARY KEY, turn INTEGER, ts REAL, role TEXT, text TEXT,
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
CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, payload TEXT
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


def connect(root, session_id):
    path = db_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default


def import_session(root, session_id, force=False):
    """Load sessions/<sid>/memory.json, events/<sid>.json, journal/<sid>.jsonl."""
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
    events = _read_json(root / 'events' / (session_id + '.json'), {})
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


def open_or_import(root, session_id):
    """Never break an old install: import JSON when the db is missing."""
    root = Path(root)
    fresh = not db_path(root, session_id).exists()
    conn, info = import_session(root, session_id, force=False)
    info['fresh'] = fresh
    return conn, info


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
        for (eid,) in conn.execute("SELECT id FROM events").fetchall():
            if str(eid) not in live:
                conn.execute("DELETE FROM events WHERE id=?", (eid,))
        for ev in events or []:
            if not isinstance(ev, dict):
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
