# -*- coding: utf-8 -*-
"""Seven-dimension event vector (host-neutral; no I/O, no prompt)."""
from __future__ import annotations
from ..core.types import EventVector
from ..core.util import clamp01

DIMENSIONS = ("intensity", "self_relevance", "schema_conflict",
              "relation_weight", "novelty", "unresolved", "repetition")


def extract_vector(meta=None, affect=None) -> EventVector:
    """Build the seven-dim event vector from metadata and an L1 affect snapshot.

    Missing values default to neutral (0.0); all dims are clamped to [0, 1].
    Deterministic and pure: no host access, no LLM, no writes.
    """
    m = meta if isinstance(meta, dict) else {}
    a = affect if isinstance(affect, dict) else {}
    return EventVector(
        intensity=clamp01(m.get("intensity", a.get("intensity", 0.0))),
        self_relevance=clamp01(m.get("self_relevance",
                                   m.get("self_defining", a.get("self_relevance", 0.0)))),
        schema_conflict=clamp01(m.get("schema_conflict",
                                     m.get("conflict", a.get("schema_conflict", 0.0)))),
        relation_weight=clamp01(m.get("relation_weight",
                                     a.get("relation_weight", a.get("trust", 0.0)))),
        novelty=clamp01(m.get("novelty", a.get("novelty", 0.0))),
        unresolved=clamp01(m.get("unresolved", a.get("unresolved", 0.0))),
        repetition=clamp01(m.get("repetition", a.get("repetition", 0.0))),
    )


def vector_dict(meta=None, affect=None) -> dict:
    """Return extract_vector() as a plain dict (JSON-friendly)."""
    return extract_vector(meta, affect).as_dict()

def value_score(meta=None, affect=None) -> float:
    """Deterministic memory-value score (trust is deliberately excluded).

    value = BASE + W_I*intensity + W_V*|valence| + W_S*self_relevance
            + W_M*mainline - W_R*routine
    Missing fields default to neutral; result clamped to [0, 1].
    """
    from ..core.config import (VALUE_BASE, VALUE_W_INTENSITY, VALUE_W_VALENCE,
                               VALUE_W_SELF, VALUE_W_MAINLINE, VALUE_W_ROUTINE)
    m = meta if isinstance(meta, dict) else {}
    a = affect if isinstance(affect, dict) else {}
    vec = extract_vector(m, a)
    try:
        valence = abs(float(m.get("valence", a.get("valence", 0.0)) or 0.0))
    except Exception:
        valence = 0.0
    mainline = m.get("mainline", a.get("goals") and 0.5 or 0.0)
    try:
        mainline = float(mainline or 0.0)
    except Exception:
        mainline = 0.0
    routine = m.get("routine", 0.0)
    try:
        routine = float(routine or 0.0)
    except Exception:
        routine = 0.0
    value = (VALUE_BASE
             + VALUE_W_INTENSITY * vec.intensity
             + VALUE_W_VALENCE * clamp01(valence)
             + VALUE_W_SELF * vec.self_relevance
             + VALUE_W_MAINLINE * clamp01(mainline)
             - VALUE_W_ROUTINE * clamp01(routine))
    return round(clamp01(value), 6)
