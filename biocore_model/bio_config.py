# -*- coding: utf-8 -*-
"""ConfigMixin: settings / profile / api-config layer replicated from main.py.

复刻自 main.py（逐字保留方法体与注释），只做两类最小改造：

1) 路径依赖注入（不再引用 main 的模块级常量）：
   - DATA_DIR              -> self._data_dir（回退 self.data_dir）
   - PROFILE_PATH          -> self._profile_path
   - _PERSIST_DATA_DIR     -> self._persist_dir
   - API_CONFIG_PATH       -> self._api_config_path（回退 self._data_dir / "api_config.json"）
2) 不 import main：日志使用本模块 logger（同名 "astrbot"），_sha256 在本文件内复刻一份。

未搬入本文件、仍由宿主（main.py）提供的依赖方法：
   _load_llm_functions / _save_api_config      （_load_api_config 末尾调用）
   _functions_public / _astrbot_*_default       （_public_api_config 调用）
   _config_providers / _config_provider_sources （_astrbot_*_default 调用）
后续批次可继续把这些方法搬进同一个 mixin（mixin 方法解析顺序在宿主类之前即可）。

    class BioCorePlugin(ConfigMixin, Star):
        ...
        self._data_dir = DATA_DIR
        self._persist_dir = _PERSIST_DATA_DIR
        self._profile_path = PROFILE_PATH
        self._api_config_path = API_CONFIG_PATH
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

try:  # AstrBot requires the host logger
    from astrbot.api import logger
except Exception:  # pragma: no cover - offline tests
    class _NullLogger:  # offline fallback: never imports stdlib logging
        def _noop(self, *args, **kwargs):
            return None
        debug = info = warning = error = exception = critical = _noop
    logger = _NullLogger()


def _sha256(text: str) -> str:
    """main.py 同名助手复刻（避免 import main）。"""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:32]


def _resolve_data_dir(host) -> Path:
    """self._data_dir -> self.data_dir -> '.'（路径注入的唯一回退链）。"""
    value = getattr(host, "_data_dir", None) or getattr(host, "data_dir", None)
    return Path(str(value)) if value else Path(".")


class ConfigMixin:
    """Settings/profile/api-config methods lifted verbatim from main.py."""

    # -- injected paths -------------------------------------------------
    def _configured_path(self, key):
        raw = str(self.config.get(key, "") or "").strip()
        return Path(raw) if raw else None

    def _settings_path(self):
        return _resolve_data_dir(self) / "settings.json"

    def _profile_file(self):
        """Candidate file: self._profile_path or <data_dir>/persona_profile.json."""
        value = getattr(self, "_profile_path", None)
        return Path(str(value)) if value else (_resolve_data_dir(self) / "persona_profile.json")

    def _persist_dir_path(self):
        """Candidate dir: self._persist_dir or the injected data dir."""
        value = getattr(self, "_persist_dir", None)
        return Path(str(value)) if value else _resolve_data_dir(self)

    def _api_config_file(self):
        """Candidate file: self._api_config_path or <data_dir>/api_config.json."""
        value = getattr(self, "_api_config_path", None)
        return Path(str(value)) if value else (_resolve_data_dir(self) / "api_config.json")

    # -- replicated methods ---------------------------------------------
    def _load_profile(self):
        try:
            _profile_file = None
            for _cand in (self._profile_file(),
                          self._persist_dir_path() / "persona_profile.json"):
                try:
                    if _cand.exists():
                        _profile_file = _cand
                        break
                except Exception:
                    continue
            if _profile_file is not None:
                d = json.loads(_profile_file.read_text(encoding="utf-8"))
                self.profile = dict(d.get("profile") or {})
                self.persona_text = str(d.get("persona") or "")
                _ph = str(d.get("persona_hash") or "")
                self._persona_compiled_hash = _ph or (_sha256(self.persona_text) if self.persona_text else "")
                _schema = d.get("schema")
                if isinstance(_schema, list):
                    self.schema_texts = [str(x).strip()[:60] for x in _schema
                                         if str(x).strip()][:6]
                _style = d.get("style")
                if isinstance(_style, dict):
                    _tag = str(_style.get("intimacy_style") or "neutral")
                    if _tag not in ("neutral", "playful", "gentle", "reserved"):
                        _tag = "neutral"
                    _terms = [str(x).strip()[:12] for x in (_style.get("address_terms") or [])
                              if str(x).strip()][:3]
                    self.persona_style = {"intimacy_style": _tag, "address_terms": _terms}
                logger.info("[biocore] loaded profile %s", _profile_file)
        except Exception as exc:
            logger.warning("[biocore] profile load failed: %s", exc)

    def _load_settings(self):
        try:
            p = self._settings_path()
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                # Single source of truth = AstrBot plugin config. Legacy dashboard
                # toggles in settings.json only apply when config does not define
                # the key (otherwise they silently overrode plugin config).
                for key in ("proactive_reply", "memory_dedup_embedding", "inject_intent",
                            "kb_enabled", "hybrid_retrieval", "safety_enabled",
                            "llm_memory_candidates", "llm_only_reply_summary",
                            "we_memory_enabled"):
                    if key in d and key not in self.config:
                        setattr(self, key, bool(d[key]))
                if "safety_enabled" in d and "safety_enabled" not in self.config:
                    self.safety_enabled = bool(d.get("safety_enabled"))
                    self.cross_session_memory = not self.safety_enabled
                    self.sensitive_memory_protection = self.safety_enabled
                if "persona_id" in d and "persona_id" not in self.config:
                    self.persona_id = str(d.get("persona_id") or "").strip()
                if isinstance(d.get("kb_names"), list) and "kb_names" not in self.config:
                    self.kb_names = [str(x) for x in d.get("kb_names") if str(x).strip()]
        except Exception as exc:
            logger.warning("[biocore] settings load failed: %s", exc)

    def _save_settings(self):
        try:
            self._settings_path().write_text(json.dumps({
                "proactive_reply": bool(self.proactive_reply),
                "memory_dedup_embedding": bool(self.memory_dedup_embedding),
                "hybrid_retrieval": bool(getattr(self, "hybrid_retrieval", True)),
                "safety_enabled": bool(getattr(self, "safety_enabled", False)),
                "llm_memory_candidates": bool(
                    getattr(self, "llm_memory_candidates", True)),
                "we_memory_enabled": bool(getattr(self, "we_memory_enabled", False)),
            "bc_prompt_mode": str(getattr(self, "bc_prompt_mode", "telemetry") or "telemetry"),
            "summary_max_chars": int(getattr(self, "summary_max_chars", 0) or 0),
            "llm_only_reply_summary": bool(
                    getattr(self, "llm_only_reply_summary", True)),
                "persona_id": str(getattr(self, "persona_id", "") or ""),
                "inject_intent": bool(self.inject_intent),
                "kb_enabled": bool(getattr(self, "kb_enabled", False)),
                "kb_names": list(getattr(self, "kb_names", [])),
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:
            logger.warning("[biocore] settings save failed: %s", exc)

    def _load_api_config(self):
        try:
            _path = self._api_config_file()
            if _path.exists():
                d = json.loads(_path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    self.api_config = d
        except Exception as exc:
            logger.warning("[biocore] api config load failed: %s", exc)
            self.api_config = {}
        self._load_llm_functions()

    def _public_api_config(self):
        llm = self._astrbot_llm_default()
        emb = self._astrbot_embedding_default()
        rrk = self._astrbot_rerank_default()
        tts = self._astrbot_tts_default()
        img = self._astrbot_image_default()
        def one(kind, default):
            saved = self.api_config.get(kind) if isinstance(self.api_config.get(kind), dict) else {}
            source = saved.get("source") or ("astrbot" if default else "custom")
            base = saved.get("base_url")
            model = saved.get("model")
            if not base:
                base = (default or {}).get("base_url", "")
            if not model:
                model = (default or {}).get("model", "")
            enabled = saved.get("enabled")
            if enabled is None:
                enabled = bool(default) if kind != "llm" else True
            return {
                "source": source if source in ("astrbot", "custom") else "custom",
                "base_url": base,
                "model": model,
                "key_saved": bool(saved.get("api_key")) or bool((default or {}).get("has_key")),
                "provider_id": (default or {}).get("provider_id", ""),
                "enabled": bool(enabled),
                "voice": str(saved.get("voice") or ""),
                "size": str(saved.get("size") or ""),
                "format": str(saved.get("format") or ""),
            }
        compression = self.api_config.get("compression") if isinstance(self.api_config.get("compression"), dict) else {}
        return {
            "functions": self._functions_public(),
            "llm": one("llm", llm),
            "embedding": one("embedding", emb),
            "rerank": one("rerank", rrk),
            "tts": one("tts", tts),
            "image": one("image", img),
            "compression": {
                "enabled": bool(compression.get("enabled", False)),
                "threshold": int(compression.get("threshold", 6000) or 6000),
                "max_chars": int(compression.get("max_chars", 800) or 800),
            },
        }
