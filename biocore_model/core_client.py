# -*- coding: utf-8 -*-
"""BioCore core client (AstrBot side) - disabled by default."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ENV_ENABLED="BIOCORE_CORE_CLIENT"; ENV_STORE="BIOCORE_MEMORY_STORE"; ENV_SCRIPT="BIOCORE_SERVICE_SCRIPT"
DEFAULT_TIMEOUT=3.0; MAX_RESTARTS=1
def _truthy(value): return str(value or "").strip().lower() in ("1","true","yes","on")
def default_store():
    env=str(os.environ.get(ENV_STORE) or "").strip()
    return env or str(Path.home()/".dsh"/"memory_store")
def default_service_script():
    env=str(os.environ.get(ENV_SCRIPT) or "").strip()
    if env and Path(env).is_file(): return env
    here=Path(__file__).resolve(); candidates=[here.parents[2]/"dsh-biocore-memory"/"service"/"server.py",here.parents[1]/"service"/"server.py",here.parent/"server.py"]
    for candidate in candidates:
        try:
            if candidate.is_file(): return str(candidate)
        except Exception: continue
    return ""
class CoreClient:
    def __init__(self, store=None, enabled=None, timeout=DEFAULT_TIMEOUT, runner=None, service_script=None, python=None, max_restarts=MAX_RESTARTS):
        self.store=str(store or default_store()); self.enabled=_truthy(os.environ.get(ENV_ENABLED)) if enabled is None else bool(enabled)
        self.timeout=float(timeout if timeout is not None else DEFAULT_TIMEOUT); self.runner=runner
        self.service_script=str(service_script if service_script is not None else default_service_script()); self.python=python or sys.executable
        self.max_restarts=max(0,int(max_restarts)); self.last_error=""; self._closed=False; self._next_id=1; self._process=None; self._reader=None
        self._responses={}; self._dead=False; self._condition=threading.Condition()
    def set_timeout(self, seconds):
        try: value=float(seconds)
        except Exception: return self.timeout
        if value < 1.0 or value > 60.0: return self.timeout
        self.timeout=value; return self.timeout
    def close(self):
        self._closed=True; self._kill()
    def __enter__(self): return self
    def __exit__(self,*exc_info): self.close(); return False
    def _kill(self):
        process=self._process; self._process=None
        if process is not None:
            try: process.terminate(); process.wait(timeout=1.0)
            except Exception:
                try: process.kill()
                except Exception: pass
        with self._condition: self._dead=True; self._responses.clear(); self._condition.notify_all()
    def _start(self):
        if self.runner is not None or self._process is not None: return
        if not self.service_script or not Path(self.service_script).is_file(): self.last_error="service_script_missing"; return
        try:
            child=subprocess.Popen([self.python,self.service_script,"--store",self.store],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding="utf-8",bufsize=1)
        except Exception as error: self.last_error="spawn_failed: "+str(error); return
        with self._condition: self._process=child; self._dead=False; self._responses={}
        self._reader=threading.Thread(target=self._read_loop,args=(child,),name="biocore-core-reader",daemon=True); self._reader.start()
    def _read_loop(self, process):
        try:
            for line in process.stdout:
                text=str(line or "").strip()
                if not text: continue
                try: message=json.loads(text)
                except Exception: continue
                if not isinstance(message,dict): continue
                with self._condition: self._responses[message.get("id")]=message; self._condition.notify_all()
        except Exception: pass
        finally:
            with self._condition:
                if self._process is process: self._dead=True
                self._condition.notify_all()
    def _reset_process(self): self._kill()
    def _transmit(self, request):
        if self.runner is not None: return self.runner(dict(request),self.timeout)
        self._start()
        if self._process is None: return None
        request_id=request.get("id")
        try:
            self._process.stdin.write(json.dumps(request,ensure_ascii=False)+"\n"); self._process.stdin.flush()
        except Exception as error: self.last_error="write_failed: "+str(error); self._reset_process(); return None
        deadline=time.monotonic()+max(0.1,self.timeout)
        with self._condition:
            while request_id not in self._responses:
                remaining=deadline-time.monotonic()
                if remaining<=0: return None
                if self._dead: return None
                self._condition.wait(min(remaining,0.1))
            return self._responses.pop(request_id)
    def _call(self, method, params=None):
        if self._closed or not self.enabled: return None
        attempts=0
        while True:
            request={"id":self._next_id,"method":str(method),"params":dict(params or {})}; self._next_id+=1
            try: response=self._transmit(request)
            except TimeoutError as error: self.last_error="timeout: "+str(error); self._reset_process(); return None
            except (ChildProcessError,BrokenPipeError,EOFError,OSError) as error:
                self.last_error="process_error: "+str(error); self._reset_process(); attempts+=1
                if attempts > self.max_restarts: return None
                continue
            except Exception as error: self.last_error="client_error: "+str(error); return None
            if not isinstance(response,dict):
                if not self.last_error: self.last_error="timeout_or_eof"
                self._reset_process(); return None
            if response.get("ok") is True:
                result=response.get("result"); self.last_error=""; return result if isinstance(result,dict) else {"value":result}
            error=response.get("error") if isinstance(response.get("error"),dict) else {}
            self.last_error=str(error.get("code") or "error")+": "+str(error.get("message") or ""); return None
    def remember(self,text,tags=None,importance=None,role="user"): return self._call("memory.remember",{"text":str(text or ""),"tags":list(tags or []),"importance":importance,"role":role or "user"})
    def recall(self,query,limit=3): return self._call("memory.recall",{"query":str(query or ""),"limit":int(limit or 3)})
    def forget(self,entry_id=None,query=None,limit=5):
        if entry_id: return self._call("memory.forget",{"id":str(entry_id)})
        if not query: return None
        found=self._call("memory.recall",{"query":str(query),"limit":int(limit or 5)})
        results=found.get("results") if isinstance(found,dict) else None
        if not isinstance(results,list) or not results: return None
        removed=[]
        for row in results:
            row_id=row.get("id") if isinstance(row,dict) else None
            if not row_id: continue
            response=self._call("memory.forget",{"id":str(row_id)})
            if isinstance(response,dict) and response.get("removed"): removed.append(str(row_id))
        return {"ok":True,"removed":removed,"count":len(removed)}
    def state(self,limit=12,scope="global"): return self._call("memory.state",{"limit":int(limit or 12),"scope":str(scope or "global")})
    def bio_snapshot(self,session_id="default"): return self._call("bio.snapshot",{"session_id":str(session_id or "default")})
    def health(self): return self._call("health.check",{})
