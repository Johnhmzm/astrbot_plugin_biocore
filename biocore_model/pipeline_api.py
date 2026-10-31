# -*- coding: utf-8 -*-
"""PIPE-3 read-only pipeline API: dashboard status, toggle, dry-run.

Read-only by design:
- payload_status() never mutates the pipeline (only initialises persisted switches).
- payload_toggle() flips one stage switch and persists it under
  ui_settings.autonomy.pipeline_stages; required stages are refused.
- payload_dryrun() runs the shadow pipeline on a sample text with no llm and no
  core, so nothing is sent and no biological state is written.

No main import; no network; persistence goes through ui_settings (injectable
plugin/data_dir so tests can use a temp directory).
"""
from __future__ import annotations

import time

from . import runtime, ui_settings

SCHEMA = "bc.pipeline.api.v1"
MODES = ("shadow", "active")
MODE_DEFAULT = "shadow"
REQUIRED_STAGES = ("perceive", "decide", "present")
PREVIEW_LIMIT = 200
SAMPLE_LIMIT = 500
_BOOTED = set()


def _ts():
    return round(time.time(), 3)


def _plugin_key(plugin):
    return id(plugin) if plugin is not None else 0


def _stage_rows():
    status = runtime.get_pipeline().get_status()
    rows = []
    for row in status.get("stages") or []:
        rows.append({
            "name": str(row.get("name") or ""),
            "required": bool(row.get("required")),
            "enabled": bool(row.get("enabled")),
            "last_status": str(row.get("last_status") or ""),
            "last_ms": round(float(row.get("last_ms") or 0.0), 3),
        })
    return rows


def load_switches(plugin=None):
    """Persisted stage switches from ui_settings.autonomy.pipeline_stages."""
    try:
        data = ui_settings.load(plugin)
    except Exception:
        return {}
    autonomy = data.get("autonomy") if isinstance(data.get("autonomy"), dict) else {}
    raw = autonomy.get("pipeline_stages")
    if not isinstance(raw, dict):
        return {}
    return {str(name): bool(value) for name, value in raw.items()
            if isinstance(value, bool)}


def save_switches(plugin=None, switches=None):
    """Persist {stage: bool} under ui_settings.autonomy.pipeline_stages."""
    clean = {str(name): bool(value) for name, value in (switches or {}).items()
             if isinstance(value, bool)}
    try:
        result = ui_settings.save(plugin, {"autonomy": {"pipeline_stages": clean}})
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "switches": clean}
    return {"ok": bool(result.get("ok")), "file": str(result.get("file") or ""),
            "switches": clean}


def load_mode(plugin=None):
    """Persisted pipeline mode from ui_settings.autonomy.pipeline_mode."""
    try:
        data = ui_settings.load(plugin)
    except Exception:
        return MODE_DEFAULT
    autonomy = data.get("autonomy") if isinstance(data.get("autonomy"), dict) else {}
    mode = str(autonomy.get("pipeline_mode") or MODE_DEFAULT).strip().lower()
    return mode if mode in MODES else MODE_DEFAULT


def save_mode(plugin=None, mode=MODE_DEFAULT):
    """Persist shadow|active and apply it in-process (no restart needed)."""
    value = str(mode or "").strip().lower()
    if value not in MODES:
        raise ValueError("mode must be shadow|active")
    try:
        result = ui_settings.save(plugin, {"autonomy": {"pipeline_mode": value}})
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "mode": value}
    runtime.apply_mode(value)
    return {"ok": bool(result.get("ok")), "file": str(result.get("file") or ""),
            "mode": value}


def boot(plugin=None):
    """Load persisted switches + mode into runtime once per plugin instance."""
    key = _plugin_key(plugin)
    if key in _BOOTED:
        return False
    _BOOTED.add(key)
    switches = load_switches(plugin)
    if switches:
        runtime.apply_switches(switches)
    try:
        runtime.apply_mode(load_mode(plugin))
    except ValueError:
        runtime.reset_mode()
    return True


def reset_boot():
    _BOOTED.clear()


def payload_status(plugin=None):
    """Read-only pipeline projection for the dashboard."""
    boot(plugin)
    status = runtime.get_pipeline().get_status()
    return {
        "mode": runtime.get_mode(),
        "stages": _stage_rows(),
        "last_trace": status.get("last_trace") or {},
        "updated_ts": _ts(),
        "schema": SCHEMA,
        "switches": runtime.get_switches(),
    }


def payload_mode(plugin=None, mode=None):
    """Read or switch the pipeline mode (shadow|active); persists the switch."""
    boot(plugin)
    if mode is None:
        return {"ok": True, "mode": runtime.get_mode(), "modes": list(MODES)}
    try:
        saved = save_mode(plugin, mode)
    except ValueError:
        return {"ok": False, "mode": runtime.get_mode(), "message": "invalid_mode",
                "modes": list(MODES)}
    return {"ok": bool(saved.get("ok")), "mode": runtime.get_mode(),
            "saved": bool(saved.get("ok")), "modes": list(MODES)}


def payload_toggle(plugin=None, name="", enabled=True):
    """Enable/disable one stage and persist it; required stages are refused."""
    boot(plugin)
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "stages": _stage_rows(), "message": "name_required"}
    if name in REQUIRED_STAGES and not enabled:
        return {"ok": False, "stages": _stage_rows(), "message": "required_stage",
                "name": name}
    switches = runtime.get_switches()
    try:
        runtime.set_enabled(name, bool(enabled))
    except KeyError:
        return {"ok": False, "stages": _stage_rows(), "message": "unknown_stage",
                "name": name}
    except ValueError:
        return {"ok": False, "stages": _stage_rows(), "message": "required_stage",
                "name": name}
    switches[name] = bool(enabled)
    saved = save_switches(plugin, switches)
    return {"ok": True, "stages": _stage_rows(), "name": name,
            "enabled": bool(enabled), "saved": bool(saved.get("ok")),
            "switches": switches}


def payload_dryrun(plugin=None, sample_text="", now=None):
    """Run the shadow pipeline on sample text; nothing is sent, no core write."""
    boot(plugin)
    text = str(sample_text or "").strip()
    if not text:
        return {"ok": False, "mode": "dryrun", "trace": {}, "out_preview": "",
                "message": "sample_text_required", "updated_ts": _ts()}
    stamp = float(now) if now is not None else time.time()
    ctx = runtime.make_request_ctx(
        plugin=plugin, event=None, core=None, text=text[:SAMPLE_LIMIT],
        memory=[], now=stamp,
        meta={"dryrun": True, "write_core": False, "observe": False, "llm": None})
    out = runtime.run_reply(ctx)
    trace = out.get("trace") if isinstance(out.get("trace"), dict) else {}
    preview = runtime.reply_text(out)
    if not preview:
        preview = str(out.get("state_text") or "")
    if not preview:
        decision = out.get("decision")
        if isinstance(decision, dict):
            preview = "decision:" + str(decision.get("reason") or "")
    error = (out.get("meta") or {}).get("pipeline_error")
    return {"ok": error is None, "mode": "dryrun", "trace": trace,
            "out_preview": str(preview)[:PREVIEW_LIMIT],
            "stages": len(trace.get("stages") or []), "error": error,
            "updated_ts": _ts()}
