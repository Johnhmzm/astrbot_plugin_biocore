# -*- coding: utf-8 -*-
"""Reply length (max_tokens) read/write with AstrBot config sync."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MIN_TOKENS = 128
MAX_TOKENS = 4096


class ReplyLimitError(Exception):
    def __init__(self, message, status=400):
        self.status = int(status)
        super().__init__(str(message))


def normalize(body) -> dict:
    data = body if isinstance(body, dict) else {}
    value = data.get("max_tokens", None)
    try:
        value = int(value)
    except Exception:
        raise ReplyLimitError("max_tokens must be int", 400)
    if value < MIN_TOKENS or value > MAX_TOKENS:
        raise ReplyLimitError("max_tokens out of range 128-4096", 400)
    return {"max_tokens": value}


def _providers(config) -> list:
    cfg = config if isinstance(config, dict) else {}
    provider = cfg.get("provider")
    if isinstance(provider, dict):
        return list(provider.values())
    if isinstance(provider, list):
        return provider
    return []


def read_from_config(config) -> dict:
    providers = _providers(config)
    chosen = None
    for item in providers:
        if isinstance(item, dict) and item.get("enable", True) and item.get("max_tokens") is not None:
            chosen = item
            break
    if chosen is None:
        chosen = next((item for item in providers if isinstance(item, dict)), {})
    token = chosen.get("max_tokens", None) if isinstance(chosen, dict) else None
    try:
        token = int(token) if token is not None else 800
    except Exception:
        token = 0
    return {"max_tokens": token,
            "provider_id": str(chosen.get("id") or chosen.get("type") or "") if isinstance(chosen, dict) else "",
            "provider_name": str(chosen.get("name") or chosen.get("model") or "") if isinstance(chosen, dict) else "",
            "source": "astrbot"}


def read(plugin) -> dict:
    try:
        config = plugin.context.get_config()
    except Exception:
        config = {}
    return read_from_config(config)


async def apply(plugin, body) -> dict:
    values = normalize(body)
    config = None
    try:
        config = plugin.context.get_config()
    except Exception:
        config = None
    restart_required = False
    applied = False
    if isinstance(config, dict):
        providers = _providers(config)
        target = None
        for item in providers:
            if isinstance(item, dict) and item.get("enable", True) and item.get("max_tokens") is not None:
                target = item
                break
        if target is None and providers and isinstance(providers[0], dict):
            target = providers[0]
        if target is not None:
            target["max_tokens"] = values["max_tokens"]
            try:
                save = getattr(plugin.context, "save_config_async", None)
                if save is not None:
                    await save(config)
                applied = True
            except Exception:
                applied = False
    file_path = ""
    if not applied:
        restart_required = True
    else:
        try:
            active = find_active_config(plugin)
            if active is not None and persist_max_tokens(active, values["max_tokens"]):
                file_path = str(active)
                restart_required = False
            else:
                restart_required = True
        except Exception:
            restart_required = True
    return {"ok": True, "applied": {"max_tokens": values["max_tokens"]},
            "restart_required": restart_required, "file": file_path}


def _candidate_paths(plugin=None) -> list:
    """Active AstrBot config candidates, first existing wins."""
    paths = []
    env_dir = os.environ.get("ASTRBOT_DATA_DIR") or ""
    if env_dir:
        paths.append(Path(env_dir) / "cmd_config.json")
    try:
        # file lives at <instance>/core/data/plugins/<plugin>/biocore_model/reply_limit.py
        parents = Path(__file__).resolve().parents
        core_data = parents[3] if len(parents) > 3 else parents[-1]
        paths.append(core_data / "cmd_config.json")
        instance_root = core_data.parent.parent  # <instance>
        paths.append(instance_root / "data" / "cmd_config.json")
    except Exception:
        pass
    try:
        root = Path(getattr(plugin, "data_dir", "")) if plugin is not None else None
        if root:
            paths.append(Path(root) / "cmd_config.json")
    except Exception:
        pass
    return paths


def find_active_config(plugin=None):
    for path in _candidate_paths(plugin):
        try:
            if path.is_file():
                return path
        except Exception:
            continue
    return None


def _backup(path: Path) -> None:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = path.with_name(path.name + ".bak_replylimit_" + stamp)
    try:
        backup.write_bytes(path.read_bytes())
    except Exception:
        return
    try:
        backups = sorted(path.parent.glob(path.name + ".bak_replylimit_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[3:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def persist_max_tokens(path, max_tokens: int) -> bool:
    """Atomic write to the active AstrBot config; backup before changing."""
    try:
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        providers = raw.get("provider")
        target = None
        if isinstance(providers, dict):
            target = next((item for item in providers.values() if isinstance(item, dict)), None)
        elif isinstance(providers, list):
            target = next((item for item in providers if isinstance(item, dict)), None)
        if target is None:
            return False
        target["max_tokens"] = int(max_tokens)
        _backup(path)
        tmp = path.with_name(path.name + ".tmp_replylimit")
        tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        return False
