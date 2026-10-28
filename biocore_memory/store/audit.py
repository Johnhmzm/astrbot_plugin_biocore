# -*- coding: utf-8 -*-
"""Append-only JSONL audit log with size rotation (pure store helper; no AstrBot).

Module is disabled by default: callers MUST check `enabled` before wiring it.
The helper never reads business state and never calls LLMs; it only appends rows
and rotates the active file to "<name>.1" after it grows beyond 5 MB.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

enabled = False
AUDIT_ENABLED = enabled

MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TAIL = 50


class _AuditFile:
    def __init__(self, path):
        self.path = Path(path)

    def _line(self, record) -> str:
        row = dict(record) if isinstance(record, dict) else {"value": record}
        row.setdefault("ts", round(time.time(), 6))
        return json.dumps(row, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    def write(self, record) -> bool:
        """Append one JSONL row; rotate active file to .1 when over MAX_BYTES."""
        try:
            line = self._line(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            try:
                if self.path.stat().st_size > MAX_BYTES:
                    rotated = self.path.with_name(self.path.name + ".1")
                    os.replace(self.path, rotated)
            except OSError:
                pass
            return True
        except Exception:
            return False

    def read_tail(self, n=DEFAULT_TAIL) -> list:
        """Return up to n most-recent rows (malformed lines are skipped)."""
        try:
            limit = max(0, int(n))
        except Exception:
            limit = DEFAULT_TAIL
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        rows = []
        for line in lines[-limit:] if limit else []:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            rows.append(obj)
        return rows


def audit_file(path):
    """Create an audit-log helper for one path (no IO until write/read)."""
    return _AuditFile(path)


__all__ = ["enabled", "AUDIT_ENABLED", "audit_file", "MAX_BYTES", "DEFAULT_TAIL"]
