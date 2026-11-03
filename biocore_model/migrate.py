# -*- coding: utf-8 -*-
"""1.3.4 -> 1.4.0 data migration (settings / accumulator / old memory).

Design: one pure-ish entry point migrate(plugin) -> report dict. It only reads
and writes JSON files; it never imports main. Idempotent: ui_settings gets a
top-level schema_version; field backfills are also safe to repeat (missing-only).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import ui_settings

try:  # AstrBot requires the host logger
    from astrbot.api import logger
except Exception:  # pragma: no cover - offline tests
    class _NullLogger:  # offline fallback: never imports stdlib logging
        def _noop(self, *args, **kwargs):
            return None
        debug = info = warning = error = exception = critical = _noop
    logger = _NullLogger()

SCHEMA_VERSION = 4
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
    copied = {"settings": 0, "memory": 0, "states": 0, "graph": 0}
    for name in ("settings", "memory", "states", "graph"):
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
        # task-146 rule 3: back up the whole memory/ directory (JSON docs and
        # the SQLite db incl. WAL) before any migration write.
        try:
            _db = memory / "memory.sqlite3"
            if _db.is_file():
                try:
                    import sqlite3 as _sqlite3
                    _conn = _sqlite3.connect(str(_db), timeout=5.0)
                    try:
                        _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    finally:
                        _conn.close()
                except Exception:
                    pass
        except Exception:
            pass
        for src in sorted(memory.iterdir()):
            if not src.is_file():
                continue
            if src.name.endswith(".corrupt.bak"):
                continue
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
    graph = _graph_dir(plugin)
    if graph.is_dir():
        for src in graph.glob("*.json"):
            try:
                _atomic_copy(src, root / "graph" / src.name)
                copied["graph"] += 1
            except Exception:
                continue
        try:
            from . import entity_graph as _eg_backup
        except Exception:  # pragma: no cover
            import entity_graph as _eg_backup  # type: ignore
        db = graph / _eg_backup.SQLITE_FILE
        if db.is_file():
            try:
                _eg_backup.checkpoint(db)
                _atomic_copy(db, root / "graph" / db.name)
                copied["graph"] += 1
            except Exception:
                pass
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
    report = {"ok": False,
              "restored": {"settings": 0, "memory": 0, "states": 0,
                           "graph": 0},
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
    # task-146 rule 6: restore the SQLite store from the JSON backup (and the
    # backed-up DB when present). JSON stays the fallback if this fails.
    try:
        try:
            from . import memory_store as _ms_restore
        except Exception:  # pragma: no cover
            import memory_store as _ms_restore  # type: ignore
        memory_target = _data_dir(plugin) / "memory"
        memory_target.mkdir(parents=True, exist_ok=True)
        backup_memory = root / "memory"
        db_backup = backup_memory / _ms_restore.SQLITE_FILE
        if db_backup.is_file():
            target_db = memory_target / _ms_restore.SQLITE_FILE
            try:
                import sqlite3 as _sqlite3_restore
                if target_db.is_file():
                    _conn = _sqlite3_restore.connect(str(target_db), timeout=5.0)
                    try:
                        _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    finally:
                        _conn.close()
            except Exception:
                pass
            _atomic_copy(db_backup, target_db)
            for suffix in ("-wal", "-shm"):
                try:
                    Path(str(target_db) + suffix).unlink(missing_ok=True)
                except Exception:
                    pass
            report["restored"]["memory_db"] = 1
        elif backup_memory.is_dir():
            result = _ms_restore.restore(backup_memory, memory_target)
            if result.get("ok"):
                report["restored"]["memory_db"] = int(
                    result.get("entries", 0) or 0)
            else:
                report["warnings"].append(
                    "memory db restore failed: " + str(result.get("error") or ""))
    except Exception as exc:
        report["warnings"].append("memory db restore failed: %s" % exc)

    graph_target = _graph_dir(plugin)
    graph_target.mkdir(parents=True, exist_ok=True)
    try:
        from . import entity_graph as _eg_restore
    except Exception:  # pragma: no cover
        import entity_graph as _eg_restore  # type: ignore
    current_db = graph_target / _eg_restore.SQLITE_FILE
    for src in (root / "graph").glob("*.json"):
        try:
            _atomic_copy(src, graph_target / src.name)
            report["restored"]["graph"] += 1
        except Exception:
            report["warnings"].append("graph restore failed: " + src.name)
    backup_db = root / "graph" / _eg_restore.SQLITE_FILE
    if backup_db.is_file():
        old_db = current_db.with_name(current_db.name + ".restore-old")
        try:
            if current_db.is_file():
                _eg_restore.checkpoint(current_db)
                _atomic_copy(current_db, old_db)
            _atomic_copy(backup_db, current_db)
            for suffix in ("-wal", "-shm"):
                Path(str(current_db) + suffix).unlink(missing_ok=True)
            report["restored"]["graph"] += 1
            try:
                old_db.unlink(missing_ok=True)
            except Exception:
                pass
        except Exception as exc:
            if old_db.is_file():
                try:
                    _atomic_copy(old_db, current_db)
                except Exception:
                    pass
            report["warnings"].append(
                "graph restore failed: %s" % type(exc).__name__)
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


def _graph_dir(plugin):
    """Where the entity graph lives (authority first, legacy data dir second)."""
    for candidate in (ui_settings.authority_dir(plugin) / "graph",
                      _data_dir(plugin) / "graph"):
        if candidate.is_dir():
            return candidate
    return ui_settings.authority_dir(plugin) / "graph"


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


def _ensure_graph(plugin, stats, warnings):
    """v3: SQLite graph (create / import legacy graph.json / recover corrupt)."""
    try:
        try:
            from . import entity_graph as _eg
        except Exception:  # pragma: no cover
            import entity_graph as _eg  # type: ignore
        graph_dir = _graph_dir(plugin)
        graph_dir.mkdir(parents=True, exist_ok=True)
        db_path = graph_dir / _eg.SQLITE_FILE
        json_path = graph_dir / "graph.json"
        db_existed = db_path.is_file()
        db_corrupt = False
        if db_existed:
            try:
                with db_path.open("rb") as _fh:
                    db_corrupt = _fh.read(16) != b"SQLite format 3\x00"
            except Exception:
                db_corrupt = True
        json_corrupt = False
        json_data = None
        if json_path.is_file():
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8-sig"))
                json_data = _eg.normalize_graph(raw)
            except Exception:
                json_corrupt = True
                try:
                    import shutil as _shutil
                    _shutil.copyfile(
                        json_path,
                        json_path.with_name(json_path.name + ".corrupt.bak"))
                except Exception:
                    pass
        store = _eg.open_store(db_path)
        try:
            db_empty = _eg.stats(store)["entities"] == 0
            imported = {"entities": 0, "edges": 0}
            source = "none"
            if db_empty and json_data is not None and json_data["entities"]:
                imported = store.import_json(json_path)
                source = "json"
            store.export_json(json_path)
            state = _eg.stats(store)
            if json_corrupt or db_corrupt:
                stats["graph"] = "recovered"
            elif source == "json":
                stats["graph"] = "imported"
            elif not db_existed:
                stats["graph"] = "created"
            else:
                stats["graph"] = ("ok" if state["entities"] else "empty")
            stats["graph_imported"] = imported
            stats["graph_entities"] = state["entities"]
            stats["graph_edges"] = state["edges"]
            logger.info(
                "[biocore] graph sqlite ready: db=%s entities=%d edges=%d "
                "source=%s recovered=%s", db_path.name, state["entities"],
                state["edges"], source, bool(json_corrupt or db_corrupt))
        finally:
            store.close()
        return db_path
    except Exception as exc:
        warnings.append("graph init failed: %s" % type(exc).__name__)
        stats["graph"] = "failed"
        return None

def _ensure_memory_sqlite(plugin, stats, warnings):
    """v4: memory/*.json entries -> memory.sqlite3 (auto backup, idempotent).

    Rules (user requirement: 老用户升级不能丢数据):
    - backup the whole memory/ dir under backups/pre-migration-<stamp>/ first;
    - import only when the DB is empty (both sides present -> config wins, no
      implicit merge);
    - on any failure the JSON files stay untouched and the plugin keeps JSON
      mode (this function never raises).
    """
    try:
        try:
            from . import memory_store as _ms
        except Exception:  # pragma: no cover
            import memory_store as _ms  # type: ignore
        memory_dir = _memory_dir(plugin)
        if memory_dir is None:
            memory_dir = ui_settings.authority_dir(plugin) / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        backup_root = ui_settings.authority_dir(plugin) / "backups"
        backup = _ms._backup_memory_dir(memory_dir, backup_root,
                                        label="pre-migration")
        report = _ms.ensure_store(memory_dir, backup_root=None,
                                  label="pre-migration")
        stats["memory_backup"] = backup
        stats["memory_db"] = report.get("state", "failed")
        stats["memory_db_entries"] = int(report.get("entries", 0) or 0)
        stats["memory_db_sessions"] = int(report.get("sessions", 0) or 0)
        _migration = report.get("migration") or {}
        stats["memory_dedupe_merged"] = int(
            _migration.get("merged_pairs", 0) or 0)
        stats["memory_dedupe_deleted"] = int(
            _migration.get("deleted_rows", 0) or 0)
        stats["memory_dedupe_backup"] = str(
            report.get("dedupe_backup") or "")
        if _migration.get("ran"):
            logger.info(
                "[biocore] memory dedupe: merged_pairs=%d deleted_rows=%d "
                "backfilled=%d backup=%s",
                int(stats["memory_dedupe_merged"]),
                int(stats["memory_dedupe_deleted"]),
                int(_migration.get("backfilled", 0) or 0),
                bool(stats["memory_dedupe_backup"]))
        if not report.get("ok"):
            warnings.append("memory sqlite ensure failed: %s"
                            % str(report.get("error") or "")[:120])
        logger.info(
            "[biocore] memory sqlite ready: backend=%s sessions=%d entries=%d "
            "source=%s backup=%s",
            "sqlite", int(stats["memory_db_sessions"]),
            int(stats["memory_db_entries"]), report.get("state", "?"),
            bool(backup.get("dir")))
        return report
    except Exception as exc:
        warnings.append("memory sqlite failed: %s: %s"
                        % (type(exc).__name__, exc))
        stats["memory_db"] = "failed"
        return {}


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
    _ensure_graph(plugin, stats, warnings)
    _ensure_memory_sqlite(plugin, stats, warnings)
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
