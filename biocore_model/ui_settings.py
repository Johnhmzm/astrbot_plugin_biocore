# -*- coding: utf-8 -*-
"""BioCore-authoritative UI settings (survives AstrBot restarts).

Single storage authority: plugin_data/astrbot_plugin_biocore/ui_settings.json
(the same directory as persona_profile.json / memory files). The legacy
plugins/<plugin>/data/ui_settings.json is migrated once per process (newer file
wins, keys merged), then never read again. Every load/save goes through the
authority path, so the 60s tick, page/status and the dashboard always agree.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:  # AstrBot requires the host logger
    from astrbot.api import logger
except Exception:  # pragma: no cover - offline tests
    class _NullLogger:  # offline fallback: never imports stdlib logging
        def _noop(self, *args, **kwargs):
            return None
        debug = info = warning = error = exception = critical = _noop
    logger = _NullLogger()

SCHEMA = 1
FILE_NAME = "ui_settings.json"
PLUGIN_NAME = "astrbot_plugin_biocore"
MIGRATION_LOG = "[biocore] ui_settings migrated from plugins/data to plugin_data"

DEFAULTS = {
    "reply_soft": {"enabled": True, "target_chars": 10, "max_chars": 30},
    "reply_split": {"enabled": False, "mode": "astrbot", "max_chars": 300, "inject_newlines": True},
    "autonomy": {"enabled": False, "send": False, "threshold": 0.6, "max_chars": 120,
                 "accumulator": {"V": 0.0, "ticks_since_fire": 0, "drift": 0.0, "leak": 0.15, "sigma": 0.06, "theta": 0.55, "last_tick_ts": 0.0}},
    # Fallback biological state used when no user core exists yet (restart):
    # the life loop hydrates a synthetic core from here and writes it back.
    "bio_state": {},
}

_MODULE_DIR = Path(__file__).resolve().parent
_PLUGIN_DIR = _MODULE_DIR.parent
# Repo layout: <data>/plugins/<plugin>/data -> <data>/plugin_data/<canonical>.
_DEFAULT_BASE = _PLUGIN_DIR.parents[1] if len(_PLUGIN_DIR.parents) > 1 else _PLUGIN_DIR
_DEFAULT_AUTHORITY = _DEFAULT_BASE / "plugin_data" / PLUGIN_NAME
_LEGACY_FILE = _PLUGIN_DIR / "data" / FILE_NAME
_MIGRATED: set[str] = set()


def _is_plugins_data(path: Path) -> bool:
    """True for <data>/plugins/<plugin>/data (the legacy A layout)."""
    return path.name == "data" and path.parent.parent.name == "plugins"


def authority_dir(plugin=None) -> Path:
    """The single directory that owns ui_settings.json (env override for ops)."""
    env = str(os.getenv("BIOCORE_UI_SETTINGS_DIR") or "").strip()
    if env:
        return Path(env)
    raw = None
    for attr in ("data_dir", "DATA_DIR"):
        raw = getattr(plugin, attr, None) if plugin is not None else None
        if raw:
            break
    if not raw:
        return _DEFAULT_AUTHORITY
    path = Path(str(raw))
    if _is_plugins_data(path):
        return path.parent.parent.parent / "plugin_data" / PLUGIN_NAME
    if path.parent.name == "plugin_data" and path.name.startswith(PLUGIN_NAME):
        return path.parent / PLUGIN_NAME
    return path


def base_dir(plugin=None) -> Path:
    return authority_dir(plugin)


def _legacy_candidates(plugin=None) -> list[Path]:
    env = str(os.getenv("BIOCORE_UI_SETTINGS_LEGACY") or "").strip()
    if env:
        return [Path(env)]
    authority = authority_dir(plugin)
    out: list[Path] = []
    raw = None
    for attr in ("data_dir", "DATA_DIR"):
        raw = getattr(plugin, attr, None) if plugin is not None else None
        if raw:
            break
    if raw:
        candidate = Path(str(raw)) / FILE_NAME
        if _is_plugins_data(Path(str(raw))) and candidate != authority:
            out.append(candidate)
    elif _LEGACY_FILE != authority:
        out.append(_LEGACY_FILE)
    return out


def _read_dict(path: Path) -> dict:
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                return raw
    except Exception:
        pass
    return {}


def _merge_legacy(authority: Path, legacy: Path) -> bool:
    legacy_data = _read_dict(legacy)
    if not legacy_data:
        return False
    existing = _read_dict(authority)
    try:
        if authority.is_file() and legacy.stat().st_mtime <= authority.stat().st_mtime:
            return False  # authority is newer: never overwrite with stale legacy
    except Exception:
        pass
    merged = dict(existing)
    for section, values in legacy_data.items():
        if section == "schema":
            continue
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section] = {**merged[section], **values}
        else:
            merged[section] = values
    merged["schema"] = SCHEMA
    authority.parent.mkdir(parents=True, exist_ok=True)
    if authority.is_file():
        _backup(authority)
    tmp = authority.with_name(authority.name + ".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, authority)
    logger.info(MIGRATION_LOG)
    return True


def _migrate(plugin=None) -> None:
    authority = authority_dir(plugin)
    key = str(authority)
    if key in _MIGRATED:
        return
    _MIGRATED.add(key)
    target = authority / FILE_NAME
    for legacy in _legacy_candidates(plugin):
        if legacy == target or not legacy.is_file():
            continue
        try:
            _merge_legacy(target, legacy)
        except Exception as exc:
            logger.warning("[biocore] ui_settings migration failed: %s", exc)


def settings_path(plugin=None) -> Path:
    """The one authority path (migration is idempotent and happens first)."""
    _migrate(plugin)
    return authority_dir(plugin) / FILE_NAME


def load(plugin=None) -> dict:
    data = json.loads(json.dumps(DEFAULTS))
    try:
        raw = _read_dict(settings_path(plugin))
        if raw:
            for section, values in DEFAULTS.items():
                current = raw.get(section)
                if isinstance(current, dict):
                    data[section].update(current)
    except Exception:
        pass
    return data


def _backup(path: Path) -> None:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:
        (path.with_name(path.name + ".bak_" + stamp)).write_bytes(path.read_bytes())
    except Exception:
        return
    try:
        backups = sorted(path.parent.glob(path.name + ".bak_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[3:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def save(plugin=None, updates=None) -> dict:
    path = settings_path(plugin)
    try:
        data = load(plugin)
        for section, values in (updates or {}).items():
            if section in DEFAULTS and isinstance(values, dict):
                data[section].update(values)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            _backup(path)
        payload = dict(data)
        # Preserve one-way migration marker: load() only merges known sections,
        # so a later save would otherwise drop schema_version and re-run migrate.
        try:
            _raw = _read_dict(path)
            if "schema_version" in _raw:
                payload["schema_version"] = _raw["schema_version"]
        except Exception:
            pass
        payload["schema"] = SCHEMA
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return {"ok": True, "file": str(path)}
    except Exception as error:
        return {"ok": False, "file": str(path), "reason": type(error).__name__}


def apply_to_plugin(plugin, data=None) -> dict:
    """Startup: runtime attributes always mirror the file (authoritative)."""
    data = data if isinstance(data, dict) else load(plugin)
    soft = data.get("reply_soft") or {}
    split = data.get("reply_split") or {}
    auto = data.get("autonomy") or {}
    try:
        plugin.reply_soft_limit_enabled = bool(soft.get("enabled", True))
        plugin.reply_soft_target_chars = int(soft.get("target_chars", 10))
        plugin.reply_soft_max_chars = int(soft.get("max_chars", 30))
    except Exception:
        pass
    try:
        plugin.reply_split_enabled = bool(split.get("enabled", False))
        plugin.reply_split_mode = str(split.get("mode", "astrbot"))
        plugin.reply_split_max_chars = int(split.get("max_chars", 300))
    except Exception:
        pass
    try:
        plugin.proactive_autonomy = bool(auto.get("enabled", False))
        plugin.proactive_send = bool(auto.get("send", False))
    except Exception:
        pass
    return data
