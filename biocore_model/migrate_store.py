# -*- coding: utf-8 -*-
"""AstrBot engine store -> BioCore core store, read-only migration mapping.

The AstrBot plugin keeps its engine store under the plugin data directory
(memory.json or memory/<session>.json). The core service expects
<store>/memory.json with entries carrying id/text/ts/role/tags/importance/pin/
client_scope. This module maps the known fields, reports everything unknown and
never writes the source. Dry-run is the default; apply=True writes the target
atomically and refuses to overwrite a non-empty target unless force=True.

Standard library only; no AstrBot import; no network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SOURCE_ENV = "BIOCORE_ASTROBOT_STORE"
DATA_ENV = "BIOCORE_ASTROBOT_DATA"
TARGET_SCHEMA = 1
CORE_KEYS = ("id", "text", "ts", "role", "tags", "importance", "pin", "client_scope", "valid_at")
# Rich engine fields handled explicitly (not "unmapped").
HANDLED_EXTRA = {"vector", "embedding_model", "vector_model"}
# engine field -> core field (known, intentional mapping only)
FIELD_MAP = {
    "id": "id",
    "text": "text",
    "ts": "ts",
    "role": "role",
    "importance": "importance",
    "pin": "pin",
    "scope": "client_scope",
    "valid_at": "valid_at",
    "tags": "tags",
}
OPTIONAL_DEFAULTS = {"role": "user", "tags": [], "importance": 0.5, "pin": False, "client_scope": "global"}
REQUIRED_FIELDS = ("text",)


def _candidate_data_dirs():
    here = Path(__file__).resolve()
    home = Path.home()
    candidates = [
        home / ".astrbot_launcher" / "instances",
        home / "Desktop" / "plugin_data",
        here.parents[2] / "plugin_data",
    ]
    return candidates


def detect_source(candidates=None):
    """Locate the AstrBot engine store (file or data dir); None when absent."""
    env = str(os.environ.get(SOURCE_ENV) or "").strip()
    if env:
        path = Path(env).expanduser()
        if path.exists():
            return str(path)
    roots = []
    data_override = str(os.environ.get(DATA_ENV) or "").strip()
    if data_override:
        roots.append(Path(data_override).expanduser())
    for candidate in candidates or _candidate_data_dirs():
        try:
            root = Path(candidate)
            if not root.exists():
                continue
            if root.name == "plugin_data":
                roots.extend(sorted(root.glob("astrbot_plugin_biocore_standalone")))
            else:
                roots.extend(sorted(root.glob("*/core/data/plugin_data/astrbot_plugin_biocore_standalone")))
        except Exception:
            continue
    for root in roots:
        try:
            direct = root / "memory.json"
            if direct.is_file():
                return str(direct)
            memory_dir = root / "memory"
            if memory_dir.is_dir() and any(memory_dir.glob("*.json")):
                return str(memory_dir)
            if root.is_dir() and any(root.glob("*.json")) and root.name == "memory":
                return str(root)
        except Exception:
            continue
    return None


def _source_files(source):
    path = Path(source)
    if path.is_file():
        return [path]
    if path.is_dir():
        files = sorted(path.glob("*.json")) if path.name == "memory" else sorted(path.glob("memory/*.json"))
        return [file for file in files if file.is_file()]
    return []


def load_source(source):
    """Read engine entries from a file/dir; returns (entries, meta)."""
    files = _source_files(source)
    entries = []
    corrupt = 0
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        except Exception:
            corrupt += 1
            continue
        rows = doc.get("entries") if isinstance(doc, dict) else None
        if isinstance(rows, list):
            entries.extend(row for row in rows if isinstance(row, dict))
    meta = {"source": str(source), "files": len(files), "corrupt_files": corrupt, "source_entries": len(entries)}
    return entries, meta


def _core_scope(entry):
    value = str(entry.get("client_scope") or entry.get("scope") or "default").strip()
    if not value or value in ("default", "global", "all"):
        return "global"
    if value.startswith("session:"):
        return value
    return "global"


def _core_id(entry):
    raw = entry.get("id")
    if raw not in (None, ""):
        return str(raw)[:64]
    seed = "|".join([str(entry.get("text") or ""), str(entry.get("ts") or ""), str(entry.get("role") or "")])
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def convert(entries):
    """Map engine entries to core entries; returns (core_entries, report)."""
    rows = entries if isinstance(entries, list) else []
    core_entries = []
    unmapped = {}
    missing = {}
    generated_ids = 0
    skipped = 0
    vectors_migrated = 0
    vectors_dropped = 0
    for entry in rows:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        if not str(entry.get("text") or "").strip():
            for name in REQUIRED_FIELDS:
                missing[name] = missing.get(name, 0) + 1
            skipped += 1
            continue
        mapped = {}
        for source_key, target_key in FIELD_MAP.items():
            if source_key in entry:
                mapped[target_key] = entry[source_key]
        for key in entry.keys():
            if key not in FIELD_MAP and key not in HANDLED_EXTRA:
                unmapped[key] = unmapped.get(key, 0) + 1
        core = {
            "id": _core_id(entry),
            "text": str(entry.get("text")).strip(),
            "ts": _as_float(entry.get("ts"), 0.0),
            "role": str(entry.get("role") or OPTIONAL_DEFAULTS["role"]),
            "tags": _as_list(entry.get("tags"), OPTIONAL_DEFAULTS["tags"]),
            "importance": _as_float(entry.get("importance"), OPTIONAL_DEFAULTS["importance"]),
            "pin": bool(entry.get("pin", OPTIONAL_DEFAULTS["pin"])),
            "client_scope": _core_scope(entry),
        }
        if "valid_at" in entry and entry.get("valid_at") is not None:
            core["valid_at"] = _as_float(entry.get("valid_at"), None)
        # Vector passthrough: only when every component is a finite real number.
        vector = entry.get("vector")
        if isinstance(vector, (list, tuple)) and vector:
            clean = []
            ok = True
            for item in vector:
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    ok = False
                    break
                number = float(item)
                if not _is_finite(number):
                    ok = False
                    break
                clean.append(number)
            if ok and clean:
                core["vector"] = clean
                model = entry.get("embedding_model") or entry.get("vector_model")
                if model:
                    core["vector_model"] = str(model)[:120]
                vectors_migrated += 1
            else:
                vectors_dropped += 1
        if not entry.get("id"):
            generated_ids += 1
        core_entries.append(core)
    report = {
        "source_entries": len(rows),
        "converted": len(core_entries),
        "skipped": skipped,
        "generated_ids": generated_ids,
        "vectors_migrated": vectors_migrated,
        "vectors_dropped": vectors_dropped,
        "unmapped_fields": unmapped,
        "missing_required": missing,
        "sample": core_entries[:3],
    }
    return core_entries, report


def _is_finite(value):
    try:
        number = float(value)
    except Exception:
        return False
    return number == number and number not in (float('inf'), float('-inf'))


def _as_float(value, default):
    try:
        return float(value)
    except Exception:
        return default


def _as_list(value, default):
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return list(default)
    return [str(value)]


def _target_doc(core_entries, source, meta):
    return {
        "entries": core_entries,
        "tombstones": [],
        "schema_version": TARGET_SCHEMA,
        "meta": {
            "migration": "astrbot-engine-to-biocore-core",
            "source": str(source or ""),
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "source_files": meta.get("files"),
        },
    }


def _atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp")
    try:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, str(path))
    finally:
        try:
            if not handle.closed:
                handle.close()
            if os.path.exists(handle.name):
                os.remove(handle.name)
        except Exception:
            pass


def run(src=None, dst=None, apply=False, force=False):
    """Dry-run by default; apply=True writes the target atomically."""
    source = src or detect_source()
    result = {"ok": bool(source), "dry_run": not bool(apply), "applied": False,
              "source": source or "", "target": str(dst or ""),
              "source_entries": 0, "converted": 0, "skipped": 0, "generated_ids": 0,
              "vectors_migrated": 0, "vectors_dropped": 0,
              "unmapped_fields": {}, "missing_required": {}, "sample": [],
              "corrupt_files": 0, "error": ""}
    if not source or not _source_files(source):
        result["error"] = "source_not_found"
        result["ok"] = False
        return result
    entries, meta = load_source(source)
    result.update({"source_entries": meta.get("source_entries", 0),
                   "corrupt_files": meta.get("corrupt_files", 0)})
    core_entries, report = convert(entries)
    result.update({key: report[key] for key in ("source_entries", "converted", "skipped", "generated_ids",
                                                "vectors_migrated", "vectors_dropped",
                                                "unmapped_fields", "missing_required", "sample")})
    if meta.get("corrupt_files"):
        result["error"] = "corrupt_source"
        return result
    if not apply:
        return result
    if not dst:
        result["error"] = "target_required"
        return result
    target = Path(dst)
    try:
        if target.exists() and target.stat().st_size > 0 and not force:
            result["error"] = "target_not_empty"
            return result
    except Exception:
        pass
    try:
        _atomic_write_json(target, _target_doc(core_entries, source, meta))
    except Exception as error:
        result["error"] = "write_failed: " + str(error)
        return result
    result["applied"] = True
    result["dry_run"] = False
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Map AstrBot engine memory store to BioCore core schema (dry-run by default)")
    parser.add_argument("--dry-run", action="store_true", help="report only (default)")
    parser.add_argument("--apply", action="store_true", help="write the target store")
    parser.add_argument("--force", action="store_true", help="allow overwriting a non-empty target")
    parser.add_argument("--src", default="", help="engine store file or memory dir")
    parser.add_argument("--dst", default="", help="core memory.json path")
    args = parser.parse_args(argv)
    result = run(src=args.src or None, dst=args.dst or None, apply=bool(args.apply and not args.dry_run), force=args.force)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
