# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .core_client import CoreClient


class CoreBridge:
    def __init__(self, config=None, data_dir=None, core_factory=None):
        cfg=config if isinstance(config,dict) else {}; self.config=cfg
        self.data_dir=Path(data_dir) if data_dir else Path(cfg.get("data_dir") or ".")
        self.mode=str(cfg.get("core_client_mode") or "off").strip().lower()
        if self.mode not in ("off","shadow","primary"): self.mode="off"
        self.enabled=bool(cfg.get("core_client_enabled",False)) or self.mode!="off"
        self.store=str(cfg.get("core_client_store") or "").strip() or str(self.data_dir/"core_store"/"memory.json")
        self.timeout=float(cfg.get("core_client_timeout",2.0) or 2.0); self.max_failures=int(cfg.get("core_client_max_failures",5) or 5)
        self._factory=core_factory or CoreClient; self._client=None; self.failures=0; self.fail_count=0
        self.circuit_open=False; self.calls=0; self.last_error=""; self.shadow_path=self.data_dir/"shadow_diff.jsonl"
        self.migrated_available=(self.data_dir/"core_store"/"memory.json").is_file()
    def store_path(self): return str(self.data_dir/"core_store"/"memory.json") if self.migrated_available and not str(self.config.get("core_client_store") or "").strip() else self.store
    def _get_client(self):
        if self._client is None:
            try: self._client=self._factory(store=self.store_path(),enabled=True,timeout=self.timeout)
            except Exception as error: self.last_error=str(error); self._client=None
        return self._client
    def _record_failure(self, error):
        self.failures+=1; self.fail_count=self.failures; self.last_error=str(error or "failure")
        if self.failures>=self.max_failures: self.circuit_open=True
    def _record_success(self): self.failures=0; self.fail_count=0; self.last_error=""
    def _record_shadow(self,data):
        try:
            self.shadow_path.parent.mkdir(parents=True,exist_ok=True)
            with open(self.shadow_path,"a",encoding="utf-8") as h: h.write(json.dumps(dict(data or {}),ensure_ascii=False)+"\n")
        except Exception: pass
    def media_probe(self):
        if not self.enabled or self.circuit_open:
            return None
        ok = False
        reason = ""
        try:
            client = self._get_client()
            if client is not None and hasattr(client, "_call"):
                result = client._call("media.caption", {"text": "probe"})
                ok = result is not None
                if not ok:
                    reason = str(getattr(client, "last_error", "") or "")
        except Exception as error:
            reason = str(error)
        try:
            with open(self.data_dir / "media-probe.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"ts": round(time.time(), 3), "ok": bool(ok), "reason": str(reason or ("provider_unavailable" if not ok else ""))[:160]}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return {"ok": ok, "reason": reason}
    def summary_dry_run(self, payload):
        if not self.enabled or self.mode not in ("primary", "shadow") or self.circuit_open:
            return None
        body = dict(payload or {})
        ok = False
        try:
            client = self._get_client()
            if client is not None and hasattr(client, "_call"):
                params = dict(body); params["dry_run"] = True
                result = client._call("summary.daily", params)
                ok = result is not None
        except Exception:
            ok = False
        try:
            chars = len(str(body.get("text") or ""))
            with open(self.data_dir / "summary-dryrun.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"ts": round(time.time(), 3), "ok": bool(ok), "chars": chars}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return None
    def identity_signal(self, payload):
        if not self.enabled or self.mode != "primary" or self.circuit_open:
            return None
        try:
            client = self._get_client()
            if client is not None and hasattr(client, "_call"):
                result = client._call("identity.writeback", {"signal": dict(payload or {})})
                if result is not None:
                    return result
        except Exception:
            pass
        try:
            with open(self.data_dir / "identity-signals.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(dict(payload or {}), ensure_ascii=False) + "\n")
        except Exception:
            return None
        return None
    def relation_update(self, payload):
        if not self.enabled or self.mode != "primary" or self.circuit_open:
            return None
        try:
            client = self._get_client()
            if client is None:
                return None
            if hasattr(client, "_call"):
                return client._call("relation.update", dict(payload or {}))
            if hasattr(client, "relation_update"):
                return client.relation_update(payload)
        except Exception:
            return None
        return None
    def record_episode(self, action, outcome, reward=0.0, signals=None):
        if not self.enabled:
            return None
        payload = {"action": str(action), "outcome": str(outcome), "reward": float(reward or 0.0), "signals": signals or {}}
        client = self._get_client()
        if client is not None and hasattr(client, "episode_log"):
            try:
                return client.episode_log(payload)
            except Exception:
                pass
        try:
            with open(self.data_dir / "episodes-local.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            return None
        return payload
    def remember(self,text,role="user",importance=None):
        if not self.enabled or self.circuit_open: return None
        self.calls+=1
        try:
            client=self._get_client(); result=client.remember(text,importance=importance) if client is not None else None
            ok=isinstance(result,dict) and result.get("ok") is True
            if not ok: self._record_failure("remember_failed")
            else: self._record_success()
        except Exception as error: self._record_failure(error); result=None; ok=False
        if self.mode=="shadow":
            self._record_shadow({"kind":"remember","ts":round(time.time(),3),"text_hash":hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:12],"core_ok":ok,"core_entry_id":str((result or {}).get("id") or "") if isinstance(result,dict) else "","core_error":"" if ok else str(self.last_error or "remember_failed")})
            return None
        return result if self.mode=="primary" else None
    def remember_shadow(self,text,role="user",importance=0.5):
        self.remember(text,role=role,importance=importance); return self.mode=="shadow" and self.failures==0
    def record_remember_shadow(self,text_hash,old_stored,core_stored):
        row={"ts":round(time.time(),3),"text_hash":str(text_hash or "")[:64],"old_stored":bool(old_stored),"core_stored":bool(core_stored),"same":bool(old_stored)==bool(core_stored)}
        self._record_shadow(row); return row
    def recall(self,query,limit=3,old_result=None,old_ids=None,latency_old=0.0):
        if not self.enabled or self.mode=="off" or self.circuit_open: return None
        self.calls+=1
        try:
            client=self._get_client(); result=client.recall(query,limit=limit) if client is not None else None
            if result is None: self._record_failure("recall_failed"); return None
            self._record_success()
            if self.mode=="shadow":
                core_ids=[str(r.get("id")) for r in (result.get("results") or []) if isinstance(r,dict)]
                self._record_shadow({"kind":"recall","ts":round(time.time(),3),"query":str(query or ""),"old_ids":list(old_ids or [])[:20],"core_ids":core_ids[:20],"overlap":len(set(old_ids or [])&set(core_ids)),"latency_old":round(float(latency_old or 0.0),4),"latency_core":0.0})
            return result
        except Exception as error: self._record_failure(error); return None
    def forget(self,entry_id=None,query=None,limit=5):
        if not self.enabled or self.mode not in ("primary","shadow") or self.circuit_open: return None
        self.calls+=1
        try:
            client=self._get_client(); result=client.forget(entry_id=entry_id,query=query,limit=limit) if client is not None else None
            if result is None: self._record_failure("forget_failed"); return None
            self._record_success(); return result
        except Exception as error: self._record_failure(error); return None
    def forget_via_core(self,entry_id=None,query=None):
        if not self.enabled or self.mode!="primary" or self.circuit_open: return {"used_core":False,"removed":0}
        result=self.forget(entry_id=entry_id,query=query)
        if isinstance(result,dict) and result.get("ok") is True:
            removed=result.get("removed") or []; return {"used_core":True,"removed":len(removed) if isinstance(removed,list) else int(removed or 0)}
        return {"used_core":False,"removed":0}
    def record_shadow(self,query,old_ids,core_ids,latency_old=0.0,latency_core=0.0):
        row={"kind":"recall","ts":round(time.time(),3),"query":str(query or ""),"old_ids":list(old_ids or [])[:20],"core_ids":list(core_ids or [])[:20],"overlap":len(set(old_ids or [])&set(core_ids or [])),"latency_old":round(float(latency_old),4),"latency_core":round(float(latency_core),4)}
        self._record_shadow(row); return row
    @staticmethod
    def rows_to_text(rows):
        return "\n".join("- "+str(r.get("text") or "").strip() for r in (rows or []) if isinstance(r,dict) and str(r.get("text") or "").strip())
    def circuit_state(self): return {"circuit_open":bool(self.circuit_open),"fail_count":int(self.fail_count),"last_error":str(self.last_error or "")}
    def health(self): return {"enabled":bool(self.enabled),"mode":self.mode,"circuit_open":bool(self.circuit_open),"fail_count":int(self.fail_count),"last_error":str(self.last_error or ""),"store":self.store_path()}
