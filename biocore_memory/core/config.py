# -*- coding: utf-8 -*-
"""All memory-layer thresholds/defaults in one place."""
from __future__ import annotations

SCHEMA_VERSION = 1
MAX_VERSIONS = 8
TOMBSTONE_LIMIT = 100
DEFAULT_BUDGET = 3
MAX_BUDGET = 5

# recall fusion / tiers (M2)
CUE_WEIGHT = 0.50
SEM_WEIGHT = 0.30
IMPORTANCE_WEIGHT = 0.10
TIME_BONUS = 0.10
HIGH_TIER = 0.55
MID_TIER = 0.35

# source credibility gate (separate from importance)
SOURCE_MIN_CONFIDENCE = 0.55
SOURCE_CONFIDENCE_DEFAULT = 0.70

# memory value formula (deterministic; trust is NOT part of value)
VALUE_BASE = 0.20
VALUE_W_INTENSITY = 0.30
VALUE_W_VALENCE = 0.20
VALUE_W_SELF = 0.15
VALUE_W_MAINLINE = 0.15
VALUE_W_ROUTINE = 0.20

# eviction weights (read-only score)
EVICT_W_SALIENCE = 0.30
EVICT_W_POSITION = 0.20
EVICT_W_REDUNDANCY = 0.20
EVICT_W_CONFIDENCE = 0.15
EVICT_W_STALENESS = 0.15

# identity write-back gate
SAME_DIRECTION_MIN = 3
MAX_STEP = 0.02
MAJOR_EVENT_STEP = 0.02

# thread card
THREAD_TTL = 21600.0
THREAD_LIMIT = 3

# memory-point gate (OR): value >= MIN_VALUE or importance >= MIN_IMPORTANCE or self >= MIN_SELF
# (event centrality / emotional intensity; self-reference effect; engineering thresholds)
MEMORY_POINT_MIN_VALUE = 0.60
MEMORY_POINT_MIN_SELF = 0.45
MEMORY_POINT_MIN_IMPORTANCE = 0.75

# engine wiring knobs (all read by MemoryEngine only)
RATE_LIMIT_PER_MIN = 30
COMPRESS_MAX_CHARS = 200
AUDIT_TAIL = 50
COOC_MAX_ENTRIES = 400
# after-turn auto consolidation: every N successful remember() calls
CONSOLIDATE_AUTO_TURNS = 10


# Per-mechanism flags: safety/read-path filters default ON; every optional
# mechanism defaults OFF and must keep the old code path when disabled.
# A flags.json in the data directory overrides these booleans at engine start
# (and MemoryEngine.set_flags(..., persist=True) rewrites it).
FLAGS = {
    # safety / read-path (default ON)
    # GA-03: keep engine default ON. DSH private mode disables it per-store via
    # <dsh store>/flags.json; the shared engine must not be relaxed globally.
    "security": True,          # store/security.should_reject before write
    "provenance": True,        # provenance hash tag + chained tombstones
    "source_filter": True,     # low-confidence candidates are counted/dropped
    "temporal_filter": True,   # honour valid_at/invalid_at on recall
    "dedupe": True,            # remember-side L0-L3 dedupe
    "relay": True,             # relay card
    "thread": True,            # thread card / TTL expiry
    "embedding": True,         # optional embedding provider
    # attention / model features (default OFF)
    "slots": False,
    "boundary": False,         # slots/boundary.py event-boundary switching
    "three_channel": False,
    "eviction_readonly": False,
    "identity": False,
    "identity_writeback": False,
    "due_hints": False,
    # recall extensions (default OFF)
    "bm25": False,
    "bm25_multi": False,
    "ppr": False,
    "mmr": False,
    "complexity": False,
    "constraints": False,
    "tiering": False,
    "entity_boost": False,
    "inhibition": False,
    "retrieval_practice": False,
    "compress": False,         # output-only summary, never mutates the store
    "source_consistency": False,  # source-rank marking/downweight on recall
    # eviction extension modules (default OFF)
    "heat": False,
    "consequence": False,
    "tiering_exec": False,
    "apply_evictions": False,  # tick() may really soft-delete archived entries
    "deletion_audit": False,   # derived-data coverage audit after forget()
    "adaptive_evict": False,   # adaptive_score replaces the tick eviction score

    # write-path extensions (default OFF)
    "consistency": False,      # old/new fact conflict annotation on remember
    "rate_limit": False,
    "audit": False,
    "permissions": False,
    "notes": False,
    "media": False,
    "notes_link": False,
    "ledger": False,
    # index / graph
    "graph": False,
    "cue_writeback": True,      # store cue_index fields on each new entry (index-only, no recall change)
    # consolidation modules (default OFF)
    "consolidate_auto": False,  # after-turn auto consolidate every CONSOLIDATE_AUTO_TURNS remembers
    "consolidate_gated": False,
    "consolidate_tree": False,
    "consolidate_reflection": False,
    "consolidate_neighbors": False,
    "consolidate_writeback": False,
    "narrative": False,        # identity narrative update at consolidate end
}
