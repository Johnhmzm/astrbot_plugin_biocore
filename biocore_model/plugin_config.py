# -*- coding: utf-8 -*-
"""Explicit atomic persistence for this plugin's own AstrBot config file."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

FILE_NAME = "astrbot_plugin_biocore_standalone_config.json"


def candidate_paths(plugin=None) -> list:
    paths = []
    try:
        data_dir = Path(getattr(plugin, "data_dir", "") or "")
        if str(data_dir):
            paths.append(data_dir / "config" / FILE_NAME)
            paths.append(data_dir.parent / "config" / FILE_NAME)
    except Exception:
        pass
    try:
        plugin_dir = Path(__file__).resolve().parent.parent  # .../plugins/<plugin>
        core_data = plugin_dir.parent.parent  # .../core/data
        paths.append(core_data / "config" / FILE_NAME)
        paths.append(core_data.parent / "config" / FILE_NAME)
    except Exception:
        pass
    env_dir = os.environ.get("ASTRBOT_CONFIG_DIR") or ""
    if env_dir:
        paths.append(Path(env_dir) / FILE_NAME)
    return paths


def find_config(plugin=None):
    for path in candidate_paths(plugin):
        try:
            if path.is_file():
                return path
        except Exception:
            continue
    return None


def _read(path: Path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    return json.loads(text), bom


def _backup(path: Path) -> None:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:
        (path.with_name(path.name + ".bak_replysplit_" + stamp)).write_bytes(path.read_bytes())
    except Exception:
        return
    try:
        backups = sorted(path.parent.glob(path.name + ".bak_replysplit_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[3:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def persist_updates(updates, plugin=None) -> dict:
    """Merge updates into the plugin config file (atomic, BOM-preserving)."""
    path = find_config(plugin)
    if path is None:
        return {"ok": False, "file": "", "reason": "config not found"}
    try:
        data, bom = _read(path)
        if not isinstance(data, dict):
            return {"ok": False, "file": str(path), "reason": "invalid config"}
        data.update(updates or {})
        _backup(path)
        tmp = path.with_name(path.name + ".tmp_replysplit")
        text = json.dumps(data, ensure_ascii=False, indent=2)
        tmp.write_text(text, encoding="utf-8-sig" if bom else "utf-8")
        os.replace(tmp, path)
        return {"ok": True, "file": str(path)}
    except Exception as error:
        return {"ok": False, "file": str(path), "reason": type(error).__name__}
