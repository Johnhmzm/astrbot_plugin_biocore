# -*- coding: utf-8 -*-
"""Block assembly layer (L0): main.py only assembles blocks, it holds no logic.

Every extracted part of BioCore / BioCorePlugin is declared here as a Block:

  kind="core_mixin"   -> merged into a dynamically created BioCore subclass
  kind="plugin_mixin" -> methods bound onto BioCorePlugin
  kind="pipeline"     -> pipeline instance attached to the assembled core class
  kind="feedback"     -> registrar called with the plugin class

Per-block switches live in ui_settings: {"blocks": {"enabled": {id: false}}}.
Missing switches default to True. Disabling a core mixin keeps that class out of
the inheritance chain and explicitly re-binds the mixin's public methods to the
host's _orig_* fallbacks (so behaviour degrades instead of disappearing).

This module imports brother modules only -- it must never import main.py, so
tests and headless services can import it without AstrBot.
"""
from __future__ import annotations

import json

try:  # AstrBot requires the host logger
    from astrbot.api import logger
except Exception:  # pragma: no cover - offline tests
    class _NullLogger:  # offline fallback: never imports stdlib logging
        def _noop(self, *args, **kwargs):
            return None
        debug = info = warning = error = exception = critical = _noop
    logger = _NullLogger()

try:  # package import (plugin runtime)
    from . import plugin_routes as _routes
    from .bio_autonomy_state import AutonomyStateMixin
    from .bio_config import ConfigMixin
    from .bio_daily import DailyMixin
    from .bio_emotion import EmotionMixin
    from .bio_emotion2 import Emotion2Mixin
    from .bio_goal import GoalMixin
    from .bio_identity import IdentityMixin
    from .bio_noise import NoiseMixin
    from .bio_physiology2 import Physiology2Mixin
    from .bio_snapshot import SnapshotMixin
    from .bio_state import StateMixin
    from .bio_util import UtilMixin
    from .runtime import build_default_pipeline
except Exception:  # pragma: no cover - top-level import (tests / standalone)
    import plugin_routes as _routes  # type: ignore
    from bio_autonomy_state import AutonomyStateMixin  # type: ignore
    from bio_config import ConfigMixin  # type: ignore
    from bio_daily import DailyMixin  # type: ignore
    from bio_emotion import EmotionMixin  # type: ignore
    from bio_emotion2 import Emotion2Mixin  # type: ignore
    from bio_goal import GoalMixin  # type: ignore
    from bio_identity import IdentityMixin  # type: ignore
    from bio_noise import NoiseMixin  # type: ignore
    from bio_physiology2 import Physiology2Mixin  # type: ignore
    from bio_snapshot import SnapshotMixin  # type: ignore
    from bio_state import StateMixin  # type: ignore
    from bio_util import UtilMixin  # type: ignore
    from runtime import build_default_pipeline  # type: ignore

RoutesMixin = _routes.RoutesMixin


class Block:
    """One declarative assembly unit (id / kind / target / factory)."""

    __slots__ = ("id", "kind", "target", "factory")

    def __init__(self, id, kind, target, factory):
        self.id = str(id)
        self.kind = str(kind)
        self.target = str(target)
        self.factory = factory

    def __repr__(self):
        return "Block(id=%r, kind=%r, target=%r)" % (self.id, self.kind, self.target)


def register_feedback(plugin_cls):
    """Bind the stateless feedback_* helpers onto the plugin class (idempotent).

    main.py has no feedback binding block today; this registrar is the single
    place the feedback layer attaches, exposed as _fb_<layer>_<name> so the
    plugin can opt into it incrementally without touching the class body.
    """
    try:
        from . import feedback_guard, feedback_llm, feedback_memory, feedback_user
    except Exception:  # pragma: no cover
        import feedback_guard  # type: ignore
        import feedback_llm  # type: ignore
        import feedback_memory  # type: ignore
        import feedback_user  # type: ignore
    bound = 0
    for prefix, module in (("guard", feedback_guard), ("llm", feedback_llm),
                           ("memory", feedback_memory), ("user", feedback_user)):
        for name, value in vars(module).items():
            if name.startswith("_") or isinstance(value, type) or not callable(value):
                continue
            setattr(plugin_cls, "_fb_%s_%s" % (prefix, name), staticmethod(value))
            bound += 1
    return bound


BLOCKS = [
    # -- 11 core mixins (target: BioCore) ---------------------------------
    Block("util", "core_mixin", "core", UtilMixin),
    Block("emotion", "core_mixin", "core", EmotionMixin),
    Block("goal", "core_mixin", "core", GoalMixin),
    Block("state", "core_mixin", "core", StateMixin),
    Block("snapshot", "core_mixin", "core", SnapshotMixin),
    Block("daily", "core_mixin", "core", DailyMixin),
    Block("emotion2", "core_mixin", "core", Emotion2Mixin),
    Block("noise", "core_mixin", "core", NoiseMixin),
    Block("physiology2", "core_mixin", "core", Physiology2Mixin),
    Block("identity", "core_mixin", "core", IdentityMixin),
    Block("autonomy_state", "core_mixin", "core", AutonomyStateMixin),
    # -- plugin layers (target: BioCorePlugin) ----------------------------
    Block("routes", "plugin_mixin", "plugin", RoutesMixin),
    Block("config", "plugin_mixin", "plugin", ConfigMixin),
    # -- cross-cutting layers ---------------------------------------------
    Block("pipeline", "pipeline", "core", build_default_pipeline),
    Block("feedback", "feedback", "plugin", register_feedback),
]

_CACHE = {}


def _enabled_map(plugin=None):
    """block_id -> bool, from plugin.blocks_enabled or ui_settings.blocks.enabled."""
    raw = getattr(plugin, "blocks_enabled", None)
    if not isinstance(raw, dict):
        try:
            try:
                from . import ui_settings as _ui
            except Exception:  # pragma: no cover
                import ui_settings as _ui  # type: ignore
            data = _ui.load(plugin) if plugin is not None else _ui.load(None)
            section = data.get("blocks") if isinstance(data, dict) else None
            raw = section.get("enabled") if isinstance(section, dict) else None
            if not isinstance(raw, dict):
                # ui_settings.load() only merges known DEFAULTS sections; the
                # blocks switch is read straight from the file (schema stays open).
                path = _ui.settings_path(plugin)
                if path.is_file():
                    file_data = json.loads(path.read_text(encoding="utf-8-sig"))
                    section = file_data.get("blocks") if isinstance(file_data, dict) else None
                    raw = section.get("enabled") if isinstance(section, dict) else None
        except Exception:
            raw = None
    out = {}
    for block in BLOCKS:
        out[block.id] = bool(raw.get(block.id, True)) if isinstance(raw, dict) else True
    return out


def _mixin_method_names(mixin_cls):
    names = []
    seen = set()
    for base in getattr(mixin_cls, "__mro__", ()):
        if base is object:
            continue
        for name, value in vars(base).items():
            if name.startswith("__") or name in seen:
                continue
            if callable(value) or isinstance(value, (staticmethod, classmethod)):
                names.append(name)
                seen.add(name)
    return names


def _orig_raw(cls, name):
    """Raw _orig_* descriptor on the host class, tolerant to naming variants."""
    stripped = name.lstrip("_")
    for cand in ("_orig_" + stripped, "_orig" + stripped, "_orig_" + name, "_orig" + name):
        for base in getattr(cls, "__mro__", ()):
            if cand in vars(base):
                return vars(base)[cand]
    return None


def assemble(plugin, core_cls, plugin_cls, host_globals=None):
    """Assemble the effective core/plugin classes from BLOCKS + enabled map.

    Returns {"core_cls", "enabled", "skipped"}; repeated calls with the same
    arguments and switches return the same cached result (idempotent).
    """
    enabled = _enabled_map(plugin)
    key = (id(core_cls), id(plugin_cls),
           tuple(sorted(enabled.items())),
           id(host_globals) if host_globals is not None else 0)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    core_blocks = [b for b in BLOCKS if b.kind == "core_mixin"]
    plugin_blocks = [b for b in BLOCKS if b.kind == "plugin_mixin"]
    skipped = [b.id for b in BLOCKS if not enabled[b.id]]

    # 1) core class: only mixins that the host base is not already made of.
    add = tuple(b.factory for b in core_blocks
                if enabled[b.id] and isinstance(b.factory, type)
                and not issubclass(core_cls, b.factory))
    Core = type("BioCore", add + (core_cls,), {})

    # 2) disabled core mixin -> explicit _orig_* fallback overrides.
    fallbacks = 0
    for block in core_blocks:
        if enabled[block.id]:
            continue
        for name in _mixin_method_names(block.factory):
            raw = _orig_raw(core_cls, name)
            if raw is None:
                continue
            setattr(Core, name, raw)
            fallbacks += 1

    # 3) plugin mixins: bind enabled layers onto the plugin class.
    bound = 0
    for block in plugin_blocks:
        if not enabled[block.id]:
            continue
        if block.id == "routes":
            injected = dict(host_globals) if isinstance(host_globals, dict) else {}
            injected["BioCore"] = Core
            try:
                _routes.install(injected)
            except Exception as exc:  # pragma: no cover
                logger.warning("[biocore] routes install failed: %s", exc)
            for name in getattr(_routes, "ROUTE_NAMES", ()):
                fn = getattr(block.factory, name, None)
                if fn is not None:
                    setattr(plugin_cls, name, fn)
                    bound += 1
            continue
        for name in _mixin_method_names(block.factory):
            value = getattr(block.factory, name, None)
            if value is not None:
                setattr(plugin_cls, name, value)
                bound += 1

    # 4) pipeline + feedback blocks.
    for block in BLOCKS:
        if not enabled[block.id]:
            continue
        if block.kind == "pipeline":
            try:
                setattr(Core, block.id, block.factory())
            except Exception as exc:  # pragma: no cover
                logger.warning("[biocore] pipeline block failed: %s", exc)
        elif block.kind == "feedback":
            try:
                block.factory(plugin_cls)
            except Exception as exc:  # pragma: no cover
                logger.warning("[biocore] feedback block failed: %s", exc)

    n_core = sum(1 for b in core_blocks if enabled[b.id])
    n_plugin = sum(1 for b in plugin_blocks if enabled[b.id])
    logger.info("[biocore] blocks assembled: %d core / %d plugin / skipped=%s",
                n_core, n_plugin, skipped)
    result = {"core_cls": Core, "enabled": dict(enabled), "skipped": skipped}
    _CACHE[key] = result
    return result
