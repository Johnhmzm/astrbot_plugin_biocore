# -*- coding: utf-8 -*-
"""1.3.4 -> 1.4.0 data migration (settings / accumulator / old memory).

Design: one pure-ish entry point migrate(plugin) -> report dict. It only reads
and writes JSON files; it never imports main. Idempotent: ui_settings gets a
top-level schema_version; field backfills are also safe to repeat (missing-only).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from . import ui_settings

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
OLD_SCHEMA_VERSION = 1
MEMORY_STORAGE_S = 0.45
MEMORY_AROUSAL = 0.4
ACC_DEFAULTS = {"theta": 0.55, "cooldown_seconds": 1800,
                "daily_cap": 5, "last_umo": ""}


def _read(path):
    try:
        if path and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            ui_settings._backup(path)
        except Exception:
            pass
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _data_dir(plugin):
    for attr in ("data_dir", "DATA_DIR"):
        raw = getattr(plugin, attr, None) if plugin is not None else None
        if raw:
            return Path(str(raw))
    return ui_settings.authority_dir(plugin)


def _legacy_settings(plugin):
    try:
        for path in ui_settings._legacy_candidates(plugin):
            if path and path.is_file():
                return Path(path)
    except Exception:
        pass
    data = _data_dir(plugin)
    if ui_settings._is_plugins_data(data):
        candidate = data / ui_settings.FILE_NAME
        if candidate.is_file():
            return candidate
    return None


def _authority_settings(plugin):
    return ui_settings.authority_dir(plugin) / ui_settings.FILE_NAME


def schema_version(plugin=None):
    try:
        return int(_read(_authority_settings(plugin)).get("schema_version", 0) or 0)
    except Exception:
        return 0


def _atomic_copy(src, dst):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".migrate-tmp")
    try:
        tmp.write_bytes(Path(src).read_bytes())
        os.replace(tmp, dst)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _create_backup(plugin):
    """Copy settings / memory docs / states before migration (auto, internal)."""
    base = ui_settings.authority_dir(plugin)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    root = base / "backups" / ("pre-migration-" + stamp)
    copied = {"settings": 0, "memory": 0, "states": 0}
    for name in ("settings", "memory", "states"):
        (root / name).mkdir(parents=True, exist_ok=True)
    settings_candidates = []
    try:
        settings_candidates.extend(ui_settings._legacy_candidates(plugin))
    except Exception:
        pass
    authority = _authority_settings(plugin)
    if authority.is_file():
        settings_candidates.append(authority)
    seen = set()
    for src in settings_candidates:
        src = Path(src)
        if not src.is_file() or str(src) in seen:
            continue
        seen.add(str(src))
        target = root / "settings" / (src.name if len(seen) == 1
                                      else "legacy_" + src.name)
        try:
            _atomic_copy(src, target)
            copied["settings"] += 1
        except Exception:
            continue
    memory = _memory_dir(plugin)
    if memory is not None:
        for src in memory.glob("*.json"):
            try:
                _atomic_copy(src, root / "memory" / src.name)
                copied["memory"] += 1
            except Exception:
                continue
    states = _data_dir(plugin) / "states"
    if not states.is_dir():
        states = base / "states"
    if states.is_dir():
        for src in states.glob("*.json"):
            try:
                _atomic_copy(src, root / "states" / src.name)
                copied["states"] += 1
            except Exception:
                continue
    if not any(copied.values()):
        try:
            root.rmdir()
        except Exception:
            pass
        return "", copied
    return str(root), copied


def restore(backup_dir, plugin=None):
    """Copy a pre-migration backup back (one-command rollback)."""
    root = Path(backup_dir)
    report = {"ok": False, "restored": {"settings": 0, "memory": 0, "states": 0},
              "warnings": []}
    if not root.is_dir():
        report["warnings"].append("backup dir missing")
        return report
    if plugin is None:
        plugin = type("RestoreHost", (), {
            "data_dir": str(root.parent.parent)})()
    base = _data_dir(plugin)
    authority = _authority_settings(plugin)
    for src in (root / "settings").glob("*.json"):
        try:
            target = authority if src.name == ui_settings.FILE_NAME else (
                base / ("legacy_" + src.name))
            _atomic_copy(src, target)
            report["restored"]["settings"] += 1
        except Exception as exc:
            report["warnings"].append("settings restore failed: %s" % exc)
    for name in ("memory", "states"):
        target_dir = base / name
        target_dir.mkdir(parents=True, exist_ok=True)
        for src in (root / name).glob("*.json"):
            try:
                _atomic_copy(src, target_dir / src.name)
                report["restored"][name] += 1
            except Exception as exc:
                report["warnings"].append("%s restore failed: %s" % (name, exc))
    report["ok"] = not report["warnings"]
    logger.info("[biocore] migrate restore done: %s warnings=%d",
                report["restored"], len(report["warnings"]))
    return report


def _flatten(data, prefix=""):
    out = {}
    for key, value in (data or {}).items():
        name = prefix + str(key)
        if isinstance(value, dict) and value:
            out.update(_flatten(value, name + "."))
        else:
            out[name] = value
    return out


def _merge_settings(plugin, stats, warnings):
    """a) Merge old A -> new B when A exists and B is absent/stale."""
    legacy = _legacy_settings(plugin)
    authority = _authority_settings(plugin)
    if legacy is None:
        stats["settings"] = "absent"
        return _read(authority)
    old = _read(legacy)
    if not old:
        stats["settings"] = "empty_legacy"
        return _read(authority)
    new = _read(authority)
    try:
        stale = (not authority.is_file()
                 or legacy.stat().st_mtime > authority.stat().st_mtime)
    except Exception:
        stale = not authority.is_file()
    if not stale:
        stats["settings"] = "authority_newer"
        return new
    overridden = []
    merged = dict(new)
    for section, values in old.items():
        if section == "schema":
            continue
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            for key, value in values.items():
                if key in merged[section] and merged[section][key] != value:
                    overridden.append(section + "." + str(key))
            merged[section] = {**merged[section], **values}
        else:
            if section in merged and merged[section] != values:
                overridden.append(str(section))
            merged[section] = values
    try:
        _write(authority, merged)
    except Exception as exc:
        warnings.append("settings write failed: %s" % type(exc).__name__)
        stats["settings"] = "write_failed"
        return _read(authority)
    stats["settings"] = "merged"
    stats["overridden"] = len(overridden)
    stats["overridden_keys"] = overridden[:12]
    return merged


def _autonomy_params(plugin):
    try:
        getter = getattr(plugin, "_autonomy_params", None)
        if callable(getter):
            params = getter()
            if isinstance(params, dict):
                return params
    except Exception:
        pass
    return {}


def _infer_last_umo(plugin):
    data = _data_dir(plugin)
    state_dir = data / "states"
    if not state_dir.is_dir():
        state_dir = ui_settings.authority_dir(plugin) / "states"
    try:
        files = sorted(state_dir.glob("*.json"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
    except Exception:
        files = []
    for path in files[:5]:
        row = _read(path)
        for key in ("umo", "last_umo", "session", "unified_msg_origin"):
            value = str(row.get(key) or "").strip()
            if value:
                return value
        if path.stem and path.stem not in ("state", "bio_state"):
            return path.stem
    return ""


def _fix_accumulator(plugin, data, stats):
    """b) Accumulator keys + dirty V/theta repair."""
    auto = data.get("autonomy")
    if not isinstance(auto, dict) or "accumulator" not in auto:
        stats["accumulator"] = "absent"
        return data
    acc = auto.get("accumulator") or {}
    if not isinstance(acc, dict):
        stats["accumulator"] = "absent"
        return data
    params = _autonomy_params(plugin)
    try:
        theta = float(params.get("theta", 0.55) or 0.55)
    except Exception:
        theta = 0.55
    fixed = []
    try:
        if float(acc.get("V", 0.0) or 0.0) < 0:
            acc["V"] = 0.0
            fixed.append("V")
    except Exception:
        acc["V"] = 0.0
        fixed.append("V")
    if "theta" not in acc or acc.get("theta") in (None, "", 0, "0"):
        acc["theta"] = theta
        fixed.append("theta")
    else:
        try:
            if abs(float(acc.get("theta")) - 0.55) < 1e-9 and abs(theta - 0.55) > 1e-9:
                acc["theta"] = theta
                fixed.append("theta")
        except Exception:
            acc["theta"] = theta
            fixed.append("theta")
    for key in ("cooldown_seconds", "daily_cap"):
        if key not in acc:
            acc[key] = int(params.get("cooldown_s" if key == "cooldown_seconds"
                                         else "daily_cap",
                                     ACC_DEFAULTS[key]) or ACC_DEFAULTS[key])
            fixed.append(key)
    if not str(acc.get("last_umo") or "").strip():
        acc["last_umo"] = _infer_last_umo(plugin)
        if acc["last_umo"]:
            fixed.append("last_umo")
    data["autonomy"] = data.get("autonomy") or {}
    data["autonomy"]["accumulator"] = acc
    stats["accumulator"] = "fixed" if fixed else "ok"
    stats["accumulator_fixed"] = fixed
    return data


def _memory_dir(plugin):
    data = _data_dir(plugin)
    for candidate in (data / "memory",
                      ui_settings.authority_dir(plugin) / "memory"):
        if candidate.is_dir():
            return candidate
    return None


def _retrieval_from_mtime(path, now=None):
    now = float(now if now is not None else time.time())
    try:
        age_days = max(0.0, (now - path.stat().st_mtime) / 86400.0)
    except Exception:
        age_days = 0.0
    return round(max(0.05, min(0.95, 0.9 / ((1.0 + age_days) ** 0.5))), 3)


def _backfill_memory(plugin, stats):
    """c) Old entries missing fields -> storage_s/retrieval_s/access_count..."""
    directory = _memory_dir(plugin)
    if directory is None:
        stats["memory"] = "absent"
        return 0
    touched = 0
    entries_total = 0
    now = time.time()
    try:
        files = sorted(directory.glob("*.json"))
    except Exception:
        files = []
    for path in files:
        doc = _read(path)
        entries = doc.get("entries") if isinstance(doc.get("entries"), list) else None
        if entries is None:
            continue
        changed = False
        fallback_retrieval = _retrieval_from_mtime(path, now)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entries_total += 1
            if "storage_s" not in entry:
                entry["storage_s"] = MEMORY_STORAGE_S
                changed = True
            if "retrieval_s" not in entry:
                entry["retrieval_s"] = fallback_retrieval
                changed = True
            if "access_count" not in entry:
                entry["access_count"] = 1
                changed = True
            if "arousal_at_encoding" not in entry:
                entry["arousal_at_encoding"] = MEMORY_AROUSAL
                changed = True
            if "hidden" not in entry:
                entry["hidden"] = False
                changed = True
        if changed:
            doc["entries"] = entries
            try:
                _write(path, doc)
            except Exception:
                continue
            touched += 1
    stats["memory"] = ("backfilled" if touched else
                      ("ok" if entries_total else "empty"))
    stats["memory_files"] = touched
    stats["memory_entries"] = entries_total
    return entries_total


def migrate(plugin) -> dict:
    """Run the 1.3.4 -> 1.4.0 migration once; safe to call again."""
    report = {"applied": [], "warnings": [], "stats": {},
              "schema_version": SCHEMA_VERSION, "ts": time.time(),
              "backup_dir": ""}
    stats = report["stats"]
    warnings = report["warnings"]
    authority = _authority_settings(plugin)
    current = _read(authority)
    try:
        version = int(current.get("schema_version", 0) or 0)
    except Exception:
        version = SCHEMA_VERSION
    if version >= SCHEMA_VERSION:
        stats["already"] = True
        report["schema_version"] = version
        logger.info("[biocore] migrate skipped: schema_version=%s (up-to-date)", version)
        return report
    # Auto backup before any write; failure is a warning, migration continues.
    try:
        backup_dir, copied = _create_backup(plugin)
        report["backup_dir"] = backup_dir
        stats["backup"] = copied
        if backup_dir:
            logger.info("[biocore] migrate backup: %s", backup_dir)
    except Exception as exc:
        warnings.append("backup failed: %s" % type(exc).__name__)
    data = _merge_settings(plugin, stats, warnings)
    if stats.get("settings") == "merged":
        report["applied"].append("settings")
    before_acc = json.dumps((data.get("autonomy") or {}).get("accumulator") or {},
                            ensure_ascii=False, sort_keys=True)
    data = _fix_accumulator(plugin, data, stats)
    after_acc = json.dumps((data.get("autonomy") or {}).get("accumulator") or {},
                           ensure_ascii=False, sort_keys=True)
    if stats.get("accumulator") == "fixed":
        report["applied"].append("accumulator")
    stats["accumulator_before"] = before_acc
    stats["accumulator_after"] = after_acc
    _backfill_memory(plugin, stats)
    if stats.get("memory") == "backfilled":
        report["applied"].append("memory")
    data["schema_version"] = SCHEMA_VERSION
    try:
        _write(authority, data)
        report["schema_version"] = SCHEMA_VERSION
    except Exception as exc:
        warnings.append("authority write failed: %s" % type(exc).__name__)
        report["schema_version"] = version
    fixed = stats.get("accumulator_fixed") or []
    logger.info(
        "[biocore] migrate done: settings=%s(%d keys overridden), "
        "accumulator=%s(%s), memory=%d entries backfilled, warnings=%d",
        stats.get("settings", "?"), int(stats.get("overridden", 0) or 0),
        stats.get("accumulator", "?"), ",".join(fixed) or "none",
        int(stats.get("memory_entries", 0) or 0
            if stats.get("memory") == "backfilled" else 0), len(warnings))
    return report
