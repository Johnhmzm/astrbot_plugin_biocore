# -*- coding: utf-8 -*-
"""DSH adapter CLI for the host-neutral memory engine.

Standard library only; never imports astrbot, never renders a prompt.
Run with: python -m biocore_memory.adapters.dsh_cli <command> ...
All output is JSON. Global --store selects the data directory
(default ./data/memory_store, engine file <store>/memory.json).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


def _engine_class():
    try:
        from ..engine import MemoryEngine  # package import
    except (ImportError, ValueError):
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from biocore_memory.engine import MemoryEngine
    return MemoryEngine


def _emit(payload, code=0):
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return code


def _parse_since(value):
    """Parse 24h/7d/30m/3600s to seconds; None when absent/invalid."""
    if not value:
        return None
    m = re.fullmatch(r"\s*(\d+)([smhd])\s*", str(value).lower())
    if not m:
        return None
    unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
    return int(m.group(1)) * unit


def dispatch(engine, action, **kwargs):
    """Compatibility dispatcher shared by DSH callers (JSON-safe results)."""
    if action == "remember":
        return engine.remember(kwargs.get("event") or kwargs)
    if action == "recall":
        return engine.recall(kwargs.get("query", ""),
                             budget=kwargs.get("budget", 3),
                             vector=kwargs.get("vector"))
    if action == "forget":
        return engine.forget(kwargs.get("entry_id", ""))
    if action == "pin":
        return engine.pin(kwargs.get("entry_id", ""),
                          bool(kwargs.get("pinned", True)))
    return {"error": "unknown_action"}


def _compact(entry):
    return {k: entry.get(k) for k in ("id", "text", "role", "ts", "hits",
                                      "importance", "pin", "tags", "source")}


def cmd_remember(args):
    engine = _engine_class()(data_dir=args.store)
    tags = [t.strip() for t in str(args.tags or "").split(",") if t.strip()]
    worth = {}
    if getattr(args, "worth", None):
        try:
            raw = str(args.worth).strip()
            try:
                worth = json.loads(raw)
            except Exception:
                worth = json.loads(raw.replace("'", '"'))
            if not isinstance(worth, dict):
                raise ValueError("worth must be a JSON object")
            if not isinstance(worth, dict):
                raise ValueError("worth must be a JSON object")
        except Exception as exc:
            return _emit({"ok": False, "command": "remember",
                          "error": "invalid_worth", "detail": str(exc)}, 2)
    for name, key in (("importance", "importance"), ("self_relevance", "self_relevance"),
                      ("mainline", "mainline")):
        value = getattr(args, name, None)
        if value is not None:
            worth[key] = float(value)
    meta = {"tags": tags, "source": str(args.source or "user")}
    for key in ("mainline", "routine", "self_defining"):
        if key in worth:
            meta[key] = worth[key]
    event = {"text": args.text, "role": "user", "session": "", "metadata": meta}
    if "importance" in worth:
        try:
            event["importance"] = max(0.0, min(1.0, float(worth["importance"])))
        except Exception:
            pass
    if "self_relevance" in worth:
        try:
            event["self_relevance"] = max(0.0, min(1.0, float(worth["self_relevance"])))
        except Exception:
            pass
    entry = engine.remember(event)
    engine.save()
    if not entry:
        return _emit({"ok": False, "command": "remember",
                      "error": "text_too_short_or_invalid"}, 2)
    return _emit({"ok": True, "command": "remember", "entry": _compact(entry)})


def cmd_recall(args):
    engine = _engine_class()(data_dir=args.store)
    rows = engine.recall(args.query, budget=max(1, int(args.limit or 3)),
                         mode=getattr(args, 'mode', 'now') or 'now')
    try:
        from ..core.config import MID_TIER
    except ImportError:
        MID_TIER = 0.35
    out = []
    for row in rows or []:
        row = row if isinstance(row, dict) else {}
        entry = row.get("entry") if isinstance(row.get("entry"), dict) else {}
        score = float(row.get("score") or 0.0)
        if score < float(MID_TIER):
            continue
        out.append({"id": entry.get("id"), "text": entry.get("text"),
                    "score": score, "mode": row.get("mode"),
                    "tier": "expand" if score >= 0.55 else "hint",
                    "role": entry.get("role"), "ts": entry.get("ts")})
    return _emit({"ok": True, "command": "recall", "query": args.query,
                  "count": len(out), "results": out,
                  "hint": "no_cue" if not out else ""})


def cmd_forget(args):
    engine = _engine_class()(data_dir=args.store)
    result = engine.forget(args.entry_id)
    engine.save()
    return _emit({"ok": result is not None, "command": "forget",
                  "id": args.entry_id, "result": result})


def cmd_pin(args, pinned):
    engine = _engine_class()(data_dir=args.store)
    result = engine.pin(args.entry_id, pinned)
    engine.save()
    return _emit({"ok": result is not None, "command": "pin" if pinned else "unpin",
                  "id": args.entry_id, "pinned": pinned, "result": result})


def cmd_consolidate(args):
    since = _parse_since(args.since)
    return _emit({"ok": True, "command": "consolidate", "noop": True,
                  "since_seconds": since,
                  "reason": "engine has no consolidate pass; CLI degraded to no-op",
                  "hint": "use tick/forget policies or implement engine.consolidate"})


def cmd_checkup(args):
    engine = _engine_class()(data_dir=args.store)
    entries = [e for e in engine.store.entries if isinstance(e, dict)]
    index = engine.build_index()
    now = time.time()
    recent = sorted(entries, key=lambda e: (-float(e.get("ts", 0) or 0),
                                            -int(e.get("hits", 0) or 0)))[:5]
    actions = []
    if not entries:
        actions.append({"action": "remember", "why": "store is empty", "count": 0})
    if entries and not index.get("entities"):
        actions.append({"action": "rebuild_index", "why": "entity index empty",
                        "count": len(entries)})
    singles = [e for e in entries if int(e.get("hits", 1) or 1) <= 1]
    if singles:
        actions.append({"action": "revisit_or_forget",
                        "why": "single-hit entries", "count": len(singles)})
    old = [e for e in entries if now - float(e.get("ts", 0) or 0) > 90 * 86400]
    if old:
        actions.append({"action": "eviction_snapshot",
                        "why": "entries older than 90d", "count": len(old)})
    report = {"ok": not actions, "command": "checkup",
              "store": str(Path(args.store).resolve() / "memory.json"),
              "entries": len(entries),
              "index": {k: len(v) for k, v in index.items()},
              "recent": [{"id": e.get("id"), "ts": e.get("ts"),
                          "hits": e.get("hits")} for e in recent],
              "top_actions": actions[:5]}
    return _emit(report, 1 if actions else 0)


def _flags_path(store):
    return Path(store) / "flags.json"


def cmd_flags(args):
    path = _flags_path(args.store)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if getattr(args, "set", ""):
        for item in str(args.set).split(","):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key, value = key.strip(), value.strip().lower()
            data[key] = value in ("1", "true", "on", "yes")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return _emit({"ok": True, "command": "flags", "path": str(path), "flags": data})


def cmd_import(args):
    engine = _engine_class()(data_dir=args.store)
    try:
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except Exception as exc:
        return _emit({"ok": False, "command": "import", "error": str(exc)[:120]}, 2)
    result = engine.import_data(payload)
    return _emit({"ok": bool(result.get("ok")), "command": "import", "result": result})


def cmd_export(args):
    engine = _engine_class()(data_dir=args.store)
    payload = engine.export()
    if getattr(args, "out", ""):
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return _emit({"ok": True, "command": "export", "out": args.out,
                      "entries": len(payload.get("entries") or [])})
    return _emit({"ok": True, "command": "export", "payload": payload})


def cmd_stats(args):
    engine = _engine_class()(data_dir=args.store)
    return _emit({"ok": True, "command": "stats", "monitor": engine.monitor()})


def cmd_snapshot(args):
    """Write the read-only UI snapshot and echo it; store is not modified."""
    engine = _engine_class()(data_dir=args.store)
    out = str(getattr(args, "out", "") or "") or str(Path(args.store) / "snapshot.json")
    target = engine.write_snapshot(out)
    if target is None:
        return _emit({"ok": False, "command": "snapshot", "path": out,
                      "error": "snapshot_write_failed"}, 2)
    payload = {}
    try:
        payload = json.loads(Path(out).read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    result = {"ok": True, "command": "snapshot", "path": out}
    if isinstance(payload, dict):
        result.update(payload)
    try:
        print(json.dumps(result, ensure_ascii=True, indent=1))
    except Exception:
        print(json.dumps({"ok": True, "command": "snapshot", "path": out}, ensure_ascii=True))
    return 0


def cmd_consolidate_run(args):
    engine = _engine_class()(data_dir=args.store)
    return _emit({"ok": True, "command": "consolidate", "result": engine.consolidate(level=1)})


def build_parser():
    p = argparse.ArgumentParser(prog="biocore-memory",
                                description="DSH adapters for BioCore memory")
    p.add_argument("--store", default="./data/memory_store",
                   help="memory data directory (default ./data/memory_store)")
    sp = p.add_subparsers(dest="command", required=True)
    r = sp.add_parser("remember", help="store one memory")
    r.add_argument("text")
    r.add_argument("--tags", default="")
    r.add_argument("--source", default="user")
    r.add_argument("--worth", default="",
                   help='memory-value JSON from the agent: {"importance":0.7,"self_relevance":0.5,"mainline":0.3}')
    r.add_argument("--importance", type=float, default=None)
    r.add_argument("--self-relevance", dest="self_relevance", type=float, default=None)
    r.add_argument("--mainline", type=float, default=None)
    r.set_defaults(func=cmd_remember)
    r = sp.add_parser("recall", help="query memories")
    r.add_argument("query")
    r.add_argument("--limit", type=int, default=3)
    r.add_argument("--mode", default="now", choices=("now", "then"))
    r.set_defaults(func=cmd_recall)
    r = sp.add_parser("forget", help="delete by id")
    r.add_argument("entry_id")
    r.set_defaults(func=cmd_forget)
    r = sp.add_parser("pin", help="pin by id")
    r.add_argument("entry_id")
    r.set_defaults(func=lambda a: cmd_pin(a, True))
    r = sp.add_parser("unpin", help="unpin by id")
    r.add_argument("entry_id")
    r.set_defaults(func=lambda a: cmd_pin(a, False))
    r = sp.add_parser("consolidate", help="degraded no-op report")
    r.add_argument("--since", default="24h")
    r.set_defaults(func=cmd_consolidate)
    r = sp.add_parser("checkup", help="health report; exit!=0 if actions")
    r.set_defaults(func=cmd_checkup)
    r = sp.add_parser("flags", help="list or set module flags (flags.json)")
    r.add_argument("--set", default="")
    r.set_defaults(func=cmd_flags)
    r = sp.add_parser("import", help="import entries/tombstones from JSON")
    r.add_argument("--file", required=True)
    r.set_defaults(func=cmd_import)
    r = sp.add_parser("export", help="export store JSON")
    r.add_argument("--out", default="")
    r.set_defaults(func=cmd_export)
    r = sp.add_parser("stats", help="engine monitor counters")
    r.set_defaults(func=cmd_stats)
    r = sp.add_parser("snapshot",
                      help="write <store>/snapshot.json and echo it (read-only)")
    r.add_argument("--out", default="",
                   help="snapshot path (default <store>/snapshot.json)")
    r.set_defaults(func=cmd_snapshot)
    r = sp.add_parser("consolidate-run", help="run gated consolidation")
    r.set_defaults(func=cmd_consolidate_run)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except Exception as exc:  # JSON error, never traceback for CLI consumers
        return _emit({"ok": False, "command": args.command,
                      "error": str(exc)[:400]}, 2)


if __name__ == "__main__":
    raise SystemExit(main())