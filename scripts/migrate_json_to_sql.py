# -*- coding: utf-8 -*-
"""Import an existing JSON store into SQLite (idempotent, dry-run friendly).

Usage:
  python scripts/migrate_json_to_sql.py <store_root> [session ...] [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from biocore_memory.store import sql_store as S


def discover(root):
    sessions = root / 'sessions'
    if not sessions.exists():
        return []
    return sorted(p.name for p in sessions.iterdir() if p.is_dir())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('sessions', nargs='*')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    root = Path(args.root)
    targets = args.sessions or discover(root)
    if not targets:
        print('no sessions found under %s' % (root / 'sessions'))
        return 1
    for sid in targets:
        if args.dry_run:
            memory = root / 'sessions' / sid / 'memory.json'
            events = root / 'events' / (sid + '.json')
            journal = root / 'journal' / (sid + '.jsonl')
            print('%-16s memory=%s events=%s journal=%s db=%s'
                  % (sid, memory.exists(), events.exists(), journal.exists(),
                     S.db_path(root, sid).exists()))
            continue
        conn, info = S.import_session(root, sid, force=args.force)
        claims = conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0]
        events = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        journal = conn.execute('SELECT COUNT(*) FROM journal').fetchone()[0]
        conn.close()
        print('%-16s imported=%s entries=%d events=%d claims=%d journal=%d'
              % (sid, info.get('imported'), info.get('entries', 0), events, claims, journal))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
