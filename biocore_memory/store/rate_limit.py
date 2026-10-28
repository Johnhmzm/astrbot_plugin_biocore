# -*- coding: utf-8 -*-
"""Persistent sliding-window rate limiter (pure store helper; no AstrBot).

Module is disabled by default: callers MUST check `enabled` before using it.
State is a JSON file holding recent timestamps; writes use a temp file + replace
so a restart (or a crash during write) does not reset the window.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

enabled = False
RATE_LIMIT_ENABLED = enabled

WINDOW_SECONDS = 60


class FileRateLimiter:
    def __init__(self, path, max_per_min=30):
        self.path = Path(path)
        try:
            self.max_per_min = max(1, int(max_per_min))
        except Exception:
            self.max_per_min = 30
        self._lock = threading.Lock()

    def _load(self) -> list:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        raw = data.get("timestamps") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        out = []
        for value in raw:
            try:
                out.append(float(value))
            except Exception:
                continue
        return out

    def _save(self, stamps) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".",
                                       suffix=".tmp", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"timestamps": [round(float(x), 6) for x in stamps]},
                              f, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
                    f.flush()
                os.replace(tmp, self.path)
            finally:
                try:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                except OSError:
                    pass
            return True
        except Exception:
            return False

    def check(self, now=None) -> bool:
        """Record one allowed event when under the window limit."""
        try:
            stamp = float(now if now is not None else time.time())
        except Exception:
            stamp = time.time()
        cutoff = stamp - WINDOW_SECONDS
        with self._lock:
            active = sorted(x for x in self._load() if x > cutoff)
            if len(active) >= self.max_per_min:
                self._save(active[-self.max_per_min:])
                return False
            active.append(stamp)
            active = active[-self.max_per_min:]
            return bool(self._save(active))


def rate_limiter(path, max_per_min=30):
    """Create a persistent limiter for one path (no IO until check)."""
    return FileRateLimiter(path, max_per_min=max_per_min)


__all__ = ["enabled", "RATE_LIMIT_ENABLED", "FileRateLimiter", "rate_limiter",
           "WINDOW_SECONDS"]
