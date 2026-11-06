# -*- coding: utf-8 -*-
"""All memory-layer thresholds/defaults in one place."""
from __future__ import annotations

SCHEMA_VERSION = 1
MAX_VERSIONS = 8
TOMBSTONE_LIMIT = 100
DEFAULT_BUDGET = 3
MAX_BUDGET = 5

# recall fusion / tiers (M2). [engineering] no fitting source; .50/.30/.10/.10
# is the single口径 now (the old "0.6/0.4" comment and the task's .4/.3/.2/.1
# are retired, code unchanged).
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
# [engineering] product definition, no behavioural data behind the weights.
VALUE_BASE = 0.20
VALUE_W_INTENSITY = 0.30
VALUE_W_VALENCE = 0.20
VALUE_W_SELF = 0.15
VALUE_W_MAINLINE = 0.15
VALUE_W_ROUTINE = 0.20

# eviction weights (read-only score) [engineering]
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
MEMORY_POINT_MIN_VALUE = 0.60   # [engineering]
MEMORY_POINT_MIN_SELF = 0.45
MEMORY_POINT_MIN_IMPORTANCE = 0.75

# engine wiring knobs (all read by MemoryEngine only)
RATE_LIMIT_PER_MIN = 30
COMPRESS_MAX_CHARS = 200
AUDIT_TAIL = 50
COOC_MAX_ENTRIES = 400
# after-turn auto consolidation: every N successful remember() calls
CONSOLIDATE_AUTO_TURNS = 10

# recall -> affect feedback (task-218): a recalled memory nudges the live
# affect a little. Engine owns the state; recall/feedback.py owns the guards.
# [engineering] gain / step / cooldown / floor are hand-set (see PAPER-MAP.md).
FEEDBACK_MAX_STEP = 0.02    # per-turn cap on |delta valence| and |delta arousal|
FEEDBACK_GAIN = 0.50        # share of (recalled - current) that flows back
FEEDBACK_COOLDOWN = 1800.0  # same entry: no second feedback inside 30 minutes
FEEDBACK_NEG_FLOOR = -0.40  # at/below this valence a further negative pull is dropped


# ---------------------------------------------------------------- spatial ranking
# distance = sum(w_axis * d_axis) over the five memory axes.
# Equal weights are a NEUTRAL engineering default: no axis is privileged and
# nothing here was fitted to data. A store overrides them with
# flags["spatial_weights"] or BIOCORE_SPATIAL_WEIGHTS (JSON).
SPATIAL_WEIGHTS = {"semantic": 0.20, "time": 0.20, "affect": 0.20,
                   "social": 0.20, "activation": 0.20}

# Time is numeric only: ts and query_ts are compared, text is never scanned
# for date or cue words. There is no temporal word list anywhere in the core.

# spatial_select (default OFF) is the candidate stage in front of the ordinary
# scoring fusion: the WHOLE store is ranked by weighted five-axis distance and
# only the nearest SPATIAL_SELECT_DEPTH entries are handed to the existing
# scorer. This is the usual two-stage shape of approximate/exact hybrid search
# (Malkov & Yashunin 2018, HNSW: a bounded candidate list, then exact scoring;
# VLDB 2025 hybrid querying on vectors: the vector stage proposes candidates,
# the structured conditions still decide). 20 is an engineering candidate cap,
# not a fitted constant; a store can override it with flags["spatial_depth"]
# or BIOCORE_SPATIAL_DEPTH.
SPATIAL_SELECT_DEPTH = 20

# spatial_index (default ON): above SPATIAL_INDEX_THRESHOLD entries the semantic
# axis is bucketed by the sign pattern of the first SPATIAL_INDEX_PREFIX dims
# (LSH, Indyk & Motwani 1998). The bucket is a PRUNING structure, not an
# approximation: every bucket keeps a unit centroid and a radius, and
# |x - t| >= |c - t| - |x - c| with 1 - cos = |x - t|^2 / 2 for unit vectors
# lower-bounds the semantic distance of every member, so a bucket whose bound
# cannot beat the k-th best is skipped safely and the bucketed answer stays
# identical to the exact one. Below the threshold the exact traversal runs.
SPATIAL_INDEX_THRESHOLD = 5000
SPATIAL_INDEX_PREFIX = 8

# spatial_standardize (default ON): each axis distance is divided by the
# store's own standard deviation for that axis (Mahalanobis 1936), so an axis
# with a wide spread cannot outvote a narrow one just because of its units.
# An axis whose distances do not vary (std < SPATIAL_DEAD_AXIS_STD) is dead
# and gets weight 0 -- only dimensions that actually vary carry information
# (Kriegeskorte & Kievit 2013). Below SPATIAL_STANDARDIZE_MIN_SAMPLE entries
# the statistics are not trusted and the equal-weight raw sum is kept.
SPATIAL_STANDARDIZE_MIN_SAMPLE = 30
SPATIAL_DEAD_AXIS_STD = 0.01

# spatial_event_expand (default OFF): event segmentation (Zacks 2007) cuts a
# session into segments at change points -- a gap longer than the window, a
# different topic, or a different set of people. The coordinates stay per
# entry; the segment is only an extra dimension a recall can widen by.
EVENT_WINDOW_SECONDS = 600

# near_dup_time (default ON): a changed fact arrives as a near duplicate of the
# stored memory. Plus topic/entity overlap, plus different numbers/dates, marks
# the older one superseded. No keyword list, no version key.
# The threshold belongs to the MEASURE, not to the mechanism: a cosine of 0.9
# and a Jaccard of 0.75 are not the same test, so one number cannot serve both.
# Cosine: 0.90 (AGM-conservative -- a missed mark is cheaper than a wrong one).
# Jaccard: 0.75 (a Chinese paraphrase pair measures ~0.79; 0.85 would miss it).
# A store overrides each with flags["near_dup_cosine"] / ["near_dup_jaccard"]
# or BIOCORE_NEAR_DUP_COSINE / BIOCORE_NEAR_DUP_JACCARD.
NEAR_DUP_COSINE = 0.90
NEAR_DUP_JACCARD = 0.75

# point_expand (default OFF): hits first, then the neighbours of each hit
# inside its own event segment. POINT_EXPAND_RADIUS is how far +/- the hit
# grows (1 = one memory either side); POINT_EXPAND_TOKENS is the block budget.
POINT_EXPAND_RADIUS = 1
POINT_EXPAND_TOKENS = 1500

# spatial_cover_select (default OFF): choose k from the pool by spread, not by
# rank. MMR's redundancy term is the five-axis space distance; lambda 0.3
# balances relevance against coverage. The pool is the existing top-N.
SPATIAL_COVER_LAMBDA = 0.3
SPATIAL_COVER_POOL = 20



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
    # arXiv 2610.36308: same-key version resolution (default ON; the old
    # behaviour is "nothing extracted, nothing marked, nothing filtered").
    "memory_versioning": True,
    # Howard & Kahana 2002: rank by the weighted sum of the five axes
    # (default ON; OFF falls back to the old lexicographic order_key).
    "spatial_weighted": True,
    # Full-store candidate selection before the scoring fusion (default OFF;
    # OFF keeps the old recall path byte for byte -- nothing is pre-selected).
    "spatial_select": False,
    # Semantic sign-pattern bucketing above SPATIAL_INDEX_THRESHOLD entries
    # (default ON: it is exact, so it can only save work, never change a row).
    "spatial_index": True,
    # Per-axis standardisation + dead-axis removal (default ON; OFF is the
    # equal-weight raw sum, byte for byte the old ordering).
    "spatial_standardize": True,
    # Usage feedback + axis-weight learning (both default ON; OFF keeps the
    # equal 0.2 weights and writes no feedback rows).
    "spatial_feedback": True,
    "spatial_learn": True,
    # Event-expanded recall: a hit also brings its segment neighbours.
    "spatial_event_expand": False,
    # Near-duplicate, newer wins (default ON; OFF marks nothing at all).
    "near_dup_time": True,
    # Date prefix on injected memories (default ON; OFF is the old text).
    "memory_date_prefix": True,
    # Recall by event segment (default OFF; OFF is the per-entry path).
    "segment_recall": False,
    # Point-expand: hits first, then their neighbours (default OFF).
    "point_expand": False,
    # point_expand_rerank: expand, then rerank the pool (ON) / inject after (OFF).
    "point_expand_rerank": True,
    # Coverage select: pick k by five-axis spread instead of rank (default OFF).
    "spatial_cover_select": False,


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
    "mood_recall": False,
    "affect_encoding": False,
    "memory_feedback": False,  # task-218: recalled affect nudges the live affect
    "preference_drift": False,  # task-219: repeated topics drift value_order weights
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
