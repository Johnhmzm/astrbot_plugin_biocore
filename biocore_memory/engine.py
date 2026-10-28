# -*- coding: utf-8 -*-
"""MemoryEngine: orchestration only.

Owns the public API and wires every optional mechanism behind a boolean flag
declared in core/config.py FLAGS. A flags.json in the data directory overrides
those booleans at engine start, so "change the flag, change the behaviour".

Rules:
- orchestration only: no algorithm thresholds live here (core/config.py);
- never imports astrbot and never writes prompt text;
- every optional mechanism defaults OFF and its disabled path is the old code;
- optional sub-modules are imported lazily and degrade silently when missing,
  so a partially landed tree still runs.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .core.config import (COMPRESS_MAX_CHARS, DEFAULT_BUDGET, FLAGS,
                          MEMORY_POINT_MIN_IMPORTANCE, MEMORY_POINT_MIN_SELF,
                          MEMORY_POINT_MIN_VALUE, RATE_LIMIT_PER_MIN)
from .core.util import clamp01, now_ts, sha12
from .engine_helpers import (annotate_tiers, check_after_remember,
                             cosine_vectors, explicit_number,
                             is_protected_entry, slots_ingest,
                             source_filtered_count, value_of, vector_for)
from .store.json_store import MemoryStore
from .event.extract import event_from_any
from .event._types import MemoryEvent
from .index import cue_score
from .recall import recall_entries
from .evict import eviction_order, eviction_score
from .identity import identity_snapshot as _identity_snapshot, is_identity
from .identity.api import write as _identity_write
from .relay import relay_card as _relay_card
from .thread import expire_threads, thread_card as _thread_card, update_thread

_EMPTY_INDEX = ("entities", "place", "time_coarse", "event_name", "id")
_SUMMARY_SOURCES = ("consolidate", "ti_mem", "reflection")


def is_memory_point(value, importance, self_relevance):
    """Memory-point gate (OR semantics, literature-backed).

    Any single strong signal is enough:
      - value >= 0.60        -> composite value formula
      - importance >= 0.75   -> event centrality / emotional intensity
                                (Berntsen & Rubin 2006; Talarico et al. 2004)
      - self_relevance >= 0.45 -> self-reference effect
                                (Rogers et al. 1977; Symons & Johnson 1997)
    Thresholds are engineering values, not paper parameters.
    """
    def _num(raw):
        try:
            return float(raw or 0.0)
        except Exception:
            return 0.0
    return bool(_num(value) >= MEMORY_POINT_MIN_VALUE
                or _num(importance) >= MEMORY_POINT_MIN_IMPORTANCE
                or _num(self_relevance) >= MEMORY_POINT_MIN_SELF)


class MemoryEngine:
    def __init__(self, data_dir=None, affect=None, embedder=None, store=None,
                 path=None, now=None, three_channel=None,
                 eviction_readonly=None, identity_writeback=None,
                 config=None, slots_enabled=None, due_hints_enabled=None):
        self.affect = affect
        self.config = config if isinstance(config, dict) else {}
        self.flags = dict(FLAGS)
        overrides = (self.config.get("flags")
                     if isinstance(self.config.get("flags"), dict) else {})
        for key, value in overrides.items():
            if isinstance(value, bool):
                self.flags[str(key)] = value
        _dir = Path(data_dir) if data_dir is not None else None
        if _dir is None and path is not None:
            _dir = Path(path).parent
        self._data_dir = _dir
        self._flag_file = (_dir / "flags.json") if _dir is not None else None
        self._load_flag_file()
        self.principal = (self.config.get("principal")
                          if isinstance(self.config.get("principal"), dict) else None)
        if embedder is None and self.flags.get("embedding", True):
            try:
                from .recall.embedding import load_provider
                embedder = load_provider(self.config)
            except Exception:
                embedder = None
        self.embedder = embedder
        self.three_channel = (bool(three_channel) if three_channel is not None
                              else bool(self.flags.get("three_channel", False)))
        self.eviction_readonly = (bool(eviction_readonly)
                                  if eviction_readonly is not None
                                  else bool(self.flags.get("eviction_readonly", False)))
        self.identity_writeback_enabled = (
            bool(identity_writeback) if identity_writeback is not None
            else bool(self.flags.get("identity_writeback",
                                     self.flags.get("identity", False))))
        self.slots_enabled = (bool(slots_enabled) if slots_enabled is not None
                              else bool(self.flags.get("slots", False)))
        self.due_hints_enabled = (bool(due_hints_enabled) if due_hints_enabled is not None
                                  else bool(self.flags.get("due_hints", False)))
        self.slot_registry = None
        if self.slots_enabled:
            try:
                from .slots import SlotRegistry
                self.slot_registry = SlotRegistry(enabled=True)
            except Exception:
                self.slot_registry = None
        self._last_slots = None
        self._last_recall_tiers = None
        self._identity_state = {}
        self._threads = {}
        self._open_loops = []
        self._last_dedupe = None
        self._last_identity_check = None
        self._last_security = None
        self._last_compress = None
        self._last_retrieval = None
        self._last_ledger = None
        self._last_constraint_hint = None
        self._audit = None
        self._rate_limiters = {}
        self._cooc = {}
        self._last_graph_edge_count = 0
        self._last_slots_msg = ""
        self._last_slots_ts = 0.0
        self._last_evictions = None
        self._last_deletion_audit = None
        self._last_consistency = None
        self._last_source_consistency = None
        self._last_narrative = None
        if store is not None:
            self.store = store
        else:
            if path is None and data_dir is not None:
                path = Path(data_dir) / "memory.json"
            self.store = MemoryStore.load(path) if path else MemoryStore()
        self.now = now if callable(now) else (lambda: time.time())

    # -- flags ------------------------------------------------------------
    def _flag(self, name, default=False):
        try:
            return bool(self.flags.get(name, default))
        except Exception:
            return bool(default)

    def _load_flag_file(self):
        if self._flag_file is None:
            return False
        try:
            import json as _json
            if not self._flag_file.exists():
                return False
            data = _json.loads(self._flag_file.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        changed = False
        for key, value in data.items():
            if isinstance(value, bool):
                self.flags[str(key)] = value
                changed = True
        return changed

    def reload_flags(self):
        """Re-read flags.json and refresh derived switches at runtime."""
        self._load_flag_file()
        self._sync_attributes()
        return dict(self.flags)

    def set_flags(self, overrides, persist=False):
        """Apply boolean flag overrides; optionally rewrite flags.json."""
        changed = {}
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                if isinstance(value, bool):
                    self.flags[str(key)] = value
                    changed[str(key)] = value
        self._sync_attributes()
        if persist and self._flag_file is not None and changed:
            try:
                import json as _json
                data = {}
                if self._flag_file.exists():
                    existing = _json.loads(self._flag_file.read_text(encoding="utf-8"))
                    if isinstance(existing, dict):
                        data = existing
                data.update(changed)
                self._flag_file.parent.mkdir(parents=True, exist_ok=True)
                self._flag_file.write_text(
                    _json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
            except Exception:
                pass
        return dict(self.flags)

    def _sync_attributes(self):
        self.three_channel = bool(self.flags.get("three_channel", False))
        self.eviction_readonly = bool(self.flags.get("eviction_readonly", False))
        self.identity_writeback_enabled = bool(
            self.flags.get("identity_writeback", self.flags.get("identity", False)))
        self.slots_enabled = bool(self.flags.get("slots", False))
        self.due_hints_enabled = bool(self.flags.get("due_hints", False))
        if self.slots_enabled and self.slot_registry is None:
            try:
                from .slots import SlotRegistry
                self.slot_registry = SlotRegistry(enabled=True)
            except Exception:
                self.slot_registry = None
        elif not self.slots_enabled:
            self.slot_registry = None

    def _bump(self, key, amount=1):
        try:
            return int(self.store.bump_stats(key, amount) or 0)
        except Exception:
            return 0

    def _set_last_op(self, entry, action, when=None):
        """Record the last write/dedupe action on one entry (UI read-only)."""
        if not isinstance(entry, dict):
            return entry
        meta = entry.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
            entry["metadata"] = meta
        meta["last_op"] = str(action or "noop")[:16]
        try:
            meta["last_op_ts"] = round(
                float(when if when is not None else self.now()), 3)
        except Exception:
            meta["last_op_ts"] = 0.0
        return entry

    # -- persistence ------------------------------------------------------
    def save(self):
        return self.store.save()

    def export(self):
        return self.store.export()

    def _flush_stats(self):
        if self.store.path is not None:
            try:
                self.store.save()
            except Exception:
                pass

    def write_snapshot(self, path=None):
        """Write the read-only UI snapshot JSON (never raises).

        Merges timeline / slots_snapshot / dedupe_actions / graph_snapshot /
        monitor into one document. Default target is <store>/snapshot.json;
        the write is atomic (temp file + os.replace) and a failure returns
        None without touching the caller's main flow.
        """
        try:
            target = Path(path) if path is not None else None
            if target is None:
                base = self._data_dir
                if base is None and getattr(self.store, "path", None) is not None:
                    base = Path(self.store.path).parent
                if base is None:
                    return None
                target = Path(base) / "snapshot.json"
            elif target.is_dir():
                target = target / "snapshot.json"
            payload = {
                "schema": "bc.memory.snapshot.v1",
                "ts": round(now_ts(self.now()), 3),
                "timeline": self.timeline(),
                "slots": self.slots_snapshot(),
                "dedupe_actions": self.dedupe_actions(),
                "graph": self.graph_snapshot(),
                "monitor": self.monitor(),
                "memory_points": self.memory_points_snapshot(),
                "index": self.index_snapshot(),
                "loops": self.loops_snapshot(),
                "flags_all": dict(self.flags),
            }
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            try:
                tmp.write_text(json.dumps(payload, ensure_ascii=False,
                                          indent=1, default=str),
                               encoding="utf-8")
                os.replace(str(tmp), str(target))
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
            return target
        except Exception:
            return None

    def _write_snapshot_safe(self, path=None):
        try:
            return self.write_snapshot(path)
        except Exception:
            return None

    # -- optional mechanism adapters --------------------------------------
    def _audit_path(self):
        base = self._data_dir
        if base is None and getattr(self.store, "path", None) is not None:
            base = Path(self.store.path).parent
        if base is None:
            return None
        return Path(base) / "audit.jsonl"

    def _audit_write(self, action, entry_id="", event="", detail=None):
        if not self._flag("audit"):
            return False
        path = self._audit_path()
        if path is None:
            return False
        try:
            if self._audit is None:
                from .store.audit import audit_file
                self._audit = audit_file(path)
            row = {"schema": "bc.memory.audit.v1",
                   "action": str(action or "")[:40],
                   "entry_id": str(entry_id or "")[:80],
                   "event": str(event or "")[:40]}
            if detail is not None:
                row["detail"] = str(detail)[:200]
            if self._audit.write(row):
                self._bump("audit_writes")
                return True
        except Exception:
            pass
        return False

    def _rate_limit_ok(self, scope):
        if not self._flag("rate_limit"):
            return True
        base = self._data_dir
        if base is None and getattr(self.store, "path", None) is not None:
            base = Path(self.store.path).parent
        if base is None:
            return True
        key = sha12(str(scope or "default"))
        limiter = self._rate_limiters.get(key)
        if limiter is None:
            try:
                from .store.rate_limit import rate_limiter
                limiter = rate_limiter(Path(base) / ("rate_limit_%s.json" % key),
                                       max_per_min=int(RATE_LIMIT_PER_MIN))
            except Exception:
                return True
            self._rate_limiters[key] = limiter
        try:
            allowed = bool(limiter.check(now_ts(self.now())))
        except Exception:
            allowed = True
        if not allowed:
            self._bump("rate_limited")
        return allowed

    def _permission_ok(self, entry, scope, action="write"):
        if not self._flag("permissions"):
            return True
        try:
            from .core import permissions
        except Exception:
            return True
        principal = self.principal
        if not isinstance(principal, dict):
            principal = {"role": "user", "scopes": [str(scope or "default")]}
        previous = permissions.enabled
        permissions.enabled = True
        try:
            if action == "read":
                allowed = bool(permissions.can_read(entry, principal))
            else:
                allowed = bool(permissions.can_write(entry, principal))
        except Exception:
            allowed = True
        finally:
            permissions.enabled = previous
        if not allowed:
            self._bump("permissions_denied")
            self._audit_write("permission_denied", (entry or {}).get("id")
                              if isinstance(entry, dict) else "", action)
        return allowed

    def _security_check(self, entry):
        if not self._flag("security"):
            return False, "security_disabled"
        try:
            from .store import security
        except Exception:
            return False, "security_unavailable"
        previous = security.SECURITY_ENABLED
        security.SECURITY_ENABLED = True
        try:
            reject, reason = security.should_reject(entry)
        except Exception:
            return False, "security_fallback"
        finally:
            security.SECURITY_ENABLED = previous
        return bool(reject), str(reason)

    def _apply_media(self, entry):
        if not self._flag("media") or not isinstance(entry, dict):
            return entry
        media = entry.get("media")
        if not isinstance(media, dict) or not media:
            return entry
        try:
            from .store.media import attach
        except Exception:
            return entry
        try:
            result = attach(entry)
        except Exception:
            return entry
        if isinstance(result, dict):
            stored = result.get("media") if isinstance(result.get("media"), dict) else {}
            if stored and (stored != media or stored.get("redacted")):
                self._bump("media_attached")
            return result
        return entry

    def _apply_notes(self, entry):
        if not self._flag("notes") or not isinstance(entry, dict):
            return entry
        try:
            from .event.notes import make_note
        except Exception:
            return entry
        try:
            tags = entry.get("tags") if isinstance(entry.get("tags"), list) else None
            links = (entry.get("related_ids")
                     if isinstance(entry.get("related_ids"), list) else None)
            note = make_note(entry.get("text"), tags=tags, links=links)
        except Exception:
            return entry
        if isinstance(note, dict):
            entry["note"] = note
            meta = entry.get("metadata")
            if isinstance(meta, dict):
                meta["note"] = note
            self._bump("notes_written")
        return entry

    def _apply_notes_link(self, entry):
        if not self._flag("notes_link") or not isinstance(entry, dict):
            return entry
        try:
            from .event import notes_link as notes_link_mod
        except Exception:
            return entry
        try:
            result = notes_link_mod.enrich_entry(entry, enabled=True)
        except Exception:
            return entry
        if isinstance(result, dict):
            meta = result.get("metadata")
            if isinstance(meta, dict) and isinstance(meta.get("note"), dict):
                self._bump("notes_linked")
            return result
        return entry

    def _apply_ledger(self, event, now=None):
        if not self._flag("ledger"):
            return None
        meta = getattr(event, "metadata", None)
        if not isinstance(meta, dict) and isinstance(event, dict):
            meta = event
        if not isinstance(meta, dict):
            return None
        signal = any(meta.get(key) is not None for key in
                     ("trust_delta", "conflict_delta", "relationship_kind"))
        if not signal:
            return None
        try:
            from .identity import ledger
        except Exception:
            return None
        try:
            result = ledger.append_entry(self.store, dict(meta),
                                         now=now_ts(now or self.now()), enabled=True)
        except Exception:
            return None
        written = len(result.get("written") or []) if isinstance(result, dict) else 0
        if written:
            self._bump("ledger_writes", written)
        self._last_ledger = result
        return result

    def _cooc_refresh(self):
        if not self._flag("entity_boost"):
            return
        try:
            from .index.entity_boost import build_cooccurrence
            self._cooc = build_cooccurrence(self.store.entries)
        except Exception:
            self._cooc = {}

    def _apply_entity_boost(self, rows, query):
        if not self._flag("entity_boost"):
            return rows
        try:
            from .index import entity_boost as eb_mod
            from .index.entities import cues as cue_entities
        except Exception:
            return rows
        if not self._cooc:
            self._cooc_refresh()
        if not isinstance(self._cooc, dict) or not self._cooc:
            return rows
        try:
            query_entities = cue_entities(str(query or "")).get("entities") or []
        except Exception:
            query_entities = []
        if not query_entities:
            return rows
        boosted = 0
        for row in rows:
            entry = row.get("entry") if isinstance(row, dict) else None
            if not isinstance(entry, dict):
                continue
            entry_entities = entry.get("entities")
            if not isinstance(entry_entities, list) or not entry_entities:
                try:
                    entry_entities = cue_entities(str(entry.get("text") or "")
                                                  ).get("entities") or []
                except Exception:
                    entry_entities = []
            names = [name for name in query_entities if name in entry_entities]
            value = 0.0
            for name in names:
                try:
                    value = max(value, float(eb_mod.boost(name, self._cooc) or 0.0))
                except Exception:
                    continue
            if value > 0:
                row["score"] = round(min(1.0, float(row.get("score") or 0.0) + value), 6)
                reasons = row.get("reasons")
                if isinstance(reasons, list):
                    reasons.append("entity_boost")
                else:
                    row["reasons"] = ["entity_boost"]
                boosted += 1
        if boosted:
            self._bump("entity_boost_hits", boosted)
            rows.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return rows

    def _graph_edges(self):
        if not self._flag("graph"):
            return []
        try:
            from .index import graph as graph_mod
            raw = graph_mod.build_links(self.store.entries)
        except Exception:
            return []
        edges = self._normalize_edges(raw)
        if edges and len(edges) != self._last_graph_edge_count:
            self._bump("graph_edges", max(0, len(edges) - self._last_graph_edge_count))
            self._last_graph_edge_count = len(edges)
        return edges

    @staticmethod
    def _normalize_edges(raw):
        edges = []
        if isinstance(raw, dict):
            for src, dsts in raw.items():
                if isinstance(dsts, (list, tuple, set)):
                    for dst in dsts:
                        edges.append((str(src), str(dst)))
                elif dsts is not None:
                    edges.append((str(src), str(dsts)))
            return edges
        for item in raw or []:
            if isinstance(item, dict):
                src = item.get("src", item.get("source", item.get("from")))
                dst = item.get("dst", item.get("target", item.get("to")))
                if src is not None and dst is not None:
                    edges.append((str(src), str(dst)))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                edges.append((str(item[0]), str(item[1])))
        return edges

    def _apply_inhibition_filter(self, entries):
        if not self._flag("inhibition"):
            return entries
        try:
            from .evict import inhibition as inhibition_mod
            return inhibition_mod.filter_inhibited(entries)
        except Exception:
            return entries

    def _mark_inhibition(self, entries, selected_ids):
        if not self._flag("inhibition"):
            return 0
        try:
            from .evict import inhibition as inhibition_mod
            touched = inhibition_mod.mark_inhibited(entries, selected_ids)
        except Exception:
            return 0
        if touched:
            self._bump("inhibition_applied", len(touched))
        return len(touched or [])

    def _apply_retrieval_practice(self, rows, stamp):
        if not self._flag("retrieval_practice"):
            return 0
        try:
            from .recall import retrieval_practice as rp_mod
        except Exception:
            return 0
        updated = 0
        for row in rows:
            entry = row.get("entry") if isinstance(row, dict) else None
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id") or "")
            try:
                patch = rp_mod.update_stability(entry, success=True, now=stamp,
                                                enabled=True)
            except Exception:
                patch = {}
            if not isinstance(patch, dict) or not patch:
                continue
            try:
                if entry_id and self.store.find(entry_id) is not None:
                    self.store.update(entry_id, **patch)
                else:
                    entry.update(patch)
                updated += 1
            except Exception:
                continue
        if updated:
            self._bump("retrieval_practice", updated)
        self._last_retrieval = {"updated": updated}
        return updated

    def _boundary_signal(self, entry, stamp):
        if not (self._flag("boundary") and self._flag("slots")):
            return 0.0, False
        try:
            from .slots import boundary as boundary_mod
        except Exception:
            return 0.0, False
        text = str((entry or {}).get("text") or "") if isinstance(entry, dict) else ""
        previous = str(getattr(self, "_last_slots_msg", "") or "")
        previous_ts = float(getattr(self, "_last_slots_ts", 0.0) or 0.0)
        gap = max(0.0, float(stamp) - previous_ts) if previous_ts else 0.0
        try:
            is_boundary, score = boundary_mod.is_boundary(
                {"prev_msg": previous, "cur_msg": text, "dt": gap})
        except Exception:
            return 0.0, False
        self._last_slots_msg = text
        self._last_slots_ts = float(stamp)
        if is_boundary:
            self._bump("boundary_switches")
        return float(score or 0.0), bool(is_boundary)

    def _compress_entries(self, entries):
        if not self._flag("compress"):
            self._last_compress = None
            return None
        try:
            from .store import compress as compress_mod
        except Exception:
            return None
        previous = compress_mod.enabled
        compress_mod.enabled = True
        try:
            result = compress_mod.compress(entries,
                                           max_chars=int(COMPRESS_MAX_CHARS))
        except Exception:
            result = {"summary": "", "ids": []}
        finally:
            compress_mod.enabled = previous
        if isinstance(result, dict) and result.get("summary"):
            self._bump("compress_runs")
        self._last_compress = result
        return result

    def _apply_tiering_exec(self, entries, stamp):
        if not self._flag("tiering_exec"):
            return None
        try:
            from .store import tiering as tiering_mod
            from .store import tiering_exec as tiering_exec_mod
        except Exception:
            return None
        previous = tiering_mod.TIERING_ENABLED
        tiering_mod.TIERING_ENABLED = True
        try:
            result = tiering_exec_mod.apply_tiers(entries, now=stamp)
        except Exception:
            return None
        finally:
            tiering_mod.TIERING_ENABLED = previous
        archived = result.get("archived") if isinstance(result, dict) else None
        if archived:
            self._bump("tiering_archived", len(archived))
        self._tiering_exec_applied = result
        return result

    def _store_load(self):
        """Normalized store load (0..1) used by the adaptive eviction flag."""
        try:
            from .store.tiering import WARM_BUDGET
            budget = float(WARM_BUDGET or 0)
        except Exception:
            budget = 200.0
        if budget <= 0:
            return 0.0
        try:
            return max(0.0, min(1.0, len(self.store.entries) / budget))
        except Exception:
            return 0.0

    def _adaptive_eviction_score(self, entry, base, load):
        """Replace one base eviction score via evict/adaptive.adaptive_score."""
        if not self._flag("adaptive_evict"):
            return base
        try:
            from .evict import adaptive as adaptive_mod
            importance = float((entry or {}).get("importance", 0.5) or 0.5)
        except Exception:
            return base
        try:
            return float(adaptive_mod.adaptive_score(
                base, load=load, importance=importance) or 0.0)
        except Exception:
            return base

    def _apply_consistency(self, entry):
        """Annotate old/new fact conflicts on the new entry (never overwrites)."""
        if not self._flag("consistency") or not isinstance(entry, dict):
            return entry
        try:
            from .event import consistency as consistency_mod
        except Exception:
            return entry
        previous = consistency_mod.CONSISTENCY_ENABLED
        consistency_mod.CONSISTENCY_ENABLED = True
        try:
            old_entries = [x for x in self.store.entries
                           if isinstance(x, dict)
                           and str(x.get("id") or "") != str(entry.get("id") or "")]
            result = consistency_mod.detect_conflicts(entry, old_entries)
        except Exception:
            result = None
        finally:
            consistency_mod.CONSISTENCY_ENABLED = previous
        if isinstance(result, dict) and result.get("conflict"):
            meta = entry.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
                entry["metadata"] = meta
            targets = [str(x) for x in (result.get("target_ids") or []) if str(x)]
            meta["conflict"] = {
                "flag": True,
                "against_id": targets[0] if targets else "",
                "against_ids": targets[:8],
                "reasons": [str((item or {}).get("reason") or "")
                            for item in (result.get("details") or [])][:8],
                "detected_ts": round(now_ts(self.now()), 3)}
            meta["uncertainty"] = float(result.get("uncertainty") or 0.0)
            self._bump("consistency_conflicts")
            self._audit_write("consistency_conflict", entry.get("id"),
                              "remember",
                              "against=%s" % (targets[0] if targets else ""))
        self._last_consistency = result
        return entry

    def _apply_source_consistency(self, rows):
        """Mark source_rank per candidate and downweight conflicting sources."""
        if not self._flag("source_consistency"):
            return rows
        try:
            from .store import source_consistency as source_mod
        except Exception:
            return rows
        previous = source_mod.SOURCE_CONSISTENCY_ENABLED
        source_mod.SOURCE_CONSISTENCY_ENABLED = True
        ranked = 0
        conflicts = 0
        try:
            candidates = [row.get("entry") for row in rows
                          if isinstance(row, dict)
                          and isinstance(row.get("entry"), dict)]
            for row in rows:
                entry = row.get("entry") if isinstance(row, dict) else None
                if not isinstance(entry, dict):
                    continue
                try:
                    rank = float(source_mod.source_rank(entry) or 0.0)
                except Exception:
                    rank = 0.0
                try:
                    check = source_mod.detect_conflicts(entry, candidates)
                except Exception:
                    check = None
                row["source_rank"] = round(rank, 4)
                if isinstance(check, dict) and check.get("conflict"):
                    row["source_conflict"] = {
                        "flag": True,
                        "confidence": float(check.get("confidence") or 0.0),
                        "source_rank": float(check.get("source_rank") or rank),
                        "target_ids": [str(x) for x in
                                       (check.get("target_ids") or [])][:8]}
                    row["score"] = round(
                        float(row.get("score") or 0.0) * (0.85 + 0.15 * rank), 6)
                    conflicts += 1
                else:
                    row["source_conflict"] = {"flag": False}
                ranked += 1
        finally:
            source_mod.SOURCE_CONSISTENCY_ENABLED = previous
        if ranked:
            self._bump("source_consistency_ranked", ranked)
        if conflicts:
            self._bump("source_consistency_conflicts", conflicts)
            rows.sort(key=lambda item: float(item.get("score") or 0.0),
                      reverse=True)
        self._last_source_consistency = {"ranked": ranked, "conflicts": conflicts}
        return rows

    def _apply_narrative(self, now=None):
        """Run one identity-narrative update at the end of consolidation."""
        if not self._flag("narrative"):
            return None
        try:
            from .identity import narrative as narrative_mod
        except Exception:
            return None
        previous = narrative_mod.NARRATIVE_ENABLED
        narrative_mod.NARRATIVE_ENABLED = True
        try:
            entries = [x for x in self.store.entries
                       if isinstance(x, dict) and not x.get("deleted")]
            outcome = narrative_mod.apply_update(
                self.store, entries=entries, now=now_ts(now or self.now()),
                enabled=True)
        except Exception:
            outcome = None
        finally:
            narrative_mod.NARRATIVE_ENABLED = previous
        if not isinstance(outcome, dict):
            return None
        written = 1 if outcome.get("updated") else 0
        try:
            version = int(outcome.get("version") or 0)
        except Exception:
            version = 0
        report = {"written": written, "version": version,
                  "reason": str(outcome.get("reason") or ""),
                  "identity_id": str(outcome.get("id") or "")}
        if written:
            self._bump("narrative_writes")
            self._audit_write("narrative", report["identity_id"],
                              "consolidate", "version=%d" % version)
        self._last_narrative = report
        return report

    # -- remember ---------------------------------------------------------
    def remember(self, event, scope=None):
        raw_event = event
        ev = event_from_any(event)
        text = str(getattr(ev, "text", "") or "").strip()
        if len(text) < 2:
            return None
        stamp = now_ts(getattr(ev, "ts", 0.0) or self.now())
        vector = vector_for(self, ev)
        meta = getattr(ev, "metadata", {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        if isinstance(raw_event, dict):
            # event_from_any() only keeps dataclass fields; dict payloads may
            # carry tags/media/topic/scope/etc. Keep them as metadata extras.
            merged = dict(meta)
            for key, value in raw_event.items():
                if key == "metadata" or key in MemoryEvent.__dataclass_fields__:
                    continue
                merged.setdefault(key, value)
            meta = merged
            ev.metadata = meta
        entry_scope = str(scope or getattr(ev, "scope", "")
                          or meta.get("scope") or "default")
        explicit_importance = explicit_number(event, "importance")
        explicit_self = explicit_number(event, "self_relevance")
        probe = {"text": text, "scope": entry_scope,
                 "role": str(getattr(ev, "role", "user") or "user")}
        if not self._permission_ok(probe, entry_scope, "write"):
            return None
        if not self._rate_limit_ok(entry_scope):
            return None
        for existing in self.store.entries:
            if (str(existing.get("text") or "") == text
                    and str(existing.get("role") or "user")
                    == str(getattr(ev, "role", "user") or "user")):
                existing["hits"] = int(existing.get("hits", 1) or 1) + 1
                if vector:
                    existing["vector"] = vector
                self._last_dedupe, self._last_identity_check = None, None
                _chk = (check_after_remember(self.store, existing,
                                             embedder=self.embedder)
                        if self._flag("dedupe")
                        else {"dedupe": {"action": "keep",
                                         "reason": "dedupe_disabled"},
                              "identity": None})
                self._last_dedupe = _chk.get("dedupe")
                self._last_identity_check = _chk.get("identity")
                if self._flag("dedupe"):
                    # The exact-text branch is the engine's L0 merge.
                    self._set_last_op(existing, "merge", stamp)
                    self._bump("dedupe_exact_merge_count")
                    if self._last_dedupe and self._last_dedupe.get("action") in ("merge", "update"):
                        self._bump("dedupe_merge_count")
                else:
                    self._set_last_op(existing, "noop", stamp)
                    self._bump("dedupe_noop_count")
                self._slots_ingest(existing)
                self._cooc_refresh()
                self._audit_write("remember_merge", existing.get("id"), "remember")
                self._flush_stats()
                self._write_snapshot_safe()
                return existing
        entry = {
            "id": (str(getattr(ev, "id", "") or "") or sha12(text + str(stamp))),
            "text": text,
            "role": str(getattr(ev, "role", "user") or "user"),
            "session": str(getattr(ev, "session", "") or ""),
            "ts": stamp,
            "valid_at": stamp,
            "vector": vector,
            "hits": 1,
            "importance": (explicit_importance if explicit_importance is not None
                           else value_of(ev)),
            "self_relevance": (explicit_self if explicit_self is not None
                               else clamp01(getattr(ev, "self_relevance", 0.0))),
            "memory_source": "direct",
            "memory_confidence": 0.7,
            "pin": False,
            "previous_versions": [],
            "module": "biocore_memory",
            "scope": entry_scope,
        }
        entry.update({k: v for k, v in meta.items() if k not in entry})
        try:
            memory_value = float(value_of(ev))
        except Exception:
            memory_value = clamp01(entry.get("importance", 0.5), 0.5)
        entry["value"] = round(memory_value, 6)
        entry["memory_point"] = bool(is_memory_point(
            entry["value"], entry.get("importance", memory_value),
            entry.get("self_relevance", 0.0)))
        _role = str(getattr(ev, "role", "user") or "user")
        if "memory_confidence" in meta:
            entry["memory_confidence"] = clamp01(meta.get("memory_confidence"), 0.7)
        try:
            confidence = clamp01(entry.get("memory_confidence", 0.7), 0.7)
        except Exception:
            confidence = 0.7
        entry["provenance"] = {
            "source": str(("user" if _role == "user"
                           else (entry.get("source") or "assistant"))),
            "ts": stamp, "user_direct": _role == "user",
            "confidence": round(confidence, 4)}
        entry.setdefault("source", "biocore_memory:" + str(entry.get("id") or ""))
        if self._flag("provenance"):
            try:
                from .store.provenance import source_tag
                entry["provenance"].update(source_tag(
                    text, entry["provenance"].get("source"), stamp))
            except Exception:
                pass
        rejected, reason = self._security_check(entry)
        if rejected:
            self._bump("security_rejected")
            self._last_security = {"rejected": True, "reason": reason}
            self._audit_write("security_rejected", entry.get("id"), "remember", reason)
            self._flush_stats()
            return None
        entry = self._apply_media(entry)
        entry = self._apply_notes(entry)
        entry = self._apply_notes_link(entry)
        added = self.store.add(entry)
        if added is None:
            return None
        _chk = (check_after_remember(self.store, added, embedder=self.embedder)
                if self._flag("dedupe")
                else {"dedupe": {"action": "keep", "reason": "dedupe_disabled"},
                      "identity": None})
        self._last_dedupe = _chk.get("dedupe")
        self._last_identity_check = _chk.get("identity")
        action = (str((self._last_dedupe or {}).get("action") or "keep")
                  if self._flag("dedupe") else "noop")
        if action in ("merge", "update"):
            target_id = (self._last_dedupe or {}).get("target_id")
            target = self.store.find(target_id) if target_id else None
            self._set_last_op(target if isinstance(target, dict) else added,
                              action, stamp)
            self._bump("dedupe_merge_count" if action == "merge"
                       else "dedupe_update_count")
        elif action == "flag":
            self._set_last_op(added, "flag", stamp)
            self._bump("dedupe_flag_count")
        elif action == "keep":
            self._set_last_op(added, "add", stamp)
            self._bump("dedupe_add_count")
        else:
            self._set_last_op(added, "noop", stamp)
            self._bump("dedupe_noop_count")
        self._apply_ledger(ev, stamp)
        self._apply_consistency(added)
        self._slots_ingest(added)
        self._cooc_refresh()
        self._audit_write("remember", added.get("id"), "remember",
                          "source=%s" % str(added.get("memory_source") or ""))
        self._flush_stats()
        self._write_snapshot_safe()
        return added

    # -- recall -----------------------------------------------------------
    def recall(self, query, budget=DEFAULT_BUDGET, vector=None, scope="default",
               mode="now", principal=None):
        entries = [e for e in self.store.entries
                   if isinstance(e, dict) and not e.get("deleted")
                   and str(e.get("scope") or "default") == str(scope or "default")
                   and not e.get("archived")]
        if self._flag("permissions"):
            checked = []
            for entry in entries:
                if self._permission_ok(entry, scope, "read"):
                    checked.append(entry)
            entries = checked
        filtered = 0
        if self._flag("source_filter"):
            filtered = source_filtered_count(entries)
            if filtered:
                self._bump("source_filtered", filtered)
        if self._flag("temporal_filter"):
            try:
                from .recall.filters import filter_valid
                entries = filter_valid(entries, at=float(self.now()), mode=mode)
            except Exception:
                pass
        if self._flag("inhibition"):
            entries = self._apply_inhibition_filter(entries)
        if self._flag("complexity"):
            try:
                from .recall.complexity import suggest
                budget = max(1, min(5, int(suggest(query).get("budget", budget))))
            except Exception:
                pass
        self._last_constraint_hint = None
        if self._flag("constraints"):
            try:
                from .recall.constraints import check_constraints
                self._last_constraint_hint = check_constraints(
                    query, open_loops=self._open_loops,
                    commitments=[x for x in self.store.entries
                                 if isinstance(x, dict) and x.get("promise")])
            except Exception:
                self._last_constraint_hint = None
        rows = recall_entries(entries, query, budget=budget, vector=vector,
                              embedder=self.embedder,
                              three_channel=self.three_channel,
                              now=float(self.now()), cue_scorer=cue_score)
        if self._flag("bm25"):
            try:
                from .recall.bm25 import score as _bm25
                from .recall.bm25 import score_multi as _bm25_multi
                scorer = _bm25_multi if self._flag("bm25_multi") else _bm25
                for row in rows:
                    text = str((row.get("entry") or {}).get("text") or "")
                    row["score"] = round(0.7 * float(row.get("score") or 0.0)
                                         + 0.3 * scorer(query, text), 6)
                rows.sort(key=lambda item: item.get("score") or 0.0, reverse=True)
            except Exception:
                pass
        rows = self._apply_entity_boost(rows, query)
        if self._flag("ppr"):
            self._apply_ppr(rows, entries)
        rows = self._apply_source_consistency(rows)
        if self._flag("mmr") and len(rows) > 1:
            try:
                from .recall import mmr as mmr_mod
                # MMR diversity needs candidate vectors: expose entry.vector on
                # the row (mmr_select reads row["vector"] via _vec()).
                attached = []
                for row in rows:
                    if not isinstance(row, dict) or "vector" in row:
                        continue
                    entry = row.get("entry")
                    vector = entry.get("vector") if isinstance(entry, dict) else None
                    if isinstance(vector, list) and vector:
                        row["vector"] = list(vector)
                        attached.append(row)
                previous = mmr_mod.MMR_ENABLED
                mmr_mod.MMR_ENABLED = True
                try:
                    rows = mmr_mod.mmr_select(rows, k=budget,
                                              cosine_fn=cosine_vectors)
                finally:
                    mmr_mod.MMR_ENABLED = previous
                    for row in attached:
                        row.pop("vector", None)
            except Exception:
                pass
        if self._flag("tiering"):
            annotated = annotate_tiers(rows)
            self._last_recall_tiers = {
                "high": sum(1 for r in annotated if r.get("tier") == "high"),
                "mid": sum(1 for r in annotated if r.get("tier") == "mid"),
                "low": sum(1 for r in annotated if r.get("tier") == "low")}
            for key, value in self._last_recall_tiers.items():
                if value:
                    self._bump("tier_" + key, value)
            rows = [r for r in annotated if r.get("usage") != "drop"]
        else:
            self._last_recall_tiers = None
        stamp = float(self.now())
        self._apply_retrieval_practice(rows, stamp)
        if self.slot_registry is not None:
            for row in rows:
                self._slots_ingest(row.get("entry") or {}, cue=row.get("score", 0.0))
        if self._flag("inhibition"):
            selected = [str((r.get("entry") or {}).get("id") or "") for r in rows]
            self._mark_inhibition(entries, selected)
        if self._flag("compress"):
            self._compress_entries(entries)
        self._bump("recall_count")
        self._audit_write("recall", "", "recall",
                          "query=%s rows=%d mode=%s" % (str(query)[:40], len(rows), mode))
        self._flush_stats()
        return rows

    def _apply_ppr(self, rows, entries):
        try:
            from .recall.ppr import expand_ppr
        except Exception:
            return rows
        edges = self._graph_edges() if self._flag("graph") else []
        if not edges:
            for entry in entries:
                for rid in (entry.get("related_ids") or []):
                    edges.append((str(entry.get("id") or ""), str(rid)))
        if not edges:
            return rows
        seeds = [str((row.get("entry") or {}).get("id") or "")
                 for row in rows[:2]]
        seeds = [seed for seed in seeds if seed]
        if not seeds:
            return rows
        try:
            extra = expand_ppr(seeds, edges, hops=2, damping=0.5)
        except Exception:
            return rows
        by_id = {str(x.get("id") or ""): x for x in entries}
        added = 0
        for entry_id, ppr_score in extra[:2]:
            entry = by_id.get(entry_id)
            if entry is None:
                continue
            rows.append({"entry": entry, "score": round(float(ppr_score), 6),
                         "mode": "ppr", "reasons": ["ppr"]})
            added += 1
        if added:
            self._bump("ppr_expansions", added)
        return rows

    # -- forget / invalidate ----------------------------------------------
    def forget(self, entry_id, hard=False, reason="deleted", now=None, scope=None):
        entry = self.store.find(entry_id)
        if entry is None:
            return False
        if scope is not None and str(entry.get("scope") or "default") != str(scope):
            return False
        stamp = now_ts(now or self.now())
        before = len(self.store.tombstones)
        removed = self.store.remove(entry_id, now=stamp, reason=reason, hard=hard)
        if removed:
            if not hard and self._flag("provenance"):
                try:
                    from .store.provenance import append_tombstone
                    del self.store.tombstones[before:]
                    append_tombstone(self.store.tombstones, entry, now=stamp,
                                     reason=reason)
                except Exception:
                    pass
            self._propagate_delete(entry, now=stamp)
            self._tombstone_chain = None
            if self._flag("deletion_audit"):
                try:
                    self._clean_derived_refs(entry_id, entry.get("text"))
                except Exception:
                    pass
                try:
                    self._last_deletion_audit = self.deletion_audit(
                        entry_id, text=str(entry.get("text") or ""))
                    self._bump("deletion_audits")
                    self._audit_write(
                        "deletion_audit", entry_id, "forget",
                        "residue=%d" % (self._last_deletion_audit.get("residue") or 0))
                except Exception:
                    self._last_deletion_audit = None
            self._audit_write("forget", entry_id, "forget", reason)
            self._flush_stats()
            self._write_snapshot_safe()
        return removed

    def invalidate(self, entry_id, now=None):
        """Mark an entry invalid at ts (dual-temporal); it stays stored."""
        entry = self.store.find(entry_id)
        if entry is None:
            return None
        stamp = now_ts(now or self.now())
        try:
            from .store.versions import mark_invalid
            patch = mark_invalid(entry_id, at=stamp)
            if isinstance(patch, dict):
                patch = dict(patch)
                patch.pop("id", None)
                self.store.update(entry_id, **patch)
        except Exception:
            return None
        self._audit_write("invalidate", entry_id, "invalidate")
        self._flush_stats()
        return self.store.find(entry_id)

    def pin(self, entry_id, pinned=True):
        result = self.store.pin(entry_id, pinned)
        if result:
            self._audit_write("pin" if pinned else "unpin", entry_id, "pin")
            self._flush_stats()
        return result

    def _propagate_delete(self, entry, now=None):
        """Mark related anchors, drop identity evidence, clean thread refs."""
        target = str(entry.get("id") or "")
        text = str(entry.get("text") or "")
        count = 0
        for other in self.store.entries:
            if not isinstance(other, dict):
                continue
            related = (str(other.get("anchor") or "") == target
                       or target in [str(x) for x in (other.get("related_ids") or [])]
                       or str(other.get("event_anchor") or "") == target)
            evidence = other.get("identity_evidence")
            if isinstance(evidence, list):
                kept = [x for x in evidence
                        if not (isinstance(x, dict) and target in
                                (str(x.get("id") or ""), str(x.get("entry_id") or "")))]
                if len(kept) != len(evidence):
                    self.store.update(other.get("id"), identity_evidence=kept)
                    count += 1
            if related:
                self.store.update(other.get("id"), related_deleted=True,
                                  deleted_anchor=target)
                count += 1
        for key, card in list(self._threads.items()):
            if isinstance(card, dict) and (target in str(card.get("id") or "")
                                          or text[:20] in str(card.get("topic") or "")):
                self._threads.pop(key, None)
                count += 1
        self._open_loops = [x for x in self._open_loops
                            if target not in str(x.get("id") or "")
                            and text[:20] not in str(x.get("topic") or "")]
        if count:
            self._bump("delete_propagation", count)
        return count

    def _clean_derived_refs(self, target_id, text=None):
        """Drop a deleted id from derived summary entries' source_ids."""
        target = str(target_id or "")
        if not target:
            return 0
        cleaned = 0
        for entry in self.store.entries:
            if not isinstance(entry, dict):
                continue
            source = str(entry.get("source") or entry.get("memory_source") or "")
            if source not in _SUMMARY_SOURCES:
                continue
            changed = False
            refs = entry.get("source_ids")
            if isinstance(refs, list):
                kept = [str(x) for x in refs if str(x) != target]
                if len(kept) != len(refs):
                    entry["source_ids"] = kept
                    changed = True
            meta = entry.get("metadata")
            if isinstance(meta, dict) and isinstance(meta.get("source_ids"), list):
                kept = [str(x) for x in meta["source_ids"] if str(x) != target]
                if len(kept) != len(meta["source_ids"]):
                    meta["source_ids"] = kept
                    changed = True
            if changed:
                entry["derived_stale"] = True
                entry["derived_updated_ts"] = round(now_ts(self.now()), 3)
                cleaned += 1
        return cleaned

    def deletion_audit(self, entry_id, text=None):
        """Read-only coverage audit of derived data after one deletion.

        Returns {target, covered, missed, residue}: covered lists the derived
        areas with no residual reference, missed lists residual areas (with a
        reason). Tombstone rows are intentionally retained (audit chain) and
        are reported as covered, never as missed.
        """
        target = str(entry_id or "")
        text = str(text or "")
        report = {"target": target, "covered": [], "missed": [], "residue": 0}
        if not target:
            report["missed"].append({"area": "target", "count": 1,
                                     "reason": "empty_entry_id"})
            report["residue"] = 1
            return report
        entries = [x for x in self.store.entries if isinstance(x, dict)]

        def _mark(area, ids, reason):
            if ids:
                report["missed"].append({"area": area, "count": len(ids),
                                         "reason": reason, "ids": ids[:8]})
                report["residue"] += len(ids)
            else:
                report["covered"].append(area)

        # 1) consolidation summaries (role=system/source=consolidate etc.)
        summary_ids = []
        for entry in entries:
            source = str(entry.get("source") or entry.get("memory_source") or "")
            if source not in _SUMMARY_SOURCES:
                continue
            refs = entry.get("source_ids")
            refs = list(refs) if isinstance(refs, list) else []
            meta = entry.get("metadata")
            if isinstance(meta, dict) and isinstance(meta.get("source_ids"), list):
                refs += meta["source_ids"]
            if target in [str(x) for x in refs]:
                summary_ids.append(str(entry.get("id") or ""))
        _mark("summary", summary_ids, "summary source_ids still reference target")

        # 2) identity evidence / anchors (deleted_anchor is a cleanup marker)
        identity_ids = []
        for other in entries:
            evidence = other.get("identity_evidence")
            if isinstance(evidence, list) and any(
                    isinstance(x, dict) and target in
                    (str(x.get("id") or ""), str(x.get("entry_id") or ""))
                    for x in evidence):
                identity_ids.append(str(other.get("id") or ""))
                continue
            if (str(other.get("anchor") or "") == target
                    or str(other.get("event_anchor") or "") == target):
                identity_ids.append(str(other.get("id") or ""))
        _mark("identity_evidence", identity_ids,
              "identity evidence/anchor still references target")

        # 3) index/graph edges (derived from live, non-deleted entries)
        graph_ids = []
        try:
            from .index.graph import build_links
            links = build_links([x for x in entries if not x.get("deleted")]) or {}
            if target in links:
                graph_ids.append(target)
            graph_ids.extend(str(key) for key, values in links.items()
                             if target in [str(x) for x in (values or [])])
        except Exception:
            links = {}
        _mark("graph", graph_ids[:8], "graph still contains target node/edge")

        # 4) thread cards / open loops
        thread_ids = []
        for key, card in self._threads.items():
            if not isinstance(card, dict):
                continue
            topic = str(card.get("topic") or "")
            if (target in str(card.get("id") or "")
                    or (text and text[:20] and text[:20] in topic)):
                thread_ids.append(str(card.get("id") or key))
        for loop in self._open_loops:
            label = str((loop or {}).get("id") or (loop or {}).get("topic") or "")                 if isinstance(loop, dict) else str(loop)
            if target in label or (text and text[:20] and text[:20] in label):
                thread_ids.append(label[:80])
        _mark("thread", thread_ids[:8], "thread/open-loop still references target")

        # 5) tombstones are retained on purpose (hash-chain audit trail)
        tomb_count = sum(1 for tomb in self.store.tombstones
                         if isinstance(tomb, dict)
                         and str(tomb.get("id") or "") == target)
        if tomb_count:
            report["covered"].append("tombstone_chain(intentional, retained)")
        else:
            report["covered"].append("tombstone_chain(absent)")
        return report

    # -- slots ------------------------------------------------------------
    def _slots_ingest(self, entry, cue=None):
        if self.slot_registry is None or not isinstance(entry, dict):
            return None
        stamp = now_ts(self.now())
        ctx = {"now": stamp,
               "cue": cue if cue is not None else 1.0,
               "goal": float(entry.get("goal_relevance", 0.5) or 0.5),
               "boundary_score": float(entry.get("boundary_score", 0.0) or 0.0),
               "salience": float(entry.get("importance", 0.5) or 0.5),
               "slot_count": len(getattr(self.slot_registry, "slots", []) or []),
               "total_chars": self.slot_registry.total_chars(),
               "budget_chars": 360,
               "preempt_used_ts": stamp}
        boundary_score, is_boundary = self._boundary_signal(entry, stamp)
        if boundary_score:
            ctx["boundary_score"] = max(ctx["boundary_score"], boundary_score)
        if is_boundary:
            ctx["boundary_score"] = 1.0
        try:
            self._last_slots = slots_ingest(self.slot_registry, entry, ctx)
            if self._last_slots.get("evicted"):
                self._bump("slots_evicted", len(self._last_slots["evicted"]))
            if self._last_slots.get("decision") == "admit":
                self._bump("slots_admitted")
            return self._last_slots
        except Exception:
            self._last_slots = None
            return None

    # -- tick / eviction --------------------------------------------------
    def tick(self, now=None, apply_evictions=None):
        stamp = now_ts(now or self.now())
        entries = [x for x in self.store.entries if isinstance(x, dict)]
        evictions_requested = (bool(apply_evictions)
                               if apply_evictions is not None
                               else self._flag("apply_evictions"))
        tiering_exec_report = self._apply_tiering_exec(entries, stamp)
        total = max(1, len(entries))
        adaptive_on = self._flag("adaptive_evict")
        load = self._store_load() if adaptive_on else 0.0
        adaptive_scored = 0
        rows = []
        for position, entry in enumerate(entries):
            redundancy = 1.0 if any(
                other is not entry
                and str(other.get("text") or "") == str(entry.get("text") or "")
                for other in entries) else 0.0
            base = eviction_score(entry, now=stamp,
                                  position=position / float(total),
                                  redundancy=redundancy)
            score = base
            if adaptive_on:
                score = self._adaptive_eviction_score(entry, base, load)
                adaptive_scored += 1
            row = {"entry": entry, "score": score,
                   "id": str(entry.get("id") or "")}
            if adaptive_on:
                row["base_score"] = base
            rows.append(row)
        ordered = eviction_order(rows)
        result = {"now": stamp, "candidates": ordered[:20], "count": len(ordered),
                  "deleted": 0, "readonly": True, "policy": ordered[:20],
                  "stats": self._stats_snapshot(ordered)}
        if adaptive_on:
            result["adaptive"] = {"load": round(load, 4),
                                  "scored": adaptive_scored}
            if adaptive_scored:
                self._bump("adaptive_scored", adaptive_scored)
        eviction_report = None
        if evictions_requested:
            eviction_report = self._apply_evictions(stamp)
            if isinstance(eviction_report, dict):
                result["apply_evictions"] = eviction_report
                result["deleted"] = len(eviction_report.get("deleted") or [])
                result["readonly"] = False
        if self._flag("heat"):
            try:
                from .evict import heat as heat_mod
                previous = heat_mod.HEAT_ENABLED
                heat_mod.HEAT_ENABLED = True
                try:
                    result["heat"] = {str(x.get("id") or ""): heat_mod.heat(x, now=stamp)
                                      for x in entries}
                finally:
                    heat_mod.HEAT_ENABLED = previous
            except Exception:
                result["heat"] = {}
        if self._flag("consequence"):
            try:
                from .evict import consequence as consequence_mod
                previous = consequence_mod.CONSEQUENCE_ENABLED
                consequence_mod.CONSEQUENCE_ENABLED = True
                try:
                    result["consequence"] = {
                        str(x.get("id") or ""): consequence_mod.consequence(x)
                        for x in entries}
                finally:
                    consequence_mod.CONSEQUENCE_ENABLED = previous
            except Exception:
                result["consequence"] = {}
        if tiering_exec_report is not None:
            result["tiering_exec"] = tiering_exec_report
        compressed = self._compress_entries(entries)
        if compressed is not None:
            result["compress"] = compressed
        result["stats"] = self._stats_snapshot(ordered)
        self._audit_write("tick", "", "tick",
                          "entries=%d candidates=%d" % (len(entries), len(ordered)))
        if ((tiering_exec_report or {}).get("archived") or compressed
                or (eviction_report or {}).get("deleted")):
            self._flush_stats()
        self._write_snapshot_safe()
        return result

    def _apply_evictions(self, now=None):
        """Soft-delete archived entries (never removes data; never touches pins).

        Uses the read-only evict/policy partition to find low-value candidates,
        then marks each one deleted=true with a tombstone. Protected entries
        (pin / identity anchor+evidence / promise / P0-P1) are always skipped.
        """
        stamp = now_ts(now or self.now())
        try:
            from .evict.policy import tick as policy_tick
            plan = policy_tick(self.store.entries, now=stamp)
        except Exception:
            return {"applied": False, "reason": "policy_unavailable",
                    "deleted": [], "protected": 0, "candidates": 0,
                    "tombstones": 0, "now": stamp}
        candidates = [str(x) for x in (plan.get("archive") or []) if str(x)]
        deleted = []
        protected = 0
        tombstones_before = len(self.store.tombstones)
        for entry_id in candidates:
            entry = self.store.find(entry_id)
            if not isinstance(entry, dict) or entry.get("deleted"):
                continue
            if is_protected_entry(entry):
                protected += 1
                continue
            entry["deleted"] = True
            entry["deleted_ts"] = round(stamp, 3)
            entry["deleted_reason"] = "evicted"
            try:
                if self._flag("provenance"):
                    from .store.provenance import append_tombstone
                else:
                    from .store.tombstone import append_tombstone
                append_tombstone(self.store.tombstones, entry, now=stamp,
                                 reason="evicted")
            except Exception:
                pass
            deleted.append(entry_id)
        report = {"applied": True, "deleted": deleted, "protected": protected,
                  "candidates": len(candidates),
                  "tombstones": max(0, len(self.store.tombstones) - tombstones_before),
                  "now": stamp}
        if deleted:
            self._bump("evictions_applied", len(deleted))
            self._bump("evict_tombstones", report["tombstones"])
            self._audit_write("evictions", "", "tick",
                              "deleted=%d protected=%d" % (len(deleted), protected))
        self._last_evictions = report
        return report

    def restore_evictions(self, entry_ids=None, now=None):
        """Roll back soft evictions: deleted=false, all original fields kept."""
        stamp = now_ts(now or self.now())
        if entry_ids is not None:
            try:
                ids = [str(x) for x in entry_ids]
            except Exception:
                ids = []
        else:
            ids = [str(entry.get("id") or "") for entry in self.store.entries
                   if isinstance(entry, dict)
                   and entry.get("deleted_reason") == "evicted"]
        restored = []
        for entry_id in ids:
            entry = self.store.find(entry_id)
            if not isinstance(entry, dict):
                continue
            if entry.get("deleted_reason") != "evicted":
                continue
            entry["deleted"] = False
            entry.pop("deleted_ts", None)
            entry.pop("deleted_reason", None)
            entry["restored_ts"] = round(stamp, 3)
            restored.append(entry_id)
        if restored:
            self._bump("evictions_restored", len(restored))
            self._audit_write("evictions_restored", "", "restore",
                              "restored=%d" % len(restored))
            self._flush_stats()
            self._write_snapshot_safe()
        return {"restored": restored, "count": len(restored), "now": stamp}

    # -- identity / relay / thread ---------------------------------------
    def identity_snapshot(self):
        return _identity_snapshot(self.store.entries)

    def relay_card(self):
        if not self._flag("relay"):
            return {"identity": [], "relationship": [], "recent_changes": [],
                    "promises": [], "open_loops": []}
        card = _relay_card(self.store.entries, now=self.now(),
                           open_loops=self._open_loops,
                           due_enabled=self.due_hints_enabled)
        self._bump("relay_count")
        return card

    def thread_update(self, topic, status="active", now=None):
        if not self._flag("thread"):
            return {}
        self._threads, card = update_thread(self._threads, topic, status=status,
                                            now=now or self.now())
        self._expire_threads(now=now)
        return card or {}

    def thread_card(self, now=None, ttl=None):
        if not self._flag("thread"):
            return []
        self._expire_threads(now=now, ttl=ttl)
        kwargs = {"threads": self._threads,
                  "now": now_ts(now or self.now())}
        if ttl is not None:
            kwargs["ttl"] = ttl
        return _thread_card(self.store.entries, **kwargs)

    def _expire_threads(self, now=None, ttl=None):
        args = {"now": now or self.now()}
        if ttl is not None:
            args["ttl"] = ttl
        active, loops = expire_threads(self._threads, **args)
        changed = False
        for card in loops:
            topic = card.get("topic")
            if topic and topic not in [x.get("topic") for x in self._open_loops]:
                self._open_loops.append({"topic": topic, "ts": card.get("updated_ts")})
                changed = True
        if changed:
            self._open_loops = self._open_loops[-20:]
        return active, loops

    # -- import / export --------------------------------------------------
    def import_data(self, payload, scope=None):
        """Symmetric with export: entries/tombstones/stats; failure is atomic."""
        if not isinstance(payload, dict):
            return {"ok": False, "reason": "invalid_payload"}
        old_doc = None
        try:
            entries = payload.get("entries")
            if not isinstance(entries, list):
                raise ValueError("entries must be a list")
            tombstones = payload.get("tombstones", [])
            if not isinstance(tombstones, list):
                raise ValueError("tombstones must be a list")
            stats = payload.get("stats")
            if not isinstance(stats, dict):
                meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                stats = meta.get("stats", {})
            if not isinstance(stats, dict):
                raise ValueError("stats must be an object")
            selected = []
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("entry must be an object")
                if scope is not None and str(entry.get("scope") or "default") != str(scope):
                    continue
                selected.append(dict(entry))
            old_doc = self.store.export()
            old_meta = dict(self.store.meta)
            new_meta = dict(old_meta)
            new_meta["stats"] = {str(k): int(v or 0) for k, v in stats.items()}
            doc = dict(old_doc)
            doc["entries"] = selected
            doc["tombstones"] = [dict(x) for x in tombstones if isinstance(x, dict)]
            doc["meta"] = new_meta
            self.store.import_doc(doc)
            if self.store.path:
                self.store.save()
            self._cooc_refresh()
            self._audit_write("import", "", "import",
                              "entries=%d" % len(selected))
            return {"ok": True, "entries": len(selected),
                    "tombstones": len(doc["tombstones"]), "stats": len(new_meta["stats"])}
        except Exception as exc:
            if old_doc is not None:
                try:
                    self.store.import_doc(old_doc)
                except Exception:
                    pass
            return {"ok": False, "reason": str(exc)[:120]}

    # -- consolidation ----------------------------------------------------
    def consolidate(self, level=1, now=None):
        """Gated consolidation pipeline; writes only with the *_writeback flag."""
        stage_flags = ("consolidate_gated", "consolidate_tree",
                       "consolidate_reflection", "consolidate_neighbors",
                       "consolidate_writeback")
        if not any(self._flag(key) for key in stage_flags):
            return {"enabled": False}
        entries = [x for x in self.store.entries
                   if isinstance(x, dict) and not x.get("summarized")
                   and not x.get("archived")]
        stamp = now_ts(now or self.now())
        result = {"enabled": True, "level": int(level or 1), "written": 0,
                  "marked": 0}
        try:
            from .consolidate import gated as gated_mod
            from .consolidate import neighbors as neighbors_mod
            from .consolidate import reflection as reflection_mod
            from .consolidate import tree as tree_mod
        except Exception as exc:
            result["error"] = str(exc)[:120]
            return result
        previous = {
            "gated": gated_mod.GATED_ENABLED,
            "tree": tree_mod.TREE_ENABLED,
            "reflection": reflection_mod.REFLECTION_ENABLED,
            "neighbors": neighbors_mod.NEIGHBORS_ENABLED,
        }
        gated_mod.GATED_ENABLED = self._flag("consolidate_gated")
        tree_mod.TREE_ENABLED = self._flag("consolidate_tree")
        reflection_mod.REFLECTION_ENABLED = self._flag("consolidate_reflection")
        neighbors_mod.NEIGHBORS_ENABLED = self._flag("consolidate_neighbors")
        try:
            if self._flag("consolidate_gated"):
                result["gated"] = bool(gated_mod.should_consolidate(entries,
                                                                    now=stamp))
                if not result["gated"]:
                    result["reason"] = "gate_closed"
                    self._write_snapshot_safe()
                    return result
            summary_ids = []
            tree_data = {}
            if self._flag("consolidate_tree"):
                result["tree"] = tree_mod.build_summary(entries, level=level)
                tree_data = (result["tree"]
                             if isinstance(result["tree"], dict) else {})
                # Level items are only real summaries when generated is true.
                if tree_data.get("generated"):
                    for item in (tree_data.get("items") or []):
                        summary_ids.extend(item.get("source_ids") or [])
                        if item.get("id"):
                            summary_ids.append(item.get("id"))
            if self._flag("consolidate_reflection"):
                result["reflections"] = reflection_mod.propose(entries)
                for item in (result["reflections"] or []):
                    summary_ids.extend(item.get("source_ids") or [])
            if self._flag("consolidate_neighbors"):
                result["neighbors"] = [neighbors_mod.strengthen(x, entries)
                                       for x in entries[:5]]
            summary_ids = sorted({str(x) for x in summary_ids if str(x)})
            real_summary = (bool(result.get("reflections"))
                            or bool(tree_data.get("generated")))
            written = 0
            if self._flag("consolidate_writeback"):
                written += self._consolidate_writeback(result, stamp)
            if real_summary and written == 0 and summary_ids:
                summary = self._consolidate_summary(result, summary_ids, stamp)
                if summary is not None:
                    written += 1
                    result["summary_id"] = summary.get("id")
                    result["summary"] = summary.get("text")
            if written == 0:
                # No real tree/reflection content: never write a placeholder
                # summary and never mark the source entries.
                result["noop"] = True
            if real_summary and written:
                for entry_id in summary_ids:
                    if self.store.find(entry_id) is not None:
                        self.store.update(entry_id, summarized=True)
                        result["marked"] += 1
            narrative_report = self._apply_narrative(stamp)
            if narrative_report is not None:
                result["narrative"] = narrative_report
            result["written"] = written
            self._bump("consolidate_writes", written)
            self._bump("consolidate_runs")
            self._audit_write("consolidate", result.get("summary_id") or "",
                              "consolidate",
                              "written=%d marked=%d" % (result["written"],
                                                        result["marked"]))
            self._flush_stats()
            self._write_snapshot_safe()
            return result
        finally:
            gated_mod.GATED_ENABLED = previous["gated"]
            tree_mod.TREE_ENABLED = previous["tree"]
            reflection_mod.REFLECTION_ENABLED = previous["reflection"]
            neighbors_mod.NEIGHBORS_ENABLED = previous["neighbors"]

    def _consolidate_summary(self, result, source_ids, stamp):
        pieces = []
        reflections = result.get("reflections") or []
        if reflections:
            pieces.append(str(reflections[0].get("text") or ""))
        tree_data = result.get("tree") or {}
        if tree_data.get("generated"):
            pieces.append("时间树 L%s 已整理 %d 项" % (
                tree_data.get("level"),
                len(tree_data.get("items") or [])))
        if not pieces:
            pieces.append("已整理 %d 条记忆" % len(source_ids))
        text = "；".join(piece for piece in pieces if piece)[:200]
        if not text:
            return None
        try:
            summary = self.store.add({
                "id": sha12("consolidate" + text + str(stamp)),
                "text": text, "role": "system", "ts": stamp,
                "valid_at": stamp, "importance": 0.6,
                "memory_confidence": 0.8, "memory_source": "consolidate",
                "source": "consolidate", "module": "consolidate",
                "source_ids": list(source_ids)[:20], "scope": "default",
                "previous_versions": []})
        except Exception:
            return None
        return summary

    def _consolidate_writeback(self, result, stamp):
        try:
            from .consolidate import writeback as writeback_mod
        except Exception:
            return 0
        previous = writeback_mod.WRITEBACK_ENABLED
        writeback_mod.WRITEBACK_ENABLED = True
        written = 0
        try:
            if result.get("reflections"):
                outcome = writeback_mod.apply_reflections(self.store,
                                                          result["reflections"])
                written += len(outcome.get("written") or [])
                result["reflections_written"] = outcome
                # Surface source_ids at the top level for CLI/read-only consumers.
                for entry_id in outcome.get("written") or []:
                    entry = self.store.find(entry_id)
                    if not isinstance(entry, dict):
                        continue
                    meta = entry.get("metadata")
                    ids = meta.get("source_ids") if isinstance(meta, dict) else None
                    if isinstance(ids, list) and ids and not entry.get("source_ids"):
                        entry["source_ids"] = [str(x) for x in ids][:20]
            if result.get("neighbors"):
                outcome = writeback_mod.apply_neighbors(self.store,
                                                        result["neighbors"])
                written += int(outcome.get("linked") or 0)
                result["neighbors_written"] = outcome
            tree_data = result.get("tree") or {}
            if tree_data.get("generated"):
                outcome = writeback_mod.write_tree(self.store, tree_data)
                written += int(outcome.get("written") or 0)
                result["tree_written"] = outcome
        except Exception as exc:
            result["writeback_error"] = str(exc)[:100]
        finally:
            writeback_mod.WRITEBACK_ENABLED = previous
        return written

    # -- identity write-back ----------------------------------------------
    def identity_write(self, trigger=None, evidence=None, delta=0.0,
                       entry_id=None, direction=1, step=None, major_event=False):
        """Delegate to identity gate: evidence>=3 or major event, <=0.02/step."""
        result = _identity_write(
            self.store, self.identity_writeback_enabled, self._identity_state,
            trigger=trigger, evidence=evidence, delta=delta, entry_id=entry_id,
            direction=direction, step=step, major_event=major_event,
            now=now_ts(self.now()))
        if result.get("allowed"):
            self._bump("identity_write_count")
            self._audit_write("identity_write", entry_id or "", "identity")
        return result

    # -- indexes / snapshots ---------------------------------------------
    def build_index(self):
        """Build the cue index (entities/place/time/event/id) for CLI checkup."""
        try:
            from .index.cue_index import build_index as _build
            return _build(self.store.entries)
        except Exception:
            return {key: {} for key in _EMPTY_INDEX}

    def graph_links(self):
        """Return {id: [related_ids]} when the graph flag is on."""
        if not self._flag("graph"):
            return {}
        try:
            from .index.graph import build_links
            return build_links(self.store.entries) or {}
        except Exception:
            return {}

    def timeline(self):
        """Read-only dual-temporal timeline: valid_at/invalid_at per entry.

        Old entries written before dual-temporal support have no valid_at and
        are returned with null fields (never back-filled here).
        """
        rows = []
        for entry in self.store.entries:
            if not isinstance(entry, dict):
                continue
            valid_at = entry.get("valid_at")
            invalid_at = entry.get("invalid_at")
            try:
                valid_at = float(valid_at) if valid_at is not None else None
            except Exception:
                valid_at = None
            try:
                invalid_at = float(invalid_at) if invalid_at is not None else None
            except Exception:
                invalid_at = None
            rows.append({"id": str(entry.get("id") or ""),
                         "valid_at": valid_at,
                         "invalid_at": invalid_at,
                         "text": str(entry.get("text") or "")})
        rows.sort(key=lambda row: (row["valid_at"] is None,
                                   row["valid_at"] if row["valid_at"] is not None else 0.0,
                                   row["id"]))
        return rows

    def slots_snapshot(self):
        """Read-only attention-slot budget snapshot (empty when slots are off)."""
        total_budget = 360
        try:
            from .slots.registry import TOTAL_BUDGET_CHARS
            total_budget = int(TOTAL_BUDGET_CHARS)
        except Exception:
            pass
        registry = self.slot_registry if self._flag("slots") else None
        if registry is None:
            return {"enabled": False, "slots": [], "total_chars": 0,
                    "total_budget": total_budget}
        slots = []
        for slot in getattr(registry, "slots", []) or []:
            items = []
            for item in getattr(slot, "items", []) or []:
                if isinstance(item, dict):
                    items.append({"id": str(item.get("id") or ""),
                                  "text": str(item.get("text")
                                              or item.get("content") or "")[:120]})
                else:
                    items.append({"id": "", "text": str(item)[:120]})
            chars = 0
            try:
                chars = int(slot.chars())
            except Exception:
                chars = sum(len(item["text"]) for item in items)
            slots.append({"id": str(getattr(slot, "slot_id", "")),
                          "kind": str(getattr(slot, "kind", "")),
                          "items": items,
                          "chars": chars,
                          "budget": int(getattr(slot, "budget_chars", 0) or 0)})
        try:
            total_chars = int(registry.total_chars() or 0)
        except Exception:
            total_chars = sum(slot["chars"] for slot in slots)
        return {"enabled": True, "slots": slots, "total_chars": total_chars,
                "total_budget": total_budget}

    def dedupe_actions(self):
        """Read-only write/dedupe action counters (from persisted store stats)."""
        counts = self.store.stats()
        def _count(key):
            try:
                return int(counts.get(key, 0) or 0)
            except Exception:
                return 0
        return {"add": _count("dedupe_add_count"),
                "merge": (_count("dedupe_merge_count")
                          + _count("dedupe_exact_merge_count")),
                "update": _count("dedupe_update_count"),
                "flag": _count("dedupe_flag_count"),
                "noop": _count("dedupe_noop_count")}

    def graph_snapshot(self, limit=12):
        """Read-only weighted link graph (edges + node count) for the UI."""
        try:
            limit = max(1, min(200, int(limit or 12)))
        except Exception:
            limit = 12
        entries = [entry for entry in self.store.entries
                   if isinstance(entry, dict) and str(entry.get("id") or "")]
        by_id = {str(entry.get("id") or ""): entry for entry in entries}
        if not by_id:
            return {"edges": [], "nodes": 0, "entries": 0, "total_edges": 0}
        try:
            from .index import graph as graph_mod
            links = graph_mod.build_links(entries) or {}
        except Exception:
            links = {}
        seen = set()
        edges = []
        for source, targets in links.items():
            if source not in by_id:
                continue
            for target in targets or []:
                target = str(target or "")
                if target not in by_id or target == source:
                    continue
                key = (source, target) if source <= target else (target, source)
                if key in seen:
                    continue
                seen.add(key)
                weight = 0.0
                try:
                    weight = float(graph_mod.pair_score(by_id[source],
                                                        by_id[target]) or 0.0)
                except Exception:
                    weight = 0.0
                edges.append({"from": source, "to": target,
                              "weight": round(weight, 4)})
        edges.sort(key=lambda edge: (-edge["weight"], edge["from"], edge["to"]))
        nodes = set()
        for edge in edges:
            nodes.add(edge["from"])
            nodes.add(edge["to"])
        return {"edges": edges[:limit], "nodes": len(nodes),
                "entries": len(by_id), "total_edges": len(edges)}

    def _stats_snapshot(self, candidates=None):
        counts = self.store.stats()
        order = candidates if candidates is not None else self._eviction_rows()
        active = [t for t in self._threads.values()
                  if isinstance(t, dict) and t.get("status") == "active"]
        return {
            "entries": len(self.store.entries),
            "pinned": sum(1 for x in self.store.entries
                          if isinstance(x, dict) and x.get("pin")),
            "tombstones": len(self.store.tombstones),
            "by_module": self._by_module(),
            "recalls": counts.get("recall_count", 0),
            "dedupe_merges": counts.get("dedupe_merge_count", 0),
            "evict_candidates": len(order),
            "identity_writes": counts.get("identity_write_count", 0),
            "relay_cards": counts.get("relay_count", 0),
            "threads_active": len(active),
            "source_filtered": counts.get("source_filtered", 0),
            "tier_high": counts.get("tier_high", 0),
            "tier_mid": counts.get("tier_mid", 0),
            "tier_low": counts.get("tier_low", 0),
            "slots_admitted": counts.get("slots_admitted", 0),
            "slots_evicted": counts.get("slots_evicted", 0),
            "delete_propagation": counts.get("delete_propagation", 0),
            "security_rejected": counts.get("security_rejected", 0),
            "audit_writes": counts.get("audit_writes", 0),
            "rate_limited": counts.get("rate_limited", 0),
            "permissions_denied": counts.get("permissions_denied", 0),
            "compress_runs": counts.get("compress_runs", 0),
            "media_attached": counts.get("media_attached", 0),
            "notes_written": counts.get("notes_written", 0),
            "notes_linked": counts.get("notes_linked", 0),
            "entity_boost_hits": counts.get("entity_boost_hits", 0),
            "graph_edges": counts.get("graph_edges", 0),
            "ppr_expansions": counts.get("ppr_expansions", 0),
            "tiering_archived": counts.get("tiering_archived", 0),
            "retrieval_practice": counts.get("retrieval_practice", 0),
            "inhibition_applied": counts.get("inhibition_applied", 0),
            "boundary_switches": counts.get("boundary_switches", 0),
            "ledger_writes": counts.get("ledger_writes", 0),
            "consolidate_runs": counts.get("consolidate_runs", 0),
            "consolidate_writes": counts.get("consolidate_writes", 0),
            "evictions_applied": counts.get("evictions_applied", 0),
            "evictions_restored": counts.get("evictions_restored", 0),
            "evict_tombstones": counts.get("evict_tombstones", 0),
            "deletion_audits": counts.get("deletion_audits", 0),
            "consistency_conflicts": counts.get("consistency_conflicts", 0),
            "adaptive_scored": counts.get("adaptive_scored", 0),
            "source_consistency_ranked": counts.get("source_consistency_ranked", 0),
            "source_consistency_conflicts": counts.get("source_consistency_conflicts", 0),
            "narrative_writes": counts.get("narrative_writes", 0),
            "by_scope": self._by_scope(),
        }

    def _by_scope(self):
        out = {}
        for entry in self.store.entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("scope") or "default")
            out[key] = out.get(key, 0) + 1
        return out

    def _by_module(self):
        out = {}
        for entry in self.store.entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("module") or entry.get("memory_source") or "unknown")
            out[key] = out.get(key, 0) + 1
        return out

    def _eviction_rows(self):
        total = max(1, len(self.store.entries))
        rows = []
        for position, entry in enumerate(self.store.entries):
            if not isinstance(entry, dict):
                continue
            redundancy = 1.0 if any(
                other is not entry
                and str(other.get("text") or "") == str(entry.get("text") or "")
                for other in self.store.entries) else 0.0
            rows.append({"entry": entry,
                         "score": eviction_score(entry, now=now_ts(self.now()),
                                                 position=position / float(total),
                                                 redundancy=redundancy),
                         "id": str(entry.get("id") or "")})
        return eviction_order(rows)

    def monitor(self):
        """Read-only module health snapshot (no defaults/behaviour change)."""
        return self._stats_snapshot()

    def eviction_snapshot(self, now=None):
        if not self.eviction_readonly:
            return {"enabled": False, "candidates": [], "deleted": 0}
        report = self.tick(now=now)
        report.update({"enabled": True, "readonly": True})
        return report

    def memory_points_snapshot(self):
        """Read-only memory-point projection (stored flag, else computed live).

        Legacy entries written before the memory_point field existed are gated
        on the fly with is_memory_point(value or importance, importance,
        self_relevance) and marked projected=true. Nothing is written back to
        the store; this is projection only.
        """
        rows = []
        for entry in self.store.entries:
            if not isinstance(entry, dict):
                continue
            flag = entry.get("memory_point")
            projected = False
            if isinstance(flag, bool):
                is_point = flag
            else:
                try:
                    raw_value = float(entry.get("value") or 0.0)
                except Exception:
                    raw_value = 0.0
                try:
                    importance = float(entry.get("importance") or 0.0)
                except Exception:
                    importance = 0.0
                try:
                    self_relevance = float(entry.get("self_relevance") or 0.0)
                except Exception:
                    self_relevance = 0.0
                is_point = bool(is_memory_point(raw_value or importance,
                                                importance, self_relevance))
                projected = True
            if not is_point:
                continue
            try:
                value = round(float(entry.get("value") or 0.0), 6)
            except Exception:
                value = 0.0
            if projected and value == 0.0:
                try:
                    value = round(float(entry.get("importance") or 0.0), 6)
                except Exception:
                    value = 0.0
            row = {"id": str(entry.get("id") or ""),
                   "text": str(entry.get("text") or ""),
                   "value": value,
                   "importance": round(float(entry.get("importance") or 0.0), 6),
                   "self_relevance": round(
                       float(entry.get("self_relevance") or 0.0), 6),
                   "ts": float(entry.get("ts") or 0.0),
                   "scope": str(entry.get("scope") or "default")}
            if projected:
                row["projected"] = True
            rows.append(row)
        rows.sort(key=lambda row: (-row["value"], -row["ts"], row["id"]))
        return rows

    def index_snapshot(self):
        """Real cue-index projection: entities/place/time_coarse/event_name counts."""
        try:
            index = self.build_index()
        except Exception:
            index = {}
        projection = {}
        for key in ("entities", "place", "time_coarse", "event_name"):
            bucket = index.get(key) if isinstance(index, dict) else None
            try:
                projection[key] = len(bucket) if isinstance(bucket, dict) else 0
            except Exception:
                projection[key] = 0
        return projection

    def loops_snapshot(self):
        """Read-only projection of the seven memory big loops A-G for the UI.

        Each loop is {id, name, brain, modules: [flags], active, items: counts,
        small_loops: [{from, to, name, active}]}. active is True when any small
        loop is active; built-in capability nodes (store/index/recall/scores)
        are always active, optional mechanisms follow their engine flag.
        items are counters/totals projected from the existing store, flags,
        slots, graph and narrative state. Pure read: no algorithm, no writes.
        """
        try:
            flags = dict(self.flags or {})
            entries = [e for e in self.store.entries if isinstance(e, dict)]
            stats = self.store.stats() or {}
            tombstones = len(self.store.tombstones)
            slot_info = self.slots_snapshot()
            slots = [s for s in (slot_info.get("slots") or [])
                     if isinstance(s, dict)]
            index = self.build_index()
            identity_rows = [e for e in entries if is_identity(e)]
            narrative_version = 0
            notes = 0
            summaries = 0
            for row in entries:
                try:
                    narrative_version = max(
                        narrative_version,
                        int(row.get("identity_narrative_version") or 0))
                except Exception:
                    pass
                meta = row.get("metadata")
                if isinstance(meta, dict) and meta.get("note"):
                    notes += 1
                if (str(row.get("role") or "") == "system"
                        or str(row.get("source") or "") in _SUMMARY_SOURCES
                        or row.get("consolidated")):
                    summaries += 1
            threads_active = sum(
                1 for card in self._threads.values()
                if isinstance(card, dict) and card.get("status") == "active")
            slot_items = sum(len(s.get("items") or []) for s in slots)

            def count(key):
                try:
                    return int(stats.get(key, 0) or 0)
                except Exception:
                    return 0

            def small(spec):
                out = []
                for name, source, target, base in spec:
                    out.append({"from": source, "to": target, "name": name,
                                "active": bool(flags.get(name, False))
                                if base is None else bool(base)})
                return out

            specs = (
                ("A", "编码-存储", "海马 ↔ 新皮层", (
                    ("store", "remember", "entries", True),
                    ("index", "text", "cue_index", True),
                    ("dedupe", "remember", "store", None),
                    ("provenance", "remember", "source_tag", None),
                    ("notes", "remember", "metadata.note", None),
                    ("notes_link", "remember", "links", None),
                    ("media", "remember", "metadata.media", None),
                    ("consistency", "memory", "conflict_flag", None),
                ), {"entries": len(entries),
                    "pinned": sum(1 for e in entries if e.get("pin")),
                    "notes": notes,
                    "dedupe_merges": count("dedupe_merge_count"),
                    "indexed": len(index.get("id") or {})}),
                ("B", "提取-强化", "前额叶 ↔ 海马", (
                    ("recall", "query", "ranked", True),
                    ("embedding", "text", "semantic", None),
                    ("three_channel", "candidates", "fusion", None),
                    ("bm25", "query", "lexical", None),
                    ("bm25_multi", "query", "lexical_multi", None),
                    ("ppr", "seeds", "graph_expand", None),
                    ("graph", "entries", "edges", None),
                    ("mmr", "ranked", "diverse", None),
                    ("complexity", "query", "budget", None),
                    ("constraints", "query", "hint", None),
                    ("tiering", "ranked", "tier", None),
                    ("entity_boost", "entities", "score", None),
                    ("inhibition", "losers", "suppressed", None),
                    ("retrieval_practice", "hits", "stability", None),
                    ("source_consistency", "candidates", "source_rank", None),
                ), {"recalls": count("recall_count"),
                    "tier_high": count("tier_high"),
                    "tier_mid": count("tier_mid"),
                    "tier_low": count("tier_low"),
                    "graph_edges": count("graph_edges"),
                    "ppr_expansions": count("ppr_expansions"),
                    "retrieval_practice": count("retrieval_practice"),
                    "inhibition_applied": count("inhibition_applied")}),
                ("C", "巩固-重构", "海马-皮层、睡眠", (
                    ("consolidate_gated", "consolidate", "gate", None),
                    ("consolidate_tree", "events", "summary_tree", None),
                    ("consolidate_reflection", "events", "reflection", None),
                    ("consolidate_neighbors", "entry", "links", None),
                    ("consolidate_writeback", "summary", "store", None),
                    ("compress", "output", "summary", None),
                    ("narrative", "C", "F", None),
                ), {"consolidate_runs": count("consolidate_runs"),
                    "consolidate_writes": count("consolidate_writes"),
                    "summaries": summaries,
                    "narrative_writes": count("narrative_writes"),
                    "narrative_version": narrative_version}),
                ("D", "遗忘-抑制", "前扣带 ↔ 基底节", (
                    ("eviction_score", "tick", "scores", True),
                    ("eviction_readonly", "tick", "report", None),
                    ("heat", "entry", "heat", None),
                    ("consequence", "entry", "consequence", None),
                    ("adaptive_evict", "tick", "score", None),
                    ("tiering_exec", "tick", "archived", None),
                    ("apply_evictions", "tick", "soft_delete", None),
                    ("deletion_audit", "forget", "audit", None),
                ), {"entries": len(entries),
                    "tombstones": tombstones,
                    "evictions_applied": count("evictions_applied"),
                    "evictions_restored": count("evictions_restored"),
                    "evict_tombstones": count("evict_tombstones"),
                    "adaptive_scored": count("adaptive_scored")}),
                ("E", "注意-选择", "丘脑 ↔ 顶叶", (
                    ("slots", "context", "registry", None),
                    ("boundary", "messages", "switch", None),
                    ("due_hints", "loops", "hint", None),
                ), {"slots": len(slots),
                    "slot_items": slot_items,
                    "slot_chars": int(slot_info.get("total_chars") or 0),
                    "slot_budget": int(slot_info.get("total_budget") or 0),
                    "boundary_switches": count("boundary_switches")}),
                ("F", "社会-自我", "默认网络 / 内侧前额叶", (
                    ("identity_read", "store", "identity", True),
                    ("identity", "entries", "snapshot", None),
                    ("identity_writeback", "evidence", "identity", None),
                    ("relay", "identity", "card", None),
                    ("thread", "turns", "thread_card", None),
                    ("ledger", "relation", "ledger", None),
                    ("narrative", "consolidate", "identity_narrative", None),
                ), {"identity_entries": len(identity_rows),
                    "relay_cards": count("relay_count"),
                    "threads_active": threads_active,
                    "ledger_writes": count("ledger_writes"),
                    "narrative_writes": count("narrative_writes"),
                    "narrative_version": narrative_version}),
                ("G", "安全-监控", "岛叶 / 前扣带", (
                    ("tombstone", "delete", "tombstone", True),
                    ("security", "write", "reject", None),
                    ("source_filter", "recall", "filter", None),
                    ("temporal_filter", "recall", "validity", None),
                    ("audit", "write_delete", "audit_jsonl", None),
                    ("rate_limit", "scope", "window", None),
                    ("permissions", "scope", "gate", None),
                    ("deletion_audit", "forget", "audit", None),
                ), {"security_rejected": count("security_rejected"),
                    "source_filtered": count("source_filtered"),
                    "audit_writes": count("audit_writes"),
                    "rate_limited": count("rate_limited"),
                    "permissions_denied": count("permissions_denied"),
                    "deletion_audits": count("deletion_audits"),
                    "tombstones": tombstones}),
            )
            loops = []
            for loop_id, name, brain, spec, items in specs:
                small_loops = small(spec)
                modules = []
                for row in spec:
                    flag = row[0]
                    if flag in FLAGS and flag not in modules:
                        modules.append(flag)
                loops.append({
                    "id": loop_id, "name": name, "brain": brain,
                    "modules": modules,
                    "active": any(item["active"] for item in small_loops),
                    "items": dict(items),
                    "small_loops": small_loops})
            return loops
        except Exception:
            return []
