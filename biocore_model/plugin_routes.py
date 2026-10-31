# -*- coding: utf-8 -*-
"""RoutesMixin: BioCorePlugin 的 35 个 page_* 路由方法，逐字复刻自 main.py。

生成方式：AST 从 main.py 抽取 BioCorePlugin 的同名 async 方法源码（含缩进与注释，
一字未改）。本文件不 import main；路由体里引用的 main 模块级对象
（DATA_DIR/MEMORY_DIR/STATE_DIR/USER_DIR/EVENT_ARCHIVE_PATH/DEFAULT_PROFILE/
DEFAULT_MEMORY_TRACE/LLM_FUNCTIONS/LLM_FUNCTION_DEFAULTS/_memory_index_rows/
_relationship_rows/BioCore/_sha256/interpretation/memory_meta）通过 install()
在 main.py 末尾绑定阶段从宿主 globals 注入。

绑定后 main.py 的原方法源码保留（不删除），运行时被同名属性覆盖；删掉末尾
绑定块即可回退到原方法。self._xxx 调用仍解析到宿主类（BioCorePlugin）上的
方法，所以本 mixin 必须与宿主类一起使用。
"""
from __future__ import annotations

import base64
import datetime
import io
import json
import logging
import shutil
import tempfile
import time
import types
import zipfile
from pathlib import Path

try:  # 包内导入（插件运行时）
    from .. import interpretation, memory_meta
except Exception:  # pragma: no cover - 顶层导入（测试/独立运行）
    import interpretation  # type: ignore
    import memory_meta  # type: ignore

logger = logging.getLogger("astrbot")

# main.py 模块级对象占位；install() 会用宿主同名对象覆盖。
DATA_DIR = None
MEMORY_DIR = None
STATE_DIR = None
USER_DIR = None
EVENT_ARCHIVE_PATH = None
DEFAULT_PROFILE = None
DEFAULT_MEMORY_TRACE = None
LLM_FUNCTIONS = ()
LLM_FUNCTION_DEFAULTS = {}
BioCore = None
_memory_index_rows = None
_relationship_rows = None
_sha256 = None

_INJECT_NAMES = (
    "DATA_DIR", "MEMORY_DIR", "STATE_DIR", "USER_DIR", "EVENT_ARCHIVE_PATH",
    "DEFAULT_PROFILE", "DEFAULT_MEMORY_TRACE", "LLM_FUNCTIONS",
    "LLM_FUNCTION_DEFAULTS", "BioCore", "_memory_index_rows",
    "_relationship_rows", "_sha256", "interpretation", "memory_meta",
)


def install(host_globals=None, package=None):
    """Inject host globals and align __package__ for the copied route bodies.

    Route bodies keep their original method-local imports
    (e.g. "from .biocore_model import pipeline_api"). Copying a method does not
    change the module a relative import resolves against, so the host package
    (main.py's __package__) is applied here: plugin_routes.__package__ must be
    the plugin package, not "...biocore_model". Without it those 12 routes would
    resolve ".biocore_model" one level too deep.
    """
    g = globals()
    injected = 0
    if not isinstance(host_globals, dict):
        return injected
    for name in _INJECT_NAMES:
        if name in host_globals and host_globals[name] is not None:
            g[name] = host_globals[name]
            injected += 1
    target = package if package is not None else host_globals.get("__package__")
    if target:
        g["__package__"] = str(target)
    return injected


def _ui_settings_module():
    """ui_settings module (package import first, top-level fallback)."""
    try:
        from . import ui_settings as _ui
        return _ui
    except Exception:
        try:
            from biocore_model import ui_settings as _ui
            return _ui
        except Exception:
            return None


_MODULE_FILE = Path(__file__).resolve()


def _module_candidate_paths():
    """Absolute ui_settings candidates derived from this file's own location.

    Live layout (AstrBot instance):
        .../core/data/plugins/<plugin>/biocore_model/plugin_routes.py
    parents: [0]=biocore_model, [1]=<plugin>, [2]=plugins, [3]=data (core/data)
    so parents[3] is the instance data root. This path does not depend on any
    plugin attribute (data_dir may be missing or stale on a live instance).
    """
    here = Path(globals().get("_MODULE_FILE") or __file__).resolve()
    try:
        data_root = here.parents[3]
    except IndexError:
        data_root = here.parent
    return [
        data_root / "plugin_data" / "astrbot_plugin_biocore" / "ui_settings.json",
        data_root / "plugins" / "astrbot_plugin_biocore_standalone"
        / "data" / "ui_settings.json",
    ]


def _settings_path_candidates(host):
    """[Path] ordered: module-derived absolute paths first, then host attributes.

    Module-derived candidates win because they survive a missing/stale data_dir;
    host-derived ones (data_dir/_data_dir/DATA_DIR/_persist_dir, resolved through
    ui_settings.settings_path) remain as fallbacks for dev trees and tests.
    """
    paths = []
    seen = set()

    def _add(path):
        if path is None:
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        paths.append(Path(path))

    for path in _module_candidate_paths():
        _add(path)
    ui = _ui_settings_module()
    if ui is not None and host is not None:
        hosts = []
        if getattr(host, "data_dir", None):
            hosts.append(host)
        for attr in ("_data_dir", "DATA_DIR", "_persist_dir"):
            base = getattr(host, attr, None)
            if not base:
                continue
            hosts.append(type("_UiSettingsHost", (), {"data_dir": str(base)})())
        for candidate in hosts:
            try:
                _add(ui.settings_path(candidate))
            except Exception:
                continue
    return paths


def _read_accumulator(path):
    """Direct JSON read of ui_settings.autonomy.accumulator (no load() merge)."""
    if path is None:
        return {}
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    acc = ((data.get("autonomy") or {}).get("accumulator") or {})
    if isinstance(acc, dict) and acc and any(value is not None
                                            for value in acc.values()):
        return acc
    return {}


def _authority_settings_path(host):
    """Best settings path: first with a usable accumulator, else first existing."""
    candidates = _settings_path_candidates(host)
    for path in candidates:
        if _read_accumulator(path):
            return path
    for path in candidates:
        try:
            if Path(path).exists():
                return path
        except Exception:
            continue
    return candidates[0] if candidates else None


def _autonomy_accumulator(host):
    """(accumulator, used_path): first candidate with a non-empty accumulator."""
    for path in _settings_path_candidates(host):
        acc = _read_accumulator(path)
        if acc:
            return acc, path
    return {}, None



ROUTE_NAMES = (
    "page_memory_point_feedback",
    "page_event_summary",
    "page_backup",
    "page_download",
    "page_data_export",
    "page_data_delete_token",
    "page_data_delete",
    "page_restore",
    "page_memory_rollback",
    "page_memory_delete",
    "page_memory_pin",
    "page_memory_restore",
    "page_consolidate",
    "page_status",
    "page_self_model",
    "page_toggle",
    "page_pipeline",
    "page_pipeline_toggle",
    "page_pipeline_dryrun",
    "page_persona_compile",
    "page_autonomy_test",
    "page_autonomy_tick_now",
    "page_proactive_preview",
    "page_autonomy_check",
    "page_autonomy",
    "page_reply_limit",
    "page_reply_split",
    "page_reply_soft",
    "page_memory",
    "page_core_mode",
    "page_download_info",
    "page_insight",
    "page_api_config",
    "page_kb_config",
    "page_models",
)


class RoutesMixin:
    async def page_memory_point_feedback(self):
        """POST memory-point feedback: important/unimportant/edit_label/restore/reevaluate."""
        from quart import request
        try:
            body = await request.get_json(silent=True) or {}
        except Exception:
            body = {}
        event_id, action, error = self._parse_memory_point_feedback_request(body)
        if error:
            return {"status": "error", "message": error}
        record = self._find_event_summary_record(event_id)
        if record is None:
            return {"status": "error", "message": "事件不存在"}
        if action == "reevaluate":
            return await self._page_memory_point_reevaluate(record, event_id)
        if action == "edit_label":
            title = str(body.get("title") or "").strip()
            small = str(body.get("small_summary") or "").strip()
            if not title and not small:
                return {"status": "error", "message": "至少提供标题或小标签"}
            if len(title) > 80:
                return {"status": "error", "message": "标题不能超过 80 字"}
            if len(small) > 80:
                return {"status": "error", "message": "小标签不能超过 80 字"}
        if (action == "restore"
                and not isinstance(record.get("feedback_prev"), dict)
                and not isinstance(record.get("reevaluate_prev"), dict)):
            return {"status": "error", "message": "没有可恢复的反馈前版本"}
        try:
            changed = self._rewrite_jsonl_atomic(
                EVENT_ARCHIVE_PATH,
                lambda obj: self._apply_memory_point_feedback(obj, event_id, action, body))
        except Exception as exc:
            logger.warning("[biocore] memory point feedback rewrite failed: %s", exc)
            changed = 0
        if changed <= 0:
            return {"status": "error", "message": "事件不存在或写入失败"}
        # Per-session copy stays in sync (best effort; same atomic rewrite).
        try:
            session = str(record.get("session") or "")
            if session:
                self._rewrite_jsonl_atomic(
                    self._event_session_file(session),
                    lambda obj: self._apply_memory_point_feedback(
                        obj, event_id, action, body))
        except Exception:
            pass
        saved = self._find_event_summary_record(event_id) or {}
        return {"status": "ok", "data": self._memory_point_public(saved)}

    async def page_event_summary(self):
        """Regenerate (LLM/fallback) or manually edit one archived event summary."""
        from quart import request
        try:
            body = await request.get_json(silent=True) or {}
        except Exception:
            body = {}
        event_id, action, error = self._parse_event_summary_request(body)
        if error:
            return {"status": "error", "message": error}
        record = self._find_event_summary_record(event_id)
        if record is None:
            return {"status": "error", "message": "事件不存在"}
        try:
            if action == "regenerate":
                updates = await self._regenerate_event_summary_fields(record)
            else:
                big, small, error = self._validate_edited_event_summary(
                    body.get("big_summary"), body.get("small_summary"),
                    getattr(self, "summary_max_chars", 0))
                if error:
                    return {"status": "error", "message": error}
                updates = {"big_summary": big, "small_summary": small,
                           "summary_status": "edited", "summary_edited": True,
                           "summary_updated_ts": time.time()}
                if body.get("title") is not None:
                    checked_title, title_error = self._validate_edited_event_title(
                        body.get("title"))
                    if title_error:
                        return {"status": "error", "message": title_error}
                    updates["title"] = checked_title
        except Exception as exc:
            logger.warning("[biocore] event summary %s failed: %s", action, exc)
            return {"status": "error", "message": "处理失败"}
        # task-51: a regenerate fills a missing secondary emotion from the live
        # core spectrum (primary excluded). update never rewrites it; no core
        # data keeps the field empty instead of fabricating one.
        if action == "regenerate" and not str(record.get("emotion_secondary") or "").strip():
            _secondary = self._event_secondary_for_record(record)
            if _secondary:
                updates["emotion_secondary"] = _secondary
        try:
            changed = self._rewrite_jsonl_atomic(
                EVENT_ARCHIVE_PATH,
                lambda obj: self._apply_event_summary_with_history(obj, event_id, updates))
        except Exception as exc:
            logger.warning("[biocore] event summary rewrite failed: %s", exc)
            changed = 0
        if changed <= 0:
            return {"status": "error", "message": "事件不存在或写入失败"}
        saved = self._find_event_summary_record(event_id) or {}
        history = saved.get("summary_history")
        payload = dict({"event_id": event_id, "action": action}, **updates)
        if "emotion_secondary" not in payload and str(saved.get("emotion_secondary") or "").strip():
            payload["emotion_secondary"] = str(saved.get("emotion_secondary") or "").strip()
        if isinstance(saved.get("emotion_nuance"), list):
            payload["emotion_nuance"] = list(saved.get("emotion_nuance") or [])[:3]
        if isinstance(saved.get("emotion_layers"), list):
            payload["emotion_layers"] = [dict(x) for x in (saved.get("emotion_layers") or [])[:4]
                                         if isinstance(x, dict)]
        try:
            payload["emotion_intensity"] = round(
                float(saved.get("emotion_intensity", 0.0) or 0.0), 4)
        except Exception:
            pass
        if str(saved.get("emotion_layers_source") or "").strip():
            payload["emotion_layers_source"] = str(
                saved.get("emotion_layers_source") or "").strip()
        payload["summary_history"] = history if isinstance(history, list) else []
        return {"status": "ok", "data": payload}

    async def page_backup(self):
        """P0-1: POST + explicit confirm; returns a one-time download token."""
        from quart import request
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可备份"}
        if not body.get("confirm"):
            return {"status": "error",
                    "message": "需要二次确认：备份含记忆/状态，但不含 API Key"}
        try:
            data = self._safe_backup_zip()
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180]}
        stamp = time.strftime("%Y%m%d_%H%M")
        filename = "biocore_safe_" + stamp + ".zip"
        token = _sha256(str(time.time()) + "|" + str(len(data)) + "|" + filename)[:24]
        store = getattr(self, "_download_tokens", {}) or {}
        store[token] = (data, filename, time.time())
        self._download_tokens = dict(list(store.items())[-5:])
        return {"status": "ok", "data": {
            "token": token, "filename": filename, "size": len(data),
            "download_url": "/astrbot_plugin_biocore/page/download/" + token}}

    async def page_download(self, token: str):
        try:
            from quart import Response
        except Exception:
            Response = None
        item = (getattr(self, "_download_tokens", {}) or {}).pop(token, None)
        if not item:
            return {"status": "error", "message": "token invalid or already used"}
        data, filename, ts = item
        if time.time() - float(ts or 0) > 300:
            return {"status": "error", "message": "token expired"}
        if Response is None:
            return {"status": "error", "message": "server cannot stream"}
        return Response(data, mimetype="application/zip", headers={
            "Content-Disposition": "attachment; filename=" + filename,
            "Cache-Control": "no-store"})

    async def page_data_export(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可导出"}
        if not body.get("confirm"):
            return {"status": "error", "message": "需要二次确认（导出含个人记忆）"}
        return {"status": "ok", "data": self._data_export_payload()}

    async def page_data_delete_token(self):
        """P2: one-time token for hard-delete confirmation (not a boolean)."""
        from quart import request
        try:
            body = await request.get_json(silent=True) or {}
        except Exception:
            body = {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可删除"}
        token = _sha256(str(time.time()) + "|" + str(id(self)))[:24]
        store = getattr(self, "_delete_tokens", {}) or {}
        store[token] = time.time()
        self._delete_tokens = dict(list(store.items())[-5:])
        return {"status": "ok", "data": {"token": token, "expires_in": 300}}

    async def page_data_delete(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可删除"}
        token = str(body.get("token") or "")
        store = getattr(self, "_delete_tokens", {}) or {}
        issued = store.get(token)
        if not token or issued is None:
            return {"status": "error",
                    "message": "需要一次性删除确认 token（先调用 data_delete_token）"}
        if time.time() - float(issued or 0) > 300:
            return {"status": "error", "message": "删除 token 已过期"}
        self._delete_tokens.pop(token, None)
        scopes = body.get("scopes")
        return self._delete_data_scopes(scopes)

    async def page_restore(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可恢复"}
        raw_b64 = str(body.get("base64") or "")
        if not raw_b64:
            return {"status": "error", "message": "empty backup"}
        try:
            raw = base64.b64decode(raw_b64)
            z = zipfile.ZipFile(io.BytesIO(raw))
        except Exception as exc:
            return {"status": "error", "message": "invalid zip: %s" % exc}
        names = [n for n in z.namelist() if n.startswith("data/") and not n.endswith("/")]
        if not names:
            return {"status": "error", "message": "backup has no data/ entries"}
        # automatic safety backup of current data before overwrite
        try:
            backup_dir = DATA_DIR.parent / "restore_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            safety = backup_dir / ("before_restore_" + stamp + ".zip")
            with zipfile.ZipFile(safety, "w", zipfile.ZIP_DEFLATED) as bz:
                for f in DATA_DIR.rglob("*"):
                    if f.is_file() and "__pycache__" not in f.parts:
                        bz.write(f, str(f.relative_to(DATA_DIR)))
        except Exception as exc:
            logger.warning("[biocore] restore safety backup failed: %s", exc)
        count = 0
        skipped_api_config = False
        _stage = Path(tempfile.mkdtemp(prefix="biocore_restore_stage_"))
        _rollback = Path(tempfile.mkdtemp(prefix="biocore_restore_rollback_"))
        staged_files = {}
        rollback_files = {}
        try:
            for name in names:
                rel = name[len("data/"):]
                if self._is_secret_name(rel.split("/")[-1]) or                         rel.lower().endswith("api_config.json"):
                    # P2: never overwrite the live API keys from a backup.
                    skipped_api_config = True
                    continue
                parts = [x for x in rel.split("/") if x not in ("", ".", "..")]
                if not parts:
                    continue
                rel_clean = "/".join(parts)
                staged = _stage.joinpath(*parts)
                staged.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, open(staged, "wb") as out:
                    shutil.copyfileobj(src, out)
                staged_files[rel_clean] = staged
                dest = DATA_DIR.joinpath(*parts)
                if dest.exists():
                    snap = _rollback.joinpath(*parts)
                    snap.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(dest), str(snap))
                    rollback_files[rel_clean] = snap
            count, _err = self._commit_restore(staged_files, rollback_files)
            if _err:
                return {"status": "error",
                        "message": "restore failed, 已回滚: %s" % _err}
        except Exception as exc:
            logger.warning("[biocore] restore failed: %s", exc)
            return {"status": "error", "message": "restore failed, 已回滚: %s" % exc}
        finally:
            try:
                shutil.rmtree(_stage, ignore_errors=True)
                shutil.rmtree(_rollback, ignore_errors=True)
            except Exception:
                pass
        try:
            self._load_profile()
            self._load_settings()
            self._load_api_config()
            self.cores = {}
        except Exception:
            pass
        logger.info("[biocore] restored %s data files", count)
        return {"status": "ok", "data": {
            "files": count,
            "api_config_skipped": skipped_api_config,
            "message": ("已恢复 %d 个文件；已跳过 api_config（保留当前 Key）" % count)}}

    async def page_memory_rollback(self, session: str, entry_id: str):
        """Rollback one memory entry to its previous version (dashboard API)."""
        try:
            path, doc = self._memory_doc_for_session(session)
            entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
            target = self._memory_find_entry(entries, entry_id)
            if target is None:
                return {"status": "error", "message": "memory entry not found", "data": {}}
            if not memory_meta.rollback_entry(target):
                return {"status": "error", "message": "no previous version", "data": {}}
            try:
                _text = str(target.get("text", ""))
                _sens = bool(target.get("sensitive"))
                if not _sens and getattr(self, "safety_enabled", False):
                    _sens = bool(memory_meta.classify_sensitivity(_text).get("sensitive"))
                _vec = await self._embed_text_guarded(_text, _sens)
                if _vec:
                    target["vector"] = _vec
                    target["needs_reindex"] = False
                else:
                    target["needs_reindex"] = True
            except Exception:
                target["needs_reindex"] = True
            target["rollback_ts"] = time.time()
            self._memory_save_doc_for_session(path, doc)
            return {"status": "ok", "data": {"session": session, "id": entry_id, "text": target.get("text", "")[:160]}}
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180], "data": {}}

    async def page_memory_delete(self, session: str, entry_id: str):
        """Soft-delete one memory entry; keeps a tombstone for audit."""
        try:
            path, doc = self._memory_doc_for_session(session)
            entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
            target = self._memory_find_entry(entries, entry_id)
            if target is None:
                return {"status": "error", "message": "memory entry not found", "data": {}}
            doc["tombstones"] = (doc.get("tombstones") if isinstance(doc.get("tombstones"), list) else [])[-100:]
            doc["tombstones"].append({
                "id": entry_id, "ts": round(time.time(), 3),
                "status": "已删除",
                "sha256": _sha256(str(target.get("text", "")))[:16],
            })
            doc["entries"] = [e for e in entries if not (isinstance(e, dict) and self._memory_entry_id(e) == entry_id)]
            memory_meta.append_write_log(doc, op="DELETE", entry_id=entry_id,
                                         reason="dashboard", ts=time.time())
            # Propagate the deletion to derived summaries/events/insights.
            try:
                _event = types.SimpleNamespace(unified_msg_origin=session)
                self._propagate_memory_deletion(_event, target, doc, reason="dashboard")
            except Exception:
                pass
            self._memory_save_doc_for_session(path, doc)
            return {"status": "ok", "data": {"session": session, "id": entry_id, "deleted": True}}
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180], "data": {}}

    async def page_memory_pin(self, session: str, entry_id: str):
        """task-38: pin/unpin one memory entry (pinned rows escape the cap)."""
        from quart import request
        try:
            body = await request.get_json(silent=True) or {}
        except Exception:
            body = {}
        if not getattr(self, "memory_pin_enabled", True):
            return {"status": "error", "message": "pin 功能未开启"}
        try:
            path, doc = self._memory_doc_for_session(session)
            entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
            target = self._memory_find_entry(entries, entry_id)
            if target is None:
                return {"status": "error", "message": "memory entry not found", "data": {}}
            pinned = bool(body.get("pin", True))
            memory_meta.set_pinned(target, pinned)
            target["pin_ts"] = round(time.time(), 3)
            memory_meta.append_write_log(doc, op="PIN" if pinned else "UNPIN",
                                         entry_id=entry_id, reason="dashboard",
                                         ts=time.time())
            self._memory_save_doc_for_session(path, doc)
            return {"status": "ok", "data": {"session": session, "id": entry_id,
                                             "pin": pinned}}
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180], "data": {}}

    async def page_memory_restore(self, session: str, entry_id: str):
        """Restore a soft-deleted entry, or recreate one from a tombstone.

        Note: archive/insight redactions made at deletion time are not undone
        (deletion propagation is one-way for derived artifacts).
        """
        try:
            path, doc = self._memory_doc_for_session(session)
            entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
            target = self._memory_find_entry(entries, entry_id)
            from_tombstone = False
            if target is not None:
                if not memory_meta.restore_entry(target):
                    return {"status": "error", "message": "memory entry is not deleted",
                            "data": {}}
            else:
                tombstones = doc.get("tombstones") if isinstance(doc.get("tombstones"), list) else []
                tomb = next((item for item in tombstones if isinstance(item, dict)
                             and str(item.get("id") or "") == entry_id), None)
                if tomb is None:
                    return {"status": "error", "message": "memory entry not found", "data": {}}
                if not str(tomb.get("text") or "").strip():
                    return {"status": "error",
                            "message": "tombstone 已脱敏，无法从 tombstone 恢复原文",
                            "data": {}}
                target = {"id": entry_id,
                          "text": str(tomb.get("text") or "")[:1200],
                          "role": "user", "ts": time.time(), "hits": 1,
                          "importance": 0.5, "memory_source": "inferred",
                          "memory_confidence": 0.35, "memory_tier": "warm",
                          "last_write_op": "RESTORE",
                          "restored_from_tombstone": True}
                doc["tombstones"] = [item for item in tombstones
                                     if not (isinstance(item, dict)
                                             and str(item.get("id") or "") == entry_id)]
                entries.append(target)
                from_tombstone = True
            try:
                _text = str(target.get("text", ""))
                _sens = bool(target.get("sensitive"))
                if not _sens and getattr(self, "safety_enabled", False):
                    _sens = bool(memory_meta.classify_sensitivity(_text).get("sensitive"))
                _vec = await self._embed_text_guarded(_text, _sens)
                if _vec:
                    target["vector"] = _vec
                    target["needs_reindex"] = False
                else:
                    target["needs_reindex"] = True
            except Exception:
                target["needs_reindex"] = True
            target["restored_ts"] = time.time()
            target["last_write_op"] = "RESTORE"
            memory_meta.append_write_log(
                doc, op="RESTORE", entry_id=entry_id,
                reason=("tombstone" if from_tombstone else "soft_delete"),
                ts=time.time())
            self._memory_save_doc_for_session(path, doc)
            return {"status": "ok", "data": {"session": session, "id": entry_id,
                                            "text": str(target.get("text") or "")[:160],
                                            "restored": True,
                                            "from_tombstone": from_tombstone}}
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180], "data": {}}

    async def page_consolidate(self):
        """Force one memory consolidation pass over all local sessions."""
        results = []
        try:
            files = sorted(MEMORY_DIR.glob("*.json"))
        except Exception:
            files = []
        if getattr(self, "_consolidating", False):
            return {"status": "ok", "data": {"files": 0, "message": "already running"}}
        self._consolidating = True
        try:
            for f in files:
                key = f.stem
                ev = types.SimpleNamespace(unified_msg_origin=key)
                try:
                    core = self._core(ev)
                    await self._consolidate_memory(ev, core, force=True)
                    results.append(key)
                except Exception as exc:
                    logger.warning("[biocore] manual consolidation failed: %s", exc)
        finally:
            self._consolidating = False
            self._last_consolidation = time.time()
        return {"status": "ok", "data": {"files": len(results), "sessions": len(files)}}

    async def page_status(self):
        try:
            self._ensure_autonomy_task()
        except Exception:
            pass
        _personas = []
        try:
            _pm = getattr(self.context, "persona_manager", None)
            if _pm is not None:
                for _p in (await _pm.get_all_personas()):
                    _pid = str(getattr(_p, "persona_id", "") or "")
                    _pname = str(getattr(_p, "name", "") or _pid)
                    if _pid:
                        _personas.append({"id": _pid, "name": _pname})
        except Exception:
            _personas = []
        cores = []
        for key, core in list(self.cores.items())[:20]:
            cores.append({
                "key": key,
                "snapshot": core.snapshot(),
                "intent": {**core.intent(), "plan": interpretation.plan(core)},
                "working_set": self._working_set_preview(key),
            })
        if not cores:
            # The in-memory cache is empty after a restart. Load persisted
            # states so the dashboard does not silently fall back to demo data.
            try:
                files = sorted(STATE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:20]
            except Exception:
                files = []
            for path in files:
                try:
                    state = json.loads(path.read_text(encoding="utf-8"))
                    core = BioCore(self.profile)
                    core.load_state(state)
                    cores.append({
                        "key": path.stem,
                        "snapshot": core.snapshot(),
                        "intent": {**core.intent(), "plan": interpretation.plan(core)},
                        "working_set": self._working_set_preview(path.stem),
                    })
                except Exception:
                    continue
        _data = {
            "enabled": self.enabled,
            "inject_intent": self.inject_intent,
            "proactive_reply": self.proactive_reply,
            "memory_dedup_embedding": self.memory_dedup_embedding,
            "memory_worthiness_enabled": bool(
                getattr(self, "memory_worthiness_enabled", True)),
            "hybrid_retrieval": bool(getattr(self, "hybrid_retrieval", True)),
            "safety_enabled": bool(getattr(self, "safety_enabled", False)),
            "llm_memory_candidates": bool(
                getattr(self, "llm_memory_candidates", True)),
            "we_memory_enabled": bool(getattr(self, "we_memory_enabled", False)),
            "bc_prompt_mode": str(getattr(self, "bc_prompt_mode", "telemetry") or "telemetry"),
            "summary_max_chars": int(getattr(self, "summary_max_chars", 0) or 0),
            "llm_only_reply_summary": bool(
                getattr(self, "llm_only_reply_summary", True)),
            "insight_auto_enabled": bool(getattr(self, "insight_auto_enabled", False)),
            "persona_loaded": bool(self.persona_text),
            "persona_id": str(getattr(self, "persona_id", "") or ""),
            "personas": _personas,
            "llm_functions": self._functions_public(),
            "llm_providers": self._llm_provider_options(),
            "profile": self.profile or dict(DEFAULT_PROFILE),
            "api_config": self._public_api_config(),
            "memory": self._memory_stats(),
            # Read-only dashboard contract (bounded): memory entries per
            # session with provenance/confidence/write-op metadata, tombstone
            # audit rows, and per-user relationship state/trajectory/maps.
            "memory_index": _memory_index_rows(MEMORY_DIR),
            "relationships": _relationship_rows(USER_DIR),
            "last_memory_meta": {
                "calibration_delta": 0.0, "calibration_sources": 0,
                **dict(getattr(self, "_last_memory_meta", {}) or {})},
            "last_memory_trace": {**DEFAULT_MEMORY_TRACE,
                                  **dict(getattr(self, "_last_memory_trace", {}) or {})},
            # Paper mechanisms also at top level for dashboard/API consumers.
            "circadian_alertness": round(float(getattr(cores[0], "circadian_alertness", 0.5)), 3) if cores else 0.5,
            "allostatic_load": round(float(getattr(cores[0], "allostatic_load", 0.0)), 3) if cores else 0.0,
            "homeostasis": dict(getattr(cores[0], "homeostasis", {}) or {}) if cores else {},
            # L-T02/L-T03..L-T12 read-only runtime surface (bounded, no prompt text)
            "last_cause_trace": [dict(x) for x in (getattr(self, "_last_cause_trace", []) or [])[:8]
                                 if isinstance(x, dict)],
            "last_strategy_hint": str(getattr(self, "_last_strategy_hint", "") or "")[:140],
            # task-36 read-only projections are appended ONLY when their opt-in
            # switches are ON (P1-2: default OFF => no new page/status fields).
            "kb_config": {"enabled": bool(getattr(self, "kb_enabled", False)),
                          "names": list(getattr(self, "kb_names", []))},
            "kb_available": await self._kb_available(),
            "astrbot_llm": {k: v for k, v in (self._astrbot_llm_default() or {}).items() if not k.startswith("_")},
            "astrbot_embedding": {k: v for k, v in (self._astrbot_embedding_default() or {}).items() if not k.startswith("_")},
            "astrbot_rerank": {k: v for k, v in (self._astrbot_rerank_default() or {}).items() if not k.startswith("_")},
            "astrbot_tts": {k: v for k, v in (self._astrbot_tts_default() or {}).items() if not k.startswith("_")},
            "astrbot_image": {k: v for k, v in (self._astrbot_image_default() or {}).items() if not k.startswith("_")},
            "cores": cores,
            "self_model": dict(self.self_model or {}),
            "events": [dict(_ev,
                            effective_merge_count=self._decayed_merge_count(_ev))
                       for _ev in self._event_archive(30, read_only=True)
                       if isinstance(_ev, dict)],
            "insights": self._insights(5),
        }
        # P1-2: default-OFF telemetry/token/consistency add no keys at all.
        if getattr(self, "llm_telemetry_enabled", False):
            _data["llm_telemetry"] = {
                "enabled": True,
                "counters": dict(((getattr(self, "_llm_telemetry", {}) or {}).get("counters") or {})),
                "recent": [dict(x) for x in (((getattr(self, "_llm_telemetry", {}) or {}).get("recent") or []))[:10]
                           if isinstance(x, dict)]}
        if getattr(self, "token_usage_enabled", False):
            _data["token_usage"] = {
                "enabled": True,
                "available": bool(((getattr(self, "_token_usage", {}) or {}).get("available", False))),
                "sessions": {str(k)[:80]: dict(v) for k, v in
                             list((((getattr(self, "_token_usage", {}) or {}).get("sessions") or {})).items())[:10]
                             if isinstance(v, dict)}}
        if (getattr(self, "reply_consistency_enabled", False)
                and cores and isinstance(getattr(cores[0], "reply_consistency", None), dict)):
            _data["reply_consistency"] = dict(cores[0].reply_consistency)
        # 1.3.1 model-layer read-only panels (each one gated by its switch).
        if (getattr(self, "bc_trace_enabled", False)
                and isinstance(getattr(self, "_last_injection_trace", None), dict)):
            _data["injection_trace"] = dict(self._last_injection_trace)
            _data["parse_stats"] = dict(interpretation.PARSE_STATS)
        if (getattr(self, "think_selfcheck_trace_enabled", True)
                and isinstance(getattr(self, "_last_reverse_check", None), dict)):
            _data["reverse_check"] = dict(self._last_reverse_check)
        if (getattr(self, "think_repeat_guard_enabled", False)
                and isinstance(getattr(self, "_repeat_guard", None), dict)):
            _data["repeat_guard"] = dict(self._repeat_guard)
        if getattr(self, "sycophancy_check_enabled", True):
            _syco = None
            if cores and isinstance(getattr(cores[0], "sycophancy_check", None), dict):
                _syco = dict(cores[0].sycophancy_check)
            if _syco is not None:
                _data["sycophancy_check"] = _syco
        if (getattr(self, "path_monitor_enabled", False)
                and isinstance(getattr(self, "_path_monitor", None), dict)):
            _data["path_monitor"] = dict(self._path_monitor)
        if getattr(self, "think_reflect_enabled", False):
            _data["think_reflect"] = {
                "hint": str(getattr(self, "_reflect_hint", "") or "")[:140],
                "stats": {str(k)[:80]: dict(v) for k, v in
                          list((getattr(self, "_reflect_stats", {}) or {}).items())[:10]
                          if isinstance(v, dict)}}
        if getattr(self, "token_budget_enabled", True):
            _tb = getattr(self, "_token_budget", {}) or {}
            _data["token_budget"] = {
                "enabled": True,
                "today": dict(_tb.get("today") or {}),
                "calls": int(_tb.get("calls", 0) or 0),
                "sessions": {str(k)[:80]: dict(v) for k, v in
                             list((_tb.get("sessions") or {}).items())[:10]
                             if isinstance(v, dict)},
                "prices": {"input_per_1m": float(getattr(self, "cost_input_per_1m", 2.0) or 0.0),
                           "output_per_1m": float(getattr(self, "cost_output_per_1m", 8.0) or 0.0),
                           "cache_per_1m": float(getattr(self, "cost_cache_per_1m", 0.5) or 0.0)},
                "savings_mode": bool(getattr(self, "savings_mode", False))}
        if any(getattr(self, k, False) for k in (
                "learning_bandit_enabled", "learning_relationship_enabled",
                "learning_worthiness_enabled")):
            _data["learning_state"] = {str(k)[:80]: dict(v) for k, v in
                                         (getattr(self, "_learning", {}) or {}).items()
                                         if isinstance(v, dict)}
        if (getattr(self, "relationship_chain_enabled", False)
                or getattr(self, "gottman_enabled", False)):
            _rd = getattr(cores[0], "relationship_dynamics", None) if cores else None
            if isinstance(_rd, dict):
                _data["relationship_dynamics"] = dict(_rd)
        if (getattr(self, "big5_effect_enabled", False) and cores
                and isinstance(getattr(cores[0], "big5_effect", None), dict)):
            _data["big5_effect"] = dict(cores[0].big5_effect)
        if getattr(self, "rerank_enabled", False):
            _data["rerank_stats"] = dict(getattr(self, "_rerank_stats", {}) or {})
        # P0-3 / P1-7: security + migration notices (read-only banners).
        if not getattr(self, "safety_enabled", False):
            _data["security_notice"] = {
                "safety_enabled": False,
                "message": "safety_enabled=false：公开部署建议保持开启；私人使用可关。"
                           "当前关闭敏感掩码/跨会话隔离/低置信拒答/投毒过滤。"}
        try:
            _marker = DATA_DIR / "migration_seen.json"
            if not _marker.exists():
                self._migration_note = (
                    "1.3.0 默认变化：memory_worthiness / memory_pin / "
                    "bc_budget(浪费治理) / F1 trace 默认开启；可在插件配置逐项关闭。")
                _marker.parent.mkdir(parents=True, exist_ok=True)
                _marker.write_text(json.dumps({"seen": True, "ts": time.time()}),
                                   encoding="utf-8")
        except Exception:
            pass
        if self._migration_note:
            _data["migration_note"] = self._migration_note
        _bg = getattr(self, "_bg_llm_usage", {}) or {}
        _data["background_budget"] = {
            "day": str(_bg.get("day") or ""),
            "calls": int(_bg.get("calls", 0) or 0),
            "cost": round(float(_bg.get("cost", 0.0) or 0.0), 6),
            "daily_calls": int(getattr(self, "bg_llm_daily_calls", 200) or 200),
            "daily_cost": float(getattr(self, "bg_llm_daily_cost", 2.0) or 2.0)}
        if int(getattr(self, "_corrupt_backups", 0) or 0):
            _data["corrupt_backups"] = int(self._corrupt_backups)
        _data["env_checks"] = dict(getattr(self, "_env_checks", {}) or {})
        try:
            _auto_state = getattr(self, "_autonomy_readonly_state", None)
            if callable(_auto_state):
                try:
                    _auto_state = _auto_state()
                except Exception:
                    _auto_state = None
            if not isinstance(_auto_state, dict):
                _auto_state = {}
                for _c in list((getattr(self, "cores", {}) or {}).values()):
                    try:
                        _s = _c.autonomy_state(self._relationship_of({}), persist=False)
                        if isinstance(_s, dict) and _s:
                            _auto_state = _s
                            break
                    except Exception:
                        continue
        except Exception:
            _auto_state = {}
        # Accumulator merge runs OUTSIDE the state block above: even if the
        # in-memory source (attr/method/cores) fails, the persisted authority
        # values must still reach data.autonomy.state. Path comes from
        # ui_settings.settings_path(), then a direct JSON read (load()'s merge
        # chain proved unreliable on a real plugin instance).
        _acc = {}
        _used_path = None
        _candidates = []
        try:
            _candidates = [str(path) for path in _settings_path_candidates(self)]
        except Exception:
            _candidates = []
        try:
            _acc, _used_path = _autonomy_accumulator(self)
        except Exception:
            _acc, _used_path = {}, None
        if isinstance(_acc, dict) and _acc:
            _auto_state = dict(_auto_state or {}, **_acc)
        try:
            _data["autonomy"] = {
                "enabled": bool(getattr(self, "proactive_autonomy", False)),
                "send": bool(getattr(self, "proactive_send", False)),
                "state": _auto_state or {},
                "_debug": {
                    "candidates": list(_candidates),
                    "exists": [bool(Path(path).exists()) for path in _candidates],
                    "used": str(_used_path) if _used_path else "",
                    "acc_keys": (sorted(_acc.keys())[:10]
                                 if isinstance(_acc, dict) else []),
                },
            }
        except Exception:
            pass
        return {"status": "ok", "data": _data}

    async def page_self_model(self):
        from quart import request
        if request.method == "POST":
            body = await request.get_json(silent=True) or {}
            for key in ("who_am_i", "boundaries", "consistency", "narrative"):
                if key not in body:
                    continue
                val = body.get(key)
                if key in ("boundaries", "consistency"):
                    if isinstance(val, str):
                        val = [x.strip() for x in val.splitlines() if x.strip()]
                    self.self_model[key] = [str(x)[:300] for x in (val or [])[:10]]
                else:
                    self.self_model[key] = str(val or "")[:1500]
            self._save_self_model()
        return {"status": "ok", "data": {"self_model": self.self_model}}

    async def page_toggle(self):
        from quart import request
        data = await request.get_json(silent=True) or {}
        key = str(data.get("key") or "").strip()
        _fn_enabled = {("%s_enabled" % _name): _name for _name in LLM_FUNCTIONS}
        _fn_provider = {("%s_provider" % _name): _name for _name in LLM_FUNCTIONS}
        if key in _fn_enabled or key in _fn_provider:
            _name = _fn_enabled.get(key) or _fn_provider.get(key)
            _cur = dict(self.llm_functions.get(_name) or {})
            if key in _fn_enabled:
                _cur["enabled"] = bool(data.get("value"))
            else:
                _cur["provider"] = str(data.get("value") or "follow_llm").strip() or "follow_llm"
            _cur.pop("embedding_provider", None)
            _cur.pop("rerank_provider", None)
            self.llm_functions[_name] = _cur
            self.api_config["functions"] = dict(self.llm_functions)
            self._save_api_config()
            return {"status": "ok", "data": {"key": key, "value": _cur.get("enabled") if key in _fn_enabled else _cur.get("provider")}}
        if key not in ("proactive_reply", "memory_dedup_embedding", "inject_intent",
                       "hybrid_retrieval", "safety_enabled", "llm_memory_candidates",
                       "llm_only_reply_summary", "persona_id",
                       "insight_auto_enabled"):
            return {"status": "error", "message": "unknown setting"}
        if key == "persona_id":
            _val = str(data.get("value") or "").strip()
            self.persona_id = _val
            self._save_settings()
            await self._persist_plugin_config({key: _val})
            return {"status": "ok", "data": {"key": key, "value": _val}}
        if key == "llm_only_reply_summary":
            # Legacy master switch: keep it readable, but migrate all per-function
            # routes once instead of treating it as the only switch.
            self.llm_only_reply_summary = bool(data.get("value"))
            _legacy = bool(self.llm_only_reply_summary)
            for _name in LLM_FUNCTIONS:
                self.llm_functions[_name] = {
                    "enabled": (LLM_FUNCTION_DEFAULTS[_name] if _legacy else True),
                    "provider": str((self.llm_functions.get(_name) or {}).get("provider") or "follow_llm"),
                }
            self.api_config["functions"] = dict(self.llm_functions)
            self._save_api_config()
            self._save_settings()
            await self._persist_plugin_config({key: bool(self.llm_only_reply_summary)})
            return {"status": "ok", "data": {"key": key, "value": self.llm_only_reply_summary}}
        if key == "safety_enabled":
            self.safety_enabled = bool(data.get("value"))
            self.cross_session_memory = not self.safety_enabled
            self.sensitive_memory_protection = self.safety_enabled
            self._save_settings()
            await self._persist_plugin_config({key: self.safety_enabled})
            logger.info("[biocore] safety_enabled=%s", self.safety_enabled)
            return {"status": "ok", "data": {"key": key, "value": self.safety_enabled}}
        setattr(self, key, bool(data.get("value")))
        self._save_settings()
        await self._persist_plugin_config({key: bool(getattr(self, key))})
        logger.info("[biocore] setting %s=%s", key, getattr(self, key))
        return {"status": "ok", "data": {"key": key, "value": getattr(self, key)}}

    async def page_pipeline(self):
        from .biocore_model import pipeline_api as _pa
        return {"status": "ok", "data": _pa.payload_status(self)}

    async def page_pipeline_toggle(self):
        from quart import request

        from .biocore_model import pipeline_api as _pa
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可切换流水线"}
        result = _pa.payload_toggle(self, str(body.get("name") or ""),
                                    bool(body.get("enabled", True)))
        return {"status": "ok" if result.get("ok") else "error",
                "data": result, "message": result.get("message", "")}

    async def page_pipeline_dryrun(self):
        from quart import request

        from .biocore_model import pipeline_api as _pa
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可试运行流水线"}
        return {"status": "ok",
                "data": _pa.payload_dryrun(self, str(body.get("sample_text") or ""))}

    async def page_persona_compile(self):
        from quart import request
        await request.get_json(silent=True)
        if not self._llm_allowed("persona_compile"):
            return {"status": "error", "data": {"ok": False, "error": "persona_compile_disabled",
                                                "message": "persona_compile 已被 LLM 功能开关禁用"}}
        try:
            await self._compile_profile(None)
        except Exception as exc:
            return {"status": "ok", "data": {"ok": False, "error": "compile_failed",
                                             "message": str(exc)[:180]}}
        return {"status": "ok", "data": {"ok": True,
                                         "version": len(getattr(self, "schema_texts", []) or []),
                                         "persona_hash": str(getattr(self, "_persona_compiled_hash", ""))[:12]}}

    async def page_autonomy_test(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        if body.get("reset"):
            self._autonomy_test_arm = {}
            return {"status": "ok", "data": {"ok": True, "reset": True, "V_set": 0.0}}
        core = next(iter(self.cores.values()), None) if isinstance(self.cores, dict) else None
        state = {}
        try:
            state = core.autonomy_state() if core is not None else {}
        except Exception:
            state = {}
        theta = float(state.get("threshold", 0.6) or 0.6)
        v_set = round(min(1.0, theta + 0.05), 4)
        self._autonomy_test_arm = {"V": v_set, "theta": theta, "ts": time.time()}
        try:
            from .biocore_model import ui_settings as _ui
        except Exception:
            from biocore_model import ui_settings as _ui
        _ui.save(self, {"autonomy": {"accumulator": {"V": v_set, "ticks_since_fire": 0}}})
        return {"status": "ok", "data": {"ok": True, "V_set": v_set, "theta": theta}}

    async def page_autonomy_tick_now(self):
        """Debug: run one autonomy tick immediately (no wait for 5-min loop)."""
        from quart import request
        _body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin():
            return {"ok": False, "error": "forbidden"}
        try:
            import time as _t
            _sent = await self._autonomy_tick(_t.time())
            return {"ok": True, "sent": list(_sent or []), "at": _t.time()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    async def page_proactive_preview(self):
        """Debug: build proactive prompt/text without sending."""
        from quart import request
        _body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin():
            return {"ok": False, "error": "forbidden"}
        try:
            import time as _t
            try:
                from .biocore_model import ui_settings as _ui
            except Exception:
                from biocore_model import ui_settings as _ui
            _now = _t.time()
            _acc = dict((_ui.load(self).get('autonomy') or {}).get('accumulator') or {})
            _key, _core = (None, None)
            try:
                _sessions = dict(getattr(self, '_autonomy_private_sessions', {}) or {})
                _umo = next(iter(_sessions), '') or str(_acc.get('last_umo') or '')
                _cores = getattr(self, 'cores', {}) or {}
                _core = _cores.get(_umo)
            except Exception:
                _core = None
            _persona = str(getattr(self, 'persona_text', '') or '')
            if _core is None:
                return {"ok": False, "error": "no core", "persona_len": len(_persona)}
            _built = self._build_proactive_text(_core, _acc, _now)
            _out = {'ok': True, 'persona_len': len(_persona),
                    'persona_head': _persona[:80],
                    'prompt': str(_built.get('prompt') or '')[:1200],
                    'fallback_text': str(_built.get('text') or ''),
                    'system_has_persona': bool(_persona and _persona[:40] in str(_built.get('system') or ''))}
            return _out
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    async def page_autonomy_check(self):
        from quart import request
        await request.get_json(silent=True)
        try:
            from .biocore_model import autonomy_check as _check
        except Exception:
            from biocore_model import autonomy_check as _check
        core = next(iter(self.cores.values()), None) if isinstance(self.cores, dict) else None
        state = {}
        try:
            state = core.autonomy_state(persist=False) if core is not None else {}
        except Exception:
            state = {}
        readiness = _check.snapshot(state)
        code = _check.reason(state, private=True, session=True)
        return {"status": "ok", "data": {"ok": True, "readiness": readiness,
                                         "gate": {"reason": code, "text": _check.reason_text(code)}}}

    async def page_autonomy(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可修改自主性设置"}
        try:
            from .biocore_model import autonomy_mode as _mode
        except Exception:
            from biocore_model import autonomy_mode as _mode
        try:
            result = await _mode.apply(self, body)
        except _mode.AutonomyError as exc:
            return {"status": "error", "data": {"ok": False}, "message": str(exc)}
        return {"status": "ok", "data": dict(result or {}, ok=True)}

    async def page_reply_limit(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可修改回复长度"}
        try:
            from .biocore_model import reply_limit as _limit
        except Exception:
            from biocore_model import reply_limit as _limit
        try:
            value = _limit.normalize(body)["max_tokens"]
        except _limit.ReplyLimitError as exc:
            return {"status": "error", "data": {"ok": False}, "message": str(exc)}
        path = _limit.find_active_config(self)
        if path is None:
            return {"status": "error", "data": {"ok": False}, "message": "未找到 AstrBot 配置文件"}
        ok = bool(_limit.persist_max_tokens(path, value))
        return {"status": "ok", "data": {"ok": ok, "max_tokens": value,
                                         "restart_required": True, "file": str(path)}}

    async def page_reply_split(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可修改分段设置"}
        try:
            from .biocore_model import reply_split as _split
            from .biocore_model import ui_settings as _ui
        except Exception:
            from biocore_model import reply_split as _split
            from biocore_model import ui_settings as _ui
        mode = str(body.get("mode") or "punct")
        if mode not in _split.MODES:
            return {"status": "error", "data": {"ok": False}, "message": "mode invalid"}
        enabled = bool(body.get("enabled", True))
        max_chars = max(40, min(2000, int(body.get("max_chars") or 400)))
        self.reply_split_enabled = enabled
        self.reply_split_mode = mode
        self.reply_split_max_chars = max_chars
        _ui.save(self, {"reply_split": {"enabled": enabled, "mode": mode,
                                        "max_chars": max_chars, "inject_newlines": True}})
        return {"status": "ok", "data": {"ok": True, "reply_split": _split.status(self)}}

    async def page_reply_soft(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        if not self._page_is_local_admin(body):
            return {"status": "error", "message": "仅本地管理端可修改柔化设置"}
        try:
            from .biocore_model import ui_settings as _ui
        except Exception:
            from biocore_model import ui_settings as _ui
        target = max(4, min(80, int(body.get("target_chars") or 10)))
        limit = max(target, min(200, int(body.get("max_chars") or 30)))
        enabled = bool(body.get("enabled", True))
        self.reply_soft_limit_enabled = enabled
        self.reply_soft_target_chars = target
        self.reply_soft_max_chars = limit
        _ui.save(self, {"reply_soft": {"enabled": enabled, "target_chars": target,
                                       "max_chars": limit}})
        return {"status": "ok", "data": {"ok": True, "reply_soft": {
            "enabled": enabled, "target_chars": target, "max_chars": limit}}}

    async def page_memory(self):
        from quart import request
        await request.get_json(silent=True)
        return {"status": "ok", "data": {"ok": True,
                                         "memory_index": _memory_index_rows(MEMORY_DIR),
                                         "stats": self._memory_stats()}}

    async def page_core_mode(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        try:
            from .biocore_model import core_mode as _core_mode
        except Exception:
            from biocore_model import core_mode as _core_mode
        try:
            _core_mode.authorize(self, body)
            result = await _core_mode.apply(self, body.get("mode"), via="page")
        except _core_mode.CoreModeError as exc:
            return {"status": "error", "data": {"ok": False}, "message": str(exc),
                    "status_code": int(getattr(exc, "status", 400))}
        return {"status": "ok", "data": dict(result or {}, ok=True)}

    async def page_download_info(self):
        return {"status": "ok", "data": {
            "ok": True, "route": "/astrbot_plugin_biocore/page/download/<token>",
            "message": "备份下载需先调用 page/backup 获取一次性 token"}}

    async def page_insight(self):
        """Manual '生成长期洞察' button: bypass threshold/cooldown once."""
        from quart import request
        _ = await request.get_json(silent=True) or {}
        return {"status": "ok", "data": await self.generate_manual_insight()}

    async def page_api_config(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        for kind in ("llm", "embedding", "rerank", "tts", "image"):
            incoming = body.get(kind)
            if not isinstance(incoming, dict):
                continue
            source = str(incoming.get("source") or "custom").strip()
            if source not in ("astrbot", "custom"):
                source = "custom"
            old = self.api_config.get(kind) if isinstance(self.api_config.get(kind), dict) else {}
            key = str(incoming.get("api_key") or "").strip()
            if not key:
                key = str(old.get("api_key") or "")
            entry = {
                "source": source,
                "base_url": str(incoming.get("base_url") or "").strip(),
                "api_key": key,
                "model": str(incoming.get("model") or "").strip(),
                "enabled": bool(incoming.get("enabled", True)),
            }
            for extra in ("voice", "size", "format"):
                if extra in incoming:
                    entry[extra] = str(incoming.get(extra) or "").strip()
            self.api_config[kind] = entry
        _incoming_functions = body.get("functions")
        if isinstance(_incoming_functions, dict):
            for _name in LLM_FUNCTIONS:
                _item = _incoming_functions.get(_name)
                if not isinstance(_item, dict):
                    continue
                _cur = dict(self.llm_functions.get(_name) or {})
                if "enabled" in _item:
                    _cur["enabled"] = bool(_item.get("enabled"))
                if "provider" in _item:
                    _cur["provider"] = str(_item.get("provider") or "follow_llm").strip() or "follow_llm"
                _cur.pop("embedding_provider", None)
                _cur.pop("rerank_provider", None)
                self.llm_functions[_name] = _cur
            self.api_config["functions"] = dict(self.llm_functions)
        comp = body.get("compression")
        if isinstance(comp, dict):
            self.api_config["compression"] = {
                "enabled": bool(comp.get("enabled", False)),
                "threshold": max(1000, int(comp.get("threshold", 6000) or 6000)),
                "max_chars": max(120, int(comp.get("max_chars", 800) or 800)),
            }
        self._save_api_config()
        logger.info("[biocore] api config saved")
        return {"status": "ok", "data": self._public_api_config()}

    async def page_kb_config(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        self.kb_enabled = bool(body.get("enabled", False))
        names = body.get("names") if isinstance(body.get("names"), list) else []
        self.kb_names = [str(x).strip() for x in names if str(x).strip()]
        self._save_settings()
        await self._persist_plugin_config({"kb_enabled": self.kb_enabled,
                                           "kb_names": self.kb_names})
        logger.info("[biocore] kb config enabled=%s names=%s", self.kb_enabled, self.kb_names)
        return {"status": "ok", "data": {"enabled": self.kb_enabled, "names": self.kb_names}}

    async def page_models(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        kind = str(body.get("kind") or "embedding").strip()
        source = str(body.get("source") or "custom").strip()
        return await self._fetch_models(kind, source,
                                        str(body.get("base_url") or ""),
                                        str(body.get("api_key") or ""))
