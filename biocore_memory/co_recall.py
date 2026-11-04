# -*- coding: utf-8 -*-
"""task-187: co-recall statistics -- first step: count and mark, never merge.

Two memories that keep being recalled in the same batch probably point at the
same thing. This module only keeps the score; it never changes recall, never
drops an entry, never merges anything and never calls a model:

- pure functions: normalize_id / unique_ids / pair_key / pairs turn one recall
  batch into unordered id pairs (a duplicate inside one batch counts once);
- thin storage layer: table co_recall(pair_a, pair_b, count, first_ts, last_ts)
  in memory/memory.sqlite3, upserted once per batch;
- candidates(threshold=3, window_days=30): pairs that crossed the threshold
  inside the recent window (read only);
- mark_candidates(): writes co_recall_marks (a separate table) so the panel can
  show "mergeable candidates", without touching entries;
- read_marked() / stats() / readout(): read-only entry points for the panel or
  a command. Wiring into main.py is intentionally left for the caller.

Hard boundaries: no LLM call, no change to the recall output or its thresholds,
no import of main.py. IO lives in the storage layer on purpose.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_THRESHOLD = 3
DEFAULT_WINDOW_DAYS = 30.0
SQLITE_FILE = "memory.sqlite3"
TABLE_RECALL = "co_recall"
TABLE_MARKS = "co_recall_marks"
DAY_SECONDS = 86400.0
MAX_LIMIT = 500

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _PLUGIN_ROOT / "memory" / SQLITE_FILE

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS co_recall(
    pair_a TEXT NOT NULL,
    pair_b TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    first_ts REAL NOT NULL,
    last_ts REAL NOT NULL,
    PRIMARY KEY (pair_a, pair_b)
);
CREATE INDEX IF NOT EXISTS idx_co_recall_last ON co_recall(last_ts);
CREATE INDEX IF NOT EXISTS idx_co_recall_count ON co_recall(count);
CREATE TABLE IF NOT EXISTS co_recall_marks(
    pair_a TEXT NOT NULL,
    pair_b TEXT NOT NULL,
    marked_ts REAL NOT NULL,
    threshold INTEGER NOT NULL,
    window_days REAL NOT NULL,
    PRIMARY KEY (pair_a, pair_b)
);
"""


# ------------------------------------------------------------ pure functions
def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    if number != number or number in (float("inf"), float("-inf")):
        return float(default)
    return number


def normalize_id(value):
    """One memory id as a clean string; containers and blanks become ''."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def unique_ids(ids):
    """Preserve order, drop blanks and duplicates (one batch, one occurrence)."""
    seen = []
    if not isinstance(ids, (list, tuple, set)):
        return seen
    for raw in ids:
        ident = normalize_id(raw)
        if ident and ident not in seen:
            seen.append(ident)
    return seen


def pair_key(a, b):
    """Unordered key (a, b) with a < b; None when it is not a real pair."""
    left = normalize_id(a)
    right = normalize_id(b)
    if not left or not right or left == right:
        return None
    return (left, right) if left < right else (right, left)


def pairs(ids):
    """All unordered pairs from one recall batch, sorted and de-duplicated."""
    row = unique_ids(ids)
    found = set()
    for index in range(len(row)):
        for other in range(index + 1, len(row)):
            key = pair_key(row[index], row[other])
            if key is not None:
                found.add(key)
    return sorted(found)


def qualifies(count, last_ts, threshold=DEFAULT_THRESHOLD,
              window_days=DEFAULT_WINDOW_DAYS, now=None):
    """Pure version of the candidates rule (read-only, no storage)."""
    limit = max(1, int(_num(threshold, DEFAULT_THRESHOLD)))
    days = _num(window_days, DEFAULT_WINDOW_DAYS)
    current = _now(now)
    if int(_num(count, 0.0)) < limit:
        return False
    if days <= 0.0:
        return True
    return _num(last_ts, 0.0) >= current - days * DAY_SECONDS


def _now(now=None):
    try:
        return float(now if now is not None else time.time())
    except Exception:
        return time.time()


# ----------------------------------------------------------- storage layer
def default_db_path():
    """Where a plugin data dir keeps memory/memory.sqlite3."""
    return DEFAULT_DB_PATH


def ensure_schema(conn):
    """Create the two additive tables; safe to call on every open."""
    conn.executescript(SCHEMA_SQL)
    return True


def connect(db_path=None):
    """Open (and initialize) the memory DB. Caller owns the connection."""
    path = DEFAULT_DB_PATH if db_path is None else Path(db_path)
    if str(path) != ":memory:":
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    ensure_schema(conn)
    return conn


@contextmanager
def _session(db_path=None, conn=None):
    owned = conn is None
    db = conn if conn is not None else connect(db_path)
    if not owned:
        ensure_schema(db)
    try:
        yield db
        if owned:
            db.commit()
    finally:
        if owned:
            db.close()


def record_recall(ids, ts=None, db_path=None, conn=None):
    """Count one recall batch. Unordered pairs; duplicate ids counted once."""
    batch = pairs(ids)
    stamp = _now(ts)
    row = unique_ids(ids)
    if not batch:
        return {"pairs": 0, "ids": len(row), "ts": stamp}
    with _session(db_path, conn) as db:
        db.executemany(
            "INSERT INTO co_recall(pair_a, pair_b, count, first_ts, last_ts) "
            "VALUES(?, ?, 1, ?, ?) "
            "ON CONFLICT(pair_a, pair_b) DO UPDATE SET "
            "count = co_recall.count + 1, last_ts = excluded.last_ts",
            [(left, right, stamp, stamp) for left, right in batch])
    return {"pairs": len(batch), "ids": len(row), "ts": stamp}


def _threshold(value):
    return max(1, int(_num(value, DEFAULT_THRESHOLD)))


def _window_days(value):
    return max(0.0, _num(value, DEFAULT_WINDOW_DAYS))


def _row_dict(row, current):
    left = str(row["pair_a"])
    right = str(row["pair_b"])
    last_ts = _num(row["last_ts"], 0.0)
    return {
        "pair": (left, right),
        "pair_a": left,
        "pair_b": right,
        "count": int(_num(row["count"], 0.0)),
        "first_ts": round(_num(row["first_ts"], 0.0), 3),
        "last_ts": round(last_ts, 3),
        "age_days": round(max(0.0, (current - last_ts) / DAY_SECONDS), 2),
        "marked": bool(row["marked"]),
    }


def candidates(threshold=DEFAULT_THRESHOLD,
               window_days=DEFAULT_WINDOW_DAYS, now=None, db_path=None,
               conn=None):
    """Pairs with count >= threshold whose last co-recall is inside the window."""
    limit = _threshold(threshold)
    days = _window_days(window_days)
    current = _now(now)
    sql = ("SELECT r.pair_a, r.pair_b, r.count, r.first_ts, r.last_ts, "
           "CASE WHEN m.pair_a IS NULL THEN 0 ELSE 1 END AS marked "
           "FROM co_recall r LEFT JOIN co_recall_marks m "
           "ON m.pair_a = r.pair_a AND m.pair_b = r.pair_b "
           "WHERE r.count >= ?")
    args = [limit]
    if days > 0.0:
        sql += " AND r.last_ts >= ?"
        args.append(current - days * DAY_SECONDS)
    sql += " ORDER BY r.count DESC, r.last_ts DESC, r.pair_a ASC, r.pair_b ASC"
    with _session(db_path, conn) as db:
        rows = db.execute(sql, args).fetchall()
    return [_row_dict(row, current) for row in rows]


def mark_candidates(threshold=DEFAULT_THRESHOLD,
                    window_days=DEFAULT_WINDOW_DAYS, now=None, db_path=None,
                    conn=None):
    """Mark over-threshold pairs as mergeable; no deletion, no merging."""
    limit = _threshold(threshold)
    days = _window_days(window_days)
    current = _now(now)
    rows = candidates(limit, days, current, db_path, conn)
    if not rows:
        return {"marked": 0, "threshold": limit, "window_days": days,
                "pairs": []}
    with _session(db_path, conn) as db:
        db.executemany(
            "INSERT INTO co_recall_marks(pair_a, pair_b, marked_ts, threshold, "
            "window_days) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(pair_a, pair_b) DO UPDATE SET "
            "marked_ts = excluded.marked_ts, threshold = excluded.threshold, "
            "window_days = excluded.window_days",
            [(row["pair_a"], row["pair_b"], current, limit, days)
             for row in rows])
    return {"marked": len(rows), "threshold": limit, "window_days": days,
            "pairs": rows}


def read_marked(db_path=None, conn=None, limit=None):
    """Read-only: every marked pair, newest mark first."""
    sql = ("SELECT m.pair_a, m.pair_b, m.marked_ts, m.threshold, "
           "m.window_days, COALESCE(r.count, 0) AS count, "
           "COALESCE(r.first_ts, 0.0) AS first_ts, "
           "COALESCE(r.last_ts, 0.0) AS last_ts "
           "FROM co_recall_marks m LEFT JOIN co_recall r "
           "ON r.pair_a = m.pair_a AND r.pair_b = m.pair_b "
           "ORDER BY m.marked_ts DESC, m.pair_a ASC, m.pair_b ASC")
    args = []
    if limit is not None:
        size = int(_num(limit, 0.0))
        if size > 0:
            sql += " LIMIT ?"
            args.append(min(size, MAX_LIMIT))
    with _session(db_path, conn) as db:
        rows = db.execute(sql, args).fetchall()
    out = []
    for row in rows:
        left = str(row["pair_a"])
        right = str(row["pair_b"])
        out.append({
            "pair": (left, right),
            "pair_a": left,
            "pair_b": right,
            "count": int(_num(row["count"], 0.0)),
            "marked_ts": round(_num(row["marked_ts"], 0.0), 3),
            "threshold": int(_num(row["threshold"], DEFAULT_THRESHOLD)),
            "window_days": round(_num(row["window_days"],
                                      DEFAULT_WINDOW_DAYS), 2),
        })
    return out


def stats(db_path=None, conn=None):
    """Read-only totals: pairs, co-recall events, marked pairs."""
    with _session(db_path, conn) as db:
        row = db.execute("SELECT COUNT(*) AS pairs, "
                         "COALESCE(SUM(count), 0) AS recalls "
                         "FROM co_recall").fetchone()
        marked = db.execute("SELECT COUNT(*) AS marked "
                            "FROM co_recall_marks").fetchone()
    return {
        "pairs": int(_num(row["pairs"], 0.0)),
        "recalls": int(_num(row["recalls"], 0.0)),
        "marked": int(_num(marked["marked"], 0.0)),
    }


def readout(threshold=DEFAULT_THRESHOLD, window_days=DEFAULT_WINDOW_DAYS,
            now=None, db_path=None, conn=None, limit=20):
    """Bounded read-only view for a panel page or a command reply."""
    limit = max(1, min(int(_num(limit, 20.0)), MAX_LIMIT))
    rows = candidates(threshold, window_days, now, db_path, conn)
    return {
        "threshold": _threshold(threshold),
        "window_days": round(_window_days(window_days), 2),
        "stats": stats(db_path, conn),
        "candidates": rows[:limit],
    }
