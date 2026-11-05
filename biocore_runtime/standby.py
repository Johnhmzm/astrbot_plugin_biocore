# -*- coding: utf-8 -*-
"""Standby initiative mode: when idle, let a small model write one line.

Config (dict or BIOCORE_STANDBY_* env; every key optional):
  standby_enabled          False
  standby_model_base_url   ""
  standby_model            ""
  standby_model_key        ""
  standby_every_minutes    30
  standby_active_hours     "09:00-23:00"
  standby_max_per_day      6
  standby_channel          "outbox"
  standby_timeout          20
  standby_store            ""      (memory store root; defaults to plugin data/memory)
  standby_session_id       "standby"

tick(now) reads the same session state as turn_start, asks the existing
pipeline.proactive_tick for the decision, then (only if should_send) builds a
full-persona prompt and calls an OpenAI-compatible /v1/chat/completions.
A successful line is sanitized and appended to
<store>/proactive/outbox.jsonl; cooldown/daily bookkeeping goes to
<store>/proactive/state.json. Any model failure writes no outbox.

CLI: python biocore_runtime/standby.py tick
     python biocore_runtime/standby.py sleep-loop [--once]
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_PLUGIN_ROOT = str(Path(__file__).resolve().parents[1])
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from biocore_runtime import pipeline as _pipeline  # noqa: E402

try:
    from biocore_model import sanitize as _sanitize
except Exception:  # pragma: no cover
    _sanitize = None

# [engineering] every cadence/limit below is a product decision (see
# PAPER-MAP.md); there is no user study behind 30min / 3 per day / 120min.
DEFAULTS = {
    "standby_enabled": False,
    "standby_model_base_url": "",
    "standby_model": "",
    "standby_model_key": "",
    "standby_every_minutes": 30,
    "standby_active_hours": "09:00-23:00",
    "standby_max_per_day": 3,
    "standby_cooldown_minutes": 120,
    "standby_max_no_reply": 2,
    "standby_channel": "outbox",
    "standby_timeout": 20.0,
    "standby_store": "",
    "standby_session_id": "standby",
    "standby_min_trust": 0.0,
    "standby_require_open_loop": False,
}


def _num(value, default=0.0):
    try:
        number = float(value)
    except Exception:
        return float(default)
    return number if math.isfinite(number) else float(default)


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    return bool(default)


def normalize_config(config=None):
    data = config if isinstance(config, dict) else {}
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        env_key = "BIOCORE_" + key.upper()
        if key in data:
            out[key] = data[key]
        elif os.environ.get(env_key) is not None:
            out[key] = os.environ.get(env_key)
    out["standby_enabled"] = _as_bool(out["standby_enabled"], False)
    for key in ("standby_model_base_url", "standby_model",
                "standby_model_key", "standby_channel", "standby_store",
                "standby_session_id"):
        out[key] = str(out.get(key) or "").strip()
    out["standby_every_minutes"] = max(
        1, min(24 * 60, int(_num(out.get("standby_every_minutes"), 30))))
    out["standby_max_per_day"] = max(
        1, min(100, int(_num(out.get("standby_max_per_day"), 3))))
    out["standby_cooldown_minutes"] = max(
        1, min(24 * 60, int(_num(out.get("standby_cooldown_minutes"), 120))))
    out["standby_max_no_reply"] = max(
        1, min(10, int(_num(out.get("standby_max_no_reply"), 2))))
    out["standby_timeout"] = max(
        0.2, min(120.0, _num(out.get("standby_timeout"), 20.0)))
    out["standby_min_trust"] = max(
        0.0, min(1.0, _num(out.get("standby_min_trust"), 0.0)))
    out["standby_require_open_loop"] = _as_bool(
        out.get("standby_require_open_loop"), False)
    out["standby_session_id"] = out["standby_session_id"] or "standby"
    return out


def _store_root(store):
    raw = str(store or "").strip()
    if raw:
        return Path(raw)
    return Path(_pipeline._default_store())


def _proactive_dir(store):
    return _store_root(store) / "proactive"


def _outbox_path(store):
    return _proactive_dir(store) / "outbox.jsonl"


def _bookkeeping_path(store):
    return _proactive_dir(store) / "state.json"


def _load_json(path, fallback):
    try:
        if path is None or not Path(path).exists():
            return fallback
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


def _in_active_hours(now, spec):
    text = str(spec or "").strip()
    if not text:
        return True
    try:
        start_text, end_text = text.split("-", 1)
        start_h, start_m = [int(part) for part in start_text.split(":")]
        end_h, end_m = [int(part) for part in end_text.split(":")]
    except Exception:
        return True
    local = time.localtime(now)
    minutes = local.tm_hour * 60 + local.tm_min
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start == end:
        return True
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end


def _day_key(now):
    return time.strftime("%Y-%m-%d", time.localtime(now))


def _sent_today(state, now):
    sent = state.get("sent") if isinstance(state.get("sent"), list) else []
    today = _day_key(now)
    values = []
    for item in sent:
        stamp = _num(item, 0.0)
        if stamp > 0 and time.strftime("%Y-%m-%d", time.localtime(stamp)) == today:
            values.append(stamp)
    return values


def load_state(store):
    return _load_json(_bookkeeping_path(store), {})


def load_session_state(store, session_id):
    state = _pipeline._load_session_state(_store_root(store), session_id)
    if not isinstance(state, dict):
        state = {}
    return _pipeline.apply_intero_to_state(state)


def build_prompt(state, memories, persona_text="", channel="outbox",
                 digest=""):
    """Full persona (never truncated) + thinking rule + state + memories + digest."""
    parts = []
    if persona_text:
        parts.append(str(persona_text))
    parts.append(_pipeline.THINKING_STYLE_TEXT)
    try:
        state_line = _pipeline._state_block(state, 200)
    except Exception:
        state_line = "此刻：心情平稳。"
    parts.append(state_line)
    recent = [str(item).strip() for item in (memories or []) if str(item).strip()]
    if recent:
        parts.append("最近记得：" + "；".join(recent[:3]))
    if digest:
        parts.append("上次对话：" + str(digest)[:60])
    prompt = "\n\n".join(parts)
    return prompt


def _recent_memories(store, session_id, limit=3):
    try:
        doc = _pipeline.load_memory(_store_root(store), session_id)
        entries = [entry for entry in (doc.get("entries") or [])
                   if isinstance(entry, dict) and not entry.get("deleted")
                   and not entry.get("archived")]
        entries.sort(key=lambda entry: _num(entry.get("ts"), 0.0), reverse=True)
        return [str(entry.get("text") or "")[:120] for entry in entries[:limit]]
    except Exception:
        return []


def _persona_text(store):
    try:
        profile = _pipeline.load_persona_profile({"store": str(_store_root(store))})
        return str((profile or {}).get("persona_text") or "")
    except Exception:
        return ""


def _chat_url(base_url):
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _urllib_transport(url, payload, timeout, headers):
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200) or 200)
        body = response.read()
    return status, body


def _extract_text(response_body):
    try:
        if isinstance(response_body, bytes):
            response_body = response_body.decode("utf-8", "replace")
        data = json.loads(response_body)
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        return str((message or {}).get("content") or "").strip()
    except Exception:
        return ""


def generate(prompt, config, transport=None):
    """Call the OpenAI-compatible chat endpoint; return (text, reason)."""
    cfg = normalize_config(config)
    base = cfg["standby_model_base_url"]
    model = cfg["standby_model"]
    if not base or not model:
        return "", "missing_config"
    url = _chat_url(base)
    if not url:
        return "", "missing_config"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "现在没有人说话。你想主动发一句，只回一句话，不超过60字。"},
        ],
        "temperature": 0.8,
        "max_tokens": 120,
    }
    headers = {"Content-Type": "application/json"}
    if cfg["standby_model_key"]:
        headers["Authorization"] = "Bearer " + cfg["standby_model_key"]
    call = transport or _urllib_transport
    try:
        status, body = call(url, payload, cfg["standby_timeout"], headers)
    except (TimeoutError, OSError) as error:
        return "", "timeout" if isinstance(error, TimeoutError) else "model_error"
    except Exception:
        return "", "model_error"
    try:
        status = int(status)
    except Exception:
        status = 0
    if status < 200 or status >= 300:
        return "", "http_%s" % status
    text = _extract_text(body)
    if not text:
        return "", "empty_reply"
    text = text.replace("\n", " ").strip()
    if len(text) > 60:
        text = text[:59].rstrip() + "…"
    if _sanitize is not None:
        try:
            text = _sanitize.clean(text)
        except Exception:
            pass
    if not str(text).strip():
        return "", "empty_reply"
    return str(text).strip(), "ok"


def _bookkeep(store, now, state, sent=False, reason="", text=""):
    path = _bookkeeping_path(store)
    sent_list = [stamp for stamp in (state.get("sent") or [])
                 if _num(stamp, 0.0) > 0 and now - _num(stamp, 0.0) < 7 * 86400]
    if sent:
        sent_list.append(now)
    data = {
        "last_attempt_ts": now,
        "last_sent_ts": now if sent else _num(state.get("last_sent_ts"), 0.0),
        "sent": sent_list[-50:],
        "last_reason": reason,
        "last_text": text[:80],
        "ts": now,
    }
    try:
        _write_json(path, data)
    except Exception:
        pass
    return data


def _settle_reply_bookkeeping(store, state, session_state, now, cfg):
    """Count unanswered sends; two in a row block standby."""
    awaiting = bool(state.get("awaiting_reply"))
    streak = int(_num(state.get("no_reply_streak"), 0))
    if not awaiting:
        return streak, state
    last_sent = _num(state.get("last_sent_ts"), 0.0)
    last_human = _num((session_state or {}).get("last_human_ts"), 0.0)
    if last_human > last_sent:
        streak = 0
    elif now - last_sent > cfg["standby_cooldown_minutes"] * 60.0:
        streak += 1
    else:
        return streak, state
    state = dict(state)
    state["awaiting_reply"] = False
    state["no_reply_streak"] = streak
    try:
        _write_json(_bookkeeping_path(store), state)
    except Exception:
        pass
    return streak, state


def _last_digest(session_state):
    for key in ("last_user_text", "last_digest", "last_line"):
        value = str((session_state or {}).get(key) or "").strip()
        if value:
            return value[:60]
    return ""


def _template_line(state):
    intero = (state or {}).get("intero") if isinstance((state or {}).get("intero"), dict) else {}
    if _num(intero.get("tension"), 0.5) >= 0.65:
        return "在忙吗？刚刚想起你，不用急着回。"
    return "刚刚想起你，今天还好吗？"


def tick(now=None, config=None, transport=None, proactive=None):
    """One standby tick. Returns {ok, sent, reason, text?, channel, outbox?}."""
    cfg = normalize_config(config)
    store = cfg["standby_store"] or _pipeline._default_store()
    session_id = cfg["standby_session_id"]
    now_value = _num(now, time.time())
    if now_value > 1e12:
        now_value = now_value / 1000.0
    result = {"ok": True, "sent": False, "reason": "",
              "channel": cfg["standby_channel"]}
    if not cfg["standby_enabled"]:
        result["reason"] = "disabled"
        return result
    if not _in_active_hours(now_value, cfg["standby_active_hours"]):
        result["reason"] = "outside_active_hours"
        return result
    state = load_state(store)
    session_state = load_session_state(store, session_id)
    streak, state = _settle_reply_bookkeeping(store, state, session_state,
                                              now_value, cfg)
    result["no_reply_streak"] = streak
    if streak >= cfg["standby_max_no_reply"]:
        result["reason"] = "no_reply_streak"
        return result
    if len(_sent_today(state, now_value)) >= cfg["standby_max_per_day"]:
        result["reason"] = "daily_cap"
        return result
    last_attempt = _num(state.get("last_attempt_ts"), 0.0)
    last_sent = _num(state.get("last_sent_ts"), 0.0)
    cooldown_until = max(last_attempt, last_sent) + cfg["standby_cooldown_minutes"] * 60.0
    if cooldown_until > now_value:
        result["reason"] = "cooldown"
        return result
    last_human = _num(session_state.get("last_human_ts"),
                      now_value - max(cfg["standby_every_minutes"], 180) * 60.0)
    switches = {
        "proactiveEnabled": True,
        "proactiveSend": True,
        "proactiveMinGapMinutes": cfg["standby_every_minutes"],
        "proactivePerHour": 6,
        "proactiveMinTrust": cfg["standby_min_trust"],
        "proactiveMaxChars": 60,
        "proactiveRequireOpenLoop": cfg["standby_require_open_loop"],
    }
    decision = proactive
    if decision is None:
        decision = _pipeline.proactive_tick
    try:
        decision_result = decision(
            session_id=session_id, last_human_ts=last_human,
            switches=switches, store=store, now=now_value * 1000.0,
            state_file=str(_pipeline.state_path(store, session_id)))
    except Exception:
        result["reason"] = "decision_error"
        return result
    if not isinstance(decision_result, dict):
        result["reason"] = "decision_error"
        return result
    if not decision_result.get("should_send"):
        result["reason"] = str(decision_result.get("reason") or "should_not_send")
        return result
    memories = _recent_memories(store, session_id)
    persona = _persona_text(store)
    prompt = build_prompt(session_state, memories, persona,
                          cfg["standby_channel"],
                          digest=_last_digest(session_state))
    text, reason = generate(prompt, cfg, transport=transport)
    fallback = False
    if reason != "ok" or not text:
        text = _template_line(session_state)
        reason = "template_fallback"
        fallback = True
    outbox = _outbox_path(store)
    try:
        outbox.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": round(now_value, 3),
            "text": text,
            "reason": reason,
            "state_snapshot": session_state,
            "channel": cfg["standby_channel"],
            "model": cfg["standby_model"],
            "fallback": fallback,
            "prompt": prompt,
        }
        with outbox.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        _bookkeep(store, now_value, state, sent=False, reason="outbox_write_failed")
        result["reason"] = "outbox_write_failed"
        return result
    state = dict(state)
    state["awaiting_reply"] = True
    state["no_reply_streak"] = 0
    data = _bookkeep(store, now_value, state, sent=True, reason=reason, text=text)
    data["awaiting_reply"] = True
    data["no_reply_streak"] = 0
    try:
        _write_json(_bookkeeping_path(store), data)
    except Exception:
        pass
    result.update({"sent": True, "reason": reason, "text": text,
                   "fallback": fallback, "prompt": prompt,
                   "outbox": str(outbox),
                   "sent_today": len(_sent_today(data, now_value))})
    return result


def _results_path(store):
    return _proactive_dir(store) / "results.jsonl"


def _count_lines(path):
    try:
        if path is None or not Path(path).exists():
            return 0
        return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines()
                   if line.strip())
    except Exception:
        return 0


def summary(store, now=None, enabled=False):
    """Numbers for /state; never generates or sends."""
    stamp = _num(now, time.time())
    state = load_state(store)
    sent_today = len(_sent_today(state, stamp))
    pending = max(0, _count_lines(_outbox_path(store))
                  - _count_lines(_results_path(store)))
    cfg = normalize_config({})
    last_attempt = _num(state.get("last_attempt_ts"), 0.0)
    next_at = (last_attempt + cfg["standby_every_minutes"] * 60.0
               if last_attempt > 0 else 0.0)
    return {
        "enabled": bool(enabled),
        "next_at": round(next_at, 3),
        "pending": pending,
        "sent_today": sent_today,
        "last_reason": str(state.get("last_reason") or ""),
        "no_reply_streak": int(_num(state.get("no_reply_streak"), 0)),
        "awaiting_reply": bool(state.get("awaiting_reply")),
        "cooldown_minutes": cfg["standby_cooldown_minutes"],
        "max_per_day": cfg["standby_max_per_day"],
    }


def sleep_loop(config=None, once=False):
    cfg = normalize_config(config)
    interval = max(60, int(cfg["standby_every_minutes"] * 60))
    while True:
        try:
            result = tick(config=cfg)
            print(json.dumps(result, ensure_ascii=False))
        except Exception as error:
            print(json.dumps({"ok": False, "reason": "tick_error",
                              "detail": str(error)[:200]}, ensure_ascii=False))
        if once:
            return 0
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return 0


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:])
    action = args[0] if args else "tick"
    config = {}
    index = 1
    while index < len(args):
        if args[index] == "--once":
            config["once"] = True
            index += 1
        else:
            break
    if action == "tick":
        result = tick(config=config)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    if action == "sleep-loop":
        return sleep_loop(config=config, once=bool(config.get("once")))
    print(json.dumps({"ok": False, "reason": "unknown_action",
                      "action": action}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
