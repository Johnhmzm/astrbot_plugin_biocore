#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""task-223: persistent BioCore service (one process per DSH plugin lifetime).

Protocol: one JSON object per line on stdin, one JSON reply per line on stdout.

    request  {"id": <str>, "action": <str>, "payload": {...}}
    reply    {"id": <str>, "ok": true,  "result": {...}}
             {"id": <str>, "ok": false, "reason": "...", "detail": "..."}

The action is handed to biocore_runtime.pipeline.dispatch, so every policy
stays in the existing module. A bad request or an exception is answered and
the loop keeps running; SIGTERM/SIGINT stop it cleanly. No third-party deps.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

_PLUGIN_ROOT = str(Path(__file__).resolve().parents[1])
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)
_ADAPTER_DIR = str(os.environ.get("BIOCORE_ADAPTER_DIR") or "").strip()
if _ADAPTER_DIR and _ADAPTER_DIR not in sys.path:
    sys.path.insert(0, _ADAPTER_DIR)

from biocore_runtime import pipeline  # noqa: E402

STOP = False
_IDLE_EVENT = threading.Event()


def _install_signals():
    def _stop(signum, frame):
        global STOP
        STOP = True
        _IDLE_EVENT.set()
    for name in ("SIGTERM", "SIGINT"):
        handler = getattr(signal, name, None)
        if handler is None:
            continue
        try:
            signal.signal(handler, _stop)
        except Exception:
            pass


def _reply(stream, req_id, ok, result=None, reason="", detail=""):
    payload = {"id": req_id, "ok": bool(ok)}
    if ok:
        payload["result"] = result if result is not None else {}
    else:
        payload["reason"] = str(reason or "service_error")
        if detail:
            payload["detail"] = str(detail)[:300]
    try:
        stream.write(json.dumps(payload, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
        stream.flush()
    except Exception:
        pass


def handle(req):
    """One request dict -> (ok, result, reason, detail); never raises."""
    if not isinstance(req, dict):
        return False, None, "bad_request", "request must be an object"
    req_id = req.get("id")
    action = str(req.get("action") or "").strip()
    payload = req.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    if not action:
        return False, None, "bad_request", "missing action"
    if action == "ping":
        return True, {"pong": True, "echo_len": len(json.dumps(payload)),
                      "pid": os.getpid()}, "", ""
    if action == "sleep":
        try:
            ms = max(0, min(5000, int(payload.get("ms") or 0)))
        except Exception:
            ms = 0
        time.sleep(ms / 1000.0)
        return True, {"slept": ms}, "", ""
    try:
        result = pipeline.dispatch(action, payload)
        return True, result, "", ""
    except Exception as error:  # keep the service alive
        detail = "%s: %s" % (type(error).__name__, str(error)[:200])
        try:
            traceback.print_exc(file=sys.stderr)
        except Exception:
            pass
        return False, None, "service_error", detail


def _watchdog(idle_timeout):
    """Exit when no request arrived for idle_timeout seconds (0 = never)."""
    if not idle_timeout or idle_timeout <= 0:
        return

    def _run():
        while not STOP:
            fired = _IDLE_EVENT.wait(timeout=idle_timeout)
            if fired:
                return
            if STOP:
                return
            try:
                sys.stderr.write("__bioService idle_timeout\n")
                sys.stderr.flush()
            except Exception:
                pass
            os._exit(0)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def serve(stream_in=None, stream_out=None, idle_timeout=0.0):
    global STOP
    stdin = stream_in or sys.stdin
    stdout = stream_out or sys.stdout
    _watchdog(float(idle_timeout or 0.0))
    for line in stdin:
        if STOP:
            break
        line = str(line or "").strip()
        if not line:
            continue
        _IDLE_EVENT.set()
        _IDLE_EVENT.clear()
        req_id = None
        try:
            request = json.loads(line)
            if isinstance(request, dict):
                req_id = request.get("id")
            ok, result, reason, detail = handle(request)
        except Exception as error:
            ok, result, reason, detail = (False, None, "bad_json",
                                          "%s: %s" % (type(error).__name__,
                                                      str(error)[:200]))
        _reply(stdout, req_id, ok, result, reason, detail)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--idle-timeout", type=float, default=0.0)
    args, _unknown = parser.parse_known_args(list(argv or sys.argv[1:]))
    _install_signals()
    return serve(idle_timeout=args.idle_timeout)


if __name__ == "__main__":
    raise SystemExit(main())
