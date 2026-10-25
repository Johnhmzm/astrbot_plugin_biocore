# -*- coding: utf-8 -*-
"""AstrBot BioCore plugin: a standalone biological emotion layer.

Independent copy. It does not import the Desktop companion project.
First run: read the current AstrBot persona, compile it once with the current
provider into a numeric profile, store it under this plugin's data dir.
Then on every LLM request: append a compact intent, on response: feedback.
"""
from __future__ import annotations

import json
import math
import re
import os
import shutil
import asyncio
import base64
import io
import http.client
import socket
import ssl
import subprocess
import time
import types
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image, Reply, Record
from astrbot.api.provider import ProviderRequest, LLMResponse
from astrbot.api.star import Context, Star, register

try:
    from . import interpretation
except Exception:
    import interpretation

try:
    from . import memory_meta
except Exception:
    import memory_meta

try:
    from . import relationship_meta
except Exception:
    import relationship_meta

PLUGIN_DIR = Path(__file__).resolve().parent
_LEGACY_DATA_DIR = PLUGIN_DIR / "data"
_BASE_DATA_DIR = PLUGIN_DIR.parents[1] if len(PLUGIN_DIR.parents) > 1 else PLUGIN_DIR
_PERSIST_DATA_DIR = _BASE_DATA_DIR / "plugin_data" / "astrbot_plugin_biocore_standalone"


def _init_data_dir() -> Path:
    target = Path(os.getenv("BIOCORE_DATA_DIR", str(_PERSIST_DATA_DIR)))
    target.mkdir(parents=True, exist_ok=True)
    try:
        if _LEGACY_DATA_DIR.exists() and target.resolve() != _LEGACY_DATA_DIR.resolve():
            for src in _LEGACY_DATA_DIR.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(_LEGACY_DATA_DIR)
                dst = target / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copy2(src, dst)
    except Exception:
        pass
    return target


DATA_DIR = _init_data_dir()
PROFILE_PATH = DATA_DIR / "persona_profile.json"
API_CONFIG_PATH = DATA_DIR / "api_config.json"
STATE_DIR = DATA_DIR / "states"
MEMORY_DIR = DATA_DIR / "memory"
# Local image service paths/port are configured through _conf_schema.json.
# There are no machine-specific fallback paths baked into the plugin.
IMAGE_CACHE_PATH = DATA_DIR / "image_cache.json"
EVENT_ARCHIVE_DIR = DATA_DIR / "archives"
EVENT_SESSION_DIR = EVENT_ARCHIVE_DIR / "sessions"
EVENT_ARCHIVE_PATH = EVENT_ARCHIVE_DIR / "events.jsonl"
USER_DIR = DATA_DIR / "users"
SELF_MODEL_PATH = DATA_DIR / "self_model.json"
INSIGHT_ARCHIVE_PATH = EVENT_ARCHIVE_DIR / "insights.jsonl"
EMBED_CACHE = {}

# Memory doc schema version: bumped when entry fields/migrations change.
# Old docs are upgraded lazily on load (additive defaults only).
MEMORY_SCHEMA_VERSION = 2

DEFAULT_PROFILE = {
    "O": 0.62, "C": 0.55, "E": 0.44, "A": 0.42, "N": 0.40,
    "stress_reactivity": 0.45, "recovery_rate": 0.62,
    "social_baseline": 0.44, "energy_baseline": 0.55,
    "curiosity_baseline": 0.60, "safety_baseline": 0.55,
    "da_baseline": 0.55, "oa_baseline": 0.40, "ht_baseline": 0.35,
    "autonomy_gain": 1.0, "contagion_gain": 0.10, "baseline_v": 0.05, "baseline_a": 0.40,
    "learning_rate": 0.06,
}

# Per-function LLM routing: each feature has its own enabled switch and a
# provider choice ("follow_llm" = AstrBot main chat model, or a provider_id).
# Defaults: only the two summary functions are enabled; everything else is
# opt-in. This replaces the single llm_only_reply_summary master switch while
# keeping it readable for legacy migration.
LLM_FUNCTIONS = (
    "persona_compile",
    "event_summary",
    "event_ranking",
    "insight",
    "memory_summary",
    "image_caption",
    # L-T01..L-T12: proposal-only LLM functions, all OFF by default. Each one
    # is routed through _provider_for and its prompt/parser lives in
    # interpretation.py; model output never writes biological state directly.
    "relationship_impression",
    "repair_hint",
    "empathy_hint",
    "pragmatics_hint",
    "tom_probe",
    "diary",
    "relationship_narrative",
    "humor_hint",
)
LLM_FUNCTION_DEFAULTS = {
    "persona_compile": False,
    "event_summary": True,
    "event_ranking": True,
    "insight": False,
    "memory_summary": True,
    "image_caption": False,
    "relationship_impression": False,
    "repair_hint": False,
    "empathy_hint": False,
    "pragmatics_hint": False,
    "tom_probe": False,
    "diary": False,
    "relationship_narrative": False,
    "humor_hint": False,
}
INSIGHT_MIN_NEW_EVENTS = 3
INSIGHT_COOLDOWN_SECONDS = 60 * 60
INSIGHT_FALLBACK_HOURS = 24

LLM_FUNCTION_ALIASES = {
    "persona": "persona_compile",
    "ranking": "event_ranking",
    "caption": "image_caption",
    "summary": "event_summary",
    "impression": "relationship_impression",
    "repair": "repair_hint",
    "empathy": "empathy_hint",
    "pragmatics": "pragmatics_hint",
    "tom": "tom_probe",
    "narrative": "relationship_narrative",
    "humor": "humor_hint",
}

# L-T01..L-T12 cooldowns (seconds); all functions stay OFF by default.
LLM_V2_COOLDOWNS = {
    "relationship_impression": 3600,
    "repair_hint": 900,
    "empathy_hint": 900,
    "pragmatics_hint": 900,
    "tom_probe": 600,
    "diary": 72000,
    "relationship_narrative": 86400,
    "humor_hint": 900,
}

# ACT-R retrieval constants (Anderson & Reder 1999; partial matching per
# Anderson 1994). Keeping them in one named place makes scoring tunable.
ACT_R_DECAY = 0.5
RETRIEVAL_THRESHOLD = 0.25
PARTIAL_MATCH_THRESHOLD = 0.35

# A4 continuity opener: inject "last talk" only when the user returns after a
# break, so the same-session turns and first-ever turns stay untouched.
A4_CONTINUITY_GAP_SECONDS = 600.0
A4_CONTINUITY_MAX_LOOPS = 2

# Zacks et al. (2007) event segmentation: a boundary is predicted by elapsed
# time and by the content change since the previous event in the same session.
EVENT_BOUNDARY_WINDOW_SECONDS = 1800.0
EVENT_BOUNDARY_TIME_WEIGHT = 0.62
EVENT_BOUNDARY_TEXT_WEIGHT = 0.38
EVENT_BOUNDARY_PARENT_THRESHOLD = 0.5

# Gross process model: cost paid by each regulation strategy (0..1 scale,
# distraction pays the highest bill because it leaves the concern unaddressed).
REGULATION_COST = {
    "seek_comfort": 0.003,
    "reappraise": 0.002,
    "suppress": 0.010,
    "avoid": 0.004,
    "express": 0.002,
    "distraction": 0.006,
}

# Mem0 UPDATE matching: an explicit correction ("改成/改为/其实是/更正")
# only updates a memory whose semantic similarity passes this floor; the
# exact-duplicate threshold (0.93) alone is too strict for corrections.
MEMORY_UPDATE_MATCH_THRESHOLD = 0.55

# Event-key identity: normalized keys within this window and above this
# similarity are treated as the same archived event (duplicates are merged).
EVENT_KEY_SIM_THRESHOLD = 0.82
EVENT_DUP_WINDOW_SECONDS = 21600.0

# Cowen & Keltner (2017) prototype space: which EMOTION_SPECTRUM anchors a
# basic emotion label may calibrate from this core's own state history.
SPECTRUM_FAMILY = {
    "joy": ("joy", "amusement", "contentment", "excitement", "pride", "adoration", "admiration"),
    "sadness": ("disappointment", "empathic_pain", "nostalgia", "guilt"),
    "anger": ("anger", "contempt", "disgust"),
    "fear": ("fear", "anxiety", "horror"),
    "loneliness": ("empathic_pain", "disappointment", "nostalgia"),
}

LEX = {
    "sadness": ("难过", "伤心", "委屈", "哭", "失望", "累", "撑不住"),
    "anger": ("生气", "烦", "气死", "骂", "傻逼", "滚", "恶心", "废物", "垃圾", "讨厌", "闭嘴", "没用", "蠢", "去死"),
    "fear": ("怕", "焦虑", "紧张", "担心", "失眠", "慌"),
    "joy": ("开心", "高兴", "喜欢", "好耶", "笑死", "可爱", "谢谢"),
    "loneliness": ("孤独", "一个人", "没人", "空虚"),
}


LEX["sadness"] += ("难受", "委屈", "失落", "低落")
LEX["anger"] += ("烦", "别烦", "闭嘴", "滚", "讨厌", "气人")
LEX["fear"] += ("慌", "不安", "怕", "紧张")
LEX["loneliness"] += ("丢下", "被丢下", "冷落", "忽视", "没人理", "不理我", "抛弃", "一个人", "孤单")


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:32]


def _clip(x, lo=-1.0, hi=1.0):
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return lo


def _memory_entry_id_of(entry) -> str:
    """Stable per-entry id shared by the memory API and the dashboard index."""
    if not isinstance(entry, dict):
        return ""
    eid = str(entry.get("id") or "").strip()
    if eid:
        return eid
    text = str(entry.get("text") or "").strip()
    return _sha256(text[:300])[:12] if text else ""


def _memory_index_rows(memory_dir: Path, *, max_sessions: int = 50,
                       max_entries: int = 200, max_tombstones: int = 20) -> list:
    """Read-only, bounded memory index consumed by the dashboard.

    Only contract fields are exposed. Deleted entries are omitted from the
    entries list and surfaced through tombstones (soft deletes keep a
    tombstone matching the hard-delete shape). Old entries without the new
    metadata keep neutral values instead of failing.
    """
    sessions = []
    try:
        files = sorted(Path(memory_dir).glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        files = []
    for path in files[:max(1, int(max_sessions))]:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
        rows = []
        soft_deleted = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("deleted"):
                soft_deleted.append(entry)
                continue
            if len(rows) >= max_entries:
                continue
            try:
                ts = round(float(entry.get("ts", 0) or 0), 3)
            except Exception:
                ts = 0.0
            try:
                importance = round(float(entry.get("importance", 0.5) or 0.5), 3)
            except Exception:
                importance = 0.5
            confidence = entry.get("memory_confidence")
            try:
                confidence = round(float(confidence), 4) if confidence is not None else None
            except Exception:
                confidence = None
            destination = entry.get("destination")
            provenance = entry.get("provenance")
            rows.append({
                "id": _memory_entry_id_of(entry),
                "text": str(entry.get("text") or "")[:400],
                "role": str(entry.get("role") or ""),
                "ts": ts,
                "importance": importance,
                "hits": int(entry.get("hits", 0) or 0),
                "memory_source": str(entry.get("memory_source") or "direct"),
                "memory_confidence": confidence,
                "legacy": not bool(entry.get("memory_source")),
                "memory_tier": str(entry.get("memory_tier") or ""),
                "conflict": bool(entry.get("conflict")),
                "last_write_op": str(entry.get("last_write_op") or ""),
                "previous_versions": [str(v)[:400] for v in (entry.get("previous_versions") or [])][-8:],
                "summarized": bool(entry.get("summarized")),
                "destination": dict(destination) if isinstance(destination, dict) else None,
                "provenance": dict(provenance) if isinstance(provenance, dict) else None,
                # Read-only extras for the orb memory-ball layer.
                "encoding_emotion": str(entry.get("encoding_emotion") or ""),
                "last_used": round(float(entry.get("last_used", 0) or 0), 3),
                "scope": str(entry.get("scope") or ""),
                "poison_risk": bool(entry.get("poison_risk")),
                "links": len(entry.get("links") or []),
                "self_defining": bool(entry.get("self_defining")),
                "verification": str((entry.get("verification") or {}).get("status")
                                    or memory_meta.verify_entry(entry).get("status") or "")
            })
        tombstones = []
        for item in (doc.get("tombstones") or [])[-max_tombstones:]:
            if not isinstance(item, dict):
                continue
            try:
                tomb_ts = round(float(item.get("ts", 0) or 0), 3)
            except Exception:
                tomb_ts = 0.0
            tombstones.append({
                "id": str(item.get("id") or ""),
                "ts": tomb_ts,
                "text": str(item.get("text") or "")[:200],
            })
        for entry in soft_deleted[-max_tombstones:]:
            try:
                tomb_ts = round(float(entry.get("deleted_ts") or entry.get("ts", 0) or 0), 3)
            except Exception:
                tomb_ts = 0.0
            tombstones.append({
                "id": _memory_entry_id_of(entry),
                "ts": tomb_ts,
                "text": str(entry.get("text") or "")[:200],
            })
        sessions.append({
            "session": str(path.stem),
            "entries": rows,
            "tombstones": tombstones[-max_tombstones:],
        })
    return sessions


def _relationship_rows(user_dir: Path, *, max_users: int = 50,
                       max_trajectory: int = 40) -> list:
    """Read-only, bounded relationship index consumed by the dashboard."""
    rows = []
    try:
        files = sorted(Path(user_dir).glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        files = []
    for path in files[:max(1, int(max_users))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        try:
            trust = round(float(data.get("trust", 0.5) or 0.5), 4)
        except Exception:
            trust = 0.5
        try:
            interactions = int(data.get("interactions", 0) or 0)
        except Exception:
            interactions = 0
        try:
            last_seen = round(float(data.get("last_seen", 0) or 0), 3)
        except Exception:
            last_seen = 0.0
        rel = data.get("relationship") if isinstance(data.get("relationship"), dict) else {}
        state = rel.get("state") if isinstance(rel.get("state"), dict) else None
        if not isinstance(state, dict):
            try:
                state = relationship_meta.relationship_state(trust=trust)
            except Exception:
                state = {"trust": trust, "closeness": 0.5, "conflict": 0.5,
                         "repair": 0.0, "predictability": 0.5}
        trajectory = rel.get("trajectory") if isinstance(rel.get("trajectory"), list) else []
        belief = data.get("belief_state") if isinstance(data.get("belief_state"), dict) else {}
        rows.append({
            "sender_id": str(data.get("sender_id") or ""),
            "sender_name": str(data.get("sender_name") or ""),
            "interactions": interactions,
            "trust": trust,
            "last_seen": last_seen,
            "relationship": {
                "state": {key: state.get(key) for key in
                          ("trust", "closeness", "conflict", "repair", "predictability")},
                "trajectory": [dict(x) for x in trajectory[-max_trajectory:] if isinstance(x, dict)],
                "transactive_map": rel.get("transactive_map") if isinstance(rel.get("transactive_map"), dict) else {},
                "destination_map": rel.get("destination_map") if isinstance(rel.get("destination_map"), dict) else {},
                "repair_state": rel.get("repair_state") if isinstance(rel.get("repair_state"), dict) else {},
                "absence": rel.get("absence") if isinstance(rel.get("absence"), dict) else {},
                "calibration": rel.get("calibration") if isinstance(rel.get("calibration"), dict) else {},
                "social_world": [dict(x) for x in (rel.get("social_world") or [])[:20] if isinstance(x, dict)],
                "attachment": rel.get("attachment") if isinstance(rel.get("attachment"), dict) else {},
                "milestones": [dict(x) for x in (rel.get("milestones") or [])[:10] if isinstance(x, dict)],
                "we_memory": [dict(x) for x in (rel.get("we_memory") or [])[:20] if isinstance(x, dict)],
                "commitment": round(float(rel.get("commitment", 0.0) or 0.0), 4),
                "investment": round(float(rel.get("investment", 0.0) or 0.0), 4),
                "annotations": [dict(x) for x in (rel.get("annotations") or [])[:10]
                                if isinstance(x, dict)],
            },
            "belief_state": {
                "beliefs": [str(x)[:60] for x in (belief.get("beliefs") or [])[:3] if str(x)],
                "desires": [str(x)[:60] for x in (belief.get("desires") or [])[:3] if str(x)],
                "intentions": [str(x)[:60] for x in (belief.get("intentions") or [])[:3] if str(x)],
                "confidence": round(float(belief.get("confidence", 0.0) or 0.0), 3),
            },
        })
    return rows


PLUTCHIK_WHEEL = {
    "joy": ("joy", "trust", "anticipation", "surprise"),
    "trust": ("trust", "joy", "acceptance", "admiration"),
    "fear": ("fear", "surprise", "apprehension", "awe"),
    "surprise": ("surprise", "fear", "distraction", "amazement"),
    "sadness": ("sadness", "disgust", "pensiveness", "remorse"),
    "disgust": ("disgust", "sadness", "boredom", "loathing"),
    "anger": ("anger", "anticipation", "annoyance", "rage"),
    "anticipation": ("anticipation", "anger", "interest", "vigilance"),
}

EMOTION_SPECTRUM = [
    ("admiration", "钦佩", 0.40, 0.25, 0.45, 0.55),
    ("adoration", "爱慕", 0.80, 0.45, 0.40, 0.90),
    ("aesthetic", "审美欣赏", 0.50, 0.30, 0.45, 0.60),
    ("amusement", "好笑", 0.80, 0.60, 0.55, 0.60),
    ("anger", "生气", -0.60, 0.80, 0.85, 0.30),
    ("anxiety", "焦虑", -0.40, 0.80, 0.20, 0.30),
    ("awe", "敬畏", 0.60, 0.70, 0.20, 0.60),
    ("awkwardness", "尴尬", -0.20, 0.50, 0.10, 0.40),
    ("boredom", "无聊", -0.40, 0.10, 0.40, 0.40),
    ("calmness", "平静", 0.10, 0.20, 0.50, 0.50),
    ("confusion", "困惑", -0.10, 0.50, 0.40, 0.50),
    ("contempt", "轻蔑", -0.50, 0.40, 0.90, 0.30),
    ("contentment", "满足", 0.60, 0.20, 0.60, 0.70),
    ("desire", "欲望", 0.60, 0.70, 0.60, 0.60),
    ("disappointment", "失望", -0.50, 0.30, 0.40, 0.50),
    ("disgust", "厌恶", -0.60, 0.40, 0.70, 0.40),
    ("empathic_pain", "共情痛苦", -0.40, 0.40, 0.20, 0.70),
    ("entrancement", "入迷", 0.50, 0.50, 0.40, 0.60),
    ("envy", "嫉妒", -0.40, 0.60, 0.30, 0.40),
    ("excitement", "兴奋", 0.70, 0.90, 0.50, 0.60),
    ("fear", "害怕", -0.50, 0.80, 0.20, 0.40),
    ("guilt", "内疚", -0.50, 0.40, 0.30, 0.50),
    ("horror", "恐惧", -0.80, 0.90, 0.20, 0.40),
    ("interest", "兴趣", 0.40, 0.50, 0.50, 0.60),
    ("joy", "快乐", 0.80, 0.60, 0.60, 0.70),
    ("nostalgia", "怀念", 0.30, 0.30, 0.40, 0.60),
    ("pride", "自豪", 0.60, 0.50, 0.90, 0.60),
]

def circadian_alertness(hour: Any) -> float:
    """Deterministic local-hour alertness (0..1); no LLM/network."""
    try:
        h = float(hour) % 24.0
    except Exception:
        h = 12.0
    anchors = ((0.0, 0.25), (3.0, 0.20), (6.0, 0.35), (8.0, 0.85),
               (10.0, 0.95), (13.0, 0.78), (15.0, 0.72), (17.0, 0.88),
               (20.0, 0.70), (23.0, 0.45), (24.0, 0.25))
    for i in range(1, len(anchors)):
        if h <= anchors[i][0]:
            x0, y0 = anchors[i - 1]
            x1, y1 = anchors[i]
            if x1 <= x0:
                return round(y1, 3)
            return round(y0 + (y1 - y0) * (h - x0) / (x1 - x0), 3)
    return 0.25


class BioCore:
    @staticmethod
    def _word_hit(text: str, word: str) -> bool:
        idx = text.find(word)
        while idx >= 0:
            prefix = text[max(0, idx - 2):idx]
            if not prefix.endswith(("不", "没", "别", "无")):
                return True
            idx = text.find(word, idx + len(word))
        return False

    def feedback_user(self, text: str) -> None:
        t = str(text or "")
        cold_words = ("废物", "垃圾", "讨厌", "滚", "闭嘴", "没用", "蠢", "去死", "别烦", "傻子")
        warm_words = ("谢谢", "喜欢", "陪", "辛苦", "厉害", "可爱", "抱")
        cold = sum(1 for w in cold_words if self._word_hit(t, w))
        warm = sum(1 for w in warm_words if self._word_hit(t, w))
        if cold:
            self.trust = _clip(self.trust - 0.055 * cold, 0, 1)
            self.v = _clip(self.v - 0.035 * cold, -1, 1)
            self.stress = _clip(self.stress + 0.035 * cold, 0, 1)
            self.echo_trace = _clip(self.echo_trace - 0.03 * cold, -1, 1)
        if warm:
            self.trust = _clip(self.trust + 0.012 * warm, 0, 1)
            self.v = _clip(self.v + 0.02 * warm, -1, 1)
            self.stress = _clip(self.stress - 0.01 * warm, 0, 1)

    def __init__(self, profile=None):
        self.profile = dict(profile or DEFAULT_PROFILE)
        self.v = _clip(self.profile.get("baseline_v", 0.05), -1, 1)
        self.a = _clip(self.profile.get("baseline_a", 0.4), 0, 1)
        # Compiled persona profiles use PAD-baseline names (da_baseline /
        # social_baseline); legacy profiles may use baseline_d / baseline_social.
        self.d = _clip(self.profile.get("baseline_d", self.profile.get("da_baseline", 0.55)), -1, 1)
        self.social = _clip(self.profile.get("baseline_social", self.profile.get("social_baseline", 0.55)), 0, 1)
        self.stress = 0.1
        self.energy = _clip(self.profile.get("energy_baseline", 0.55), 0, 1)
        self.trust = _clip(self.profile.get("trust", 0.55), 0, 1)
        self._derive()
        self.ticks = 0
        self.labels = {"emotion": "neutral", "intent": "hold", "expression": "normal",
                       "need": "talk", "energy": "normal", "stress": "calm"}
        self.noise = {"stress": 0.0, "energy": 0.0, "social": 0.0, "attention": 0.0, "valence": 0.0}
        self.echo = 0.0
        self.echo_trace = 0.0
        self.reflection = {"v": 0.0, "a": 0.0, "d": 0.0, "social": 0.0}
        self.momentum = {"v": 0.0, "a": 0.0, "d": 0.0, "social": 0.0}
        self.appraisal = {"novelty": 0.0, "goal_relevance": 0.0, "coping": 0.5, "agency": 0.5}
        self.compound = ""
        self.regulation = "none"
        self.history = []
        # B-T06: exploration/boredom drive (bounded state; not a claim about feelings).
        self.novelty_need = 0.5
        self.boredom = 0.0
        # B-T07: autonomy/refusal readiness (bounded state; strategy stays outside).
        self.boundary_pressure = 0.0
        self.refusal_readiness = 0.0
        # B-T09: interpersonal coupling (co-regulation proxy, not "being dragged").
        self.interpersonal = {"other_valence_est": 0.0, "coupling": 0.0, "dampening": 1.0}
        # Circadian / allostatic paper mechanisms (bounded, no prompt).
        self.circadian_alertness = circadian_alertness(
            time.localtime(time.time()).tm_hour + time.localtime(time.time()).tm_min / 60.0)
        self.allostatic_load = 0.0
        # B-T12: deterministic daily digest base (no narrative text).
        self.daily_digests = []
        self._daily_accum = {"date": "", "n": 0, "v": 0.0, "a": 0.0, "stress": 0.0,
                             "emotions": {}, "ticks": 0}
        self.open_loops = []
        self.stimuli = []
        self.goals = [
            {"key": "relationship", "name": "和重要的人保持亲近", "keywords": ("喜欢", "爱", "陪", "关系", "信任", "靠近", "一起"),
             "horizon": "long", "progress": 0.0, "priority": 0.90, "last_update": 0.0},
            {"key": "autonomy", "name": "不被当成工具", "keywords": ("废物", "命令", "必须", "听话", "工具", "滚", "闭嘴"),
             "horizon": "long", "progress": 0.0, "priority": 0.85, "last_update": 0.0},
            {"key": "competence", "name": "证明自己能做好", "keywords": ("没用", "做不好", "失败", "厉害", "做得好", "能干"),
             "horizon": "long", "progress": 0.0, "priority": 0.60, "last_update": 0.0},
            {"key": "stability", "name": "保持情绪稳定", "keywords": ("平静", "冷静", "慢慢", "不急", "休息"),
             "horizon": "short", "progress": 0.0, "priority": 0.55, "last_update": 0.0},
        ]
        self.goal_focus = ""
        self.goal_scores = {}
        self.goal_context_terms = {
            "relationship": ("喜欢", "陪", "亲近", "信任", "关系", "一起", "在乎", "记得", "承诺", "重要", "对方"),
            "autonomy": ("自由", "命令", "被迫", "工具", "听话", "安排", "关起来", "憋", "自主"),
            "competence": ("做不好", "失败", "没用", "厉害", "能干", "任务", "做好", "证明", "靠谱"),
            "stability": ("平静", "冷静", "休息", "不急", "慢慢", "稳住", "安心", "别怕"),
        }
        self.coping_history = []
        self.event_anchors = []
        self.opponent = {"v": 0.0, "a": 0.0, "d": 0.0, "social": 0.0}
        self.opponent_gain = 0.10
        self.reconsolidation_seconds = 600.0
        self.autobiography = []
        self.regulation_stats = {}
        self.attention = 0.5
        self.meta_emotion = ""
        self.goal_conflict = []
        self.self_timeline = {"past": [], "present": "", "future": []}
        self.reflection_tree = {"roots": [], "count": 0}
        self.sec = {}
        self.core_self = ""
        self.narrative_self = ""
        self._query_embedding = None
        self.emotion_decay_factors = {"anger": 0.55, "fear": 0.70, "joy": 1.15,
                                      "sadness": 1.50, "loneliness": 1.80, "neutral": 1.0}
        self.valence_decay_minutes = 120.0
        self.arousal_decay_minutes = 30.0
        self.social_decay_minutes = 180.0
        self.last_tick = __import__("time").time()
        self.ripple = {"upper": 0.0, "lower": 0.0, "overlap": 0.0, "energy": 0.0}
        self.spiking = {"rate": 0.0, "variance": 0.0, "ei": 0.0}
        self._rng = __import__("random").Random()

    def load_state(self, d: dict) -> None:
        if not isinstance(d, dict):
            return
        for key in ("v", "a", "d", "stress", "energy", "trust", "social"):
            if key in d:
                try:
                    lo = -1 if key in ("v", "d") else 0
                    hi = 1.5 if key == "a" else 1
                    setattr(self, key, _clip(d[key], lo, hi))
                except Exception:
                    pass
        self._derive()
        try:
            self.ticks = int(d.get("ticks", self.ticks) or 0)
        except Exception:
            pass
        for key in ("noise", "ripple", "spiking", "labels", "reflection", "momentum", "appraisal"):
            if isinstance(d.get(key), dict):
                setattr(self, key, dict(d[key]))
        if isinstance(d.get("stimuli"), list):
            self.stimuli = [x for x in d["stimuli"] if isinstance(x, dict)][-40:]
        if isinstance(d.get("history"), list):
            self.history = [x for x in d["history"] if isinstance(x, dict)][-80:]
        if isinstance(d.get("open_loops"), list):
            self.open_loops = [x for x in d["open_loops"] if isinstance(x, dict)][-20:]
        if isinstance(d.get("coping_history"), list):
            self.coping_history = [float(x) for x in d["coping_history"] if isinstance(x, (int, float))][-40:]
        if isinstance(d.get("event_anchors"), list):
            self.event_anchors = [x for x in d["event_anchors"] if isinstance(x, dict)][-20:]
        if isinstance(d.get("opponent"), dict):
            self.opponent = {k: float(d["opponent"].get(k, 0.0) or 0.0) for k in ("v", "a", "d", "social")}
        if isinstance(d.get("autobiography"), list):
            self.autobiography = [x for x in d["autobiography"] if isinstance(x, dict)][-80:]
        if isinstance(d.get("regulation_stats"), dict):
            self.regulation_stats = {str(k): dict(v) for k, v in d["regulation_stats"].items() if isinstance(v, dict)}
        try:
            self.attention = _clip(d.get("attention", 0.5), 0, 1)
        except Exception:
            self.attention = 0.5
        if isinstance(d.get("meta_emotion"), str):
            self.meta_emotion = d["meta_emotion"]
        if isinstance(d.get("goals"), list):
            self.goals = [dict(g) for g in d["goals"] if isinstance(g, dict)][:8]
        if isinstance(d.get("goal_conflict"), list):
            self.goal_conflict = [str(x) for x in d["goal_conflict"]][:6]
        if isinstance(d.get("goal_scores"), dict):
            self.goal_scores = {str(k): _clip(v, 0, 1) for k, v in d["goal_scores"].items()
                                if isinstance(v, (int, float))}
        for _g in self.goals:
            if not isinstance(_g, dict):
                continue
            _g.setdefault("priority", 0.5)
            _g.setdefault("last_update", 0.0)
        if isinstance(d.get("self_timeline"), dict):
            self.self_timeline = d["self_timeline"]
        if isinstance(d.get("reflection_tree"), dict):
            self.reflection_tree = d["reflection_tree"]
        elif isinstance(d.get("reflection_tree"), list):
            self.reflection_tree = {"roots": [x for x in d["reflection_tree"] if isinstance(x, dict)][-10:], "count": len(d["reflection_tree"])}
        if isinstance(d.get("sec"), dict):
            self.sec = dict(d["sec"])
        self.core_self = str(d.get("core_self") or "")
        self.narrative_self = str(d.get("narrative_self") or "")
        self.last_tick = __import__("time").time()
        for key in ("echo", "echo_trace"):
            if key in d:
                try:
                    setattr(self, key, _clip(d[key]))
                except Exception:
                    pass

    def _derive(self) -> None:
        """Derive stress/energy from v, a, dominance, social (they are not independent)."""
        v = float(getattr(self, "v", 0.0))
        a = float(getattr(self, "a", 0.5))
        d = float(getattr(self, "d", 0.55))
        soc = float(getattr(self, "social", 0.55))
        self.stress = _clip(0.45 * max(0.0, -v) * a + 0.35 * (1.0 - d) + 0.20 * (1.0 - soc), 0, 1)
        self.energy = _clip(0.45 * a + 0.25 * max(0.0, v) + 0.20 * d + 0.10 * soc, 0, 1)

    def _intensity(self) -> float:
        """Normalized current emotional intensity (0..1)."""
        v = abs(float(getattr(self, "v", 0.0)))
        a = float(getattr(self, "a", 0.5))
        d = abs(float(getattr(self, "d", 0.5)) - 0.5) * 2.0
        soc = abs(float(getattr(self, "social", 0.5)) - 0.5) * 2.0
        stress = float(getattr(self, "stress", 0.0))
        return max(0.0, min(1.0, 0.30 * v + 0.30 * a + 0.20 * stress + 0.10 * d + 0.10 * soc))

    def _goal_signature(self, g: dict) -> str:
        try:
            return "、".join([str(g.get("name") or "")] + [str(x) for x in (g.get("keywords") or ())[:6]])
        except Exception:
            return str(g.get("name") or "")

    def _goal_evidence(self, g: dict, local_text: str, context_text: str) -> float:
        """Evidence that a goal is active, from this turn plus retrieved context.

        Local keyword hits are only one channel; memory / self-narrative text is
        compared against the goal signature so relevance is not keyword-only.
        """
        try:
            t = str(local_text or "")
            ctx = str(context_text or "")
            sig = self._goal_signature(g)
            terms = tuple(g.get("keywords") or ())
            terms += tuple((getattr(self, "goal_context_terms", {}) or {}).get(str(g.get("key") or ""), ()))
            hits = sum(1 for w in terms if w and str(w) in t)
            local = min(1.0, 0.35 + 0.18 * hits) if hits else 0.0
            local = max(local, self._text_similarity(t, sig) * 0.75)
            learned = 0.0
            if ctx:
                term_hits = [w for w in terms if w and str(w) in ctx]
                coverage = len(term_hits) / max(1, len(terms))
                density = min(1.0, len(term_hits) / 5.0)
                learned = max(self._text_similarity(ctx[:900], sig) * 1.6,
                              min(1.0, 0.5 * density + 0.9 * coverage))
                for h in (getattr(self, "history", []) or [])[-12:]:
                    _txt = str((h or {}).get("text") or "")
                    if _txt and _txt in ctx:
                        learned = max(learned, self._text_similarity(_txt, sig) * 0.8)
            return max(0.0, min(1.0, max(local, 0.75 * learned)))
        except Exception:
            return 0.0

    def _resolve_goal_conflict(self, scores=None) -> None:
        """Pick a focus among active goals: high priority and low progress win."""
        scores = scores if isinstance(scores, dict) else dict(getattr(self, "goal_scores", {}) or {})
        cand = []
        for g in getattr(self, "goals", []) or []:
            if not isinstance(g, dict):
                continue
            key = str(g.get("key") or "")
            rel = float(scores.get(key, 0.0) or 0.0)
            if rel < 0.25:
                continue
            try:
                pri = float(g.get("priority", 0.5) or 0.5)
                prog = max(0.0, min(1.0, float(g.get("progress", 0.0) or 0.0)))
            except Exception:
                pri, prog = 0.5, 0.0
            cand.append((pri * (1.0 - prog), rel, g))
        if not cand:
            self.goal_focus = ""
            self.goal_conflict = []
            return
        cand.sort(key=lambda x: (x[0], x[1]), reverse=True)
        self.goal_focus = str(cand[0][2].get("name") or "")
        self.goal_conflict = [str(x[2].get("name") or "") for x in cand[1:]][:4]

    def _update_goals(self, text: str, context: str = "") -> None:
        t = str(text or "")
        ctx = str(context or "")
        scores = {}
        for g in getattr(self, "goals", []) or []:
            if not isinstance(g, dict):
                continue
            key = str(g.get("key") or "")
            scores[key] = round(self._goal_evidence(g, t, ctx), 3)
        self.goal_scores = scores
        # Deterministic priority learning: repeated evidence raises a goal,
        # neglect decays it slowly (bounded EMA; no LLM involved).
        try:
            for g in getattr(self, "goals", []) or []:
                if not isinstance(g, dict):
                    continue
                _key = str(g.get("key") or "")
                _rel = float(scores.get(_key, 0.0) or 0.0)
                memory_meta.update_goal_priority(
                    g, hit=(_rel > 0.05), relevance=_rel)
        except Exception:
            pass
        best = max(scores.values()) if scores else 0.0
        self.appraisal["goal_relevance"] = round(best, 3)
        self._resolve_goal_conflict(scores)
        _pos = sum(1 for w in ("谢谢", "喜欢", "陪", "开心", "信任", "爱") if w in t)
        _neg = sum(1 for w in ("废物", "滚", "闭嘴", "讨厌", "没用", "难受") if w in t)
        self.appraisal["norm_compatibility"] = round(max(0.0, min(1.0, 0.5 + 0.12 * _pos - 0.18 * _neg)), 3)
        self.appraisal["expectedness"] = round(1.0 - float(self.appraisal.get("novelty", 0.0) or 0.0), 3)
        self.appraisal["urgency"] = round(float(getattr(self, "a", 0.5)), 3)

    def _advance_goals(self, v_delta: float = 0.0, social_delta: float = 0.0) -> None:
        """Goal progress follows the interaction outcome, not a fixed step."""
        focus_key = ""
        focus_name = str(getattr(self, "goal_focus", "") or "")
        if not focus_name:
            return
        for g in getattr(self, "goals", []) or []:
            if str(g.get("name") or "") == focus_name:
                focus_key = str(g.get("key") or "")
                break
        if not focus_key:
            return
        try:
            rel = float((getattr(self, "goal_scores", {}) or {}).get(focus_key, 0.0) or 0.0)
            if rel <= 0.0:
                return
            gain = (0.004 * rel
                    + 0.060 * max(0.0, float(v_delta))
                    + 0.040 * max(0.0, float(social_delta))
                    - 0.060 * max(0.0, -float(v_delta)))
            gain = max(-0.06, min(0.08, gain))
            for g in self.goals:
                if str(g.get("key") or "") != focus_key:
                    continue
                g["progress"] = round(max(0.0, min(1.0, float(g.get("progress", 0.0) or 0.0) + gain)), 4)
                g["last_update"] = round(__import__("time").time(), 3)
                try:
                    memory_meta.update_goal_priority(
                        g, hit=(gain >= 0.0), relevance=min(1.0, rel + max(0.0, gain)))
                except Exception:
                    pass
                break
        except Exception:
            pass

    def bind_goal_context(self, memory_text: str = "", self_model=None, recent=None, text: str = "") -> None:
        """Fuse retrieved memory / self narrative / recent turns into goal relevance."""
        try:
            ctx_parts = [str(memory_text or "")]
            if isinstance(self_model, dict):
                ctx_parts.append(str(self_model.get("narrative") or ""))
                ctx_parts.append("、".join(str(x) for x in (self_model.get("consistency") or [])[:5]))
            if isinstance(recent, (list, tuple)):
                ctx_parts.extend(str(x)[:200] for x in recent[:8])
            ctx = "\n".join([p for p in ctx_parts if p])
            if not ctx.strip():
                return
            base = dict(getattr(self, "goal_scores", {}) or {})
            for g in getattr(self, "goals", []) or []:
                if not isinstance(g, dict):
                    continue
                key = str(g.get("key") or "")
                rel = self._goal_evidence(g, str(text or ""), ctx)
                base[key] = round(max(float(base.get(key, 0.0) or 0.0), rel), 3)
            self.goal_scores = base
            if base:
                self.appraisal["goal_relevance"] = round(min(1.0, max(base.values())), 3)
            self._resolve_goal_conflict(base)
        except Exception:
            pass

    def _update_coping(self, pre_stress: float) -> None:
        delta = float(getattr(self, "stress", 0.2)) - float(pre_stress)
        success = 0.5 - 0.8 * delta + 0.15 * (float(getattr(self, "social", 0.5)) - 0.5)
        success = max(0.0, min(1.0, success))
        self.coping_history = (list(getattr(self, "coping_history", [])) + [success])[-40:]
        if self.coping_history:
            self.appraisal["coping"] = round(sum(self.coping_history) / len(self.coping_history), 3)

    def remember_event(self, key: str, title: str, meaning: str = "", reflection: str = "",
                       embedding=None) -> None:
        key = str(key or "").strip()
        title = str(title or "").strip()
        if not key or not title:
            return
        self.event_anchors = [x for x in getattr(self, "event_anchors", [])
                              if x.get("key") != key][-19:]
        _anchor = {"key": key, "title": title, "ts": __import__("time").time()}
        if embedding:
            try:
                _anchor["embedding"] = [float(x) for x in embedding]
            except Exception:
                pass
        self.event_anchors.append(_anchor)
        self.autobiography = (list(getattr(self, "autobiography", [])) + [{
            "ts": __import__("time").time(), "key": key, "title": title,
            "meaning": str(meaning or "")[:400], "reflection": str(reflection or "")[:400],
        }])[-80:]
        try:
            self.self_timeline["past"] = [x.get("title") for x in self.autobiography[-8:]]
            self.self_timeline["present"] = str(reflection or meaning or title)[:300]
            self.self_timeline["future"] = [g.get("name") for g in (self.goals or []) if g.get("name")][:5]
            self.core_self = str(getattr(self, "core_self", "") or title)[:300]
            self.narrative_self = str(reflection or meaning or title)[:500]
        except Exception:
            pass

    @staticmethod
    def _cosine_static(a, b) -> float:
        try:
            aa = [float(x) for x in (a or [])]
            bb = [float(x) for x in (b or [])]
            if not aa or not bb:
                return 0.0
            return sum(x * y for x, y in zip(aa, bb))
        except Exception:
            return 0.0

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        a = str(a or "")
        b = str(b or "")
        if not a or not b:
            return 0.0
        def grams(x):
            x = re.sub(r"\s+", "", x)
            return {x[i:i + 2] for i in range(max(0, len(x) - 1))}
        ga, gb = grams(a), grams(b)
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / float(len(ga | gb))

    def _update_sec(self, v_delta: float, a_delta: float) -> None:
        self.sec = {
            "relevance": round(max(0.0, min(1.0, float(self.appraisal.get("goal_relevance", 0.0) or 0.0) * 0.7 + float(self.appraisal.get("novelty", 0.0) or 0.0) * 0.3)), 3),
            "implication": round(max(0.0, min(1.0, abs(float(v_delta)) * 2.0 + float(self.stress))), 3),
            "coping_potential": round(max(0.0, min(1.0, float(self.appraisal.get("coping", 0.5) or 0.5))), 3),
            "normative": round(max(0.0, min(1.0, float(self.appraisal.get("norm_compatibility", 0.5) or 0.5))), 3),
        }

    def _update_attention(self, v_delta: float, a_delta: float) -> None:
        novelty = float(self.appraisal.get("novelty", 0.0) or 0.0)
        goal = float(self.appraisal.get("goal_relevance", 0.0) or 0.0)
        salience = abs(float(v_delta)) * 1.8 + abs(float(a_delta)) * 1.2 + novelty * 0.4 + goal * 0.5
        self.attention = _clip(0.82 * float(self.attention) + 0.18 * _clip(salience, 0, 1), 0, 1)

    def _update_meta_emotion(self) -> None:
        e = str((self.labels or {}).get("emotion") or "neutral")
        t = float(self.trust)
        soc = float(self.social)
        if e == "sadness" and t < 0.55:
            self.meta_emotion = "对难过的羞耻"
        elif e == "anger" and soc < 0.50:
            self.meta_emotion = "对生气的羞耻"
        elif e == "fear" and float(self.appraisal.get("coping", 0.5)) < 0.45:
            self.meta_emotion = "对害怕的焦虑"
        elif e == "loneliness" and t >= 0.55:
            self.meta_emotion = "对孤独的承认"
        else:
            self.meta_emotion = ""

    def update_open_loops(self, text: str, now=None) -> None:
        """Deterministic prospective-memory (open loops) update from one message."""
        try:
            stamp = float(now if now is not None else __import__("time").time())
            loops = [x for x in (getattr(self, "open_loops", []) or []) if isinstance(x, dict)]
            memory_meta.resolve_open_loops(loops, text, stamp)
            for new_loop in memory_meta.detect_open_loops(text, stamp):
                merged = False
                for existing in loops:
                    if str(existing.get("status") or "open") != "open":
                        continue
                    if memory_meta.text_similarity(
                            existing.get("text", ""), new_loop.get("text", "")) >= memory_meta.OPEN_LOOP_MERGE_SIMILARITY:
                        existing["last_mentioned_ts"] = stamp
                        existing["mentioned"] = int(existing.get("mentioned", 1) or 1) + 1
                        merged = True
                        break
                if not merged:
                    loops.append(new_loop)
            self.open_loops = loops[-int(memory_meta.OPEN_LOOP_MAX):]
        except Exception:
            pass

    def observe(self, text: str, embedding=None) -> None:
        self._decay_to_now()
        self._query_embedding = embedding
        _pre_stress = float(self.stress)
        t = str(text or "")
        self._update_goals(t)
        _event_key = ""
        for _anchor in getattr(self, "event_anchors", []) or []:
            _sim = self._text_similarity(re.sub(r"\s+", "", t)[:120], str(_anchor.get("title", "")))
            if self._query_embedding and _anchor.get("embedding"):
                _sim = max(_sim, self._cosine_static(self._query_embedding, _anchor.get("embedding")))
            if _sim >= 0.55:
                _event_key = str(_anchor.get("key", ""))
                break
        v_delta, a_delta, d_delta, social_delta = 0.0, 0.0, 0.0, 0.0
        _hits = []
        for label, words in LEX.items():
            if not any(self._word_hit(t, w) for w in words):
                continue
            _hits.append(label)
            if label == "joy":
                v_delta += 0.12
                a_delta += 0.05
                d_delta += 0.04
                social_delta += 0.03
            elif label == "sadness":
                v_delta -= 0.14
                a_delta -= 0.03
                d_delta -= 0.05
            elif label == "loneliness":
                v_delta -= 0.12
                a_delta -= 0.03
                d_delta -= 0.04
                social_delta -= 0.16
            elif label == "anger":
                v_delta -= 0.12
                a_delta += 0.15
                d_delta += 0.10
                social_delta -= 0.05
            elif label == "fear":
                v_delta -= 0.16
                a_delta += 0.14
                d_delta -= 0.12
                social_delta -= 0.03
        # Short-term habituation: repeated equivalent emotional stimuli decay.
        _now = time.time()
        # B-T06: generic novelty history (also covers non-emotional repeated text).
        try:
            _novelty_text = re.sub(r"\s+", "", t)[:160]
            if _novelty_text:
                _hist = getattr(self, "_novelty_history", [])
                _seen_before = any(
                    self._text_similarity(_novelty_text, str(x)) >= 0.65
                    for x in _hist[-12:])
                if _seen_before:
                    self.boredom = _clip(self.boredom + 0.06 * (1.0 - self.boredom), 0.0, 1.0)
                    self.novelty_need = _clip(self.novelty_need + 0.03 * (1.0 - self.novelty_need), 0.0, 1.0)
                else:
                    self.boredom = _clip(self.boredom - 0.08, 0.0, 1.0)
                    self.novelty_need = _clip(0.94 * self.novelty_need + 0.06 * 0.5, 0.0, 1.0)
                self._novelty_history = (_hist + [_novelty_text])[-20:]
        except Exception:
            pass
        self.stimuli = [x for x in (getattr(self, "stimuli", []) or [])
                        if _now - float(x.get("ts", 0) or 0) <= float(getattr(self, "stimulus_decay_seconds", 300))]
        if _hits:
            _labels = tuple(sorted(set(_hits)))
            _norm = re.sub(r"\s+", "", t)[:120]
            _item = None
            for _cand in self.stimuli:
                if _event_key:
                    if str(_cand.get("event_key", "")) != _event_key:
                        continue
                    _item = _cand
                    break
                if tuple(_cand.get("labels") or ()) != _labels:
                    continue
                if self._text_similarity(_norm, str(_cand.get("text", ""))) >= 0.55:
                    _item = _cand
                    break
            if _item:
                _gap = max(0.0, _now - float(_item.get("ts", _now)))
                try:
                    _count = float(_item.get("n", 0) or 0) * math.exp(-_gap / max(30.0, float(getattr(self, "stimulus_decay_seconds", 300))))
                except Exception:
                    _count = 0.0
            else:
                _count = 0.0
            _hab = 1.0 / (1.0 + float(getattr(self, "stimulus_habituation", 0.75)) * _count)
            _novelty = float((getattr(self, "appraisal", {}) or {}).get("novelty", 0.0) or 0.0)
            _hab *= max(0.25, 1.0 - 0.6 * _novelty)
            if _item:
                _item["n"] = _count + 1
                _item["ts"] = _now
            else:
                self.stimuli.append({"labels": _labels, "text": _norm, "n": 1, "ts": _now, "event_key": _event_key})
            v_delta *= _hab
            a_delta *= _hab
            d_delta *= _hab
            social_delta *= _hab
            if _item:
                # Repeated equivalent stimulus: boredom rises, novelty need rises.
                self.boredom = _clip(self.boredom + (0.05 + 0.03 * min(3.0, _count)) * (1.0 - self.boredom), 0.0, 1.0)
                self.novelty_need = _clip(self.novelty_need + 0.04 * (1.0 - self.novelty_need), 0.0, 1.0)
            else:
                # New stimulus: boredom falls, novelty need eases toward baseline.
                self.boredom = _clip(self.boredom - 0.08, 0.0, 1.0)
                self.novelty_need = _clip(0.92 * self.novelty_need + 0.08 * 0.5, 0.0, 1.0)
        # B-T07: boundary pressure/refusal readiness from explicit command cues.
        _text_b = str(t or "")
        _commands = sum(1 for w in ("必须", "立刻", "马上", "服从", "不许", "闭嘴", "滚", "废物", "没用", "就该") if w in _text_b)
        _polite = sum(1 for w in ("请", "可以", "愿意", "谢谢", "麻烦") if w in _text_b)
        self.boundary_pressure = _clip(0.86 * self.boundary_pressure + 0.14 * min(1.0, _commands) - 0.04 * min(1.0, _polite), 0.0, 1.0)
        self.refusal_readiness = _clip(
            0.78 * self.refusal_readiness + 0.30 * self.boundary_pressure * min(1.0, _commands)
            + 0.08 * self.stress - 0.05 * min(1.0, _polite), 0.0, 1.0)
        # B-T09: estimate other's valence from the stimulus response, couple with dampening.
        _other_v = _clip(v_delta * 2.5, -1.0, 1.0)
        _gain = _clip(float(getattr(self, "profile", {}).get("contagion_gain", 0.10) or 0.10), 0.0, 0.6)
        _reg = str(getattr(self, "regulation", "none") or "none").lower()
        _damp = 0.55 if _reg in ("reappraise", "reframe") else (0.75 if _reg in ("suppress", "suppression") else 1.0)
        _coupling = _clip(_gain * _damp * abs(_other_v), 0.0, 1.0)
        self.interpersonal = {"other_valence_est": round(_other_v, 4),
                              "coupling": round(_coupling, 4), "dampening": round(_damp, 3)}
        self.v = _clip(self.v + 0.05 * _coupling * _other_v, -1, 1)
        self.a = _clip(self.a + 0.02 * _coupling * abs(_other_v), 0, 1)
        self.v = _clip(0.7 * self.v + 0.3 * v_delta, -1, 1)
        self.a = _clip(0.8 * self.a + 0.2 * (0.4 + a_delta), 0, 1)
        self.d = _clip(0.8 * self.d + 0.2 * (0.55 + d_delta), -1, 1)
        self.social = _clip(0.8 * self.social + 0.2 * (0.55 + social_delta), 0, 1)
        # Affective inertia: recent impulses keep pushing in their direction.
        self.momentum["v"] = _clip(0.75 * float(self.momentum.get("v", 0.0)) + 0.25 * v_delta, -1, 1)
        self.momentum["a"] = _clip(0.75 * float(self.momentum.get("a", 0.0)) + 0.25 * a_delta, -1, 1)
        self.momentum["d"] = _clip(0.75 * float(self.momentum.get("d", 0.0)) + 0.25 * d_delta, -1, 1)
        self.momentum["social"] = _clip(0.75 * float(self.momentum.get("social", 0.0)) + 0.25 * social_delta, -1, 1)
        self.v = _clip(self.v + 0.16 * self.momentum["v"], -1, 1)
        self.a = _clip(self.a + 0.16 * self.momentum["a"], 0, 1)
        self.d = _clip(self.d + 0.16 * self.momentum["d"], -1, 1)
        self.social = _clip(self.social + 0.16 * self.momentum["social"], 0, 1)
        # Intensity raises noise amplitude, but a dimension already near its
        # ceiling receives less effective noise (saturation).
        _int = self._intensity()
        _amp = 0.010 + 0.055 * _int
        self.v = _clip(self.v + self._rng.gauss(0, _amp * (1.0 - 0.75 * abs(self.v))), -1, 1)
        self.a = _clip(self.a + self._rng.gauss(0, _amp * (1.0 - 0.55 * self.a)), 0, 1)
        self.d = _clip(self.d + self._rng.gauss(0, _amp * 0.6 * (1.0 - 0.65 * abs(self.d))), -1, 1)
        self.social = _clip(self.social + self._rng.gauss(0, _amp * 0.5 * (1.0 - 0.65 * self.social)), 0, 1)
        # Reflection buffer: impulse proportional to intensity, then decays;
        # feedback is attenuated when the destination is already high.
        _ref_gain = 0.10 + 0.25 * _int
        self.reflection["v"] = _clip(0.90 * float(self.reflection.get("v", 0.0)) + _ref_gain * v_delta, -1, 1)
        self.reflection["a"] = _clip(0.88 * float(self.reflection.get("a", 0.0)) + _ref_gain * a_delta, -1, 1)
        self.reflection["d"] = _clip(0.92 * float(self.reflection.get("d", 0.0)) + _ref_gain * 0.6 * d_delta, -1, 1)
        self.reflection["social"] = _clip(0.92 * float(self.reflection.get("social", 0.0)) + _ref_gain * 0.6 * social_delta, 0, 1)
        self.v = _clip(self.v + self.reflection["v"] * (1.0 - 0.7 * abs(self.v)), -1, 1)
        self.a = _clip(self.a + self.reflection["a"] * (1.0 - 0.5 * self.a), 0, 1)
        self.d = _clip(self.d + self.reflection["d"] * (1.0 - 0.6 * abs(self.d)), -1, 1)
        self.social = _clip(self.social + self.reflection["social"] * (1.0 - 0.6 * self.social), 0, 1)
        # Opponent process (Solomon & Corbit): the after-reaction builds in the
        # opposite direction and decays slowly, producing an affective rebound.
        _deltas = {"v": v_delta, "a": a_delta, "d": d_delta, "social": social_delta}
        for _k in ("v", "a", "d", "social"):
            _old = float(self.opponent.get(_k, 0.0))
            self.opponent[_k] = _clip(0.86 * _old - 0.22 * _deltas[_k], -1, 1)
        self.v = _clip(self.v + float(getattr(self, "opponent_gain", 0.10)) * self.opponent["v"], -1, 1)
        self.a = _clip(self.a + float(getattr(self, "opponent_gain", 0.10)) * self.opponent["a"], 0, 1)
        self.d = _clip(self.d + float(getattr(self, "opponent_gain", 0.10)) * self.opponent["d"], -1, 1)
        self.social = _clip(self.social + float(getattr(self, "opponent_gain", 0.10)) * self.opponent["social"], 0, 1)
        self._derive()
        self._update_coping(_pre_stress)
        self._advance_goals(v_delta, social_delta)
        self._update_attention(v_delta, a_delta)
        self._update_sec(v_delta, a_delta)
        self._update_meta_emotion()
        for k in self.noise:
            self.noise[k] = _clip(0.82 * self.noise[k] + self._rng.gauss(0, 0.045), -0.3, 0.3)
        self.noise["valence"] = _clip(0.7 * self.noise["valence"] + 0.3 * v_delta, -0.3, 0.3)
        self.noise["stress"] = _clip(0.8 * self.noise["stress"] + 0.2 * (self.stress - 0.2), -0.3, 0.3)
        self.echo_trace = _clip(0.88 * self.echo_trace + 0.12 * (self.v - self.stress * 0.5), -1, 1)
        self.echo = _clip(0.7 * self.echo + 0.3 * self.echo_trace, -1, 1)
        upper = _clip(0.6 * max(0.0, self.v) + 0.2 * self.trust, 0, 1)
        lower = _clip(0.6 * max(0.0, -self.v) + 0.3 * self.stress, 0, 1)
        self.ripple = {"upper": round(upper, 3), "lower": round(lower, 3),
                       "overlap": round(min(upper, lower), 3), "energy": round((upper + lower) / 2, 3)}
        self.spiking = {"rate": round(0.02 + self.energy * 0.08, 3),
                        "variance": round(0.01 + self.stress * 0.05, 4),
                        "ei": round(0.2 + self.trust * 0.3, 3)}
        try:
            self.update_open_loops(t)
        except Exception:
            pass
        self.ticks += 1
        self.infer_labels(force=True)

    def _spectrum(self) -> list:
        v = (float(getattr(self, "v", 0.0)) + 1.0) / 2.0
        a = float(getattr(self, "a", 0.5))
        d = (float(getattr(self, "d", 0.5)) + 1.0) / 2.0
        soc = float(getattr(self, "social", 0.5))
        out = []
        _emo_bias = {
            "sadness": {"disappointment": 0.42, "empathic_pain": 0.36, "guilt": 0.18},
            "anger": {"anger": 0.52, "contempt": 0.30, "disgust": 0.18},
            "fear": {"fear": 0.52, "anxiety": 0.42, "horror": 0.24},
            "loneliness": {"empathic_pain": 0.42, "disappointment": 0.36, "nostalgia": 0.24},
            "joy": {"joy": 0.52, "contentment": 0.36, "amusement": 0.24},
        }.get(str((self.labels or {}).get("emotion") or ""), {})
        _protos = {}
        try:
            _protos = self._calibrate_spectrum_prototypes()
        except Exception:
            _protos = {}
        for key, cn, sv, sa, sd, ss in EMOTION_SPECTRUM:
            _p = _protos.get(key)
            if _p:
                sv, sa, sd, ss = _p
            dv = v - ((sv + 1.0) / 2.0)
            dd = d - ((sd + 1.0) / 2.0)
            dist = (dv * dv * 1.2 + (a - sa) ** 2 + dd * dd + (soc - ss) ** 2) ** 0.5
            dist = max(0.0, dist - float(_emo_bias.get(key, 0.0)))
            out.append((round(dist, 3), key, cn))
        out.sort(key=lambda x: x[0])
        return [{"key": k, "name": n, "distance": dist} for dist, k, n in out[:3]]

    def _spectrum_probs(self) -> list:
        try:
            out = []
            for it in self._spectrum():
                dist = max(0.001, float(it.get("distance", 1.0)))
                out.append({"key": it.get("key"), "name": it.get("name"), "p": round(1.0 / dist, 4)})
            total = sum(x["p"] for x in out) or 1.0
            for x in out:
                x["p"] = round(x["p"] / total, 4)
            return out
        except Exception:
            return []

    def _calibrate_spectrum_prototypes(self) -> dict:
        """Cowen & Keltner (2017) style prototype calibration.

        Each EMOTION_SPECTRUM anchor is mixed with the centroid of this core's
        own state history for the matching emotion family. Pure anchors are
        used until at least two observations exist, so a single turn cannot
        move the emotion map. Deterministic: no RNG, no LLM call.
        """
        anchors = {key: (sv, sa, sd, ss) for key, cn, sv, sa, sd, ss in EMOTION_SPECTRUM}
        sums = {}
        counts = {}
        hist = list(getattr(self, "history", []) or [])[-80:]
        cur_d = float(getattr(self, "d", 0.55))
        cur_soc = float(getattr(self, "social", 0.55))
        for h in hist:
            if not isinstance(h, dict):
                continue
            emo = str(h.get("emotion") or "").strip()
            keys = SPECTRUM_FAMILY.get(emo)
            if not keys:
                continue
            try:
                w = max(0.05, min(1.0, float(h.get("intensity", 0.5) or 0.5)))
            except Exception:
                w = 0.5
            try:
                hv = float(h.get("v", 0.0))
                ha = float(h.get("a", 0.5))
            except Exception:
                continue
            try:
                hd = float(h.get("d", cur_d))
            except Exception:
                hd = cur_d
            try:
                hs = float(h.get("social", cur_soc))
            except Exception:
                hs = cur_soc
            for key in keys:
                if key not in anchors:
                    continue
                acc = sums.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0.0])
                acc[0] += hv * w
                acc[1] += ha * w
                acc[2] += hd * w
                acc[3] += hs * w
                acc[4] += w
                counts[key] = int(counts.get(key, 0) or 0) + 1
        out = {}
        for key, anchor in anchors.items():
            acc = sums.get(key)
            n = int(counts.get(key, 0) or 0)
            if acc and n >= 2 and acc[4] > 0:
                alpha = min(0.35, 0.06 * n)
                centroid = [acc[0] / acc[4], acc[1] / acc[4], acc[2] / acc[4], acc[3] / acc[4]]
                out[key] = tuple((1.0 - alpha) * anchor[i] + alpha * centroid[i] for i in range(4))
            else:
                out[key] = anchor
        self._spectrum_calibration_meta = {
            "samples": len(hist),
            "families": len({str(h.get("emotion") or "") for h in hist
                             if SPECTRUM_FAMILY.get(str(h.get("emotion") or ""))}),
            "calibrated": sum(1 for k in anchors if int(counts.get(k, 0) or 0) >= 2),
        }
        return out

    def _compound_emotion(self) -> str:
        v = float(getattr(self, "v", 0.0))
        a = float(getattr(self, "a", 0.5))
        d = float(getattr(self, "d", 0.5))
        soc = float(getattr(self, "social", 0.5))
        trust = float(getattr(self, "trust", 0.5))
        w = {
            "joy": max(0.0, v) * max(0.2, a),
            "trust": trust * max(0.0, 1.0 - abs(v)),
            "sadness": max(0.0, -v) * (1.0 - a * 0.5),
            "anger": max(0.0, -v) * a * max(0.0, d - 0.5) * 2.0,
            "fear": max(0.0, -v) * a * max(0.0, 0.5 - d) * 2.0,
            "loneliness": max(0.0, -v) * max(0.0, 0.7 - soc),
            "surprise": max(0.0, float(self.appraisal.get("novelty", 0.0) or 0.0)) * max(0.2, a),
            "anticipation": max(0.0, float(self.appraisal.get("goal_relevance", 0.0) or 0.0)) * max(0.2, a),
            "disgust": max(0.0, -v) * max(0.0, 1.0 - a) * max(0.0, 0.6 - soc),
        }
        top = sorted(w.items(), key=lambda kv: kv[1], reverse=True)[:2]
        if len(top) < 2 or top[1][1] < 0.08:
            return ""
        pair = frozenset((top[0][0], top[1][0]))
        names = {
            frozenset(("joy", "trust")): "亲近",
            frozenset(("joy", "fear")): "不安的期待",
            frozenset(("joy", "sadness")): "苦甜参半",
            frozenset(("joy", "anger")): "复杂",
            frozenset(("joy", "loneliness")): "热闹中的空",
            frozenset(("trust", "fear")): "顺从的不安",
            frozenset(("trust", "sadness")): "失落",
            frozenset(("trust", "anger")): "失望的怒",
            frozenset(("trust", "loneliness")): "想念",
            frozenset(("fear", "sadness")): "无助",
            frozenset(("fear", "anger")): "戒备",
            frozenset(("fear", "loneliness")): "被抛下",
            frozenset(("sadness", "anger")): "委屈",
            frozenset(("sadness", "loneliness")): "空落",
            frozenset(("anger", "loneliness")): "被排斥的怒",
        }
        names.update({
            frozenset(("joy", "surprise")): "惊喜",
            frozenset(("trust", "surprise")): "敬畏",
            frozenset(("fear", "surprise")): "惊骇",
            frozenset(("sadness", "surprise")): "意外失落",
            frozenset(("disgust", "surprise")): "错愕",
            frozenset(("anger", "surprise")): "暴怒",
            frozenset(("anticipation", "surprise")): "期待",
            frozenset(("joy", "anticipation")): "乐观",
            frozenset(("trust", "anticipation")): "希望",
            frozenset(("fear", "anticipation")): "焦虑",
            frozenset(("sadness", "anticipation")): "悲观",
            frozenset(("disgust", "anticipation")): "蔑视",
            frozenset(("anger", "anticipation")): "攻击性",
            frozenset(("joy", "disgust")): "幸灾乐祸",
            frozenset(("trust", "disgust")): "矛盾",
            frozenset(("fear", "disgust")): "厌恶恐惧",
            frozenset(("sadness", "disgust")): "懊悔",
            frozenset(("joy", "sadness")): "苦甜参半",
            frozenset(("trust", "anger")): "失望的怒",
            frozenset(("surprise", "anticipation")): "警觉",
            frozenset(("disgust", "anger")): "轻蔑",
            frozenset(("disgust", "sadness")): "嫌恶",
            frozenset(("disgust", "fear")): "恶心",
            frozenset(("disgust", "trust")): "勉强接受",
            frozenset(("surprise", "joy")): "惊喜",
            frozenset(("surprise", "fear")): "惊骇",
            frozenset(("anticipation", "joy")): "乐观",
            frozenset(("anticipation", "fear")): "焦虑",
        })
        return names.get(pair, "混合")

    def _choose_regulation(self) -> str:
        stress = float(getattr(self, "stress", 0.0))
        trust = float(getattr(self, "trust", 0.5))
        soc = float(getattr(self, "social", 0.5))
        arousal = float(getattr(self, "a", 0.5))
        attention = float(getattr(self, "attention", 0.5))
        emo = str(self.labels.get("emotion") or "neutral")
        if stress >= 0.65:
            if trust >= 0.55:
                return "seek_comfort"
            if soc <= 0.30:
                return "avoid"
            return "reappraise"
        _cands = []
        if emo in ("anger", "fear"):
            _cands = (["suppress", "reappraise", "distraction"] if soc < 0.50
                      else ["reappraise", "express", "distraction"])
            if arousal >= 0.72:
                _cands = ["distraction"] + _cands
        elif emo == "sadness":
            _cands = ["express", "reappraise", "seek_comfort", "distraction"]
        elif emo == "loneliness":
            _cands = ["seek_comfort", "avoid", "express", "distraction"]
        elif stress >= 0.45 and arousal >= 0.70 and attention < 0.55:
            _cands = ["distraction", "reappraise"]
        if _cands:
            if getattr(self, "regulation_stats", None):
                def _rate(s):
                    st = self.regulation_stats.get(s) or {}
                    uses = int(st.get("uses", 0) or 0)
                    cost = float(st.get("cost", 0) or 0)
                    avg_cost = (cost / uses) if uses else 0.0
                    return ((float(st.get("success", 0) or 0) / uses) if uses else 0.0) - 0.05 * avg_cost
                _cands.sort(key=_rate, reverse=True)
            return _cands[0]
        return "none"

    def _record_regulation(self, strategy: str, pre_stress: float) -> None:
        """Persist uses / success / cumulative stress change / cumulative cost."""
        if not strategy or strategy == "none":
            return
        try:
            stats = self.regulation_stats
            st = stats.setdefault(strategy, {"uses": 0, "success": 0, "stress_delta": 0.0, "cost": 0.0})
            uses = int(st.get("uses", 0) or 0) + 1
            delta = float(getattr(self, "stress", 0.0)) - float(pre_stress)
            st["uses"] = uses
            st["stress_delta"] = round(float(st.get("stress_delta", 0.0) or 0.0) + delta, 5)
            st["cost"] = round(float(st.get("cost", 0.0) or 0.0) + float(REGULATION_COST.get(strategy, 0.003)), 5)
            if delta <= 0.0005:
                st["success"] = int(st.get("success", 0) or 0) + 1
        except Exception:
            pass

    def _apply_regulation(self) -> None:
        r = self.regulation
        _pre_stress = float(self.stress)
        if r == "seek_comfort":
            self.social = _clip(self.social + 0.03, 0, 1)
            self.stress = _clip(self.stress - 0.02, 0, 1)
        elif r == "reappraise":
            self.stress = _clip(self.stress - 0.04, 0, 1)
            self.v = _clip(self.v + 0.015, -1, 1)
        elif r == "suppress":
            self.stress = _clip(self.stress + 0.01, 0, 1)
            self.v = _clip(self.v - 0.005, -1, 1)
        elif r == "avoid":
            self.social = _clip(self.social - 0.03, 0, 1)
        elif r == "express":
            self.v = _clip(self.v + 0.01, -1, 1)
            self.stress = _clip(self.stress - 0.01, 0, 1)
        elif r == "distraction":
            # Brief relief: lower arousal/stress now, but attention and the
            # current goal pay for it because the concern is left unaddressed.
            self.a = _clip(self.a - 0.06, 0, 1)
            self.stress = _clip(self.stress - 0.035, 0, 1)
            self.attention = _clip(self.attention - 0.05, 0, 1)
            _focus = str(getattr(self, "goal_focus", "") or "")
            for g in self.goals:
                if str(g.get("name") or "") == _focus:
                    g["progress"] = round(max(0.0, float(g.get("progress", 0) or 0) - 0.005), 5)
                    break
        self._derive()
        self._record_regulation(r, _pre_stress)

    def infer_labels(self, force: bool = False) -> None:
        """Derive labels from the biological state when the model omits them."""
        v = float(getattr(self, "v", 0.0))
        a = float(getattr(self, "a", 0.5))
        d = float(getattr(self, "d", 0.55))
        soc = float(getattr(self, "social", 0.55))
        stress = float(getattr(self, "stress", 0.0))
        energy = float(getattr(self, "energy", 0.8))
        trust = float(getattr(self, "trust", 0.5))
        inferred = {}
        if soc <= 0.47 and v <= 0.00:
            inferred["emotion"] = "loneliness"
        elif v >= 0.16 and a >= 0.40 and d >= 0.35:
            inferred["emotion"] = "joy"
        elif v <= -0.20 and a < 0.55:
            inferred["emotion"] = "sadness"
        elif v <= -0.12 and a >= 0.55 and d >= 0.50:
            inferred["emotion"] = "anger"
        elif v <= -0.08 and a >= 0.50 and d < 0.50:
            inferred["emotion"] = "fear"
        else:
            inferred["emotion"] = "neutral"
        if v >= 0.25 and soc >= 0.35:
            inferred["intent"] = "approach"
        elif v <= -0.25 or soc <= 0.30:
            inferred["intent"] = "withdraw"
        else:
            inferred["intent"] = "hold"
        if energy >= 0.68 and v >= 0.15:
            inferred["expression"] = "open"
        elif energy <= 0.35:
            inferred["expression"] = "short"
        else:
            inferred["expression"] = "normal"
        if soc <= 0.30:
            inferred["need"] = "space"
        elif stress >= 0.65:
            inferred["need"] = "vent" if trust >= 0.40 else "space"
        elif trust >= 0.60:
            inferred["need"] = "be_heard" if v <= 0.0 else "share"
        elif v <= -0.30:
            inferred["need"] = "space"
        else:
            inferred["need"] = "talk"
        inferred["energy"] = "high" if energy >= 0.70 else ("low" if energy <= 0.35 else "normal")
        inferred["stress"] = "overloaded" if stress >= 0.70 else ("tense" if stress >= 0.35 else "calm")
        for key, value in inferred.items():
            if force or not self.labels.get(key):
                self.labels[key] = value
        self.compound = self._compound_emotion()
        self.regulation = self._choose_regulation()
        self._apply_regulation()

    def intent(self) -> dict:
        labels = dict(getattr(self, "labels", {}) or {})
        return {
            "emotion": labels.get("emotion", "neutral"),
            "energy": labels.get("energy", "normal"),
            "stress": labels.get("stress", "calm"),
            "trust": round(self.trust, 2),
            "intent": labels.get("intent", "hold"),
            "expression": labels.get("expression", "normal"),
            "need": labels.get("need", "talk"),
            "dominance": round(self.d, 2),
            "social": round(self.social, 2),
            "compound": self.compound,
            "spectrum": self._spectrum(),
            "regulation": self.regulation,
        }

    def apply_affect(self, meta: dict) -> None:
        if not isinstance(meta, dict):
            return
        def delta(key, lo=-0.30, hi=0.30):
            try:
                return _clip(meta.get(key, 0.0), lo, hi)
            except Exception:
                return 0.0
        self.v = _clip(self.v + delta("valence_delta"), -1, 1)
        self.a = _clip(self.a + delta("arousal_delta"), 0, 1)
        self.d = _clip(self.d + delta("dominance_delta"), -1, 1)
        self.social = _clip(self.social + delta("social_delta"), 0, 1)
        # Backward compatibility with old tags that only sent stress/energy.
        if "dominance_delta" not in meta and "stress_delta" in meta:
            self.d = _clip(self.d - delta("stress_delta") * 0.5, -1, 1)
        if "social_delta" not in meta and "stress_delta" in meta:
            self.social = _clip(self.social - max(0.0, delta("stress_delta")) * 0.4, 0, 1)
        self.trust = _clip(self.trust + delta("trust_delta"), 0, 1)
        self.momentum["v"] = _clip(0.75 * float(self.momentum.get("v", 0.0)) + 0.25 * delta("valence_delta"), -1, 1)
        self.momentum["a"] = _clip(0.75 * float(self.momentum.get("a", 0.0)) + 0.25 * delta("arousal_delta"), -1, 1)
        self.momentum["d"] = _clip(0.75 * float(self.momentum.get("d", 0.0)) + 0.25 * delta("dominance_delta"), -1, 1)
        self.momentum["social"] = _clip(0.75 * float(self.momentum.get("social", 0.0)) + 0.25 * delta("social_delta"), -1, 1)
        self.v = _clip(self.v + 0.12 * self.momentum["v"], -1, 1)
        self.a = _clip(self.a + 0.12 * self.momentum["a"], 0, 1)
        self.d = _clip(self.d + 0.12 * self.momentum["d"], -1, 1)
        self.social = _clip(self.social + 0.12 * self.momentum["social"], 0, 1)
        for _k in ("novelty", "goal_relevance", "coping", "agency"):
            if _k + "_delta" in meta:
                self.appraisal[_k] = _clip(float(self.appraisal.get(_k, 0.0)) + delta(_k + "_delta"), 0, 1)
        self._derive()
        allowed = {
            "emotion": {"joy", "sadness", "anger", "fear", "loneliness", "neutral"},
            "intent": {"approach", "hold", "withdraw"},
            "expression": {"open", "normal", "short"},
            "need": {"share", "space", "vent", "be_heard", "talk"},
            "energy": {"low", "normal", "high"},
            "stress": {"calm", "tense", "overloaded"},
        }
        for key, values in allowed.items():
            value = str(meta.get(key) or "").strip()
            if value in values:
                self.labels[key] = value
        self._derive()
        self.infer_labels(force=False)
        self.ticks += 1
        self.noise["valence"] = _clip(0.7 * self.noise["valence"] + 0.3 * delta("valence_delta"), -0.3, 0.3)
        self.noise["stress"] = _clip(0.8 * self.noise["stress"] + 0.2 * delta("stress_delta"), -0.3, 0.3)
        self.echo_trace = _clip(0.88 * self.echo_trace + 0.12 * (self.v - self.stress * 0.5), -1, 1)
        self.echo = _clip(0.7 * self.echo + 0.3 * self.echo_trace, -1, 1)
        upper = _clip(0.6 * max(0.0, self.v) + 0.2 * self.trust, 0, 1)
        lower = _clip(0.6 * max(0.0, -self.v) + 0.3 * self.stress, 0, 1)
        self.ripple = {"upper": round(upper, 3), "lower": round(lower, 3),
                       "overlap": round(min(upper, lower), 3), "energy": round((upper + lower) / 2, 3)}
        self.spiking = {"rate": round(0.02 + self.energy * 0.08, 3),
                        "variance": round(0.01 + self.stress * 0.05, 4),
                        "ei": round(0.2 + self.trust * 0.3, 3)}

    def feedback(self, reply: str) -> None:
        r = str(reply or "")
        warm = 0.008 * sum(1 for w in ("谢谢", "在", "陪", "懂", "一起", "抱") if w in r)
        self.trust = _clip(self.trust + warm, 0, 1)
        self.social = _clip(self.social + warm * 0.5, 0, 1)
        self._derive()
        self.echo_trace = _clip(0.9 * self.echo_trace + 0.1 * warm, -1, 1)

    def _decay_to_now(self) -> None:
        now = __import__("time").time()
        try:
            dt_min = max(0.0, (now - float(getattr(self, "last_tick", now))) / 60.0)
        except Exception:
            dt_min = 0.0
        self.last_tick = now
        if dt_min < 0.5:
            return
        def factor(halflife):
            try:
                hl = max(1.0, float(halflife))
            except Exception:
                hl = 120.0
            return 0.5 ** (dt_min / hl)
        _emo = str((getattr(self, "labels", {}) or {}).get("emotion") or "neutral")
        _ef = float((getattr(self, "emotion_decay_factors", {}) or {}).get(_emo, 1.0))
        self.v = _clip(self.v * factor(self.valence_decay_minutes * _ef), -1, 1)
        self.a = _clip(0.40 + (self.a - 0.40) * factor(self.arousal_decay_minutes * max(0.5, _ef)), 0, 1)
        self.d = _clip(0.55 + (self.d - 0.55) * factor(self.valence_decay_minutes * _ef), -1, 1)
        self.social = _clip(0.55 + (self.social - 0.55) * factor(self.social_decay_minutes * _ef), 0, 1)
        try:
            self._apply_circadian_effects()
            self._update_allostatic_load()
        except Exception:
            pass
        self._derive()

    def record_reply(self, text: str = "", meta=None) -> None:
        try:
            emo = str((self.labels or {}).get("emotion") or "neutral")
            self.history.append({
                "ts": __import__("time").time(),
                "emotion": emo,
                "compound": str(self.compound or ""),
                "intensity": round(float(self._intensity()), 3),
                "v": round(float(self.v), 3),
                "a": round(float(self.a), 3),
                "d": round(float(self.d), 3),
                "social": round(float(self.social), 3),
                "text": str(text or "")[:80],
            })
            if len(self.history) > 80:
                self.history = self.history[-80:]
        except Exception:
            pass

    def _apply_circadian_effects(self, alert=None, now=None) -> float:
        """Small attention/energy modulation from local-hour alertness."""
        try:
            if alert is None:
                current = time.localtime(time.time() if now is None else now)
                alert = circadian_alertness(current.tm_hour + current.tm_min / 60.0)
            alert = max(0.0, min(1.0, float(alert)))
            self.circadian_alertness = round(alert, 3)
            delta = 0.01 * (alert - 0.5)
            self.energy = _clip(self.energy + delta, 0.0, 1.0)
            self.attention = _clip(self.attention + delta * 0.5, 0.0, 1.0)
            return alert
        except Exception:
            return 0.5

    def _update_allostatic_load(self) -> float:
        """Slow allostatic accumulation/recovery; bounded, tiny stress offset."""
        try:
            stress = _clip(self.stress, 0.0, 1.0)
            if stress > 0.55:
                self.allostatic_load = _clip(
                    self.allostatic_load + 0.01 * (stress - 0.55) * (1.0 - self.allostatic_load), 0.0, 1.0)
            else:
                self.allostatic_load = _clip(
                    self.allostatic_load - 0.004 * (0.55 - stress), 0.0, 1.0)
            if self.allostatic_load > 0:
                self.stress = _clip(self.stress + 0.005 * self.allostatic_load, 0.0, 1.0)
            return float(self.allostatic_load)
        except Exception:
            return 0.0

    def update_daily_digest(self, now=None, event_ids=None) -> dict:
        """Deterministic daily digest base; no narrative/LLM. Bounded to 30 days."""
        try:
            current = float(time.time() if now is None else now)
            date = time.strftime("%Y-%m-%d", time.localtime(current))
            accum = getattr(self, "_daily_accum", None)
            if not isinstance(accum, dict):
                accum = {"date": "", "n": 0, "v": 0.0, "a": 0.0, "stress": 0.0,
                         "emotions": {}, "ticks": 0, "event_ids": []}
            if accum.get("date") and accum.get("date") != date:
                if int(accum.get("n", 0) or 0) > 0:
                    emotions = accum.get("emotions") or {}
                    dominant = max(emotions.items(), key=lambda kv: kv[1])[0] if emotions else "neutral"
                    n = int(accum.get("n", 1) or 1)
                    self.daily_digests.append({
                        "date": str(accum.get("date")),
                        "event_ids": [str(x) for x in (accum.get("event_ids") or [])[-50:] if str(x)],
                        "mean_v": round(float(accum.get("v", 0.0) or 0.0) / n, 4),
                        "mean_a": round(float(accum.get("a", 0.0) or 0.0) / n, 4),
                        "mean_stress": round(float(accum.get("stress", 0.0) or 0.0) / n, 4),
                        "dominant_emotion": dominant,
                        "interaction_count": n,
                    })
                    self.daily_digests = self.daily_digests[-30:]
                accum = {"date": date, "n": 0, "v": 0.0, "a": 0.0, "stress": 0.0,
                         "emotions": {}, "ticks": 0, "event_ids": []}
            accum["date"] = date
            accum["n"] = int(accum.get("n", 0) or 0) + 1
            accum["v"] = float(accum.get("v", 0.0) or 0.0) + float(self.v)
            accum["a"] = float(accum.get("a", 0.0) or 0.0) + float(self.a)
            accum["stress"] = float(accum.get("stress", 0.0) or 0.0) + float(self.stress)
            _emo = str((self.labels or {}).get("emotion") or "neutral")
            emotions = accum.get("emotions") if isinstance(accum.get("emotions"), dict) else {}
            emotions[_emo] = int(emotions.get(_emo, 0) or 0) + 1
            accum["emotions"] = emotions
            accum["ticks"] = int(accum.get("ticks", 0) or 0) + 1
            if isinstance(event_ids, (list, tuple)):
                _eids = accum.get("event_ids") if isinstance(accum.get("event_ids"), list) else []
                for _eid in event_ids:
                    if str(_eid) and str(_eid) not in _eids:
                        _eids.append(str(_eid))
                accum["event_ids"] = _eids[-50:]
            self._daily_accum = accum
            return dict(accum)
        except Exception:
            return {}

    def snapshot(self) -> dict:
        self._decay_to_now()
        return {"v": round(self.v, 4), "a": round(self.a, 4),
                "d": round(self.d, 4), "social": round(self.social, 4),
                "stress": round(self.stress, 4), "energy": round(self.energy, 4),
                "trust": round(self.trust, 4), "ticks": self.ticks,
                "noise": {k: round(float(v), 3) for k, v in self.noise.items()},
                "echo": round(self.echo, 4), "echo_trace": round(self.echo_trace, 4),
                "ripple": dict(self.ripple), "spiking": dict(self.spiking),
                "reflection": dict(self.reflection),
                "momentum": dict(self.momentum),
                "appraisal": dict(self.appraisal),
                "stimuli": list(self.stimuli)[-8:],
                "history": list(self.history)[-80:],
                "open_loops": [dict(x) for x in (getattr(self, "open_loops", []) or [])[-20:]
                               if isinstance(x, dict)],
                "open_loops_due": sum(1 for _loop in (getattr(self, "open_loops", []) or [])
                                      if isinstance(_loop, dict)
                                      and _loop.get("status") == "open"
                                      and str(_loop.get("due_hint") or "") in ("soon", "tomorrow")),
                "goal_focus": self.goal_focus,
                "coping": round(float((self.appraisal or {}).get("coping", 0.5)), 3),
                "event_anchors": list(self.event_anchors)[-5:],
                "opponent": dict(self.opponent),
                "autobiography": list(self.autobiography)[-8:],
                "regulation_stats": dict(self.regulation_stats),
                "attention": round(float(self.attention), 3),
                "novelty_need": round(float(getattr(self, "novelty_need", 0.5)), 3),
                "boredom": round(float(getattr(self, "boredom", 0.0)), 3),
                "circadian_alertness": round(float(getattr(self, "circadian_alertness", 0.5)), 3),
                "allostatic_load": round(float(getattr(self, "allostatic_load", 0.0)), 3),
                "boundary_pressure": round(float(getattr(self, "boundary_pressure", 0.0)), 3),
                "refusal_readiness": round(float(getattr(self, "refusal_readiness", 0.0)), 3),
                "interpersonal": {k: round(float(v), 4) for k, v in (getattr(self, "interpersonal", {}) or {}).items()},
                "daily_digests": [dict(x) for x in (getattr(self, "daily_digests", []) or [])[-30:]],
                "meta_emotion": self.meta_emotion,
                "goals": [{"key": g.get("key"), "name": g.get("name"), "horizon": g.get("horizon"),
                           "progress": round(float(g.get("progress", 0) or 0), 3),
                           "priority": round(float(g.get("priority", 0.5) or 0.5), 3),
                           "last_update": round(float(g.get("last_update", 0.0) or 0.0), 3)}
                          for g in self.goals],
                "goal_conflict": list(self.goal_conflict),
                "goal_scores": dict(getattr(self, "goal_scores", {}) or {}),
                "self_timeline": dict(self.self_timeline),
                "reflection_tree": self.reflection_tree,
                "spectrum_probs": self._spectrum_probs(),
                "sec": dict(self.sec),
                "core_self": self.core_self,
                "narrative_self": self.narrative_self,
                "plutchik": PLUTCHIK_WHEEL,
                "compound": self.compound,
                "regulation": self.regulation,
                "spectrum": self._spectrum(),
                "spectrum_calibration": dict(getattr(self, "_spectrum_calibration_meta", {}) or {}),
                "labels": dict(getattr(self, "labels", {}) or {})}


@register("astrbot_plugin_biocore", "Johnhmzm", "生物情绪层：注入表达意图，不生成回复", "1.2.62")
class BioCorePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.inject_intent = bool(self.config.get("inject_intent", True))
        self.compact_prompt = bool(self.config.get("compact_prompt", True))
        self.voice_transcription_enabled = bool(self.config.get("voice_transcription_enabled", True))
        try:
            self.event_summary_delay_hours = max(0, int(self.config.get("event_summary_delay_hours", 6) or 6))
        except Exception:
            self.event_summary_delay_hours = 6
        self.proactive_reply = bool(self.config.get("proactive_reply", False))
        self.memory_dedup_embedding = bool(self.config.get("memory_dedup_embedding", True))
        # Safety switch: default OFF for private use. When OFF, no masking,
        # no cross-session isolation, no forced abstention, no poison filter.
        self.safety_enabled = bool(self.config.get("safety_enabled", False))
        self.cross_session_memory = not self.safety_enabled
        self.sensitive_memory_protection = self.safety_enabled
        # Hybrid lexical+MMR retrieval and LLM-proposed write candidates.
        self.hybrid_retrieval = bool(self.config.get("hybrid_retrieval", True))
        self.llm_memory_candidates = bool(self.config.get("llm_memory_candidates", True))
        # B-T02 we-memory is evidence-gated and OFF by default (needs real
        # shared-ritual evidence before it writes relationship state).
        self.we_memory_enabled = bool(self.config.get("we_memory_enabled", False))
        # L-T02..L-T12 bounded runtime state. Only the last trace/hint is kept
        # in memory; no prompt text is stored and no reply is generated.
        self._last_cause_trace = []
        self._last_strategy_hint = ""
        self._last_memory_entries = []
        self._llm_v2_last = {}
        # LLM scope: user requirement is "LLM only for reply + summary".
        # When true, BioCore only calls the LLM for event/memory summaries;
        # persona compile / event ranking / reflection / image caption are
        # skipped (deterministic fallbacks where available).
        self.llm_only_reply_summary = bool(
            self.config.get("llm_only_reply_summary", True))
        self.llm_functions = {
            _name: {"enabled": LLM_FUNCTION_DEFAULTS[_name],
                    "provider": "follow_llm"}
            for _name in LLM_FUNCTIONS
        }
        self.first_run_persona_compile = bool(self.config.get("first_run_persona_compile", True))
        # Deprecated: [BC] sizing is owned by the interpretation layer now.
        # Kept only so existing config files do not break on load.
        self.max_intent_chars = int(self.config.get("max_intent_chars", 180) or 180)
        self.kb_enabled = bool(self.config.get("kb_enabled", False))
        _names = self.config.get("kb_names", [])
        self.kb_names = [str(x).strip() for x in _names] if isinstance(_names, (list, tuple)) else []
        self.cores = {}
        self._consolidating = False
        self._last_consolidation = 0.0
        self._last_event_archive = 0.0
        self._last_reflection = 0.0
        try:
            self.reflection_interval_hours = max(1, int(self.config.get("reflection_interval_hours", 6) or 6))
        except Exception:
            self.reflection_interval_hours = 6
        # Event-driven insight trigger: fallback is a 24h ultra-long safety net,
        # not a periodic 6h main trigger anymore.
        self._insight_fallback_hours = max(INSIGHT_FALLBACK_HOURS, int(self.reflection_interval_hours))
        # Tunable thresholds (defaults match the constants above; AstrBot plugin
        # config exposes insight_min_new_events / insight_cooldown_minutes).
        try:
            self._insight_min_new_events = max(
                1, int(self.config.get("insight_min_new_events", INSIGHT_MIN_NEW_EVENTS)
                       or INSIGHT_MIN_NEW_EVENTS))
        except Exception:
            self._insight_min_new_events = INSIGHT_MIN_NEW_EVENTS
        try:
            self._insight_cooldown_minutes = max(
                1, int(self.config.get("insight_cooldown_minutes", INSIGHT_COOLDOWN_SECONDS // 60)
                       or (INSIGHT_COOLDOWN_SECONDS // 60)))
        except Exception:
            self._insight_cooldown_minutes = INSIGHT_COOLDOWN_SECONDS // 60
        # Long-term pattern insight: main entry is the manual dashboard button;
        # automatic generation is opt-in and OFF by default.
        self.insight_auto_enabled = bool(self.config.get("insight_auto_enabled", False))
        try:
            self.stimulus_decay_seconds = max(30, int(self.config.get("stimulus_decay_seconds", 300) or 300))
            self.stimulus_habituation = max(0.0, float(self.config.get("stimulus_habituation", 0.75) or 0.75))
        except Exception:
            self.stimulus_decay_seconds = 300
            self.stimulus_habituation = 0.75
        self.image_recognition_enabled = bool(self.config.get("image_recognition_enabled", True))
        try:
            self.image_service_idle_seconds = max(30, int(self.config.get("image_service_idle_seconds", 120) or 120))
        except Exception:
            self.image_service_idle_seconds = 120
        try:
            self.image_cache_max_entries = max(20, int(self.config.get("image_cache_max_entries", 500) or 500))
        except Exception:
            self.image_cache_max_entries = 500
        def _configured_path(key):
            raw = str(self.config.get(key, "") or "").strip()
            return Path(raw) if raw else None
        self.image_llama_server = _configured_path("image_llama_server")
        self.image_llama_model = _configured_path("image_llama_model")
        self.image_llama_mmproj = _configured_path("image_llama_mmproj")
        try:
            self.image_service_port = max(1, int(self.config.get("image_service_port", 8091) or 8091))
        except Exception:
            self.image_service_port = 8091
        # Lazy image-service process/lock state (initialized here so the
        # first image request does not AttributeError).
        self._image_proc = None
        self._image_last_used = 0.0
        self._image_service_lock = None
        _triggers = self.config.get("image_trigger_words", [])
        self.image_trigger_words = ([str(x).strip() for x in _triggers if str(x).strip()]
                                    if isinstance(_triggers, (list, tuple)) else [])
        try:
            self.valence_decay_minutes = max(1.0, float(self.config.get("valence_decay_minutes", 120) or 120))
        except Exception:
            self.valence_decay_minutes = 120.0
        try:
            self.arousal_decay_minutes = max(1.0, float(self.config.get("arousal_decay_minutes", 30) or 30))
        except Exception:
            self.arousal_decay_minutes = 30.0
        try:
            self.social_decay_minutes = max(1.0, float(self.config.get("social_decay_minutes", 180) or 180))
        except Exception:
            self.social_decay_minutes = 180.0
        self.stimuli = []
        self.profile = None
        self.persona_text = ""
        # Persona selection: empty = follow AstrBot default persona.
        self.persona_id = str(self.config.get("persona_id") or "").strip()
        # Hash of the persona text whose numeric profile was compiled; lets
        # strict LLM mode still compile ONCE on first run / persona change.
        self._persona_compiled_hash = ""
        # Schema slots proposed once by the persona compiler (bounded strings).
        self.schema_texts = []
        # L-T07: bounded persona style slots proposed by the compiler (never
        # prompt text; the interpretation layer stays the only prompt owner).
        self.persona_style = {"intimacy_style": "neutral", "address_terms": []}
        self.self_model = self._load_self_model()
        if not isinstance(self.self_model.get("diary"), list):
            self.self_model["diary"] = []
        if not isinstance(self.self_model.get("relationship_narratives"), list):
            self.self_model["relationship_narratives"] = []
        self.api_config = {}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._load_profile()
        self._load_settings()
        if "kb_enabled" in self.config:
            self.kb_enabled = bool(self.config.get("kb_enabled"))
        if "kb_names" in self.config:
            _n = self.config.get("kb_names")
            if isinstance(_n, (list, tuple)):
                self.kb_names = [str(x).strip() for x in _n if str(x).strip()]
        self._load_api_config()
        self._register_page_api()
        try:
            _d = self._public_api_config()
            logger.info("[biocore] api defaults llm=%s embedding=%s rerank=%s",
                        (_d.get("llm") or {}).get("provider_id"),
                        (_d.get("embedding") or {}).get("provider_id"),
                        (_d.get("rerank") or {}).get("provider_id"))
        except Exception as exc:
            logger.warning("[biocore] api defaults probe failed: %s", exc)

    def _load_profile(self):
        try:
            if PROFILE_PATH.exists():
                d = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
                self.profile = dict(d.get("profile") or {})
                self.persona_text = str(d.get("persona") or "")
                _ph = str(d.get("persona_hash") or "")
                self._persona_compiled_hash = _ph or (_sha256(self.persona_text) if self.persona_text else "")
                _schema = d.get("schema")
                if isinstance(_schema, list):
                    self.schema_texts = [str(x).strip()[:60] for x in _schema
                                         if str(x).strip()][:6]
                _style = d.get("style")
                if isinstance(_style, dict):
                    _tag = str(_style.get("intimacy_style") or "neutral")
                    if _tag not in ("neutral", "playful", "gentle", "reserved"):
                        _tag = "neutral"
                    _terms = [str(x).strip()[:12] for x in (_style.get("address_terms") or [])
                              if str(x).strip()][:3]
                    self.persona_style = {"intimacy_style": _tag, "address_terms": _terms}
                logger.info("[biocore] loaded profile %s", PROFILE_PATH)
        except Exception as exc:
            logger.warning("[biocore] profile load failed: %s", exc)

    async def _persona_text(self, event) -> str:
        try:
            pm = self.context.persona_manager
            _pid = str(getattr(self, "persona_id", "") or self.config.get("persona_id") or "").strip()
            if _pid:
                try:
                    _p = pm.get_persona_v3_by_id(_pid)
                except Exception:
                    _p = None
                if _p:
                    if isinstance(_p, dict):
                        return str(_p.get("prompt") or _p.get("system_prompt") or "")
                    return str(getattr(_p, "prompt", "") or getattr(_p, "system_prompt", "") or "")
            p = await pm.get_default_persona_v3(getattr(event, "unified_msg_origin", None))
            if isinstance(p, dict):
                return str(p.get("prompt") or p.get("system_prompt") or "")
            return str(getattr(p, "prompt", "") or getattr(p, "system_prompt", "") or "")
        except Exception as exc:
            logger.warning("[biocore] persona read failed: %s", exc)
            return ""

    def _function_cfg(self, kind: str) -> dict:
        _name = LLM_FUNCTION_ALIASES.get(str(kind or ""), str(kind or ""))
        _all = getattr(self, "llm_functions", None)
        if not isinstance(_all, dict):
            return {"enabled": True, "provider": "follow_llm"}
        _cfg = _all.get(_name)
        if not isinstance(_cfg, dict):
            _cfg = {}
        return {
            "enabled": bool(_cfg.get("enabled", LLM_FUNCTION_DEFAULTS.get(_name, True))),
            "provider": str(_cfg.get("provider") or "follow_llm"),
        }

    def _llm_allowed(self, kind: str) -> bool:
        """Per-function LLM switch (replaces the old global strict flag)."""
        _all = getattr(self, "llm_functions", None)
        if not isinstance(_all, dict):
            # Test harness / legacy object created before this feature: keep
            # the old llm_only_reply_summary semantics when present.
            _strict = getattr(self, "llm_only_reply_summary", None)
            if _strict is None:
                return True
            return (not bool(_strict)) or str(kind or "") in ("reply", "summary")
        return self._function_cfg(kind)["enabled"]

    def _provider_kind(self, provider) -> str:
        """Classify a provider by id/model/type (chat / vision / embedding / tts / rerank)."""
        try:
            cfg = getattr(provider, "provider_config", {}) or {}
            raw = " ".join(str(x or "") for x in (
                cfg.get("id"), cfg.get("model"),
                cfg.get("provider_type"), type(provider).__name__,
            )).lower()
        except Exception:
            raw = ""
        if any(x in raw for x in ("img", "image", "vision", "t2i", "dall", "stable", "midjourney", "exusiai-img")):
            return "vision"
        if any(x in raw for x in ("tts", "speech", "voice")):
            return "tts"
        if any(x in raw for x in ("embed", "bge", "text-embedding")):
            return "embedding"
        if "rerank" in raw:
            return "rerank"
        return "chat"

    async def _provider_for(self, kind: str, event=None):
        """Resolve the LLM provider for one function.

        Default ("follow_llm") uses AstrBot's current chat provider. A configured
        provider_id is looked up via get_provider_by_id; if it is missing we log
        a warning and fall back to the main LLM instead of failing the feature.
        """
        _cfg = self._function_cfg(kind)
        _override = _cfg["provider"]
        _umo = str(getattr(event, "unified_msg_origin", "") or "") if event is not None else ""
        if _override and _override not in ("follow_llm", "main", "default", ""):
            _p = None
            try:
                _p = self.context.get_provider_by_id(_override)
            except Exception as exc:
                logger.warning("[biocore] provider lookup failed for %s (%s): %s", kind, _override, exc)
                _p = None
            if _p is not None:
                if self._provider_kind(_p) == "chat":
                    return _p
                logger.warning("[biocore] llm function %s provider %s is not a chat provider; fallback to main LLM",
                               kind, _override)
            else:
                logger.warning("[biocore] llm function %s provider %s not found; fallback to main LLM", kind, _override)
        try:
            return await self.context.get_using_provider_async(_umo)
        except Exception as exc:
            logger.warning("[biocore] main LLM provider lookup failed for %s: %s", kind, exc)
            return None


    # ------------------------------------------------------------------
    # LLM v2 (L-T01..L-T12): proposal-only model calls.
    #
    # Contract:
    #   * every function is registered in LLM_FUNCTIONS and defaults to OFF;
    #   * prompt text + output parsing only live in interpretation.py;
    #   * a model output is validated before storage (relationship_meta);
    #   * no function writes core v/a/d/trust/goals or generates a reply;
    #   * strict/legacy mode (_llm_allowed) skips every extra call.
    # ------------------------------------------------------------------
    async def _llm_v2_call(self, kind, prompt, parser, event=None, system_prompt=None):
        if not self._llm_allowed(kind):
            return None
        try:
            provider = await self._provider_for(kind, event)
        except Exception as exc:
            logger.warning("[biocore] llm v2 provider failed (%s): %s", kind, exc)
            return None
        if provider is None:
            return None
        try:
            if system_prompt:
                resp = await provider.text_chat(prompt=prompt, system_prompt=system_prompt)
            else:
                resp = await provider.text_chat(prompt=prompt)
            raw = str(getattr(resp, "completion_text", "") or "").strip()
            if not raw:
                return None
            return parser(raw)
        except Exception as exc:
            logger.warning("[biocore] llm v2 call/paser failed (%s): %s", kind, exc)
            return None

    def _llm_v2_cooldown_ok(self, kind):
        try:
            last = float((getattr(self, "_llm_v2_last", {}) or {}).get(kind, 0.0) or 0.0)
        except Exception:
            last = 0.0
        return (time.time() - last) >= float(LLM_V2_COOLDOWNS.get(kind, 600))

    def _llm_v2_mark(self, kind):
        if not isinstance(getattr(self, "_llm_v2_last", None), dict):
            self._llm_v2_last = {}
        self._llm_v2_last[kind] = time.time()

    def _user_record(self, event):
        try:
            path = self._user_path(event)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_user_record(self, event, data):
        try:
            if not isinstance(data, dict):
                return
            path = self._user_path(event)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:
            logger.warning("[biocore] user record save failed: %s", exc)

    def _relationship_of(self, user_data):
        rel = (user_data or {}).get("relationship") if isinstance(user_data, dict) else None
        return rel if isinstance(rel, dict) else {}

    def _deterministic_hint(self, text, user_data, events_raw, memory_meta):
        """One bounded deterministic token; interpretation owns the wording."""
        rel = self._relationship_of(user_data)
        repair_state = rel.get("repair_state") if isinstance(rel.get("repair_state"), dict) else {}
        hint = interpretation.repair_strategy_block(repair_state)
        if not hint and interpretation.cause_question(text):
            hint = interpretation.cause_trace_block(getattr(self, "_last_cause_trace", []))
        if not hint:
            hint = interpretation.memory_receipt_block(memory_meta, text)
        if not hint:
            hint = interpretation.grounding_check_block(memory_meta, text)
        if not hint:
            hint = interpretation.response_strategy_block(events_raw)
        return hint

    async def _maybe_llm_hints(self, event, core, user_data, events_raw, memory_meta, text):
        """Optional per-turn strategy refinement; only when a function is ON."""
        parts = [self._deterministic_hint(text, user_data, events_raw, memory_meta)]
        rel = self._relationship_of(user_data)
        state = rel.get("state") if isinstance(rel.get("state"), dict) else {}
        repair_state = rel.get("repair_state") if isinstance(rel.get("repair_state"), dict) else {}
        phase = str(repair_state.get("phase") or "stable")
        gate = str((memory_meta or {}).get("gate") or "none")
        try:
            conflict = float(state.get("conflict", 0.5) or 0.5)
            trust = float(state.get("trust", 0.5) or 0.5)
        except Exception:
            conflict, trust = 0.5, 0.5
        try:
            if phase != "stable" and self._llm_v2_cooldown_ok("repair_hint"):
                tag = await self._llm_v2_call(
                    "repair_hint", interpretation.repair_hint_prompt(repair_state),
                    interpretation.parse_repair_hint, event)
                if tag:
                    parts.append("llm_repair=" + tag)
                    self._llm_v2_mark("repair_hint")
            elif events_raw and self._llm_v2_cooldown_ok("empathy_hint"):
                tag = await self._llm_v2_call(
                    "empathy_hint", interpretation.empathy_hint_prompt(events_raw),
                    interpretation.parse_empathy_hint, event)
                if tag:
                    parts.append("llm_empathy=" + tag)
                    self._llm_v2_mark("empathy_hint")
            elif gate in ("semi", "force") and self._llm_v2_cooldown_ok("pragmatics_hint"):
                tag = await self._llm_v2_call(
                    "pragmatics_hint", interpretation.pragmatics_hint_prompt(memory_meta),
                    interpretation.parse_pragmatics_hint, event)
                if tag:
                    parts.append("llm_pragma=" + tag)
                    self._llm_v2_mark("pragmatics_hint")
            elif (conflict < 0.45 and trust > 0.5 and self._llm_v2_cooldown_ok("humor_hint")):
                tag = await self._llm_v2_call(
                    "humor_hint", interpretation.humor_hint_prompt(rel),
                    interpretation.parse_humor_hint, event)
                if tag and tag != "none":
                    parts.append("humor=" + tag)
                    self._llm_v2_mark("humor_hint")
        except Exception as exc:
            logger.warning("[biocore] llm v2 hint failed: %s", exc)
        hint = interpretation.combine_strategy_hint(*parts)
        self._last_strategy_hint = hint
        return hint

    async def _maybe_tom_probe(self, event, core, text, user_data, memory_meta):
        """L-T06: optional bounded ToM annotation; never changes core state."""
        if not self._llm_allowed("tom_probe") or not self._llm_v2_cooldown_ok("tom_probe"):
            return
        try:
            recent = [str(h.get("text") or "") for h in (core.history or [])[-6:]]
            refs = [str(x) for x in (getattr(self, "_last_memory_entries", []) or []) if str(x)][:6]
            proposal = await self._llm_v2_call(
                "tom_probe",
                interpretation.tom_prompt(user_data, recent, memory_lines=refs),
                lambda raw: interpretation.parse_tom_update(raw, allowed_refs=refs),
                event)
            if not proposal:
                return
            updated = relationship_meta.apply_tom_update(user_data, proposal, allowed_refs=refs)
            if updated:
                self._save_user_record(event, updated)
                self._llm_v2_mark("tom_probe")
        except Exception as exc:
            logger.warning("[biocore] tom probe failed: %s", exc)

    async def _maybe_relationship_impression(self, event, core):
        """L-T01: event-driven bounded impression proposals (default OFF)."""
        if not self._llm_allowed("relationship_impression"):
            return
        if not self._llm_v2_cooldown_ok("relationship_impression"):
            return
        try:
            events = [e for e in self._event_archive(12) if isinstance(e, dict)]
            important = [e for e in events
                         if float(e.get("importance", 0.0) or 0.0) >= 0.6]
            if len(important) < 3:
                return
            allowed = [str(e.get("id") or "") for e in important if str(e.get("id") or "")]
            if len(allowed) < 3:
                return
            user_data = self._user_record(event)
            proposal = await self._llm_v2_call(
                "relationship_impression",
                interpretation.relationship_impression_prompt(
                    important, self._relationship_of(user_data)),
                lambda raw: interpretation.parse_relationship_impression(
                    raw, allowed_refs=allowed),
                event)
            if not proposal:
                return
            current = self._relationship_of(user_data)
            updated = relationship_meta.apply_relationship_impression(
                current, proposal, allowed_refs=allowed)
            if not updated:
                return
            user_data["relationship"] = updated
            self._save_user_record(event, user_data)
            self._llm_v2_mark("relationship_impression")
        except Exception as exc:
            logger.warning("[biocore] relationship impression failed: %s", exc)

    async def _maybe_diary(self, event, core):
        """L-T08: at most one bounded diary entry per cooldown (default OFF)."""
        if not self._llm_allowed("diary") or not self._llm_v2_cooldown_ok("diary"):
            return
        try:
            digests = [d for d in (getattr(core, "daily_digests", []) or [])
                       if isinstance(d, dict)]
            if not digests:
                return
            digest = digests[-1]
            allowed = [str(x) for x in (digest.get("event_ids") or []) if str(x)]
            if not allowed:
                return
            titles = [str(e.get("title") or "")
                      for e in self._event_archive(10) if isinstance(e, dict)]
            parsed = await self._llm_v2_call(
                "diary", interpretation.diary_prompt(digest, titles),
                lambda raw: interpretation.parse_diary(raw, allowed_event_ids=allowed),
                event)
            if not parsed:
                return
            diary = self.self_model.get("diary")
            if not isinstance(diary, list):
                diary = []
            diary.append({"ts": time.time(), "date": str(digest.get("date") or ""),
                          "text": parsed["diary"], "evidence": parsed["evidence"],
                          "generated": True})
            self.self_model["diary"] = diary[-30:]
            self._save_self_model()
            self._llm_v2_mark("diary")
        except Exception as exc:
            logger.warning("[biocore] diary failed: %s", exc)

    async def _maybe_relationship_narrative(self, event, core):
        """L-T12: manual/periodic bounded relationship narrative (default OFF)."""
        if not self._llm_allowed("relationship_narrative"):
            return
        if not self._llm_v2_cooldown_ok("relationship_narrative"):
            return
        try:
            user_data = self._user_record(event)
            rel = self._relationship_of(user_data)
            marks = [m for m in (rel.get("milestones") or []) if isinstance(m, dict)]
            allowed = [str(m.get("key") or m.get("type") or "") for m in marks
                       if str(m.get("key") or m.get("type") or "")]
            if not allowed:
                return
            parsed = await self._llm_v2_call(
                "relationship_narrative",
                interpretation.relationship_narrative_prompt(rel),
                lambda raw: interpretation.parse_relationship_narrative(
                    raw, allowed_refs=allowed), event)
            if not parsed:
                return
            items = self.self_model.get("relationship_narratives")
            if not isinstance(items, list):
                items = []
            items.append({"ts": time.time(), "text": parsed["narrative"],
                          "evidence_refs": parsed["evidence_refs"]})
            self.self_model["relationship_narratives"] = items[-5:]
            self._save_self_model()
            self._llm_v2_mark("relationship_narrative")
        except Exception as exc:
            logger.warning("[biocore] relationship narrative failed: %s", exc)


    def _vision_provider_for(self, event=None):
        """Resolve the vision provider for image caption (never a text LLM)."""
        _cfg = self._function_cfg("image_caption")
        _override = _cfg["provider"]
        _pid = ""
        if _override and _override not in ("follow_llm", "main", "default", ""):
            _pid = _override
        if not _pid:
            try:
                _cfg_all = self.context.get_config()
                _ps = _cfg_all.get("provider_settings", {}) if isinstance(_cfg_all, dict) else {}
                _pid = str(_ps.get("default_image_caption_provider_id") or "exusiai-img")
            except Exception:
                _pid = "exusiai-img"
        try:
            _vp = self.context.get_provider_by_id(_pid)
        except Exception as exc:
            logger.warning("[biocore] vision provider lookup failed (%s): %s", _pid, exc)
            return None
        if _vp is not None and self._provider_kind(_vp) == "vision":
            return _vp
        if _vp is not None:
            logger.warning("[biocore] image_caption provider %s is not a vision provider; ignored", _pid)
        # Fall back to the configured default image provider, but never a text LLM.
        try:
            _cfg = self.context.get_config()
            _ps = _cfg.get("provider_settings", {}) if isinstance(_cfg, dict) else {}
            _def = str(_ps.get("default_image_caption_provider_id") or "")
            if _def and _def != _pid:
                _vp2 = self.context.get_provider_by_id(_def)
                if _vp2 is not None and self._provider_kind(_vp2) == "vision":
                    return _vp2
        except Exception:
            pass
        return None

    async def _compile_profile(self, event):
        text = await self._persona_text(event)
        if not text:
            self.profile = dict(DEFAULT_PROFILE)
            self.persona_text = ""
            self.schema_texts = []
            try:
                PROFILE_PATH.write_text(json.dumps(
                    {"persona": "", "profile": self.profile, "schema": [],
                     "style": dict(getattr(self, "persona_style", {}) or {})},
                    ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:
                pass
            return
        if not self._llm_allowed("persona_compile"):
            self.persona_text = text
            logger.info("[biocore] persona_compile disabled; keep saved profile")
            return
        _ph = _sha256(text)
        if getattr(self, "_persona_compiled_hash", "") == _ph and getattr(self, "profile", None):
            # Already compiled for this persona: no extra LLM call.
            self.persona_text = text
            logger.info("[biocore] persona already compiled; skip")
            return
        try:
            provider = await self._provider_for("persona_compile", event)
            if provider is None:
                self.profile = dict(DEFAULT_PROFILE)
                return
            # Prompt construction and output validation belong to the
            # interpretation layer; this wiring only calls it.
            system = interpretation.persona_compile_system()
            prompt = interpretation.persona_compile_prompt(text)
            resp = await provider.text_chat(prompt=prompt, system_prompt=system)
            raw = str(getattr(resp, "completion_text", "") or "")
            _compiled = interpretation.parse_persona_compile(raw, DEFAULT_PROFILE)
            self.profile = _compiled.get("profile") or dict(DEFAULT_PROFILE)
            self.schema_texts = list(_compiled.get("schema") or [])
            _style = _compiled.get("style") if isinstance(_compiled.get("style"), dict) else {}
            self.persona_style = {"intimacy_style": str(_style.get("intimacy_style") or "neutral"),
                                  "address_terms": list(_style.get("address_terms") or [])[:3]}
            logger.info("[biocore] persona schema slots=%s style=%s", len(self.schema_texts),
                        self.persona_style.get("intimacy_style"))
        except Exception as exc:
            logger.warning("[biocore] persona compile failed: %s", exc)
            self.profile = dict(DEFAULT_PROFILE)
        self.persona_text = text
        try:
            PROFILE_PATH.write_text(json.dumps(
                {"persona": self.persona_text, "profile": self.profile,
                 "schema": list(getattr(self, "schema_texts", []) or []),
                 "style": dict(getattr(self, "persona_style", {}) or {}),
                 "persona_hash": _sha256(self.persona_text or text)},
                ensure_ascii=False, indent=1), encoding="utf-8")
            self._persona_compiled_hash = _sha256(self.persona_text or text)
            logger.info("[biocore] first-run profile written: %s", PROFILE_PATH)
        except Exception as exc:
            logger.warning("[biocore] profile save failed: %s", exc)

    def _core(self, event) -> BioCore:
        key = str(getattr(event, "unified_msg_origin", "default") or "default")
        if key not in self.cores:
            core = BioCore(self.profile or DEFAULT_PROFILE)
            try:
                core.valence_decay_minutes = float(getattr(self, "valence_decay_minutes", 120.0))
                core.arousal_decay_minutes = float(getattr(self, "arousal_decay_minutes", 30.0))
                core.social_decay_minutes = float(getattr(self, "social_decay_minutes", 180.0))
            except Exception:
                pass
            try:
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:80]
                f = STATE_DIR / (safe + ".json")
                if f.exists():
                    core.load_state(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
            self.cores[key] = core
        return self.cores[key]

    async def _ensure_profile(self, event):
        if not self.profile and self.first_run_persona_compile:
            await self._compile_profile(event)
        elif not self.profile:
            self.profile = dict(DEFAULT_PROFILE)
            self.persona_text = ""

    def _settings_path(self):
        return DATA_DIR / "settings.json"

    def _load_settings(self):
        try:
            p = self._settings_path()
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                # Single source of truth = AstrBot plugin config. Legacy dashboard
                # toggles in settings.json only apply when config does not define
                # the key (otherwise they silently overrode plugin config).
                for key in ("proactive_reply", "memory_dedup_embedding", "inject_intent",
                            "kb_enabled", "hybrid_retrieval", "safety_enabled",
                            "llm_memory_candidates", "llm_only_reply_summary",
                            "we_memory_enabled"):
                    if key in d and key not in self.config:
                        setattr(self, key, bool(d[key]))
                if "safety_enabled" in d and "safety_enabled" not in self.config:
                    self.safety_enabled = bool(d.get("safety_enabled"))
                    self.cross_session_memory = not self.safety_enabled
                    self.sensitive_memory_protection = self.safety_enabled
                if "persona_id" in d and "persona_id" not in self.config:
                    self.persona_id = str(d.get("persona_id") or "").strip()
                if isinstance(d.get("kb_names"), list) and "kb_names" not in self.config:
                    self.kb_names = [str(x) for x in d.get("kb_names") if str(x).strip()]
        except Exception as exc:
            logger.warning("[biocore] settings load failed: %s", exc)

    def _save_settings(self):
        try:
            self._settings_path().write_text(json.dumps({
                "proactive_reply": bool(self.proactive_reply),
                "memory_dedup_embedding": bool(self.memory_dedup_embedding),
                "hybrid_retrieval": bool(getattr(self, "hybrid_retrieval", True)),
                "safety_enabled": bool(getattr(self, "safety_enabled", False)),
                "llm_memory_candidates": bool(
                    getattr(self, "llm_memory_candidates", True)),
                "we_memory_enabled": bool(getattr(self, "we_memory_enabled", False)),
            "llm_only_reply_summary": bool(
                    getattr(self, "llm_only_reply_summary", True)),
                "persona_id": str(getattr(self, "persona_id", "") or ""),
                "inject_intent": bool(self.inject_intent),
                "kb_enabled": bool(getattr(self, "kb_enabled", False)),
                "kb_names": list(getattr(self, "kb_names", [])),
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:
            logger.warning("[biocore] settings save failed: %s", exc)

    async def _persist_plugin_config(self, updates: dict):
        try:
            if isinstance(self.config, dict):
                self.config.update(updates)
                saver = getattr(self.config, "save_config_async", None)
                if saver:
                    await saver(updates)
                else:
                    saver2 = getattr(self.config, "save_config", None)
                    if saver2:
                        saver2(updates)
        except Exception as exc:
            logger.warning("[biocore] plugin config sync failed: %s", exc)

    def _load_api_config(self):
        try:
            if API_CONFIG_PATH.exists():
                d = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    self.api_config = d
        except Exception as exc:
            logger.warning("[biocore] api config load failed: %s", exc)
            self.api_config = {}
        self._load_llm_functions()

    def _load_llm_functions(self):
        """Load per-function LLM switches and provider overrides.

        Embedding/rerank model selection is intentionally NOT per-function:
        the deterministic event-ranking pipeline always follows the API 接入
        defaults (global embedding, global rerank with deterministic local
        fallback). Legacy configs that stored embedding_provider/rerank_provider
        are migrated by dropping those keys.
        """
        _defaults = {
            _name: {"enabled": LLM_FUNCTION_DEFAULTS[_name],
                    "provider": "follow_llm"}
            for _name in LLM_FUNCTIONS
        }
        _saved = self.api_config.get("functions") if isinstance(self.api_config.get("functions"), dict) else None
        if _saved is None:
            # Legacy migration: strict=true meant "summaries only"; strict=false
            # meant all capabilities available.
            _legacy = bool(getattr(self, "llm_only_reply_summary", True))
            _defaults = {
                _name: {"enabled": (LLM_FUNCTION_DEFAULTS[_name] if _legacy else True),
                         "provider": "follow_llm"}
                for _name in LLM_FUNCTIONS
            }
            self.llm_functions = _defaults
            self.api_config["functions"] = _defaults
            self._save_api_config()
            return
        _merged = {}
        _dropped_legacy = False
        for _name in LLM_FUNCTIONS:
            _raw = _saved.get(_name)
            _item = _raw if isinstance(_raw, dict) else {}
            if isinstance(_raw, dict) and (
                    "embedding_provider" in _raw or "rerank_provider" in _raw):
                _dropped_legacy = True
            _merged[_name] = {
                "enabled": bool(_item.get("enabled", LLM_FUNCTION_DEFAULTS[_name])),
                "provider": str(_item.get("provider") or "follow_llm"),
            }
        self.llm_functions = _merged
        self.api_config["functions"] = _merged
        if _dropped_legacy:
            # Persist the migration once so the dead per-function model keys go
            # away from data/api_config.json.
            self._save_api_config()

    def _save_api_config(self):
        try:
            API_CONFIG_PATH.write_text(json.dumps(self.api_config, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
        except Exception as exc:
            logger.warning("[biocore] api config save failed: %s", exc)

    def _config_providers(self):
        try:
            cfg = self.context.get_config()
            if isinstance(cfg, dict):
                return list(cfg.get("provider") or [])
            getter = getattr(cfg, "get", None)
            if getter:
                return list(getter("provider") or [])
        except Exception:
            pass
        return []

    def _config_provider_sources(self):
        try:
            cfg = self.context.get_config()
            if isinstance(cfg, dict):
                return list(cfg.get("provider_sources") or [])
            getter = getattr(cfg, "get", None)
            if getter:
                return list(getter("provider_sources") or [])
        except Exception:
            pass
        return []

    def _speaker(self, event):
        """Return the current sender's (id, display name) if available."""
        sid = ""
        name = ""
        try:
            fn = getattr(event, "get_sender_id", None)
            if callable(fn):
                sid = str(fn() or "")
        except Exception:
            pass
        try:
            fn = getattr(event, "get_sender_name", None)
            if callable(fn):
                name = str(fn() or "")
        except Exception:
            pass
        try:
            obj = getattr(event, "message_obj", None)
            sender = getattr(obj, "sender", None) if obj is not None else None
            if sender is not None:
                if not sid:
                    sid = str(getattr(sender, "user_id", "") or "")
                if not name:
                    name = str(getattr(sender, "nickname", "") or "")
        except Exception:
            pass
        return sid.strip(), name.strip()

    @staticmethod
    def _image_ref(img) -> str:
        if not isinstance(img, Image):
            return ""
        return str(getattr(img, "url", "") or getattr(img, "file", "") or getattr(img, "path", "") or "").strip()

    def _text_from_components(self, event) -> str:
        parts = []
        try:
            for msg in event.get_messages() or []:
                text = getattr(msg, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        except Exception:
            pass
        return " ".join(parts)

    def _image_refs(self, event) -> list:
        if not getattr(self, "image_recognition_enabled", True):
            return []
        try:
            messages = event.get_messages() or []
        except Exception:
            return []
        refs = []
        private = bool(getattr(event, "is_private_chat", lambda: False)())
        raw_text = str(getattr(event, "message_str", "") or "") + " " + self._text_from_components(event)
        if private:
            for msg in messages:
                if isinstance(msg, Image):
                    ref = self._image_ref(msg)
                    if ref:
                        refs.append(ref)
                if isinstance(msg, Reply):
                    for child in (getattr(msg, "chain", None) or []):
                        ref = self._image_ref(child)
                        if ref:
                            refs.append(ref)
        else:
            if not any(w and w in raw_text for w in (getattr(self, "image_trigger_words", None) or [])):
                return []
            for msg in messages:
                if isinstance(msg, Reply):
                    for child in (getattr(msg, "chain", None) or []):
                        ref = self._image_ref(child)
                        if ref:
                            refs.append(ref)
        seen = set()
        out = []
        for ref in refs:
            if ref not in seen:
                seen.add(ref)
                out.append(ref)
        return out

    def _load_image_cache(self) -> dict:
        try:
            if IMAGE_CACHE_PATH.exists():
                d = json.loads(IMAGE_CACHE_PATH.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
        return {}

    def _save_image_cache(self, cache: dict) -> None:
        try:
            if len(cache) > self.image_cache_max_entries:
                items = sorted(cache.items(), key=lambda kv: float(kv[1].get("ts", 0) or 0), reverse=True)
                cache = dict(items[:self.image_cache_max_entries])
            IMAGE_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("[biocore] image cache save failed: %s", exc)

    async def _image_health_ok(self) -> bool:
        def _check() -> bool:
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.image_service_port}/v1/models",
                    headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    return 200 <= int(resp.status) < 300
            except Exception:
                return False
        try:
            return await asyncio.to_thread(_check)
        except Exception:
            return False

    def _image_idle_watch(self):
        if self._image_proc is None:
            return
        if self._image_idle_task is not None and not self._image_idle_task.done():
            return
        self._image_idle_task = asyncio.create_task(self._image_idle_loop())

    async def _image_idle_loop(self):
        try:
            while True:
                await asyncio.sleep(5)
                if self._image_proc is None:
                    return
                if time.time() - float(self._image_last_used or 0.0) >= self.image_service_idle_seconds:
                    await self._stop_image_service()
                    return
        finally:
            self._image_idle_task = None

    async def _stop_image_service(self):
        proc = self._image_proc
        self._image_proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10, check=False)
        except Exception as exc:
            logger.warning("[biocore] image service stop failed: %s", exc)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        logger.info("[biocore] image service stopped after idle")

    async def _ensure_image_service(self) -> bool:
        self._image_last_used = time.time()
        if await self._image_health_ok():
            return True
        if self._image_service_lock is None:
            self._image_service_lock = asyncio.Lock()
        async with self._image_service_lock:
            if await self._image_health_ok():
                self._image_last_used = time.time()
                return True
            try:
                if (not self.image_llama_server or not self.image_llama_model
                        or not self.image_llama_server.is_file()
                        or not self.image_llama_model.is_file()):
                    logger.warning("[biocore] image service paths missing; configure image_llama_server / image_llama_model")
                    return False
                args = [str(self.image_llama_server), "-m", str(self.image_llama_model)]
                if self.image_llama_mmproj and self.image_llama_mmproj.is_file():
                    args += ["--mmproj", str(self.image_llama_mmproj)]
                args += ["--host", "127.0.0.1", "--port", str(self.image_service_port),
                         "-ngl", "99", "-c", "8192", "-np", "1", "-lm", "none",
                         "-cram", "0", "-ctxcp", "0", "--no-warmup"]
                flags = 0x08000000 if os.name == "nt" else 0
                self._image_proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                                    stderr=subprocess.DEVNULL,
                                                    creationflags=flags)
                logger.info("[biocore] image service starting pid=%s", self._image_proc.pid)
                for _ in range(60):
                    if await self._image_health_ok():
                        self._image_last_used = time.time()
                        self._image_idle_watch()
                        return True
                    await asyncio.sleep(1)
                logger.warning("[biocore] image service did not become ready")
                await self._stop_image_service()
                return False
            except Exception as exc:
                logger.warning("[biocore] image service start failed: %s", exc)
                self._image_proc = None
                return False

    def _load_self_model(self) -> dict:
        d = {
            "who_am_i": "一个会持续受聊天影响、但不会被单条消息完全定义的角色。",
            "boundaries": ["不接受被当作没有感受的工具", "不会被一次互动改写全部立场"],
            "consistency": ["情绪会变，但核心立场不因单次互动翻转"],
            "narrative": "",
            "version": 0,
            "_history": [],
        }
        try:
            if SELF_MODEL_PATH.exists():
                raw = json.loads(SELF_MODEL_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k in d:
                        if k in raw:
                            d[k] = raw[k]
        except Exception:
            pass
        try:
            if not SELF_MODEL_PATH.exists():
                self.self_model = d
                self._save_self_model()
        except Exception:
            pass
        return d

    def _save_self_model(self) -> None:
        try:
            SELF_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.self_model["version"] = int(self.self_model.get("version", 0) or 0) + 1
            _h = list(self.self_model.get("_history") or [])[-20:]
            _h.append({"ts": __import__("time").time(),
                       "who_am_i": self.self_model.get("who_am_i", ""),
                       "narrative": self.self_model.get("narrative", "")})
            self.self_model["_history"] = _h[-20:]
            SELF_MODEL_PATH.write_text(json.dumps(self.self_model, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    def _update_self_narrative(self, title: str, reflection: str) -> None:
        try:
            if not (title or reflection):
                return
            line = ("%s：%s" % (title, reflection)).strip("： ")
            old = str(self.self_model.get("narrative") or "").strip()
            self.self_model["narrative"] = (line + ("；" + old if old else ""))[:600]
            self._save_self_model()
        except Exception:
            pass

    def _user_path(self, event) -> Path:
        sid, _ = self._speaker(event)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (sid or "unknown"))[:60]
        return USER_DIR / (safe + ".json")

    def _we_memory_candidates(self, entries) -> list:
        """Deterministic, evidence-gated we-memory proposals (default off)."""
        out = []
        patterns = (
            ("nickname", ("叫你", "喊你", "外号", "昵称")),
            ("ritual", ("每天", "每次", "习惯", "约好", "固定")),
            ("anniversary", ("纪念日", "周年", "第一次")),
            ("inside_joke", ("梗", "暗号", "约定")),
            ("shared_object", ("我们的", "一起买", "一起做", "送给")),
        )
        for entry in (entries if isinstance(entries, list) else [])[-100:]:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            for mtype, words in patterns:
                if not any(w in text for w in words):
                    continue
                snippet = text[:40]
                out.append({"type": mtype, "text": snippet, "confidence": 0.6,
                            "evidence_refs": [str(entry.get("id") or entry.get("ts") or "m")[:80]]})
                break
        return relationship_meta.merge_we_memory([], out)

    def _touch_user(self, event, core=None) -> dict:
        try:
            sid, name = self._speaker(event)
            USER_DIR.mkdir(parents=True, exist_ok=True)
            path = self._user_path(event)
            d = {}
            if path.exists():
                try:
                    d = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    d = {}
            d["sender_id"] = sid
            d["sender_name"] = name or d.get("sender_name", "")
            try:
                _prev_last_seen = float(d.get("last_seen", 0) or 0)
            except Exception:
                _prev_last_seen = 0.0
            d["interactions"] = int(d.get("interactions", 0) or 0) + 1
            _now_seen = time.time()
            d["absence"] = relationship_meta.absence_state(_prev_last_seen, _now_seen)
            d["last_seen"] = _now_seen
            d.setdefault("first_seen", time.time())
            _session_key = str(getattr(event, "unified_msg_origin", "") or "").strip()
            if _session_key:
                _sessions = d.get("sessions") if isinstance(d.get("sessions"), list) else []
                _sessions = [str(x) for x in _sessions if str(x) and str(x) != _session_key]
                d["sessions"] = (_sessions[-19:] + [_session_key])[-20:]
            try:
                _ct = float(getattr(core, "trust", 0.5)) if core is not None else 0.5
                d["trust"] = round(0.7 * float(d.get("trust", 0.5) or 0.5) + 0.3 * _ct, 3)
            except Exception:
                d["trust"] = d.get("trust", 0.5)
            try:
                _prev_rel = d.get("relationship") if isinstance(d.get("relationship"), dict) else {}
                _prev_state = _prev_rel.get("state") if isinstance(_prev_rel.get("state"), dict) else None
                _opp = getattr(core, "opponent", {}) if core is not None else {}
                _opp_v = _opp.get("v", 0.0) if isinstance(_opp, dict) else 0.0
                _rel_state = relationship_meta.relationship_state(
                    trust=d.get("trust", 0.5),
                    social=getattr(core, "social", 0.5) if core is not None else 0.5,
                    stress=getattr(core, "stress", 0.5) if core is not None else 0.5,
                    opponent=_opp_v,
                    previous=_prev_state,
                )
                _mem_doc = self._load_memory(event)
                _entries = _mem_doc.get("entries") if isinstance(_mem_doc, dict) else []
                try:
                    _social_world = relationship_meta.build_social_world(_entries)
                except Exception:
                    _social_world = []
                _we_memory = []
                try:
                    if getattr(self, "we_memory_enabled", False):
                        _we_memory = self._we_memory_candidates(_entries)
                except Exception:
                    _we_memory = []
                _milestones = []
                try:
                    for _ev in self._event_archive(20):
                        _mk = relationship_meta.milestone_from_text(
                            str(_ev.get("title") or "") + " " + str(_ev.get("event") or ""))
                        if _mk:
                            _mk["ts"] = float(_ev.get("ts", 0) or 0)
                            _milestones.append(_mk)
                except Exception:
                    _milestones = []
                d["relationship"] = relationship_meta.update_relationship_record(
                    _prev_rel,
                    state=_rel_state,
                    ts=d.get("last_seen", time.time()),
                    transactive_map=relationship_meta.build_transactive_map(_entries),
                    destination_map=relationship_meta.build_destination_map(_entries),
                    absence=d.get("absence"),
                    social_world=_social_world,
                    milestones=_milestones,
                    we_memory=_we_memory,
                    interactions=d.get("interactions", 0),
                    repair_success=int((_prev_rel.get("repair_state") or {}).get("repair_attempts", 0) or 0),
                    promises_kept=len([x for x in _milestones if x.get("type") == "promise_kept"]),
                    annotations=(_prev_rel.get("annotations")
                                 if isinstance(_prev_rel.get("annotations"), list) else None),
                )
            except Exception:
                pass
            path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            return d
        except Exception:
            return {}

    def _event_archive(self, limit: int = 5) -> list:
        try:
            if not EVENT_ARCHIVE_PATH.exists():
                return []
            lines = EVENT_ARCHIVE_PATH.read_text(encoding="utf-8").splitlines()
            out = []
            forgotten = []
            for line in lines[-max(1, limit * 3):]:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if not isinstance(d, dict):
                    continue
                if not d.get("peripheral_forgotten"):
                    try:
                        _age_days = (time.time() - float(d.get("ts", 0) or 0)) / 86400.0
                        _central = float(d.get("centrality", 0.5) or 0.5)
                        if _age_days > (14.0 - 10.0 * _central):
                            d["peripheral_details"] = ""
                            d["peripheral_retention"] = min(float(d.get("peripheral_retention", 1.0) or 1.0), 0.05)
                            d["peripheral_forgotten"] = True
                            forgotten.append(dict(d))
                    except Exception:
                        pass
                out.append(d)
            if forgotten:
                self._persist_peripheral_forgetting(forgotten)
            # Recall/event_context are de-duplicated by normalized event_key,
            # newest first; appended duplicates from older versions collapse here.
            dedup = []
            seen = set()
            for d in out[-max(1, limit) * 3:][::-1]:
                key = self._normalize_event_key(
                    str(d.get("event_key") or d.get("title") or ""),
                    str(d.get("title") or ""))
                if key in seen:
                    continue
                seen.add(key)
                dedup.append(d)
                if len(dedup) >= limit:
                    break
            return dedup
        except Exception:
            return []

    @staticmethod
    def _same_archive_event(obj: dict, target: dict) -> bool:
        try:
            if not isinstance(obj, dict) or not isinstance(target, dict):
                return False
            tid = str(target.get("id") or "").strip()
            did = str(obj.get("id") or "").strip()
            if tid and did:
                return tid == did
            if str(obj.get("title") or "") != str(target.get("title") or ""):
                return False
            return abs(float(obj.get("ts", 0) or 0) - float(target.get("ts", 0) or 0)) <= 1.0
        except Exception:
            return False

    def _rewrite_jsonl_atomic(self, path, mutate) -> int:
        """Rewrite a JSONL archive through a sibling temp file + os.replace.

        mutate(obj) returns True when it changed the row. Unparsable lines are
        preserved verbatim and nothing is written unless a row changed.
        """
        tmp = None
        try:
            path = Path(path)
            if not path.exists():
                return 0
            rows = []
            changed = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    rows.append(("raw", line))
                    continue
                try:
                    _changed = bool(mutate(obj))
                except Exception:
                    _changed = False
                if _changed:
                    changed += 1
                rows.append(("obj", obj))
            if not changed:
                return 0
            tmp = path.with_name(path.name + ".tmp_%s_%s" % (os.getpid(), int(time.time() * 1000)))
            with open(tmp, "w", encoding="utf-8") as f:
                for kind, value in rows:
                    if kind == "raw":
                        f.write(str(value) + "\n")
                    else:
                        f.write(json.dumps(value, ensure_ascii=False) + "\n")
            os.replace(tmp, path)
            tmp = None
            return changed
        except Exception as exc:
            logger.warning("[biocore] archive rewrite failed %s: %s", path, exc)
            return 0
        finally:
            try:
                if tmp is not None and Path(tmp).exists():
                    Path(tmp).unlink()
            except Exception:
                pass

    def _persist_peripheral_forgetting(self, events) -> None:
        """Persist periphery forgetting to both archive layers.

        The returned view already hides forgotten details; this keeps the
        global events.jsonl and archives/sessions/<session>/events.jsonl in
        sync through atomic rewrites instead of append-only drift.
        """
        try:
            targets = [d for d in (events or []) if isinstance(d, dict)]
            if not targets:
                return

            def _mutate(obj):
                for target in targets:
                    if not self._same_archive_event(obj, target):
                        continue
                    obj["peripheral_details"] = ""
                    obj["peripheral_retention"] = min(
                        float(obj.get("peripheral_retention", 1.0) or 1.0), 0.05)
                    obj["peripheral_forgotten"] = True
                    return True
                return False

            self._rewrite_jsonl_atomic(EVENT_ARCHIVE_PATH, _mutate)
            seen = set()
            for target in targets:
                _sess = str(target.get("session") or "default")
                _safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in _sess)[:80]
                if _safe in seen:
                    continue
                seen.add(_safe)
                self._rewrite_jsonl_atomic(EVENT_SESSION_DIR / _safe / "events.jsonl", _mutate)
        except Exception as exc:
            logger.warning("[biocore] peripheral forgetting persist failed: %s", exc)

    def _bump_event_recall(self, ids) -> None:
        try:
            if not EVENT_ARCHIVE_PATH.exists() or not ids:
                return
            wanted = set(ids)
            rows = []
            for line in EVENT_ARCHIVE_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if isinstance(d, dict) and d.get("id") in wanted:
                    d["recall_count"] = int(d.get("recall_count", 0) or 0) + 1
                    d["last_recall"] = time.time()
                rows.append(d)
            EVENT_ARCHIVE_PATH.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8")
        except Exception:
            pass

    def _event_context(self, event) -> str:
        events = self._event_archive(9)
        if not events:
            return ""
        events = sorted(events, key=lambda e: float(e.get("importance", 0.0) or 0.0) *
                        (0.5 + 0.5 * float(e.get("centrality", 0.5) or 0.5)), reverse=True)[:3]
        lines = []
        for ev in events:
            title = str(ev.get("title") or "").strip()
            body = str(ev.get("central_details") or ev.get("event") or "").strip()
            meaning = str(ev.get("meaning_to_her") or "").strip()
            reflection = str(ev.get("reflection") or "").strip()
            if body:
                lines.append("- %s：%s%s%s" % (
                    title or "事件", body,
                    ("；意义：" + meaning) if meaning else "",
                    ("；反思：" + reflection) if reflection else ""))
        if not lines:
            return ""
        self._bump_event_recall([str(e.get("id") or "") for e in events])
        return "\n".join(lines)

    def _insights(self, limit: int = 5) -> list:
        try:
            if not INSIGHT_ARCHIVE_PATH.exists():
                return []
            out = []
            for line in INSIGHT_ARCHIVE_PATH.read_text(encoding="utf-8").splitlines()[-limit * 2:]:
                try:
                    d = json.loads(line)
                    if isinstance(d, dict):
                        try:
                            _age_days = (time.time() - float(d.get("ts", 0) or 0)) / 86400.0
                            _central = float(d.get("centrality", 0.5) or 0.5)
                            if _age_days > (14.0 - 10.0 * _central):
                                d["peripheral_details"] = ""
                                d["peripheral_retention"] = min(float(d.get("peripheral_retention", 1.0) or 1.0), 0.05)
                                d["peripheral_forgotten"] = True
                        except Exception:
                            pass
                        out.append(d)
                except Exception:
                    continue
            return out[-limit:][::-1]
        except Exception:
            return []

    def _append_insight(self, record: dict) -> None:
        try:
            EVENT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            with open(INSIGHT_ARCHIVE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _insight_state_path(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return DATA_DIR / "insight_trigger.json"

    def _load_insight_state(self) -> dict:
        try:
            path = self._insight_state_path()
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {"last_run_ts": 0.0, "last_event_ts": 0.0, "seen_ids": []}

    def _save_insight_state(self, state: dict) -> None:
        try:
            self._insight_state_path().write_text(
                json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:
            logger.warning("[biocore] insight trigger state save failed: %s", exc)

    def _insight_trigger_decision(self, state: dict, events: list, now: float | None = None) -> dict:
        """Decide whether the unified insight entry should fire.

        Rules:
        - dedupe by event id + event ts (only events newer than last_event_ts count);
        - >= insight_min_new_events (default 3) new important events
          (importance >= 0.6) AND cooldown >= insight_cooldown_minutes (default 60);
        - 24h ultra-long fallback can fire with at least 1 new important event.
        """
        current = time.time() if now is None else float(now)
        st = state if isinstance(state, dict) else {}
        try:
            last_run = float(st.get("last_run_ts", 0.0) or 0.0)
        except Exception:
            last_run = 0.0
        try:
            last_event_ts = float(st.get("last_event_ts", 0.0) or 0.0)
        except Exception:
            last_event_ts = 0.0
        seen = st.get("seen_ids") if isinstance(st.get("seen_ids"), list) else []
        seen_set = {str(x) for x in seen}
        new_events = []
        for ev in (events or []):
            if not isinstance(ev, dict):
                continue
            try:
                imp = float(ev.get("importance", 0) or 0)
            except Exception:
                imp = 0.0
            if imp < 0.6:
                continue
            eid = str(ev.get("id") or "")
            try:
                ets = float(ev.get("ts", 0) or 0)
            except Exception:
                ets = 0.0
            if eid and eid in seen_set:
                continue
            if ets and ets <= last_event_ts:
                continue
            new_events.append(ev)
        count = len(new_events)
        elapsed = current - last_run if last_run > 0 else None
        _min_new = max(1, int(getattr(self, "_insight_min_new_events",
                                      INSIGHT_MIN_NEW_EVENTS) or INSIGHT_MIN_NEW_EVENTS))
        _cooldown_s = max(60, int(getattr(self, "_insight_cooldown_minutes",
                                          INSIGHT_COOLDOWN_SECONDS // 60)
                                  or (INSIGHT_COOLDOWN_SECONDS // 60)) * 60)
        cooldown_ok = (last_run <= 0) or (elapsed is not None and elapsed >= _cooldown_s)
        fallback_ok = (last_run > 0 and elapsed is not None and
                       elapsed >= self._insight_fallback_hours * 3600)
        ready = (count >= _min_new and cooldown_ok) or (count >= 1 and fallback_ok)
        return {"ready": bool(ready), "new_count": count,
                "new_events": new_events,
                "last_run_ts": last_run, "last_event_ts": last_event_ts}

    async def _maybe_archive_insight(self, event, core, trigger: str = "event_archive"):
        """Automatic long-term insight entry (compression / event archive).

        Only runs when the opt-in auto switch is ON *and* the insight LLM
        switch is ON. There is no silent deterministic fallback: with either
        switch off nothing is written in the background.
        """
        if not bool(getattr(self, "insight_auto_enabled", False)):
            return False
        if not self._llm_allowed("insight"):
            return False
        try:
            state = self._load_insight_state()
            events = self._event_archive(50)
            decision = self._insight_trigger_decision(state, events)
            if not decision["ready"]:
                logger.info("[biocore] insight trigger skipped (%s): new=%s cooldown/fallback not met",
                            trigger, decision["new_count"])
                return False
            new_events = decision["new_events"]
            now = time.time()
            latest_ts = max([decision["last_event_ts"]] +
                            [float(e.get("ts", 0) or 0) for e in events] or [0.0])
            seen = [str(e.get("id") or "") for e in events if str(e.get("id") or "")]
            self._save_insight_state({
                "last_run_ts": now,
                "last_event_ts": latest_ts,
                "seen_ids": seen[-100:],
            })
            recent = (events[-6:] if len(events) >= 3 else new_events[-6:])
            await self._generate_insight(event, core, recent)
            logger.info("[biocore] insight triggered (%s): new=%s events=%s",
                        trigger, decision["new_count"], len(recent))
            return True
        except Exception as exc:
            logger.warning("[biocore] insight trigger failed: %s", exc)
            return False

    async def _generate_insight(self, event, core, events):
        """Generate one long-term pattern insight from the given events.

        LLM-only: when the insight switch is off this returns False and writes
        nothing (no silent deterministic note in the background).
        """
        try:
            events = [e for e in (events or []) if isinstance(e, dict)]
            if not events:
                return False
            if not self._llm_allowed("insight"):
                return False
            provider = await self._provider_for("insight", event)
            if provider is None:
                return False
            prompt = interpretation.insight_prompt(events[-6:])
            resp = await provider.text_chat(prompt=prompt)
            raw = str(getattr(resp, "completion_text", "") or "").strip()
            insight = interpretation.parse_insight(raw)
            if not insight:
                return False
            self._append_insight({
                "ts": time.time(), "insight": insight,
                "emotion": str(getattr(core, "labels", {}).get("emotion") or "neutral") if core else "neutral",
            })
            try:
                if core is not None:
                    tree = getattr(core, "reflection_tree", None)
                    if not isinstance(tree, dict):
                        tree = {"roots": [], "count": 0}
                    node = {"ts": time.time(), "insight": insight,
                            "emotion": str(getattr(core, "labels", {}).get("emotion") or "neutral"),
                            "children": []}
                    roots = tree.get("roots") or []
                    if roots:
                        roots[-1].setdefault("children", []).append(node)
                    else:
                        roots.append(node)
                    tree["roots"] = roots[-10:]
                    tree["count"] = int(tree.get("count", 0)) + 1
                    core.reflection_tree = tree
            except Exception:
                pass
            logger.info("[biocore] long-term insight archived")
            return True
        except Exception as exc:
            logger.warning("[biocore] insight generation failed: %s", exc)
            return False

    async def _archive_cross_event_insight(self, event, core):
        """Compatibility wrapper for direct callers: uses the last 6 events."""
        events = self._event_archive(6)
        if len(events) < 3:
            return
        await self._generate_insight(event, core, events[-6:])

    def _segment_event_texts(self, entries) -> list:
        try:
            rows = []
            for e in entries:
                txt = str(e.get("text", "")).strip()
                cap = str(e.get("image_caption", "") or "").strip()
                if cap:
                    txt = (txt + "\n[图片内容] " + cap).strip() if txt else ("[图片内容] " + cap)
                if txt:
                    rows.append((float(e.get("ts", 0) or 0), txt, e))
            rows.sort(key=lambda x: x[0])
        except Exception:
            return []
        segments = []
        current = []
        last = None
        for ts, txt, e in rows:
            _changed = False
            if current:
                try:
                    _changed = self._text_similarity(str(current[-1][0]), str(txt)) < 0.045 and len(str(txt)) > 8
                except Exception:
                    _changed = False
            if last is not None and ((ts - last > 1800) or _changed) and current:
                segments.append(current)
                current = []
            current.append((txt, e))
            last = ts
        if current:
            segments.append(current)
        out = []
        for seg in segments[-3:]:
            out.append([x[0] for x in seg])
        return out

    def _append_event_archive(self, record: dict) -> None:
        try:
            EVENT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            if isinstance(record, dict):
                _raw_key = str(record.get("event_key") or record.get("title") or "")
                _norm_key = self._normalize_event_key(_raw_key, str(record.get("title") or ""))
                if _norm_key:
                    record["event_key"] = _norm_key
            line = json.dumps(record, ensure_ascii=False)
            with open(EVENT_ARCHIVE_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            _sess = str(record.get("session") or "default")
            _safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in _sess)[:80]
            _dir = EVENT_SESSION_DIR / _safe
            _dir.mkdir(parents=True, exist_ok=True)
            with open(_dir / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as exc:
            logger.warning("[biocore] event archive failed: %s", exc)

    def _attachments_from_messages(self, event) -> list:
        out = []
        try:
            for m in event.get_messages() or []:
                if isinstance(m, Image):
                    ref = str(getattr(m, "url", "") or getattr(m, "file", "") or getattr(m, "path", "") or "").strip()
                    if ref:
                        out.append({"type": "image", "ref": ref[:500]})
                elif isinstance(m, Record):
                    ref = str(getattr(m, "url", "") or getattr(m, "file", "") or "").strip()
                    if ref:
                        out.append({"type": "voice", "ref": ref[:500]})
        except Exception:
            pass
        return out

    def _message_refs(self, event) -> list:
        refs = []
        try:
            for msg in event.get_messages() or []:
                got = False
                for attr in ("id", "message_id", "msg_id", "message_seq"):
                    try:
                        value = getattr(msg, attr, None)
                    except Exception:
                        value = None
                    if value:
                        refs.append(str(value)[:80])
                        got = True
                        break
                if not got:
                    text = str(getattr(msg, "text", "") or "")
                    if text:
                        refs.append(_sha256(text)[:16])
        except Exception:
            pass
        return refs[:8]

    def _memory_provenance(self, event, ts=None) -> dict:
        try:
            _sid, _sname = self._speaker(event)
        except Exception:
            _sid, _sname = "", ""
        return {"sender_id": _sid, "sender_name": _sname,
                "session": str(getattr(event, "unified_msg_origin", "") or ""),
                "ts": float(ts if ts is not None else time.time()),
                "message_refs": self._message_refs(event)}

    def _event_provenance(self, event, entries=None, ts=None) -> dict:
        prov = self._memory_provenance(event, ts)
        sources = []
        refs = list(prov.get("message_refs") or [])
        senders = {str(prov.get("sender_id") or "")}
        if entries:
            for e in entries[-24:]:
                p = e.get("provenance") if isinstance(e, dict) else None
                if not isinstance(p, dict):
                    continue
                item = {"sender_id": str(p.get("sender_id") or ""),
                        "sender_name": str(p.get("sender_name") or ""),
                        "session": str(p.get("session") or ""),
                        "ts": float(p.get("ts", 0) or 0),
                        "message_refs": list(p.get("message_refs") or [])[:6]}
                sources.append(item)
                senders.add(item["sender_id"])
                refs.extend(item["message_refs"])
        prov["sources"] = sources[-24:]
        prov["message_refs"] = list(dict.fromkeys([str(x) for x in refs if x]))[:12]
        prov["senders"] = sorted([x for x in senders if x])
        return prov

    @staticmethod
    def _source_check(text: str, texts, provenance=None, record_ts=None) -> dict:
        try:
            src = "".join(str(t) for t in texts)
            src_chars = {c for c in src if not c.isspace() and c not in "，。！？、；：,.!?;:"}
            body = {c for c in str(text or "") if not c.isspace() and c not in "，。！？、；：,.!?;:"}
            if not body:
                return {"overlap": 0.0, "coverage": 0.0, "novelty": 0.0,
                        "length_ratio": 0.0, "status": "empty",
                        "source_items": [], "time_ok": True, "speaker_ok": True,
                        "cross_ref": 0}
            overlap = sum(1 for c in body if c in src_chars) / max(1, len(body))
            covered = sum(1 for c in src_chars if c in body) / max(1, len(src_chars))
            novelty = max(0.0, len(body - src_chars) / max(1, len(body)))
            ratio = len(str(text or "")) / max(1, len(src))
            source_items = []
            try:
                prov = provenance if isinstance(provenance, dict) else {}
                _srcs = prov.get("sources") if isinstance(prov.get("sources"), list) else []
                if _srcs:
                    source_items = [dict(x) for x in _srcs if isinstance(x, dict)][:24]
                elif prov:
                    source_items = [{
                        "sender_id": str(prov.get("sender_id") or ""),
                        "sender_name": str(prov.get("sender_name") or ""),
                        "session": str(prov.get("session") or ""),
                        "ts": float(prov.get("ts", 0) or 0),
                        "message_refs": list(prov.get("message_refs") or []),
                    }]
            except Exception:
                source_items = []
            # time_ok: evidence cannot postdate the record and must be near it.
            time_ok = True
            try:
                _rts = float(record_ts if record_ts is not None else 0.0)
                _ts = [float(x.get("ts", 0) or 0) for x in source_items
                       if float(x.get("ts", 0) or 0) > 0]
                if _rts > 0 and _ts:
                    time_ok = (max(_ts) <= _rts + 300.0) and ((_rts - min(_ts)) <= 7 * 86400.0)
            except Exception:
                time_ok = True
            # speaker_ok: the claimed speaker must appear among the sources.
            speaker_ok = True
            try:
                _claim_sid = str((provenance or {}).get("sender_id") or "") if isinstance(provenance, dict) else ""
                _sids = {str(x.get("sender_id") or "") for x in source_items if str(x.get("sender_id") or "")}
                if _claim_sid and _sids:
                    speaker_ok = _claim_sid in _sids
            except Exception:
                speaker_ok = True
            # cross_ref: count independent evidence items / message refs.
            cross_ref = 0
            try:
                _refs = set()
                for x in source_items:
                    for r in (x.get("message_refs") or []):
                        _refs.add(str(r))
                cross_ref = max(len(source_items), len(_refs))
            except Exception:
                cross_ref = len(source_items)
            if overlap >= 0.55 and novelty <= 0.25 and ratio <= 1.6:
                status = "ok"
            elif overlap >= 0.35 and novelty <= 0.45:
                status = "weak"
            else:
                status = "suspect"
            if not time_ok or not speaker_ok:
                if status == "ok":
                    status = "weak"
            return {"overlap": round(overlap, 3), "coverage": round(covered, 3),
                    "novelty": round(novelty, 3), "length_ratio": round(ratio, 3),
                    "status": status, "source_items": source_items[:24],
                    "time_ok": bool(time_ok), "speaker_ok": bool(speaker_ok),
                    "cross_ref": int(cross_ref)}
        except Exception:
            return {"overlap": 0.0, "status": "unknown"}

    @staticmethod
    def _event_session_file(session: str) -> Path:
        _safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(session or "default"))[:80]
        return EVENT_SESSION_DIR / _safe / "events.jsonl"

    def _last_session_event(self, session: str):
        try:
            path = self._event_session_file(session)
            if not path.exists():
                return None
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
        return None

    def _event_boundary(self, session: str, body: str, ts: float) -> dict:
        """Zacks et al. (2007) event segmentation for the event archive.

        Boundary = weighted elapsed-time gap + content dissimilarity against
        the previous event in the same session. A boundary below the split
        threshold continues the previous episode and inherits its id as
        parent_event_id; a strong boundary starts a new root event.
        """
        prev = self._last_session_event(session)
        if not isinstance(prev, dict):
            return {"boundary_score": 0.0, "parent_event_id": "",
                    "gap_seconds": 0.0, "similarity": 0.0}
        try:
            gap = max(0.0, float(ts) - float(prev.get("ts", 0) or 0))
        except Exception:
            gap = 0.0
        try:
            sim = float(self._text_similarity(str(body or ""), str(prev.get("event") or prev.get("title") or "")))
        except Exception:
            sim = 0.0
        gap_norm = max(0.0, min(1.0, gap / EVENT_BOUNDARY_WINDOW_SECONDS))
        score = max(0.0, min(1.0, EVENT_BOUNDARY_TIME_WEIGHT * gap_norm
                            + EVENT_BOUNDARY_TEXT_WEIGHT * (1.0 - sim)))
        parent = ""
        if score < EVENT_BOUNDARY_PARENT_THRESHOLD:
            parent = str(prev.get("id") or "")
        return {"boundary_score": round(score, 3), "parent_event_id": parent,
                "gap_seconds": round(gap, 3), "similarity": round(sim, 3)}

    @staticmethod
    def _normalize_event_key(key: str, title: str = "") -> str:
        """Normalize event identity: NFKC, lowercase, punctuation/joiners removed."""
        import unicodedata

        def _norm(value) -> str:
            s = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
            s = s.replace("／", "/").replace("·", "")
            s = re.sub(r"[\s\-_/\\|｜&＆+＋~～,，.。、;；:：!！?？'\"“”‘’()（）\[\]【】<>《》]+", "", s)
            return s[:120]

        out = _norm(key)
        if not out:
            out = _norm(title)
        if not out:
            out = "evt_" + _sha256(str(key) + "|" + str(title))[:12]
        return out

    def _recent_session_events(self, session: str, limit: int = 20) -> list:
        try:
            path = self._event_session_file(session)
            if not path.exists():
                return []
            rows = []
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if isinstance(d, dict):
                    rows.append(d)
                if len(rows) >= limit:
                    break
            return rows
        except Exception:
            return []

    def _find_duplicate_event(self, session: str, event_key: str, body: str, ts: float):
        """Return the same-session archived event this record duplicates."""
        try:
            for prev in self._recent_session_events(session, 20):
                prev_key = self._normalize_event_key(
                    str(prev.get("event_key") or prev.get("title") or ""),
                    str(prev.get("title") or ""))
                if not prev_key:
                    continue
                try:
                    gap = abs(float(ts) - float(prev.get("ts", 0) or 0))
                except Exception:
                    gap = 0.0
                if gap > EVENT_DUP_WINDOW_SECONDS:
                    continue
                if prev_key == event_key:
                    return prev
                if self._text_similarity(prev_key, event_key) >= EVENT_KEY_SIM_THRESHOLD:
                    body_sim = self._text_similarity(str(body or ""), str(prev.get("event") or ""))
                    if body_sim >= 0.45:
                        return prev
        except Exception:
            pass
        return None

    def _find_global_duplicate_event(self, event_key: str, body: str, ts: float):
        """Cross-session event identity: same normalized key + body within window."""
        try:
            if not EVENT_ARCHIVE_PATH.exists():
                return None
            event_key = self._normalize_event_key(str(event_key or ""), "")
            lines = EVENT_ARCHIVE_PATH.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-200:]):
                try:
                    prev = json.loads(line)
                except Exception:
                    continue
                if not isinstance(prev, dict):
                    continue
                prev_key = self._normalize_event_key(
                    str(prev.get("event_key") or prev.get("title") or ""),
                    str(prev.get("title") or ""))
                if not prev_key:
                    continue
                try:
                    gap = abs(float(ts) - float(prev.get("ts", 0) or 0))
                except Exception:
                    gap = 0.0
                if gap > EVENT_DUP_WINDOW_SECONDS:
                    continue
                if prev_key == event_key:
                    return prev
                if self._text_similarity(prev_key, event_key) >= EVENT_KEY_SIM_THRESHOLD:
                    if self._text_similarity(str(body or ""),
                                             str(prev.get("event") or "")) >= 0.45:
                        return prev
        except Exception:
            pass
        return None

    def _find_any_duplicate_event(self, session: str, event_key: str, body: str, ts: float):
        """Same-session duplicate first, then cross-session global duplicate."""
        prev = self._find_duplicate_event(session, event_key, body, ts)
        if prev is not None:
            return prev
        return self._find_global_duplicate_event(event_key, body, ts)

    def _merge_archive_duplicate(self, prev: dict, record: dict) -> None:
        """Merge a duplicate event into the existing archive row atomically."""
        try:
            prev_id = str(prev.get("id") or "")
            if not prev_id:
                return
            _new_key = str(record.get("event_key") or "")
            _new_ts = float(record.get("ts", 0) or 0)
            _new_sources = list((record.get("provenance") or {}).get("sources") or [])[:12]
            _new_texts = list(record.get("source_texts") or [])[:12]

            def _mutate(obj):
                if str(obj.get("id") or "") != prev_id:
                    return False
                merged = [str(x) for x in (obj.get("merged_event_keys") or [])]
                if _new_key and _new_key not in merged:
                    merged.append(_new_key)
                obj["merged_event_keys"] = merged[:12]
                try:
                    obj["ts"] = max(float(obj.get("ts", 0) or 0), _new_ts)
                except Exception:
                    obj["ts"] = _new_ts
                obj["importance"] = round(max(float(obj.get("importance", 0) or 0),
                                              float(record.get("importance", 0) or 0)), 3)
                obj["centrality"] = round(max(float(obj.get("centrality", 0) or 0),
                                              float(record.get("centrality", 0) or 0)), 3)
                obj["merge_count"] = int(obj.get("merge_count", 0) or 0) + 1
                src = [str(x) for x in (obj.get("source_texts") or [])[-24:]]
                for _t in _new_texts:
                    if _t and _t not in src:
                        src.append(str(_t))
                obj["source_texts"] = src[-24:]
                prov = dict(obj.get("provenance") or {})
                sources = [x for x in (prov.get("sources") or []) if isinstance(x, dict)][-24:]
                for _item in _new_sources:
                    if isinstance(_item, dict) and _item not in sources:
                        sources.append(_item)
                prov["sources"] = sources[-24:]
                obj["provenance"] = prov
                return True

            session = str(prev.get("session") or record.get("session") or "default")
            self._rewrite_jsonl_atomic(EVENT_ARCHIVE_PATH, _mutate)
            self._rewrite_jsonl_atomic(self._event_session_file(session), _mutate)
            logger.info("[biocore] duplicate event merged: %s key=%s", prev.get("title"), _new_key)
        except Exception as exc:
            logger.warning("[biocore] duplicate merge failed: %s", exc)

    async def _archive_ranked_events_deterministic(self, event, core, entries):
        """Deterministic event candidate generation + embedding ranking.

        Used when the LLM event_ranking function is off (the default): split
        recent messages into event segments, score them with importance /
        self-schema congruence / embedding novelty / commitment cues, and
        archive the top candidates. The LLM is still optional via event_summary.
        """
        try:
            segments = self._segment_event_texts(entries)
            if not segments:
                return
            now = time.time()
            recent_events = self._event_archive(10)
            candidates = []
            for seg_texts in segments:
                seg_text = "\n".join(str(t) for t in seg_texts if str(t).strip()).strip()
                if len(seg_text) < 8:
                    continue
                seg_set = {str(t).strip() for t in seg_texts if str(t).strip()}
                seg_entries = [e for e in entries
                               if str(e.get("text", "")).strip() in seg_set]
                imp = 0.5
                vecs = []
                for e in seg_entries:
                    try:
                        imp = max(imp, float(e.get("importance", 0.5) or 0.5))
                    except Exception:
                        pass
                    _v = e.get("vector") if isinstance(e.get("vector"), list) else []
                    if _v:
                        vecs.append(_v)
                try:
                    schema = memory_meta.schema_congruence(
                        seg_text, self._self_schema_texts(core))
                except Exception:
                    schema = 0.0
                try:
                    vec = await self._embedding_for("event_ranking", seg_text[:600])
                except Exception:
                    vec = []
                if not vec and vecs:
                    try:
                        dim = len(vecs[0])
                        vec = [sum(float(v[i]) for v in vecs if i < len(v)) / len(vecs)
                               for i in range(dim)]
                    except Exception:
                        vec = []
                novelty = 0.6
                max_cos = 0.0
                for ev in recent_events:
                    _ev = ev.get("event_embedding") if isinstance(ev, dict) else None
                    if isinstance(_ev, list) and _ev:
                        max_cos = max(max_cos, self._cosine(vec, _ev))
                if vec and max_cos > 0:
                    novelty = max(0.0, min(1.0, 1.0 - max_cos))
                cues = sum(1 for w in ("承诺", "答应", "喜欢", "讨厌", "对不起", "谢谢",
                                        "以后", "永远", "骗", "害怕", "难过", "别")
                           if w in seg_text)
                cue_score = min(1.0, cues / 3.0)
                score = 0.35 * imp + 0.25 * schema + 0.20 * novelty + 0.20 * cue_score
                if imp < 0.55 or score < 0.40:
                    continue
                candidates.append((score, seg_text, seg_entries, vec, schema, imp))
            if len(candidates) > 1:
                _docs = [c[1] for c in candidates]
                _rs = await self._rerank_scores(
                    "event_ranking", "最近对话中值得记住的重要事件", _docs)
                if _rs:
                    candidates = [
                        (round(0.6 * c[0] + 0.4 * float(_rs.get(i, 0.0)), 4),
                         c[1], c[2], c[3], c[4], c[5])
                        for i, c in enumerate(candidates)
                    ]
            candidates.sort(key=lambda x: x[0], reverse=True)
            _digest_event_ids = []
            for score, body, seg_entries, vec, schema, imp in candidates[:2]:
                title = body.replace("\n", " ").strip()[:28] or "对话事件"
                _ekey = self._normalize_event_key(title, title)
                prov = self._event_provenance(event, entries, ts=now)
                check = self._source_check(body, [str(t) for t in seg_entries],
                                           provenance=prov, record_ts=now)
                dup = self._find_any_duplicate_event(
                    str(getattr(event, "unified_msg_origin", "") or ""), _ekey, body, now)
                if dup is not None:
                    continue
                _imp = round(max(0.55, min(1.0, imp * 0.7 + score * 0.3)), 3)
                record = {
                    "id": "evt_" + str(int(now)) + "_" + str(abs(hash(title + body)) % 100000),
                    "ts": now,
                    "session": str(getattr(event, "unified_msg_origin", "") or ""),
                    "title": title,
                    "event": body[:600],
                    "event_key": _ekey,
                    "centrality": round(max(0.0, min(1.0, schema)), 3),
                    "central_details": body[:400],
                    "peripheral_details": "",
                    "meaning_to_her": "",
                    "reflection": "",
                    "emotion": str((getattr(core, "labels", {}) or {}).get("emotion") or "neutral") if core else "neutral",
                    "importance": _imp,
                    "appraisal": dict(core.appraisal) if core is not None else {},
                    "confidence": round(max(0.2, min(1.0, 0.55 + 0.45 * float(check.get("overlap", 0)))), 3),
                    "source_count": len(seg_entries),
                    "source_check": check,
                    "provenance": prov,
                    "attachments": [],
                    "modalities": [],
                    "recall_count": 0,
                    "last_recall": now,
                    "strength": _imp,
                    "source_texts": list(seg_texts)[:12],
                    "ranking_mode": "deterministic_embedding",
                    "milestone": relationship_meta.milestone_from_text(title + " " + body),
                }
                if vec:
                    record["event_embedding"] = [round(float(x), 5) for x in vec]
                try:
                    times = [float(e.get("ts", 0) or 0) for e in seg_entries]
                    times = [t for t in times if t > 0]
                    if times:
                        record["time_span"] = {"start_ts": round(min(times), 3),
                                               "end_ts": round(max(times), 3),
                                               "span_seconds": round(max(times) - min(times), 3)}
                except Exception:
                    pass
                self._append_event_archive(record)
                _digest_event_ids.append(record.get("id"))
                logger.info("[biocore] deterministic event archived: %s score=%.2f", title, score)
        except Exception as exc:
            logger.warning("[biocore] deterministic event ranking failed: %s", exc)
        try:
            if core is not None:
                core.update_daily_digest(event_ids=_digest_event_ids)
        except Exception:
            pass
        await self._maybe_archive_insight(event, core, "event_archive")

    async def _archive_ranked_events(self, event, core, entries):
        """Deterministic embedding/rule event extraction (LLM is never used here).

        The event_ranking switch merely enables/disables this local pipeline;
        event summarization stays a separate optional function (event_summary).
        """
        if not entries:
            return
        if not self._llm_allowed("event_ranking"):
            return
        await self._archive_ranked_events_deterministic(event, core, entries)

    async def _archive_strong_event(self, event, core, texts, summary, attachments=None):
        if core is None:
            return
        intensity = float(core._intensity())
        strong = (intensity >= 0.35 or abs(float(core.v)) >= 0.40 or
                  float(core.a) >= 0.75 or float(core.stress) >= 0.65 or
                  (abs(float(core.v)) >= 0.28 and float(core.a) >= 0.60))
        if not strong or not texts:
            return
        if not self._llm_allowed("event_summary"):
            return
        try:
            provider = await self._provider_for("event_summary", event)
            if provider is None:
                return
            prompt = interpretation.event_summary_prompt(texts)
            resp = await provider.text_chat(prompt=prompt)
            raw = str(getattr(resp, "completion_text", "") or "").strip()
            data = interpretation.parse_event_summary(raw)
            title = str(data.get("title") or summary or "重要事件").strip()[:80]
            ev = str(data.get("event") or summary or "").strip()[:600]
            meaning = str(data.get("meaning_to_her") or "").strip()[:400]
            reflection = str(data.get("reflection") or "").strip()[:400]
            if not ev:
                return
            _prov = self._event_provenance(event, None, ts=time.time())
            _check = self._source_check(ev, texts, provenance=_prov, record_ts=_prov.get("ts"))
            _ekey = self._normalize_event_key(title, title)
            _conf = round(max(0.2, min(1.0, 0.55 + 0.45 * float(_check.get("overlap", 0)))), 3)
            record = {
                "id": "evt_" + str(int(time.time())) + "_" + str(abs(hash(summary)) % 100000),
                "ts": time.time(),
                "session": str(getattr(event, "unified_msg_origin", "") or ""),
                "title": title,
                "event": ev,
                "event_key": _ekey,
                "meaning_to_her": meaning,
                "reflection": reflection,
                "emotion": str(core.labels.get("emotion") or "neutral"),
                "importance": round(max(0.5, min(1.0, intensity)), 3),
                "appraisal": dict(core.appraisal),
                "confidence": _conf,
                "source_count": len(texts),
                "source_check": _check,
                "provenance": _prov,
                "attachments": (attachments or [])[:20],
                "modalities": sorted(set(["图片"] if any(a.get("type") == "image" for a in (attachments or [])) else []) | set(["语音"] if any(a.get("type") == "voice" for a in (attachments or [])) else [])),
                "recall_count": 0,
                "last_recall": time.time(),
                "strength": round(max(0.5, min(1.0, intensity)), 3),
                "source_texts": texts[:12],
            }
            _dup = self._find_any_duplicate_event(record.get("session") or "", _ekey, ev,
                                                 record.get("ts") or time.time())
            if _dup is not None:
                record["duplicate_of"] = str(_dup.get("id") or "")
                self._merge_archive_duplicate(_dup, record)
                return
            _bnd = self._event_boundary(record.get("session") or "", ev, record.get("ts") or time.time())
            record["boundary_score"] = _bnd.get("boundary_score", 0.0)
            record["parent_event_id"] = _bnd.get("parent_event_id", "")
            self._append_event_archive(record)
            await self._maybe_archive_insight(event, core, "event_archive")
            try:
                if core is not None:
                    core.update_daily_digest(event_ids=[record.get("id")])
            except Exception:
                pass
            self._update_self_narrative(title, reflection or meaning)
            logger.info("[biocore] strong event archived: %s", title)
        except Exception as exc:
            logger.warning("[biocore] strong event summary failed: %s", exc)

    async def _voice_context(self, event) -> str:
        if not getattr(self, "voice_transcription_enabled", True):
            return ""
        try:
            provider = await self.context.get_using_stt_provider_async(
                getattr(event, "unified_msg_origin", "") or "")
            if provider is None:
                return ""
            texts = []
            for m in event.get_messages() or []:
                if not isinstance(m, Record):
                    continue
                ref = str(getattr(m, "url", "") or getattr(m, "file", "") or getattr(m, "path", "") or "").strip()
                if not ref:
                    continue
                try:
                    txt = await provider.get_text(ref)
                    if str(txt or "").strip():
                        texts.append(str(txt).strip()[:300])
                except Exception as exc:
                    logger.warning("[biocore] voice transcribe failed: %s", exc)
            return "；".join(texts)[:600]
        except Exception as exc:
            logger.warning("[biocore] voice context failed: %s", exc)
            return ""

    async def _image_context(self, event) -> str:
        refs = self._image_refs(event)
        if not refs:
            return ""
        if not self._llm_allowed("image_caption"):
            return ""
        if not await self._ensure_image_service():
            return ""
        self._image_last_used = time.time()
        cache = self._load_image_cache()
        missing = [r for r in refs if _sha256(r) not in cache]
        if missing:
            try:
                cfg = self.context.get_config()
                provider_settings = cfg.get("provider_settings", {}) if isinstance(cfg, dict) else {}
                prompt = interpretation.image_caption_prompt(
                    provider_settings.get("image_caption_prompt"))
                # Image caption always uses the vision provider, never a text LLM.
                provider = self._vision_provider_for(event)
                if provider is not None:
                    for ref in missing[:3]:
                        try:
                            resp = await provider.text_chat(prompt=prompt, image_urls=[ref])
                            caption = interpretation.parse_image_caption(
                                str(getattr(resp, "completion_text", "") or ""))
                        except Exception as exc:
                            logger.warning("[biocore] image caption failed: %s", exc)
                            caption = ""
                        if caption:
                            cache[_sha256(ref)] = {"ref": ref, "caption": caption, "ts": time.time()}
                    self._save_image_cache(cache)
            except Exception as exc:
                logger.warning("[biocore] image provider failed: %s", exc)
        lines = []
        for ref in refs[:3]:
            item = cache.get(_sha256(ref))
            if item and item.get("caption"):
                lines.append(str(item["caption"]))
        self._image_last_used = time.time()
        if not lines:
            return ""
        return "\n".join(lines)

    def _astrbot_tts_default(self):
        try:
            provs = self.context.get_all_tts_providers()
        except Exception:
            provs = []
        p = provs[0] if provs else None
        if p:
            cfg = getattr(p, "provider_config", {}) or {}
            base = str(cfg.get("api_base") or cfg.get("tts_api_base") or "").strip()
            model = str(cfg.get("model") or cfg.get("tts_model") or getattr(p, "model", "") or "").strip()
            key = str(cfg.get("api_key") or cfg.get("tts_api_key") or "").strip()
            if base:
                return {"provider_id": str(cfg.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        for item in self._config_providers():
            if str(item.get("provider_type") or "") != "tts" or item.get("enable") is False:
                continue
            base = str(item.get("api_base") or item.get("tts_api_base") or "").strip()
            model = str(item.get("model") or item.get("tts_model") or "").strip()
            key = str(item.get("api_key") or item.get("tts_api_key") or "").strip()
            if base:
                return {"provider_id": str(item.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        return None

    def _astrbot_image_default(self):
        try:
            provs = self.context.get_all_providers()
        except Exception:
            provs = []
        sources = {str(x.get("id") or ""): x for x in self._config_provider_sources()}
        candidates = []
        for p in provs:
            cfg = getattr(p, "provider_config", {}) or {}
            pid = str(cfg.get("id") or "").lower()
            model = str(getattr(p, "get_model", lambda: "")() or cfg.get("model") or "").lower()
            if "img" in pid or "image" in pid or "img" in model or "image" in model:
                candidates.append((p, cfg))
        if candidates:
            p, cfg = candidates[0]
            src = sources.get(str(cfg.get("provider_source_id") or ""), {})
            base = str(cfg.get("api_base") or src.get("api_base") or "").strip()
            model = str(getattr(p, "get_model", lambda: "")() or cfg.get("model") or "").strip()
            raw = src.get("key") or cfg.get("key") or ""
            if isinstance(raw, list):
                raw = raw[0] if raw else ""
            key = str(raw or "").strip()
            if base:
                return {"provider_id": str(cfg.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        for item in self._config_providers():
            pid = str(item.get("id") or "").lower()
            if item.get("enable") is False or ("img" not in pid and "image" not in pid):
                continue
            src = sources.get(str(item.get("provider_source_id") or ""), {})
            base = str(item.get("api_base") or src.get("api_base") or "").strip()
            model = str(item.get("model") or item.get("id") or "").strip()
            raw = src.get("key") or item.get("key") or ""
            if isinstance(raw, list):
                raw = raw[0] if raw else ""
            key = str(raw or "").strip()
            if base:
                return {"provider_id": str(item.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        return None

    def _astrbot_llm_default(self):
        try:
            provs = self.context.get_all_providers()
        except Exception:
            provs = []
        p = provs[0] if provs else None
        if p:
            cfg = getattr(p, "provider_config", {}) or {}
            base = str(cfg.get("api_base") or "").strip()
            model = str(getattr(p, "get_model", lambda: "")() or cfg.get("model") or "").strip()
            try:
                key = str(p.get_current_key() or "").strip()
            except Exception:
                key = ""
            if base:
                return {"provider_id": str(cfg.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        # fall back to the AstrBot config table (+ provider source)
        sources = {str(x.get("id") or ""): x for x in self._config_provider_sources()}
        for item in self._config_providers():
            if item.get("enable") is False:
                continue
            ptype = str(item.get("provider_type") or "")
            if ptype and ptype != "chat_completion":
                continue
            src = sources.get(str(item.get("provider_source_id") or ""), {})
            base = str(item.get("api_base") or src.get("api_base") or "").strip()
            model = str(item.get("model") or item.get("id") or "").strip()
            raw_key = src.get("key") or item.get("key") or ""
            if isinstance(raw_key, list):
                raw_key = raw_key[0] if raw_key else ""
            key = str(raw_key or "").strip()
            if base:
                return {"provider_id": str(item.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        return None

    def _astrbot_embedding_default(self):
        try:
            provs = self.context.get_all_embedding_providers()
        except Exception:
            provs = []
        p = provs[0] if provs else None
        if p:
            cfg = getattr(p, "provider_config", {}) or {}
            base = str(cfg.get("embedding_api_base") or "").strip()
            model = str(cfg.get("embedding_model") or getattr(p, "model", "") or "").strip()
            key = str(cfg.get("embedding_api_key") or "").strip()
            if base:
                return {"provider_id": str(cfg.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        # fall back to the AstrBot config table
        for item in self._config_providers():
            if str(item.get("provider_type") or "") != "embedding":
                continue
            if item.get("enable") is False:
                continue
            base = str(item.get("embedding_api_base") or "").strip()
            model = str(item.get("embedding_model") or "").strip()
            key = str(item.get("embedding_api_key") or "").strip()
            if base:
                return {"provider_id": str(item.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        return None

    def _astrbot_rerank_default(self):
        try:
            provs = getattr(getattr(self.context, "provider_manager", None),
                            "rerank_provider_insts", []) or []
        except Exception:
            provs = []
        p = provs[0] if provs else None
        if p:
            cfg = getattr(p, "provider_config", {}) or {}
            base = str(cfg.get("rerank_api_base") or "").strip()
            suffix = str(cfg.get("rerank_api_suffix") or "")
            if suffix and base and not base.endswith(suffix):
                base = base.rstrip("/") + "/" + suffix.lstrip("/")
            model = str(cfg.get("rerank_model") or getattr(p, "model", "") or "").strip()
            key = str(cfg.get("rerank_api_key") or "").strip()
            if base:
                return {"provider_id": str(cfg.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        for item in self._config_providers():
            if str(item.get("provider_type") or "") != "rerank":
                continue
            if item.get("enable") is False:
                continue
            base = str(item.get("rerank_api_base") or "").strip()
            suffix = str(item.get("rerank_api_suffix") or "")
            if suffix and base and not base.endswith(suffix):
                base = base.rstrip("/") + "/" + suffix.lstrip("/")
            model = str(item.get("rerank_model") or "").strip()
            key = str(item.get("rerank_api_key") or "").strip()
            if base:
                return {"provider_id": str(item.get("id") or ""), "base_url": base,
                        "model": model, "has_key": bool(key), "_key": key}
        return None

    def _public_api_config(self):
        llm = self._astrbot_llm_default()
        emb = self._astrbot_embedding_default()
        rrk = self._astrbot_rerank_default()
        tts = self._astrbot_tts_default()
        img = self._astrbot_image_default()
        def one(kind, default):
            saved = self.api_config.get(kind) if isinstance(self.api_config.get(kind), dict) else {}
            source = saved.get("source") or ("astrbot" if default else "custom")
            base = saved.get("base_url")
            model = saved.get("model")
            if not base:
                base = (default or {}).get("base_url", "")
            if not model:
                model = (default or {}).get("model", "")
            enabled = saved.get("enabled")
            if enabled is None:
                enabled = bool(default) if kind != "llm" else True
            return {
                "source": source if source in ("astrbot", "custom") else "custom",
                "base_url": base,
                "model": model,
                "key_saved": bool(saved.get("api_key")) or bool((default or {}).get("has_key")),
                "provider_id": (default or {}).get("provider_id", ""),
                "enabled": bool(enabled),
                "voice": str(saved.get("voice") or ""),
                "size": str(saved.get("size") or ""),
                "format": str(saved.get("format") or ""),
            }
        compression = self.api_config.get("compression") if isinstance(self.api_config.get("compression"), dict) else {}
        return {
            "functions": self._functions_public(),
            "llm": one("llm", llm),
            "embedding": one("embedding", emb),
            "rerank": one("rerank", rrk),
            "tts": one("tts", tts),
            "image": one("image", img),
            "compression": {
                "enabled": bool(compression.get("enabled", False)),
                "threshold": int(compression.get("threshold", 6000) or 6000),
                "max_chars": int(compression.get("max_chars", 800) or 800),
            },
        }

    def _functions_public(self) -> dict:
        out = {}
        for _name in LLM_FUNCTIONS:
            _cfg = self._function_cfg(_name)
            out[_name] = {
                "enabled": bool(_cfg["enabled"]),
                "provider": str(_cfg["provider"]),
                "default_enabled": bool(LLM_FUNCTION_DEFAULTS[_name]),
            }
        return out

    def _llm_provider_options(self) -> list:
        out = []
        try:
            for _p in self.context.get_all_providers():
                _cfg = getattr(_p, "provider_config", {}) or {}
                _pid = str(_cfg.get("id") or getattr(_p, "provider_id", "") or "")
                if not _pid:
                    continue
                try:
                    _model = str(getattr(_p, "get_model", lambda: "")() or _cfg.get("model") or "")
                except Exception:
                    _model = str(_cfg.get("model") or "")
                _ptype = str(_cfg.get("provider_type") or getattr(_p, "provider_type", "") or "")
                out.append({"id": _pid, "model": _model, "type": _ptype})
        except Exception:
            out = []
        return out

    @staticmethod
    def _models_url(base: str) -> str:
        b = str(base or "").strip().rstrip("/")
        if b.endswith("/rerank"):
            b = b[:-7].rstrip("/")
        if not b.endswith("/v1"):
            b = b + "/v1"
        return b + "/models"

    async def _fetch_models(self, kind: str, source: str, base_url: str, api_key: str):
        if kind == "llm":
            default = self._astrbot_llm_default()
        elif kind == "embedding":
            default = self._astrbot_embedding_default()
        elif kind == "tts":
            default = self._astrbot_tts_default()
        elif kind == "image":
            default = self._astrbot_image_default()
        else:
            default = self._astrbot_rerank_default()
        if source == "astrbot" and default:
            base_url = default.get("base_url") or base_url
            api_key = default.get("_key") or api_key
        if not base_url:
            return {"status": "error", "message": "no api base"}
        url = self._models_url(base_url)
        def do_request():
            headers = {"Accept": "application/json"}
            if api_key:
                headers["Authorization"] = "Bearer " + api_key
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        try:
            payload = await asyncio.to_thread(do_request)
        except Exception as exc:
            return {"status": "error", "message": "%s: %s" % (type(exc).__name__, exc)}
        items = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get("models") or items.get("data") or []
        models = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    mid = item.get("id") or item.get("model") or item.get("name")
                else:
                    mid = item
                if mid:
                    models.append(str(mid))
        return {"status": "ok", "data": {"models": sorted(set(models))}}

    def _register_page_api(self):
        try:
            register = getattr(self.context, "register_web_api", None)
            if register:
                register("/astrbot_plugin_biocore/page/status", self.page_status, ["GET"],
                         "BioCore dashboard status")
                register("/astrbot_plugin_biocore/page/self_model", self.page_self_model,
                         ["GET", "POST"], "BioCore self model editor")
                register("/astrbot_plugin_biocore/page/toggle", self.page_toggle, ["POST"],
                         "BioCore dashboard toggle")
                register("/astrbot_plugin_biocore/page/api_config", self.page_api_config, ["POST"],
                         "BioCore API config")
                register("/astrbot_plugin_biocore/page/models", self.page_models, ["POST"],
                         "BioCore model list")
                register("/astrbot_plugin_biocore/page/kb_config", self.page_kb_config, ["POST"],
                         "BioCore knowledge base config")
                register("/astrbot_plugin_biocore/page/backup", self.page_backup, ["GET"],
                         "BioCore core backup")
                register("/astrbot_plugin_biocore/page/restore", self.page_restore, ["POST"],
                         "BioCore core restore")
                register("/astrbot_plugin_biocore/page/insight", self.page_insight, ["POST"],
                         "BioCore manual cross-event insight")
                register("/astrbot_plugin_biocore/page/consolidate", self.page_consolidate, ["POST"],
                         "BioCore memory consolidation")
                register("/astrbot_plugin_biocore/page/memory/rollback/<path:session>/<entry_id>",
                         self.page_memory_rollback, ["POST"], "BioCore memory rollback")
                register("/astrbot_plugin_biocore/page/memory/delete/<path:session>/<entry_id>",
                         self.page_memory_delete, ["POST"], "BioCore memory soft delete")
                register("/astrbot_plugin_biocore/page/memory/restore/<path:session>/<entry_id>",
                         self.page_memory_restore, ["POST"], "BioCore memory restore")
        except Exception as exc:
            logger.warning("[biocore] page api register failed: %s", exc)

    def _memory_stats(self):
        sessions = 0
        entries = 0
        try:
            for f in MEMORY_DIR.glob("*.json"):
                sessions += 1
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    entries += len(d.get("entries") or [])
                except Exception:
                    pass
        except Exception:
            pass
        return {"sessions": sessions, "entries": entries}

    async def _kb_available(self):
        try:
            kbs = await self.context.kb_manager.list_kbs()
            return [{"kb_id": str(getattr(k, "kb_id", "")), "kb_name": str(getattr(k, "kb_name", "")),
                     "description": str(getattr(k, "description", "") or "")} for k in (kbs or [])]
        except Exception as exc:
            logger.warning("[biocore] kb list failed: %s", exc)
            return []

    async def page_backup(self):
        import datetime
        buf = io.BytesIO()
        try:
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                root = PLUGIN_DIR
                for name in ("main.py", "metadata.yaml", "README.md", "UPDATE.md",
                             "_conf_schema.json", "preview.png"):
                    f = root / name
                    if f.is_file():
                        z.write(f, "astrbot_plugin_biocore_standalone/" + name)
                pages = root / "pages"
                if pages.is_dir():
                    for f in pages.rglob("*"):
                        if f.is_file() and "__pycache__" not in f.parts:
                            z.write(f, "astrbot_plugin_biocore_standalone/pages/" + str(f.relative_to(pages)))
                for f in DATA_DIR.rglob("*"):
                    if f.is_file() and "__pycache__" not in f.parts:
                        z.write(f, "data/" + str(f.relative_to(DATA_DIR)))
                info = ("BioCore core backup\n"
                        "Contains plugin code + data/ (persona, memory, states, API config).\n"
                        "Do not share: api_config.json may contain API keys.\n")
                z.writestr("BACKUP_INFO.txt", info)
        except Exception as exc:
            logger.warning("[biocore] backup failed: %s", exc)
            return {"status": "error", "message": str(exc)}
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        return {"status": "ok", "data": {
            "filename": "biocore_core_" + stamp + ".zip",
            "mime": "application/zip",
            "base64": base64.b64encode(buf.getvalue()).decode("ascii"),
        }}

    async def page_restore(self):
        from quart import request
        import datetime
        body = await request.get_json(silent=True) or {}
        raw_b64 = str(body.get("base64") or "")
        if not raw_b64:
            return {"status": "error", "message": "empty backup"}
        try:
            raw = base64.b64decode(raw_b64)
            z = zipfile.ZipFile(io.BytesIO(raw))
        except Exception as exc:
            return {"status": "error", "message": "invalid zip: %s" % exc}
        names = [n for n in z.namelist() if n.startswith("data/") and not n.endswith("/")]
        if not names:
            return {"status": "error", "message": "backup has no data/ entries"}
        # automatic safety backup of current data before overwrite
        try:
            backup_dir = DATA_DIR.parent / "restore_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            safety = backup_dir / ("before_restore_" + stamp + ".zip")
            with zipfile.ZipFile(safety, "w", zipfile.ZIP_DEFLATED) as bz:
                for f in DATA_DIR.rglob("*"):
                    if f.is_file() and "__pycache__" not in f.parts:
                        bz.write(f, str(f.relative_to(DATA_DIR)))
        except Exception as exc:
            logger.warning("[biocore] restore safety backup failed: %s", exc)
        count = 0
        try:
            for name in names:
                rel = name[len("data/"):]
                parts = [x for x in rel.split("/") if x not in ("", ".", "..")]
                if not parts:
                    continue
                dest = DATA_DIR.joinpath(*parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                count += 1
        except Exception as exc:
            logger.warning("[biocore] restore failed: %s", exc)
            return {"status": "error", "message": "restore failed: %s" % exc}
        try:
            self._load_profile()
            self._load_settings()
            self._load_api_config()
            self.cores = {}
        except Exception:
            pass
        logger.info("[biocore] restored %s data files", count)
        return {"status": "ok", "data": {"files": count}}

    def _memory_doc_for_session(self, session_key: str) -> tuple[Path, dict]:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(session_key or "default"))[:80]
        path = MEMORY_DIR / (safe + ".json")
        if path.exists():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    return path, d
            except Exception:
                pass
        return path, {"entries": []}

    def _memory_save_doc_for_session(self, path: Path, doc: dict) -> None:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _memory_entry_id(entry: dict) -> str:
        return _memory_entry_id_of(entry)

    @classmethod
    def _memory_find_entry(cls, entries, entry_id: str) -> dict | None:
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if isinstance(entry, dict) and cls._memory_entry_id(entry) == entry_id:
                return entry
        return None

    async def page_memory_rollback(self, session: str, entry_id: str):
        """Rollback one memory entry to its previous version (dashboard API)."""
        try:
            path, doc = self._memory_doc_for_session(session)
            entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
            target = self._memory_find_entry(entries, entry_id)
            if target is None:
                return {"status": "error", "message": "memory entry not found", "data": {}}
            if not memory_meta.rollback_entry(target):
                return {"status": "error", "message": "no previous version", "data": {}}
            try:
                _vec = await self._embed_text(str(target.get("text", "")))
                if _vec:
                    target["vector"] = _vec
                    target["needs_reindex"] = False
                else:
                    target["needs_reindex"] = True
            except Exception:
                target["needs_reindex"] = True
            target["rollback_ts"] = time.time()
            self._memory_save_doc_for_session(path, doc)
            return {"status": "ok", "data": {"session": session, "id": entry_id, "text": target.get("text", "")[:160]}}
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180], "data": {}}

    async def page_memory_delete(self, session: str, entry_id: str):
        """Soft-delete one memory entry; keeps a tombstone for audit."""
        try:
            path, doc = self._memory_doc_for_session(session)
            entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
            target = self._memory_find_entry(entries, entry_id)
            if target is None:
                return {"status": "error", "message": "memory entry not found", "data": {}}
            doc["tombstones"] = (doc.get("tombstones") if isinstance(doc.get("tombstones"), list) else [])[-100:]
            doc["tombstones"].append({"id": entry_id, "ts": time.time(), "text": str(target.get("text", ""))[:200]})
            doc["entries"] = [e for e in entries if not (isinstance(e, dict) and self._memory_entry_id(e) == entry_id)]
            memory_meta.append_write_log(doc, op="DELETE", entry_id=entry_id,
                                         reason="dashboard", ts=time.time())
            # Propagate the deletion to derived summaries/events/insights.
            try:
                _event = types.SimpleNamespace(unified_msg_origin=session)
                self._propagate_memory_deletion(_event, target, doc, reason="dashboard")
            except Exception:
                pass
            self._memory_save_doc_for_session(path, doc)
            return {"status": "ok", "data": {"session": session, "id": entry_id, "deleted": True}}
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180], "data": {}}

    async def page_memory_restore(self, session: str, entry_id: str):
        """Restore a soft-deleted entry, or recreate one from a tombstone.

        Note: archive/insight redactions made at deletion time are not undone
        (deletion propagation is one-way for derived artifacts).
        """
        try:
            path, doc = self._memory_doc_for_session(session)
            entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
            target = self._memory_find_entry(entries, entry_id)
            from_tombstone = False
            if target is not None:
                if not memory_meta.restore_entry(target):
                    return {"status": "error", "message": "memory entry is not deleted",
                            "data": {}}
            else:
                tombstones = doc.get("tombstones") if isinstance(doc.get("tombstones"), list) else []
                tomb = next((item for item in tombstones if isinstance(item, dict)
                             and str(item.get("id") or "") == entry_id), None)
                if tomb is None:
                    return {"status": "error", "message": "memory entry not found", "data": {}}
                target = {"id": entry_id,
                          "text": str(tomb.get("text") or "")[:1200],
                          "role": "user", "ts": time.time(), "hits": 1,
                          "importance": 0.5, "memory_source": "inferred",
                          "memory_confidence": 0.35, "memory_tier": "warm",
                          "last_write_op": "RESTORE",
                          "restored_from_tombstone": True}
                doc["tombstones"] = [item for item in tombstones
                                     if not (isinstance(item, dict)
                                             and str(item.get("id") or "") == entry_id)]
                entries.append(target)
                from_tombstone = True
            try:
                _vec = await self._embed_text(str(target.get("text", "")))
                if _vec:
                    target["vector"] = _vec
                    target["needs_reindex"] = False
                else:
                    target["needs_reindex"] = True
            except Exception:
                target["needs_reindex"] = True
            target["restored_ts"] = time.time()
            target["last_write_op"] = "RESTORE"
            memory_meta.append_write_log(
                doc, op="RESTORE", entry_id=entry_id,
                reason=("tombstone" if from_tombstone else "soft_delete"),
                ts=time.time())
            self._memory_save_doc_for_session(path, doc)
            return {"status": "ok", "data": {"session": session, "id": entry_id,
                                            "text": str(target.get("text") or "")[:160],
                                            "restored": True,
                                            "from_tombstone": from_tombstone}}
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180], "data": {}}

    async def page_consolidate(self):
        """Force one memory consolidation pass over all local sessions."""
        results = []
        try:
            files = sorted(MEMORY_DIR.glob("*.json"))
        except Exception:
            files = []
        if getattr(self, "_consolidating", False):
            return {"status": "ok", "data": {"files": 0, "message": "already running"}}
        self._consolidating = True
        try:
            for f in files:
                key = f.stem
                ev = types.SimpleNamespace(unified_msg_origin=key)
                try:
                    core = self._core(ev)
                    await self._consolidate_memory(ev, core, force=True)
                    results.append(key)
                except Exception as exc:
                    logger.warning("[biocore] manual consolidation failed: %s", exc)
        finally:
            self._consolidating = False
            self._last_consolidation = time.time()
        return {"status": "ok", "data": {"files": len(results), "sessions": len(files)}}

    def _working_set_preview(self, key: str) -> dict:
        """Bounded working-set exposure for the dashboard/evals (no new mechanism)."""
        try:
            doc = self._load_memory(types.SimpleNamespace(unified_msg_origin=str(key or "")))
            ws = doc.get("working_set") if isinstance(doc, dict) else []
            ids = [str(x) for x in (ws or []) if str(x)][-8:]
            return {"capacity": 8, "count": len(ids), "ids": ids}
        except Exception:
            return {"capacity": 8, "count": 0, "ids": []}

    async def page_status(self):
        _personas = []
        try:
            _pm = getattr(self.context, "persona_manager", None)
            if _pm is not None:
                for _p in (await _pm.get_all_personas()):
                    _pid = str(getattr(_p, "persona_id", "") or "")
                    _pname = str(getattr(_p, "name", "") or _pid)
                    if _pid:
                        _personas.append({"id": _pid, "name": _pname})
        except Exception:
            _personas = []
        cores = []
        for key, core in list(self.cores.items())[:20]:
            cores.append({
                "key": key,
                "snapshot": core.snapshot(),
                "intent": {**core.intent(), "plan": interpretation.plan(core)},
                "working_set": self._working_set_preview(key),
            })
        if not cores:
            # The in-memory cache is empty after a restart. Load persisted
            # states so the dashboard does not silently fall back to demo data.
            try:
                files = sorted(STATE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:20]
            except Exception:
                files = []
            for path in files:
                try:
                    state = json.loads(path.read_text(encoding="utf-8"))
                    core = BioCore(self.profile)
                    core.load_state(state)
                    cores.append({
                        "key": path.stem,
                        "snapshot": core.snapshot(),
                        "intent": {**core.intent(), "plan": interpretation.plan(core)},
                        "working_set": self._working_set_preview(path.stem),
                    })
                except Exception:
                    continue
        return {"status": "ok", "data": {
            "enabled": self.enabled,
            "inject_intent": self.inject_intent,
            "proactive_reply": self.proactive_reply,
            "memory_dedup_embedding": self.memory_dedup_embedding,
            "hybrid_retrieval": bool(getattr(self, "hybrid_retrieval", True)),
            "safety_enabled": bool(getattr(self, "safety_enabled", False)),
            "llm_memory_candidates": bool(
                getattr(self, "llm_memory_candidates", True)),
            "we_memory_enabled": bool(getattr(self, "we_memory_enabled", False)),
            "llm_only_reply_summary": bool(
                getattr(self, "llm_only_reply_summary", True)),
            "insight_auto_enabled": bool(getattr(self, "insight_auto_enabled", False)),
            "persona_loaded": bool(self.persona_text),
            "persona_id": str(getattr(self, "persona_id", "") or ""),
            "personas": _personas,
            "llm_functions": self._functions_public(),
            "llm_providers": self._llm_provider_options(),
            "profile": self.profile or dict(DEFAULT_PROFILE),
            "api_config": self._public_api_config(),
            "memory": self._memory_stats(),
            # Read-only dashboard contract (bounded): memory entries per
            # session with provenance/confidence/write-op metadata, tombstone
            # audit rows, and per-user relationship state/trajectory/maps.
            "memory_index": _memory_index_rows(MEMORY_DIR),
            "relationships": _relationship_rows(USER_DIR),
            "last_memory_meta": dict(getattr(self, "_last_memory_meta", {}) or {}),
            "last_memory_trace": dict(getattr(self, "_last_memory_trace", {}) or {}),
            # Paper mechanisms also at top level for dashboard/API consumers.
            "circadian_alertness": round(float(getattr(cores[0], "circadian_alertness", 0.5)), 3) if cores else 0.5,
            "allostatic_load": round(float(getattr(cores[0], "allostatic_load", 0.0)), 3) if cores else 0.0,
            # L-T02/L-T03..L-T12 read-only runtime surface (bounded, no prompt text)
            "last_cause_trace": [dict(x) for x in (getattr(self, "_last_cause_trace", []) or [])[:8]
                                 if isinstance(x, dict)],
            "last_strategy_hint": str(getattr(self, "_last_strategy_hint", "") or "")[:140],
            "kb_config": {"enabled": bool(getattr(self, "kb_enabled", False)),
                          "names": list(getattr(self, "kb_names", []))},
            "kb_available": await self._kb_available(),
            "astrbot_llm": {k: v for k, v in (self._astrbot_llm_default() or {}).items() if not k.startswith("_")},
            "astrbot_embedding": {k: v for k, v in (self._astrbot_embedding_default() or {}).items() if not k.startswith("_")},
            "astrbot_rerank": {k: v for k, v in (self._astrbot_rerank_default() or {}).items() if not k.startswith("_")},
            "astrbot_tts": {k: v for k, v in (self._astrbot_tts_default() or {}).items() if not k.startswith("_")},
            "astrbot_image": {k: v for k, v in (self._astrbot_image_default() or {}).items() if not k.startswith("_")},
            "cores": cores,
            "self_model": dict(self.self_model or {}),
            "events": self._event_archive(30),
            "insights": self._insights(5),
        }}

    async def page_self_model(self):
        from quart import request
        if request.method == "POST":
            body = await request.get_json(silent=True) or {}
            for key in ("who_am_i", "boundaries", "consistency", "narrative"):
                if key not in body:
                    continue
                val = body.get(key)
                if key in ("boundaries", "consistency"):
                    if isinstance(val, str):
                        val = [x.strip() for x in val.splitlines() if x.strip()]
                    self.self_model[key] = [str(x)[:300] for x in (val or [])[:10]]
                else:
                    self.self_model[key] = str(val or "")[:1500]
            self._save_self_model()
        return {"status": "ok", "data": {"self_model": self.self_model}}

    async def page_toggle(self):
        from quart import request
        data = await request.get_json(silent=True) or {}
        key = str(data.get("key") or "").strip()
        _fn_enabled = {("%s_enabled" % _name): _name for _name in LLM_FUNCTIONS}
        _fn_provider = {("%s_provider" % _name): _name for _name in LLM_FUNCTIONS}
        if key in _fn_enabled or key in _fn_provider:
            _name = _fn_enabled.get(key) or _fn_provider.get(key)
            _cur = dict(self.llm_functions.get(_name) or {})
            if key in _fn_enabled:
                _cur["enabled"] = bool(data.get("value"))
            else:
                _cur["provider"] = str(data.get("value") or "follow_llm").strip() or "follow_llm"
            _cur.pop("embedding_provider", None)
            _cur.pop("rerank_provider", None)
            self.llm_functions[_name] = _cur
            self.api_config["functions"] = dict(self.llm_functions)
            self._save_api_config()
            return {"status": "ok", "data": {"key": key, "value": _cur.get("enabled") if key in _fn_enabled else _cur.get("provider")}}
        if key not in ("proactive_reply", "memory_dedup_embedding", "inject_intent",
                       "hybrid_retrieval", "safety_enabled", "llm_memory_candidates",
                       "llm_only_reply_summary", "persona_id",
                       "insight_auto_enabled"):
            return {"status": "error", "message": "unknown setting"}
        if key == "persona_id":
            _val = str(data.get("value") or "").strip()
            self.persona_id = _val
            self._save_settings()
            await self._persist_plugin_config({key: _val})
            return {"status": "ok", "data": {"key": key, "value": _val}}
        if key == "llm_only_reply_summary":
            # Legacy master switch: keep it readable, but migrate all per-function
            # routes once instead of treating it as the only switch.
            self.llm_only_reply_summary = bool(data.get("value"))
            _legacy = bool(self.llm_only_reply_summary)
            for _name in LLM_FUNCTIONS:
                self.llm_functions[_name] = {
                    "enabled": (LLM_FUNCTION_DEFAULTS[_name] if _legacy else True),
                    "provider": str((self.llm_functions.get(_name) or {}).get("provider") or "follow_llm"),
                }
            self.api_config["functions"] = dict(self.llm_functions)
            self._save_api_config()
            self._save_settings()
            await self._persist_plugin_config({key: bool(self.llm_only_reply_summary)})
            return {"status": "ok", "data": {"key": key, "value": self.llm_only_reply_summary}}
        if key == "safety_enabled":
            self.safety_enabled = bool(data.get("value"))
            self.cross_session_memory = not self.safety_enabled
            self.sensitive_memory_protection = self.safety_enabled
            self._save_settings()
            await self._persist_plugin_config({key: self.safety_enabled})
            logger.info("[biocore] safety_enabled=%s", self.safety_enabled)
            return {"status": "ok", "data": {"key": key, "value": self.safety_enabled}}
        setattr(self, key, bool(data.get("value")))
        self._save_settings()
        await self._persist_plugin_config({key: bool(getattr(self, key))})
        logger.info("[biocore] setting %s=%s", key, getattr(self, key))
        return {"status": "ok", "data": {"key": key, "value": getattr(self, key)}}

    async def generate_manual_insight(self) -> dict:
        """Manual long-term insight (dashboard button), bypass threshold once.

        Never writes a deterministic fallback: when the insight LLM switch is
        off it only returns a message telling the user to enable it.
        """
        if not self._llm_allowed("insight"):
            return {"generated": False, "insight": "",
                    "message": "请先开启「长期模式洞察」LLM 开关再生成"}
        events = self._event_archive(12)
        if not events:
            return {"generated": False, "insight": "", "message": "还没有归档事件"}
        core = next(iter(self.cores.values()), None)
        if core is None:
            core = BioCore(dict(DEFAULT_PROFILE))
        key = next(iter(self.cores), "") or ""
        ev = types.SimpleNamespace(unified_msg_origin=key)
        ok = await self._generate_insight(ev, core, events[-6:])
        insight = ""
        try:
            if INSIGHT_ARCHIVE_PATH.exists():
                lines = [x for x in INSIGHT_ARCHIVE_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]
                if lines:
                    insight = str(json.loads(lines[-1]).get("insight") or "")
        except Exception:
            insight = ""
        if ok:
            try:
                # A manual generation also advances the auto dedupe state so
                # the background trigger does not immediately duplicate it.
                now = time.time()
                latest_ts = max([float(e.get("ts", 0) or 0) for e in events] or [0.0])
                seen = [str(e.get("id") or "") for e in events if str(e.get("id") or "")]
                self._save_insight_state({"last_run_ts": now, "last_event_ts": latest_ts,
                                          "seen_ids": seen[-100:]})
            except Exception:
                pass
        return {"generated": bool(ok), "insight": insight, "events": len(events),
                "message": "" if ok else "生成失败，请查看日志"}

    async def page_insight(self):
        """Manual '生成长期洞察' button: bypass threshold/cooldown once."""
        from quart import request
        _ = await request.get_json(silent=True) or {}
        return {"status": "ok", "data": await self.generate_manual_insight()}

    async def page_api_config(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        for kind in ("llm", "embedding", "rerank", "tts", "image"):
            incoming = body.get(kind)
            if not isinstance(incoming, dict):
                continue
            source = str(incoming.get("source") or "custom").strip()
            if source not in ("astrbot", "custom"):
                source = "custom"
            old = self.api_config.get(kind) if isinstance(self.api_config.get(kind), dict) else {}
            key = str(incoming.get("api_key") or "").strip()
            if not key:
                key = str(old.get("api_key") or "")
            entry = {
                "source": source,
                "base_url": str(incoming.get("base_url") or "").strip(),
                "api_key": key,
                "model": str(incoming.get("model") or "").strip(),
                "enabled": bool(incoming.get("enabled", True)),
            }
            for extra in ("voice", "size", "format"):
                if extra in incoming:
                    entry[extra] = str(incoming.get(extra) or "").strip()
            self.api_config[kind] = entry
        _incoming_functions = body.get("functions")
        if isinstance(_incoming_functions, dict):
            for _name in LLM_FUNCTIONS:
                _item = _incoming_functions.get(_name)
                if not isinstance(_item, dict):
                    continue
                _cur = dict(self.llm_functions.get(_name) or {})
                if "enabled" in _item:
                    _cur["enabled"] = bool(_item.get("enabled"))
                if "provider" in _item:
                    _cur["provider"] = str(_item.get("provider") or "follow_llm").strip() or "follow_llm"
                _cur.pop("embedding_provider", None)
                _cur.pop("rerank_provider", None)
                self.llm_functions[_name] = _cur
            self.api_config["functions"] = dict(self.llm_functions)
        comp = body.get("compression")
        if isinstance(comp, dict):
            self.api_config["compression"] = {
                "enabled": bool(comp.get("enabled", False)),
                "threshold": max(1000, int(comp.get("threshold", 6000) or 6000)),
                "max_chars": max(120, int(comp.get("max_chars", 800) or 800)),
            }
        self._save_api_config()
        logger.info("[biocore] api config saved")
        return {"status": "ok", "data": self._public_api_config()}

    async def page_kb_config(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        self.kb_enabled = bool(body.get("enabled", False))
        names = body.get("names") if isinstance(body.get("names"), list) else []
        self.kb_names = [str(x).strip() for x in names if str(x).strip()]
        self._save_settings()
        await self._persist_plugin_config({"kb_enabled": self.kb_enabled,
                                           "kb_names": self.kb_names})
        logger.info("[biocore] kb config enabled=%s names=%s", self.kb_enabled, self.kb_names)
        return {"status": "ok", "data": {"enabled": self.kb_enabled, "names": self.kb_names}}

    async def page_models(self):
        from quart import request
        body = await request.get_json(silent=True) or {}
        kind = str(body.get("kind") or "embedding").strip()
        source = str(body.get("source") or "custom").strip()
        return await self._fetch_models(kind, source,
                                        str(body.get("base_url") or ""),
                                        str(body.get("api_key") or ""))

    @staticmethod
    def _ipv4_json(url: str, headers: dict, payload: dict, timeout: float = 12.0) -> dict:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            raise ValueError("invalid url")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        class _IPv4HTTPSConnection(http.client.HTTPSConnection):
            def connect(self):
                infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
                ip = infos[0][4][0]
                sock = socket.create_connection((ip, self.port), self.timeout)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

        if parsed.scheme == "https":
            conn = _IPv4HTTPSConnection(host, port, timeout=timeout,
                                         context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status >= 400:
                raise RuntimeError("http %s: %s" % (resp.status, raw[:300].decode("utf-8", "replace")))
            return json.loads(raw.decode("utf-8", "replace"))
        finally:
            conn.close()

    def _embedding_runtime_config(self):
        saved = self.api_config.get("embedding") if isinstance(self.api_config.get("embedding"), dict) else {}
        if saved.get("source") == "custom" and saved.get("base_url"):
            return {"base_url": saved.get("base_url"), "api_key": saved.get("api_key", ""),
                    "model": saved.get("model", "")}
        d = self._astrbot_embedding_default()
        if d and d.get("base_url"):
            return {"base_url": d.get("base_url"), "api_key": d.get("_key", ""),
                    "model": d.get("model", "")}
        if saved.get("base_url"):
            return {"base_url": saved.get("base_url"), "api_key": saved.get("api_key", ""),
                    "model": saved.get("model", "")}
        return None

    async def _embedding_for(self, kind: str, text: str):
        """Embedding for one function; always follows the API 接入 default.

        Per-function embedding model selection was removed by user request:
        every function uses the same global embedding configuration. ``kind``
        is kept for call-site clarity and tests.
        """
        return await self._embed_text(text)

    async def _rerank_scores(self, kind: str, query: str, documents: list):
        """Optional global rerank scores keyed by candidate index (None = local).

        Event ranking never asks the user to pick a model: it follows the
        API 接入 / AstrBot default rerank provider and falls back to the
        deterministic local ranking when no provider is configured or the call
        fails. ``kind`` is kept for call-site clarity and tests.
        """
        try:
            _provs = getattr(getattr(self.context, "provider_manager", None),
                             "rerank_provider_insts", []) or []
        except Exception:
            _provs = []
        _target = _provs[0] if _provs else None
        if _target is None:
            return None
        try:
            _results = await _target.rerank(query, [str(d) for d in documents], top_n=len(documents))
            out = {}
            for _r in (_results or []):
                try:
                    _idx = int(getattr(_r, "index", None))
                    _score = float(getattr(_r, "relevance_score", 0.0) or 0.0)
                except Exception:
                    continue
                out[_idx] = max(0.0, min(1.0, _score))
            return out or None
        except Exception as exc:
            logger.warning("[biocore] global rerank failed; fallback to local ranking: %s", exc)
            return None

    async def _embed_text(self, text: str):
        text = (text or "").strip()
        if not text:
            return None
        conf = self._embedding_runtime_config()
        if not conf:
            return None
        model = str(conf.get("model") or "").strip()
        cache_key = (model, text[:1200])
        if cache_key in EMBED_CACHE:
            return EMBED_CACHE[cache_key]
        base = str(conf.get("base_url") or "").rstrip("/")
        if base.endswith("/embeddings"):
            base = base[:-11]
        url = base + "/embeddings"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if conf.get("api_key"):
            headers["Authorization"] = "Bearer " + str(conf.get("api_key"))
        payload = {"model": model, "input": [text[:2000]], "encoding_format": "float"}
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(self._ipv4_json, url, headers, payload, 12.0), timeout=15.0)
            vec = data["data"][0]["embedding"]
            if not isinstance(vec, list) or not vec:
                return None
            if len(EMBED_CACHE) > 128:
                EMBED_CACHE.clear()
            EMBED_CACHE[cache_key] = vec
            return vec
        except Exception as exc:
            logger.warning("[biocore] embedding failed: %s", exc)
            return None

    @staticmethod
    def _cosine(a, b) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    @staticmethod
    def _usable_memory_text(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return False
        if t.startswith("注意，你正在社交媒体"):
            return False
        if t.startswith("[BioCore]"):
            return False
        return True

    def _memory_path(self, event):
        key = str(getattr(event, "unified_msg_origin", "default") or "default")
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:80]
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        return MEMORY_DIR / (safe + ".json")

    def _load_memory(self, event):
        try:
            d = json.loads(self._memory_path(event).read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("entries"), list):
                d["entries"] = [e for e in d["entries"]
                                if isinstance(e, dict)
                                and self._usable_memory_text(str(e.get("text", "")))]
                try:
                    for entry in d["entries"]:
                        entry.setdefault("inhibition", 0.0)
                        entry.setdefault("suppression_count", 0)
                        entry.setdefault("memory_tier", "warm")
                        # Lazy migration: pre-provenance data is direct user/
                        # model input, not "unknown". This runs for every old
                        # entry on load, then persists on the next save.
                        if not entry.get("memory_source") and not entry.get("memory_confidence"):
                            entry["memory_source"] = "direct"
                            entry["memory_confidence"] = 0.7
                            entry["legacy_backfilled"] = True
                    if int(d.get("schema_version", 0) or 0) < MEMORY_SCHEMA_VERSION:
                        d["schema_version"] = MEMORY_SCHEMA_VERSION
                except Exception:
                    pass
                return d
        except Exception:
            pass
        return {"entries": []}

    def _save_memory(self, event, doc):
        try:
            if isinstance(doc, dict):
                doc["schema_version"] = MEMORY_SCHEMA_VERSION
            self._memory_path(event).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("[biocore] memory save failed: %s", exc)

    def _memory_bio(self, core):
        if core is None:
            return None
        return core

    def _memory_importance(self, core, role: str) -> float:
        if core is None:
            return 0.5
        salience = 0.25 + 0.35 * float(getattr(core, "a", 0.5)) + 0.25 * abs(float(getattr(core, "v", 0.0)))
        salience += 0.15 * (1.0 - float(getattr(core, "trust", 0.5)))
        if role == "assistant":
            salience *= 0.9
        return max(0.15, min(1.0, salience))

    @staticmethod
    def _restabilize_if_expired(entry: dict, now=None) -> bool:
        """Nader reconsolidation: an expired labile window restabilizes.

        Recall is the moment the memory is re-touched, so it is also the
        moment a stale destabilized window must be closed and timestamped.
        """
        try:
            if not isinstance(entry, dict):
                return False
            if entry.get("reconsolidation_state") != "destabilized":
                return False
            _now = time.time() if now is None else float(now)
            if float(entry.get("destabilized_until", 0) or 0) >= _now:
                return False
            entry["reconsolidation_state"] = "restabilized"
            entry["restabilized_ts"] = _now
            return True
        except Exception:
            return False


    def _memory_score_parts(self, core, entry: dict, cosine: float, *,
                            query_text: str = "", hybrid: bool = False,
                            sensitive_protect: bool = False) -> dict:
        """Return the deterministic score plus its bounded component factors.

        L-T02/C-T01: storing the factors here lets the runtime expose an
        auditable retrieval-contribution trace without the LLM ever generating
        one and without changing the ranking math.
        """
        importance = float(entry.get("importance", 0.5) or 0.5)
        age = max(0.0, time.time() - float(entry.get("ts", 0) or 0))
        age_days = age / 86400.0
        recency = 1.0 / math.pow(1.0 + max(0.0, age_days) * 0.35, 0.55)
        try:
            recall_count = int(entry.get("recall_count", 0) or 0)
        except Exception:
            recall_count = 0
        try:
            assoc = sum(int(v) for v in (entry.get("assoc") or {}).values())
        except Exception:
            assoc = 0
        try:
            due = 1.15 if 0 < float(entry.get("next_review_ts", 0) or 0) <= time.time() else 1.0
        except Exception:
            due = 1.0
        try:
            stability = max(0.2, float(entry.get("stability_days", 1.0) or 1.0))
        except Exception:
            stability = 1.0
        retention = math.exp(-age_days / stability)
        try:
            _d = ACT_R_DECAY
            _b = math.log(max(1e-9, (age_days + 0.05) ** (-_d)))
            base = 1.0 / (1.0 + math.exp(-(_b + 1.0)))
        except Exception:
            base = 0.5
        try:
            schema = max(0.0, min(1.0, float(entry.get("schema_congruence", 0.0) or 0.0)))
        except Exception:
            schema = 0.0
        inhibition = memory_meta.retrieval_inhibition(entry)
        regulation = str(getattr(core, "regulation", "none") or "none") if core is not None else "none"
        regulation_mod = memory_meta.regulation_memory_modifier(entry, regulation)
        lexical_mod = 1.0
        if hybrid and query_text:
            try:
                entry_text = str(entry.get("text") or "")
                variants = memory_meta.expand_query(query_text)
                lexical = max(memory_meta.lexical_overlap(variant, entry_text)
                              for variant in variants) if variants else 0.0
                lexical_mod = 1.0 + 0.12 * lexical
            except Exception:
                lexical_mod = 1.0
        sensitive_mod = 1.0
        if sensitive_protect:
            sensitive_mod = memory_meta.sensitivity_weight(entry)
        source_weight = memory_meta.retrieval_weight(entry)
        score = (cosine * (0.40 + 0.60 * importance) * recency
                 * (0.65 + 0.35 * retention)
                 * (0.85 + 0.15 * base)
                 * (1.0 + 0.10 * math.log1p(max(0, recall_count)))
                 * due
                 * (1.0 + 0.05 * math.log1p(max(0, assoc)))
                 * source_weight
                 * (1.0 + 0.10 * schema)
                 * (1.0 - 0.15 * inhibition)
                 * regulation_mod
                 * lexical_mod
                 * sensitive_mod)
        return {
            "score": float(score),
            "cosine": round(float(cosine), 6),
            "importance": round(importance, 4),
            "recency": round(recency, 4),
            "retention": round(0.65 + 0.35 * retention, 4),
            "base": round(0.85 + 0.15 * base, 4),
            "recall_boost": round(1.0 + 0.10 * math.log1p(max(0, recall_count)), 4),
            "assoc_boost": round(1.0 + 0.05 * math.log1p(max(0, assoc)), 4),
            "due": round(due, 4),
            "source_weight": round(float(source_weight), 4),
            "schema": round(schema, 4),
            "inhibition": round(float(inhibition), 4),
            "regulation": round(float(regulation_mod), 4),
            "lexical": round(float(lexical_mod), 4),
            "sensitive": round(float(sensitive_mod), 4),
        }

    def _memory_score(self, core, entry: dict, cosine: float, *,
                      query_text: str = "", hybrid: bool = False,
                      sensitive_protect: bool = False) -> float:
        parts = self._memory_score_parts(
            core, entry, cosine, query_text=query_text,
            hybrid=hybrid, sensitive_protect=sensitive_protect)
        score = float(parts.get("score", 0.0))
        try:
            trace = getattr(core, "_last_memory_trace", None) if core is not None else None
            if isinstance(trace, dict):
                eid = str(entry.get("id") or "")
                if eid and eid in [str(x) for x in (trace.get("entry_ids") or [])]:
                    valence = max(-1.0, min(1.0, float(trace.get("valence", 0.0) or 0.0)))
                    score *= 1.0 + 0.04 * valence
        except Exception:
            pass
        return max(0.0, score)

    def _memory_top_k(self, core) -> int:
        k = 4
        if core is not None:
            if float(getattr(core, "stress", 0.0)) > 0.65:
                k -= 1
            if float(getattr(core, "energy", 1.0)) < 0.35:
                k -= 1
            if float(getattr(core, "trust", 0.0)) > 0.65:
                k += 1
            if float(getattr(core, "attention", 0.5)) > 0.7:
                k += 1
            elif float(getattr(core, "attention", 0.5)) < 0.3:
                k -= 1
        return max(2, min(6, k))

    def _memory_thresholds(self, core):
        compression = self.api_config.get("compression") if isinstance(self.api_config.get("compression"), dict) else {}
        threshold = max(1000, int(compression.get("threshold", 6000) or 6000))
        limit = max(120, int(compression.get("max_chars", 800) or 800))
        if core is not None:
            stress = float(getattr(core, "stress", 0.0))
            threshold = int(threshold * (1.0 + 0.5 * stress))
            limit = int(limit * (1.0 + 0.2 * stress))
        return bool(compression.get("enabled")), threshold, limit

    def _trim_memory(self, doc, core=None):
        entries = doc.get("entries")
        if not isinstance(entries, list):
            entries = []
            doc["entries"] = entries
        if not entries:
            return
        enabled, threshold, summary_limit = self._memory_thresholds(core)
        if not enabled:
            entries[:] = entries[-80:]
            return
        # Keep summarized originals for provenance; only trim active entries.
        _archived = [e for e in entries if e.get("summarized")]
        _active = [e for e in entries if not e.get("summarized")]
        _active = _active[-200:]
        entries[:] = sorted(_archived + _active, key=lambda e: float(e.get("ts", 0) or 0))

    def _schedule_consolidation(self, event, core=None):
        enabled, threshold, _ = self._memory_thresholds(core)
        if not enabled:
            return
        try:
            doc = self._load_memory(event)
            total = sum(len(str(e.get("text", ""))) for e in (doc.get("entries") or []))
            if total <= threshold:
                return
        except Exception:
            return
        if getattr(self, "_consolidating", False):
            return
        if time.time() - float(getattr(self, "_last_consolidation", 0.0)) < 300:
            return
        self._last_consolidation = time.time()
        self._consolidating = True
        asyncio.create_task(self._consolidate_memory(event, core))

    async def _consolidate_memory(self, event, core=None, force=False):
        try:
            doc = self._load_memory(event)
            entries = doc.get("entries")
            if not isinstance(entries, list) or len(entries) < 2:
                return
            enabled, threshold, _ = self._memory_thresholds(core)
            if not enabled and not force:
                return
            total = sum(len(str(e.get("text", ""))) for e in entries)
            if total <= threshold and not force:
                return
            _delay_s = int(getattr(self, "event_summary_delay_hours", 6) or 0) * 3600
            try:
                _last_summary = float(doc.get("last_event_summary_ts", 0) or 0)
            except Exception:
                _last_summary = 0.0
            if not force and _delay_s > 0 and (_last_summary <= 0 or time.time() - _last_summary < _delay_s):
                if _last_summary <= 0:
                    doc["last_event_summary_ts"] = time.time()
                    self._save_memory(event, doc)
                return
            doc["last_event_summary_ts"] = time.time()
            _summary_use_llm = self._llm_allowed("memory_summary")
            provider = await self._provider_for("memory_summary", event) if _summary_use_llm else None
            now = time.time()
            _segments = self._segment_event_texts(entries)
            if not _segments:
                _segments = [[str(e.get("text", "")).strip() for e in entries if str(e.get("text", "")).strip()]]
            _attachments = []
            for _e in entries:
                try:
                    _attachments.extend(_e.get("attachments") or [])
                except Exception:
                    pass
            used = set()
            groups = []
            for i, e in enumerate(entries):
                if i in used or e.get("role") == "summary":
                    continue
                group = [i]
                used.add(i)
                for j in range(i + 1, len(entries)):
                    if j in used or entries[j].get("role") == "summary":
                        continue
                    if self._cosine(e.get("vector") or [], entries[j].get("vector") or []) >= 0.86:
                        group.append(j)
                        used.add(j)
                if len(group) >= 2:
                    groups.append(group)
                if len(groups) >= 3:
                    break
            if not groups:
                if time.time() - float(getattr(self, "_last_event_archive", 0.0)) > 300:
                    self._last_event_archive = time.time()
                    await self._archive_ranked_events(event, core, entries)
                    await self._maybe_archive_insight(event, core, "compression")
                return
            changed = False
            for group in groups:
                _raw_texts = [str(entries[i].get("text", "")).strip() for i in group
                              if str(entries[i].get("text", "")).strip()]
                # Dedupe near-identical memories before spending summary tokens;
                # grouping above already uses embedding cosine (>=0.86).
                texts = memory_meta.dedupe_texts(_raw_texts, threshold=0.88, limit=8)
                if len(texts) < 2:
                    continue
                payload = {"summary": "", "candidates": []}
                if _summary_use_llm and provider is not None:
                    prompt = interpretation.memory_summary_prompt(texts)
                    try:
                        resp = await provider.text_chat(prompt=prompt)
                        payload = interpretation.parse_memory_summary_payload(
                            str(getattr(resp, "completion_text", "") or ""))
                    except Exception as exc:
                        logger.warning("[biocore] memory summary failed: %s", exc)
                else:
                    # Deterministic extractive summary from embedding-grouped and
                    # deduped representatives; no LLM involved.
                    payload["summary"] = "；".join(texts[:5])[:180]
                summary = str(payload.get("summary") or "")
                candidates = payload.get("candidates") or []
                if not getattr(self, "llm_memory_candidates", True):
                    candidates = []
                if not summary:
                    continue
                vec = await self._embed_text(summary)
                if not vec:
                    continue
                importance = max(float(entries[i].get("importance", 0.5) or 0.5) for i in group)
                _sum_id = "sum_" + str(int(now)) + "_" + str(len(entries))
                for i in sorted(group, reverse=True):
                    _old = entries[i]
                    _old["summarized"] = True
                    _old["summary_id"] = _sum_id
                    _old["summarized_ts"] = now
                _src_prov = []
                for i in group:
                    _p = entries[i].get("provenance") if isinstance(entries[i], dict) else None
                    if isinstance(_p, dict):
                        _src_prov.append(_p)
                _summary_prov = {
                    "sender_id": "summary", "sender_name": "她",
                    "session": str(getattr(event, "unified_msg_origin", "") or ""),
                    "ts": now, "message_refs": [],
                    "sources": [{
                        "sender_id": str(_p.get("sender_id") or ""),
                        "sender_name": str(_p.get("sender_name") or ""),
                        "session": str(_p.get("session") or ""),
                        "ts": float(_p.get("ts", 0) or 0),
                        "message_refs": list(_p.get("message_refs") or [])[:6],
                    } for _p in _src_prov][-24:],
                }
                _summary_source = "inferred"
                _summary_conf = memory_meta.initial_confidence(_summary_source, importance)
                _summary_sens = memory_meta.classify_sensitivity(summary)
                entries.append({"id": _sum_id, "text": summary[:1200], "role": "summary",
                                "scope": "session",
                                "vector": vec, "ts": now, "hits": 1,
                                "importance": importance, "last_used": now,
                                "summary_id": _sum_id, "provenance": _summary_prov,
                                "memory_source": _summary_source,
                                "memory_confidence": _summary_conf,
                                "memory_tier": "warm", "conflict": False,
                                "last_write_op": "ADD", "last_write_ts": now,
                                "write_ops": {"ADD": 1}, "schema_congruence": 0.0,
                                "self_defining": False, "inhibition": 0.0,
                                "suppression_count": 0,
                                "encoding_regulation": str(getattr(core, "regulation", "none") or "none"),
                                "encoding_emotion": str((getattr(core, "labels", {}) or {}).get("emotion") or "neutral"),
                                "sensitive": bool(_summary_sens.get("sensitive")),
                                "pii_types": list(_summary_sens.get("types") or []),
                                "sensitivity": float(_summary_sens.get("score") or 0.0)})
                memory_meta.append_write_log(doc, op="ADD", entry_id=_sum_id,
                                             reason="summary", ts=now)
                # LLM proposes candidate facts; the deterministic policy here
                # decides ADD/UPDATE/NOOP and can never DELETE. Confidence is
                # capped below direct-user confidence by memory_meta.
                _cand_applied = 0
                for _cand in (candidates or [])[:memory_meta.CANDIDATE_MAX]:
                    try:
                        _ctext = str(_cand.get("text") or "").strip()
                        if len(_ctext) < 4:
                            continue
                        _cvec = await self._embed_text(_ctext)
                        if not _cvec:
                            continue
                        _best, _best_cos = None, 0.0
                        for _ce in entries:
                            if not isinstance(_ce, dict) or _ce.get("deleted") or _ce.get("summarized"):
                                continue
                            _cos = self._cosine(_cvec, _ce.get("vector") or [])
                            if _cos > _best_cos:
                                _best, _best_cos = _ce, _cos
                        _res = memory_meta.apply_memory_candidate(
                            entries, _cand, match=_best, cosine=_best_cos,
                            vector=_cvec, now=now, provenance=_summary_prov)
                        _entry = _res.get("entry")
                        if _res.get("op") in ("ADD", "UPDATE") and isinstance(_entry, dict):
                            self._apply_memory_encoding(_entry, core, now, _ctext)
                            memory_meta.append_write_log(
                                doc, op=_res["op"], entry_id=str(_entry.get("id") or ""),
                                reason="candidate", ts=now)
                            _cand_applied += 1
                    except Exception:
                        continue
                if _cand_applied:
                    logger.info("[biocore] llm memory candidates applied=%s", _cand_applied)
                changed = True
            if changed:
                await self._archive_ranked_events(event, core, entries)
                await self._maybe_archive_insight(event, core, "compression")
                self._trim_memory(doc, core)
                self._save_memory(event, doc)
                logger.info("[biocore] memory consolidated groups=%s entries=%s", len(groups), len(entries))
        finally:
            self._consolidating = False


    @staticmethod
    def _memory_command_line(cmd: dict) -> str:
        """Deterministic one-line data hint describing an executed memory command."""
        cmd = cmd or {}
        op = str(cmd.get("op") or "NOOP")
        target = str(cmd.get("target") or "").strip()[:40]
        if op == "PENDING":
            return "- 待确认：用户要求删除关于「%s」的记忆；用户回复“确认”后才执行。" % target
        if op == "DELETE":
            return "- 已删除关于「%s」的记忆（软删除，可恢复）。" % target
        if op == "RESTORE":
            return "- 已恢复最近删除的一条记忆。"
        if op == "ROLLBACK":
            _text = str((cmd.get("entry") or {}).get("text") or "")[:40]
            return "- 已把一条记忆回滚到上一版本：%s" % _text
        reason = str(cmd.get("reason") or "")
        if reason == "ambiguous":
            return "- 删除请求匹配到多条记忆，未执行；需要用户说得更具体。"
        if reason == "vague_target":
            return "- 删除请求缺少具体对象，未执行；需要用户说明要删除哪条记忆。"
        if reason == "no_match":
            # Silent: ordinary sentences containing delete words must not inject
            # a fake memory line into the prompt.
            return ""
        if reason == "no_restore_target":
            return "- 没有可恢复的已删除记忆。"
        if reason == "no_rollback_target":
            return "- 没有可回滚的记忆修改。"
        return ""

    def _self_schema_texts(self, core) -> list:
        """Bounded self-schema corpus for deterministic schema congruence."""
        texts = list(getattr(self, "schema_texts", []) or [])
        try:
            model = self.self_model or {}
            for key in ("who_am_i", "narrative"):
                value = str(model.get(key) or "").strip()
                if value:
                    texts.append(value)
            for key in ("boundaries", "consistency"):
                for item in (model.get(key) or []):
                    item = str(item or "").strip()
                    if item:
                        texts.append(item)
            if core is not None:
                for key in ("core_self", "narrative_self"):
                    value = str(getattr(core, key, "") or "").strip()
                    if value:
                        texts.append(value)
                for item in (getattr(core, "autobiography", []) or [])[-8:]:
                    if isinstance(item, dict):
                        value = str(item.get("title") or item.get("meaning") or "").strip()
                        if value:
                            texts.append(value)
        except Exception:
            pass
        return texts[:24]

    def _apply_memory_encoding(self, entry, core, now, text="") -> None:
        """Store deterministic encoding context: schema, regulation, affect."""
        if not isinstance(entry, dict):
            return
        try:
            schema = memory_meta.schema_congruence(
                text or str(entry.get("text") or ""), self._self_schema_texts(core))
            previous = 0.0
            try:
                previous = float(entry.get("schema_congruence", 0.0) or 0.0)
            except Exception:
                previous = 0.0
            entry["schema_congruence"] = round(max(previous, schema), 4)
            entry["self_defining"] = bool(
                memory_meta.is_self_defining(entry, entry["schema_congruence"]))
        except Exception:
            pass
        if core is not None:
            try:
                entry["encoding_regulation"] = str(getattr(core, "regulation", "none") or "none")
                entry["encoding_emotion"] = str((getattr(core, "labels", {}) or {}).get("emotion") or "neutral")
                entry["encoding_valence"] = round(float(getattr(core, "v", 0.0) or 0.0), 3)
                entry["encoding_arousal"] = round(float(getattr(core, "a", 0.5) or 0.5), 3)
            except Exception:
                pass
        _body = text or str(entry.get("text") or "")
        try:
            sensitivity = memory_meta.classify_sensitivity(_body)
            entry["sensitive"] = bool(sensitivity.get("sensitive"))
            entry["pii_types"] = list(sensitivity.get("types") or [])
            entry["sensitivity"] = float(sensitivity.get("score") or 0.0)
        except Exception:
            pass
        try:
            poison = memory_meta.detect_poisoning(_body)
            entry["poison_risk"] = bool(poison.get("poison_risk"))
            entry["poison_signals"] = list(poison.get("signals") or [])
            entry["poison_score"] = float(poison.get("risk") or 0.0)
            if entry["poison_risk"]:
                try:
                    entry["memory_confidence"] = min(
                        float(entry.get("memory_confidence", 0.5) or 0.5), 0.25)
                except Exception:
                    entry["memory_confidence"] = 0.25
        except Exception:
            pass
        # Memory permission scope: user facts may be shared across the same
        # sender's sessions; assistant summaries stay session-local.
        _role = str(entry.get("role") or "user")
        entry.setdefault("scope", "session" if _role in ("assistant", "summary") else "user")
        try:
            entry["verification"] = memory_meta.verify_entry(entry)
        except Exception:
            pass
        entry.setdefault("inhibition", 0.0)
        entry.setdefault("suppression_count", 0)


    # ------------------------------------------------------------------
    # Privacy / deletion semantics
    # ------------------------------------------------------------------
    def _redact_archive_text(self, needle: str, session: str = "") -> int:
        """Redact a deleted memory text from event archives and insights.

        Best-effort, bounded and atomic per file: matching event fields and
        source_texts are replaced/dropped, insight rows are replaced. Source
        ids/message refs are left intact because they carry no raw text.
        """
        needle = str(needle or "").strip()
        if len(needle) < 4:
            return 0
        replacement = "[已删除]"
        fields = ("title", "event", "central_details", "peripheral_details",
                  "meaning_to_her", "reflection", "event_key")
        total = 0

        def _mutate_event(obj):
            nonlocal total
            hit = False
            for field in fields:
                value = obj.get(field)
                if isinstance(value, str) and needle in value:
                    obj[field] = value.replace(needle, replacement)
                    hit = True
            sources = obj.get("source_texts")
            if isinstance(sources, list):
                kept = [str(x) for x in sources if needle not in str(x)]
                if len(kept) != len(sources):
                    obj["source_texts"] = kept
                    obj["source_redacted"] = True
                    hit = True
            if hit:
                total += 1
            return hit

        try:
            self._rewrite_jsonl_atomic(EVENT_ARCHIVE_PATH, _mutate_event)
            if session:
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(session))[:80]
                self._rewrite_jsonl_atomic(EVENT_SESSION_DIR / safe / "events.jsonl",
                                           _mutate_event)
        except Exception:
            pass

        def _mutate_insight(obj):
            nonlocal total
            value = obj.get("insight")
            if isinstance(value, str) and needle in value:
                obj["insight"] = value.replace(needle, replacement)
                total += 1
                return True
            return False

        try:
            self._rewrite_jsonl_atomic(INSIGHT_ARCHIVE_PATH, _mutate_insight)
        except Exception:
            pass
        return total

    def _propagate_memory_deletion(self, event, entry, doc, reason: str = "user_delete") -> None:
        """Propagate one memory deletion to derived summaries/events/insights."""
        try:
            if not isinstance(entry, dict) or not isinstance(doc, dict):
                return
            raw_text = str(entry.get("text") or "")
            needle = raw_text.split("\n[再巩固]")[0].strip()
            if len(needle) < 4:
                return
            now = time.time()
            # 1) summaries derived from the deleted entry in the same doc.
            for summary in (doc.get("entries") or []):
                if not isinstance(summary, dict) or summary.get("role") != "summary":
                    continue
                text = str(summary.get("text") or "")
                if needle not in text:
                    continue
                summary["text"] = text.replace(needle, "[已删除]")[:1200]
                summary["source_deleted"] = True
                try:
                    summary["memory_confidence"] = min(
                        float(summary.get("memory_confidence", 0.4) or 0.4), 0.25)
                except Exception:
                    summary["memory_confidence"] = 0.25
                memory_meta.append_write_log(doc, op="REDACT",
                                             entry_id=str(summary.get("id") or ""),
                                             reason="summary_derived", ts=now)
            # 2) event archive + insights.
            session = str(getattr(event, "unified_msg_origin", "") or "")
            changed = self._redact_archive_text(needle, session)
            if changed:
                memory_meta.append_write_log(
                    doc, op="REDACT", entry_id=str(entry.get("id") or ""),
                    reason="%s:%d" % (reason, changed), ts=now)
        except Exception as exc:
            logger.warning("[biocore] deletion propagation failed: %s", exc)

    def _cross_session_memory_entries(self, event) -> list:
        """Active memories from the same sender's other sessions (opt-in).

        Requires `cross_session_memory` and a sender id whose user file has a
        bounded `sessions` list (written by `_touch_user`). Returns
        [(session_key, entry), ...] and never mutates other docs.
        """
        if not getattr(self, "cross_session_memory", False):
            return []
        try:
            sid, _name = self._speaker(event)
            if not sid:
                return []
            path = self._user_path(event)
            if not path.exists():
                return []
            user = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(user, dict):
                return []
            current = str(getattr(event, "unified_msg_origin", "") or "")
            out = []
            for key in (user.get("sessions") or [])[-20:]:
                key = str(key or "").strip()
                if not key or key == current:
                    continue
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:80]
                mpath = MEMORY_DIR / (safe + ".json")
                if not mpath.exists():
                    continue
                try:
                    other = json.loads(mpath.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(other, dict):
                    continue
                for entry in (other.get("entries") or [])[-200:]:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("deleted") or entry.get("summarized"):
                        continue
                    out.append((key, entry))
            return out
        except Exception:
            return []

    def _apply_memory_trace(self, core, entries) -> dict:
        """Bounded memory-trace -> body nudge from recalled entries; trace read-only."""
        if core is None:
            return {}
        selected = [e for e in (entries or []) if isinstance(e, dict)][:8]
        if not selected:
            return {}
        total_w = 0.0
        val_sum = 0.0
        loop_count = 0
        ids = []
        for entry in selected:
            try:
                imp = max(0.05, min(1.0, float(entry.get("importance", 0.5) or 0.5)))
            except Exception:
                imp = 0.5
            try:
                val = float(entry.get("encoding_valence", entry.get("valence", 0.0)) or 0.0)
            except Exception:
                val = 0.0
            val = max(-1.0, min(1.0, val))
            val_sum += val * imp
            total_w += imp
            try:
                loop_count += max(0, int(entry.get("open_loop", 0) or 0))
            except Exception:
                pass
            eid = str(entry.get("id") or "")[:20]
            if eid:
                ids.append(eid)
        avg_val = (val_sum / total_w) if total_w > 0 else 0.0
        v_delta = max(-0.05, min(0.05, 0.05 * avg_val))
        stress_delta = max(-0.02, min(0.05, 0.005 * abs(avg_val) + 0.01 * min(3, loop_count)))
        try:
            core.v = _clip(float(core.v) + v_delta, -1.0, 1.0)
            core.stress = _clip(float(core.stress) + stress_delta, 0.0, 1.0)
        except Exception:
            pass
        trace = {"count": len(selected), "valence": round(avg_val, 3),
                 "stress_delta": round(stress_delta, 4),
                 "entry_ids": ids[:8], "ts": round(time.time(), 3)}
        self._last_memory_trace = trace
        try:
            core._last_memory_trace = trace
        except Exception:
            pass
        return trace

    async def _memory_recall(self, event, text: str, core=None, extra: str = "", vec=None, voice: str = "") -> str:
        self._last_memory_meta = {"count": 0, "confidence": 0.0, "source": "unknown",
                                  "abstain": False, "tiers": {}, "answer_confidence": 0.0,
                                  "gate": "none", "conflicts": 0}
        if not self.memory_dedup_embedding or not self._usable_memory_text(text):
            return ""
        doc = self._load_memory(event)
        entries = doc.get("entries")
        if not isinstance(entries, list):
            entries = []
            doc["entries"] = entries
        # Explicit memory write commands (DELETE/RESTORE/ROLLBACK) run before
        # retrieval. A staged delete only executes on an explicit confirmation
        # turn; the command text is never stored as a new memory.
        try:
            _cmd = memory_meta.handle_delete_command(doc, text, time.time())
        except Exception:
            _cmd = {"handled": False}
        if _cmd.get("handled"):
            if str(_cmd.get("op") or "") == "DELETE":
                try:
                    self._propagate_memory_deletion(
                        event, _cmd.get("entry"), doc, reason="nl_delete")
                except Exception:
                    pass
            self._save_memory(event, doc)
            self._last_memory_meta = {"count": 0, "confidence": 0.0, "source": "unknown",
                                      "abstain": False, "tiers": {}, "answer_confidence": 0.0,
                                      "gate": "none", "conflicts": 0,
                                      "write_op": str(_cmd.get("op") or "NOOP")}
            return self._memory_command_line(_cmd)
        if vec is None:
            vec = await self._embed_text(text)
        if not vec:
            return ""
        scored = []
        retrieval_pairs = []
        duplicate = None
        now = time.time()
        _just_restabilized = set()
        _working_set = doc.get("working_set") if isinstance(doc.get("working_set"), list) else []
        for e in entries:
            if e.get("summarized") or e.get("deleted"):
                continue
            if getattr(self, "safety_enabled", False) and e.get("poison_risk"):
                continue
            if self._restabilize_if_expired(e, now):
                _just_restabilized.add(id(e))
            cosine = self._cosine(vec, e.get("vector") or [])
            score = self._memory_score(
                core, e, cosine, query_text=text,
                hybrid=bool(getattr(self, "hybrid_retrieval", True)),
                sensitive_protect=bool(getattr(self, "sensitive_memory_protection", True)))
            try:
                score *= memory_meta.working_set_boost(e, _working_set)
            except Exception:
                pass
            retrieval_pairs.append((e, cosine))
            if cosine >= 0.93:
                duplicate = e
            # ACT-R partial matching + retrieval threshold (named constants).
            if cosine >= PARTIAL_MATCH_THRESHOLD and score >= RETRIEVAL_THRESHOLD:
                scored.append((score, e))
        _sid, _sname = self._speaker(event)
        _source = memory_meta.source_for_input(text=text, extra=extra, voice=voice)
        # Mem0 UPDATE path: an explicit correction is an update request even
        # when embedding similarity is below the exact-duplicate threshold.
        # Only the conservative correction detector can nominate this target.
        _update_target = None
        _explicit_update = False
        if duplicate is None:
            try:
                _scored_ids = {id(_entry) for _score, _entry in scored}
                _best = None
                for _pair in retrieval_pairs:
                    _cand, _cos = _pair
                    if id(_cand) not in _scored_ids:
                        continue
                    if _cos < MEMORY_UPDATE_MATCH_THRESHOLD:
                        continue
                    if not memory_meta.detect_conflict(_cand.get("text", ""), text):
                        continue
                    if _best is None or _cos > _best[1]:
                        _best = (_cand, _cos)
                if _best is not None:
                    _update_target = _best[0]
            except Exception:
                _update_target = None
        if duplicate is None and _update_target is not None:
            duplicate = _update_target
            _explicit_update = True
        if duplicate is not None:
            _entry_age = max(0.0, (now - float(duplicate.get("ts", now) or now)) / 86400.0)
            duplicate["ts"] = now
            duplicate["last_used"] = now
            duplicate["hits"] = int(duplicate.get("hits", 0)) + 1
            if _sid:
                duplicate["sender_id"] = _sid
            if _sname:
                duplicate["sender_name"] = _sname
            if extra:
                duplicate["image_caption"] = str(extra).strip()[:1600]
            if voice:
                duplicate["voice_text"] = str(voice).strip()[:1200]
            duplicate["memory_source"] = memory_meta.merge_sources(duplicate.get("memory_source"), _source)
            duplicate["memory_confidence"] = memory_meta.update_confidence(
                duplicate.get("memory_confidence"),
                duplicate["memory_source"],
                hits=int(duplicate.get("hits", 0) or 0),
                review_count=int(duplicate.get("review_count", 0) or 0),
                age_days=_entry_age,
            )
            if not isinstance(duplicate.get("destination"), dict):
                duplicate["destination"] = memory_meta.build_destination(_sid, _sname)
            _conflict = (memory_meta.detect_conflict(duplicate.get("text", ""), text)
                         or _explicit_update)
            if _conflict:
                _old_text = str(duplicate.get("text", ""))
                memory_meta.merge_version(duplicate, _old_text)
                _new_text = str(text or "").strip()[:1200]
                if _new_text and _new_text != _old_text:
                    duplicate["text"] = _new_text
                    duplicate["vector"] = vec
                    duplicate["vec_updated_ts"] = now
                duplicate["conflict"] = True
                duplicate["conflict_resolved"] = bool(_explicit_update)
                try:
                    self._record_calibration(
                        event,
                        "explicit_correction" if _explicit_update else "conflict",
                        duplicate.get("memory_confidence", 0.5),
                        0.0,
                    )
                except Exception:
                    pass
                if _explicit_update:
                    # The user explicitly corrected the fact: trust the newer
                    # direct statement, but keep the old version for rollback.
                    try:
                        _base_conf = float(duplicate.get("memory_confidence", 0.5) or 0.5)
                    except Exception:
                        _base_conf = 0.5
                    duplicate["memory_confidence"] = round(max(_base_conf, 0.78), 4)
                else:
                    try:
                        duplicate["memory_confidence"] = min(float(duplicate.get("memory_confidence", 0.5) or 0.5), 0.55)
                    except Exception:
                        duplicate["memory_confidence"] = 0.55
            if not duplicate.get("id"):
                duplicate["id"] = _sha256(str(duplicate.get("text", ""))[:300])[:12]
            duplicate["memory_tier"] = memory_meta.memory_tier(duplicate, now)
            _write_op = memory_meta.classify_write_op(
                duplicate, {"text": text[:1200]}, 1.0, conflict=_conflict or bool(duplicate.get("conflict"))
            )
            duplicate["last_write_op"] = _write_op
            _ops = duplicate.get("write_ops") if isinstance(duplicate.get("write_ops"), dict) else {}
            _ops[_write_op] = int(_ops.get(_write_op, 0) or 0) + 1
            duplicate["write_ops"] = _ops
            duplicate["provenance"] = self._memory_provenance(event, now)
            duplicate["last_write_ts"] = now
            self._apply_memory_encoding(duplicate, core, now, text)
            if _write_op != "NOOP":
                memory_meta.append_write_log(doc, op=_write_op, entry_id=duplicate.get("id", ""),
                                             reason="conflict" if _conflict else "duplicate", ts=now)
        else:
            _importance = self._memory_importance(core, "user")
            _new_entry = {"id": _sha256(str(text)[:300])[:12], "text": text[:1200],
                          "role": "user", "vector": vec, "ts": now, "hits": 1,
                          "sender_id": _sid, "sender_name": _sname,
                          "attachments": self._attachments_from_messages(event),
                          "image_caption": str(extra or "").strip()[:1600],
                          "voice_text": str(voice or "").strip()[:1200],
                          "provenance": self._memory_provenance(event, now),
                          "importance": _importance,
                          "memory_source": _source,
                          "memory_confidence": memory_meta.initial_confidence(_source, _importance),
                          "destination": memory_meta.build_destination(_sid, _sname),
                          "conflict": False,
                          "last_write_op": "ADD",
                          "last_write_ts": now,
                          "write_ops": {"ADD": 1},
                          "memory_tier": "hot",
                          "schema_congruence": 0.0,
                          "self_defining": False,
                          "inhibition": 0.0,
                          "suppression_count": 0,
                          "last_used": now, "next_review_ts": now + 86400, "review_count": 0}
            self._apply_memory_encoding(_new_entry, core, now, text)
            entries.append(_new_entry)
            memory_meta.append_write_log(doc, op="ADD", entry_id=_new_entry["id"],
                                         reason="new", ts=now)
            self._trim_memory(doc, core)
        self._save_memory(event, doc)
        try:
            _recent_ids = [str(_e.get("id") or "") for _e in entries[-3:]
                           if isinstance(_e, dict)]
            doc["working_set"] = memory_meta.update_working_set(
                doc.get("working_set") if isinstance(doc.get("working_set"), list) else [],
                _recent_ids, capacity=max(4, self._memory_top_k(core) * 2))
            self._save_memory(event, doc)
        except Exception:
            pass
        self._schedule_consolidation(event, core)
        scored.sort(key=lambda x: x[0], reverse=True)
        top = memory_meta.select_top(
            scored, self._memory_top_k(core),
            lambda_=(0.72 if getattr(self, "hybrid_retrieval", True) else 1.0))
        try:
            self._apply_memory_trace(core, [e for _s, e in top])
        except Exception as exc:
            logger.warning("[biocore] memory trace apply failed: %s", exc)
        # L-T02 / C-T01: auditable retrieval-contribution trace (deterministic,
        # bounded to 8 rows, no text beyond the entry id). This is a trace of
        # ranking factors, not a claim of psychological causation, and it is
        # never produced by the LLM.
        try:
            _cos_by_id = {id(_e): _cos for _e, _cos in retrieval_pairs}
            _trace = []
            for _rank, (_score, _entry) in enumerate(top[:8], start=1):
                _eid = str(_entry.get("id") or "").strip()[:20]
                if not _eid:
                    continue
                _parts = self._memory_score_parts(
                    core, _entry, _cos_by_id.get(id(_entry), 0.0),
                    query_text=text,
                    hybrid=bool(getattr(self, "hybrid_retrieval", True)),
                    sensitive_protect=bool(getattr(self, "sensitive_memory_protection", False)))
                _trace.append({
                    "entry_id": _eid,
                    "rank": _rank,
                    "score": round(float(_score), 4),
                    "cosine": _parts["cosine"],
                    "importance": _parts["importance"],
                    "source": str(_entry.get("memory_source") or "direct")[:12],
                    "tier": str(_entry.get("memory_tier") or "warm")[:8],
                    "conflict": bool(_entry.get("conflict")),
                    "components": {k: _parts[k] for k in
                                   ("recency", "retention", "schema", "inhibition",
                                    "regulation", "lexical", "sensitive", "source_weight")},
                })
            self._last_cause_trace = _trace
            self._last_memory_entries = [str(e.get("id") or "")
                                         for _s, e in top if str(e.get("id") or "")][:8]
            doc["last_recall_trace"] = _trace
            self._save_memory(event, doc)
        except Exception as _trace_exc:
            logger.warning("[biocore] recall trace failed: %s", _trace_exc)
        # Nader reconsolidation + Ebbinghaus review: recalling an item makes
        # it labile, strengthens it slightly, and schedules the next review.
        _intervals = [1, 2, 4, 7, 15, 30, 60]
        _ids = []
        for _score, e in top:
            if id(e) in _just_restabilized:
                # The expired labile window was just closed in this pass; do
                # not re-open it on the same recall.
                continue
            try:
                e["recall_count"] = int(e.get("recall_count", 0) or 0) + 1
                e["last_recall"] = now
                e["reconsolidated_ts"] = now
                e["destabilized_until"] = now + float(getattr(self, "reconsolidation_seconds", 600.0))
                e["reconsolidation_state"] = "destabilized"
                _imp = float(e.get("importance", 0.5) or 0.5)
                e["importance"] = max(0.0, min(1.0, _imp + 0.015))
                _rc = int(e.get("review_count", 0) or 0) + 1
                e["review_count"] = _rc
                _st = max(1.0, min(365.0, float(e.get("stability_days", 1.0) or 1.0) * 1.8))
                e["stability_days"] = round(_st, 3)
                _days = max(_intervals[min(_rc - 1, len(_intervals) - 1)], _st)
                e["next_review_ts"] = now + _days * 86400
                # Keep the persisted id stable: dashboard delete/rollback and
                # write_log reference it; only assign one for legacy entries.
                _eid = str(e.get("id") or "").strip()
                if not _eid:
                    _eid = _sha256(str(e.get("text", ""))[:300])[:12]
                    e["id"] = _eid
                e["last_recall_regulation"] = str(getattr(core, "regulation", "none") or "none")
                _ids.append(e)
            except Exception:
                pass
        # ACT-R-style spreading activation: co-recalled items become associated.
        for _i in range(len(_ids)):
            for _j in range(_i + 1, len(_ids)):
                try:
                    _a = _ids[_i].setdefault("assoc", {})
                    _b = _ids[_j].setdefault("assoc", {})
                    _aid = _ids[_i].get("id") or str(_i)
                    _bid = _ids[_j].get("id") or str(_j)
                    _a[_bid] = int(_a.get(_bid, 0)) + 1
                    _b[_aid] = int(_b.get(_aid, 0)) + 1
                except Exception:
                    pass
        # Memory graph links (A-MEM-like): co-recalled memories get weighted
        # directed links; the working set keeps a bounded read set per session.
        _link_lines = []
        _consistency = memory_meta.answer_consistency(top)
        try:
            for _i in range(len(_ids)):
                for _j in range(_i + 1, len(_ids)):
                    _aid = str(_ids[_i].get("id") or "").strip()
                    _bid = str(_ids[_j].get("id") or "").strip()
                    if _aid and _bid:
                        memory_meta.add_link(_ids[_i], _bid, now=now)
                        memory_meta.add_link(_ids[_j], _aid, now=now)
            _ws_current = doc.get("working_set") if isinstance(doc.get("working_set"), list) else _working_set
            doc["working_set"] = memory_meta.update_working_set(
                _ws_current, [str(e.get("id") or "") for _score, e in top],
                capacity=max(4, self._memory_top_k(core) * 2))
            _top_ids = {id(e) for _score, e in top}
            _by_id = {str(e.get("id") or ""): e for e in entries
                      if isinstance(e, dict) and str(e.get("id") or "")}
            for _score, e in top:
                for _lid in memory_meta.linked_ids(e, limit=2):
                    _nb = _by_id.get(_lid)
                    if _nb is None or id(_nb) in _top_ids:
                        continue
                    if _nb.get("deleted") or _nb.get("summarized"):
                        continue
                    if getattr(self, "safety_enabled", False) and _nb.get("poison_risk"):
                        continue
                    _nb_text = str(_nb.get("text") or "").strip().replace("\n", " ")
                    if not _nb_text:
                        continue
                    if getattr(self, "safety_enabled", False) and _nb.get("sensitive"):
                        _nb_text = memory_meta.mask_sensitive(_nb_text)
                    _link_lines.append("- 关联记忆：%s" % _nb_text[:200])
            self._save_memory(event, doc)
        except Exception:
            _link_lines = []
            _consistency = 1.0
        # Retrieval-induced forgetting: similar memories that lost this
        # competition become temporarily inhibited (they are not deleted and
        # the inhibition decays over days).
        try:
            memory_meta.apply_retrieval_inhibition(
                retrieval_pairs, [str(e.get("id") or "") for _score, e in top], now)
        except Exception:
            pass
        try:
            self._save_memory(event, doc)
        except Exception:
            pass
        # Opt-in cross-session recall: promote the same sender's memories from
        # other sessions into this session (marked, capped, never leaking to
        # other senders). Default off in config.
        _foreign_lines = []
        try:
            if getattr(self, "cross_session_memory", False):
                _known_texts = {str(e.get("text") or "") for e in entries
                                if isinstance(e, dict) and not e.get("deleted")}
                _foreign = []
                for _skey, _entry in self._cross_session_memory_entries(event):
                    _etext = str(_entry.get("text") or "").strip()
                    if not _etext or _etext in _known_texts:
                        continue
                    if getattr(self, "safety_enabled", False):
                        if _entry.get("sensitive"):
                            continue
                        if str(_entry.get("role") or "") in ("assistant", "summary"):
                            continue
                        if str(_entry.get("scope") or "user") == "session":
                            continue
                    _evec = _entry.get("vector") or []
                    _ecos = self._cosine(vec, _evec) if _evec else 0.0
                    if _ecos < PARTIAL_MATCH_THRESHOLD:
                        continue
                    _escore = self._memory_score(core, _entry, _ecos)
                    if _escore < RETRIEVAL_THRESHOLD:
                        continue
                    _foreign.append((_escore, _skey, _entry))
                _foreign.sort(key=lambda item: item[0], reverse=True)
                for _escore, _skey, _entry in _foreign[:2]:
                    _copy = dict(_entry)
                    _copy["id"] = _sha256(_skey + "|" + str(_entry.get("text"))[:200])[:12]
                    _copy["shared_from_session"] = _skey
                    _copy["ts"] = now
                    _copy["hits"] = 1
                    _copy["last_used"] = now
                    _copy["memory_tier"] = "warm"
                    try:
                        _copy["memory_confidence"] = min(
                            0.55, float(_entry.get("memory_confidence", 0.6) or 0.6))
                    except Exception:
                        _copy["memory_confidence"] = 0.5
                    if not _copy.get("memory_source"):
                        _copy["memory_source"] = "inferred"
                    entries.append(_copy)
                    _known_texts.add(_etext)
                    _foreign_lines.append("- （其他会话）%s：%s" % (
                        str(_copy.get("memory_source") or "inferred"), _etext[:200]))
                    memory_meta.append_write_log(doc, op="ADD",
                                                 entry_id=_copy["id"],
                                                 reason="cross_session", ts=now)
                if _foreign_lines:
                    self._save_memory(event, doc)
        except Exception:
            _foreign_lines = []
        self._last_memory_meta = memory_meta.summarize_recall(
            top, now, consistency=_consistency)
        _gate = str(self._last_memory_meta.get("gate") or "none")
        lines = []
        for score, e in top:
            _entry_role = str(e.get("role") or "user")
            role = "你(已总结)" if _entry_role == "summary" else ("你" if _entry_role == "assistant" else "用户")
            if _entry_role not in ("assistant", "summary"):
                who = str(e.get("sender_name") or e.get("sender_id") or "").strip()
                if who:
                    role = who
            snippet = str(e.get("text", "")).strip().replace("\n", " ")
            if getattr(self, "safety_enabled", False) and snippet and e.get("sensitive"):
                snippet = memory_meta.mask_sensitive(snippet)
            if snippet:
                lines.append("- %s：%s" % (role, snippet[:240]))
        lines.extend(_link_lines)
        lines.extend(_foreign_lines)
        memory_text = "\n".join(lines)
        if getattr(self, "safety_enabled", False) and _gate == "force":
            self._last_memory_meta["withheld"] = True
            self._last_memory_meta["abstain"] = True
            return ""
        return memory_text

    async def _remember(self, event, text: str, role: str = "user", core=None):
        if not self.memory_dedup_embedding or not self._usable_memory_text(text):
            return
        text = str(text).strip()
        if len(text) < 4:
            return
        vec = await self._embed_text(text)
        if not vec:
            return
        doc = self._load_memory(event)
        entries = doc.get("entries")
        if not isinstance(entries, list):
            entries = []
            doc["entries"] = entries
        now = time.time()
        for e in entries:
            if e.get("summarized") or e.get("deleted"):
                continue
            self._restabilize_if_expired(e, now)
            _cos = self._cosine(vec, e.get("vector") or [])
            # Nader reconsolidation: a recalled memory is labile for a window;
            # new related information can update it before restabilization.
            try:
                _window = float(e.get("destabilized_until", 0) or 0)
            except Exception:
                _window = 0.0
            if _window > now and _cos >= 0.80:
                _old_text = str(e.get("text", ""))
                e["text"] = (_old_text + "\n[再巩固] " + text)[:1200]
                try:
                    _ov = [float(x) for x in (e.get("vector") or [])]
                    e["vector"] = [0.8 * a + 0.2 * b for a, b in zip(_ov, vec)]
                except Exception:
                    pass
                e["reconsolidated_ts"] = now
                e["reconsolidation_count"] = int(e.get("reconsolidation_count", 0) or 0) + 1
                e["reconsolidation_state"] = "rewritten"
                e["destabilized_until"] = 0
                self._save_memory(event, doc)
                return
            if _cos >= 0.93:
                e["ts"] = now
                e["last_used"] = now
                e["hits"] = int(e.get("hits", 0)) + 1
                self._save_memory(event, doc)
                return
        _sid, _sname = self._speaker(event)
        if role == "assistant":
            _prov = {"sender_id": "self", "sender_name": "她",
                     "session": str(getattr(event, "unified_msg_origin", "") or ""),
                     "ts": now, "message_refs": []}
        else:
            _prov = self._memory_provenance(event, now)
        entries.append({"text": text[:1200], "role": role, "vector": vec,
                        "ts": now, "hits": 1,
                        "sender_id": _sid if role == "user" else "",
                        "sender_name": _sname if role == "user" else "",
                        "attachments": self._attachments_from_messages(event) if role == "user" else [],
                        "provenance": _prov,
                        "importance": self._memory_importance(core, role),
                        "last_used": now, "next_review_ts": now + 86400, "review_count": 0})
        self._apply_memory_encoding(entries[-1], core, now, text)
        memory_meta.append_write_log(doc, op="ADD", entry_id=str(entries[-1].get("id") or ""),
                                     reason=role, ts=now)
        self._trim_memory(doc, core)
        self._save_memory(event, doc)
        self._schedule_consolidation(event, core)

    @filter.on_llm_request()

    # ------------------------------------------------------------------
    # A4 continuity opener ("上次聊到").
    #
    # Deterministic only: no LLM call, no new line, no reply generation. The
    # three data sources are already persisted bio data:
    #   1) the latest consolidated memory summary / last archived session event
    #      (fallback: self_timeline past / autobiography title);
    #   2) unfinished open loops captured *before* the current turn;
    #   3) relationship state (closeness/conflict/repair/phase/absence).
    # It is injected only when the user returns after A4_CONTINUITY_GAP_SECONDS
    # and at least one of the three sources is non-empty.
    # ------------------------------------------------------------------
    def _record_continuity_feedback(self, event, continuity) -> None:
        """Persist A4 continuity usage/feedback into the memory doc (bounded)."""
        if not isinstance(continuity, dict) or not continuity:
            return
        try:
            doc = self._load_memory(event)
            loops = continuity.get("open_loops") if isinstance(continuity.get("open_loops"), list) else []
            doc["last_continuity"] = {
                "ts": round(time.time(), 3),
                "summary": str(continuity.get("summary") or "")[:80],
                "open_loops": [str(x.get("text") or "")[:60] for x in loops[:3] if isinstance(x, dict)],
                "relationship_used": bool(continuity.get("relationship")),
            }
            doc["continuity_feedback_count"] = int(doc.get("continuity_feedback_count", 0) or 0) + 1
            self._save_memory(event, doc)
            try:
                for loop in (getattr(self, "_continuity_last_loops", None) or [])[:3]:
                    if isinstance(loop, dict):
                        loop["last_mentioned_ts"] = time.time()
            except Exception:
                pass
        except Exception as exc:
            logger.warning("[biocore] continuity feedback write failed: %s", exc)

    def _continuity_summary(self, event, core):
        """Return a bounded last-session summary text, or "" when none exists."""
        try:
            doc = self._load_memory(event)
            entries = doc.get("entries") if isinstance(doc, dict) else []
            summaries = [e for e in (entries or [])
                         if isinstance(e, dict)
                         and str(e.get("role") or "") == "summary"
                         and str(e.get("text") or "").strip()]
            if summaries:
                summaries.sort(key=lambda e: float(e.get("ts", 0) or 0), reverse=True)
                text = str(summaries[0].get("text") or "")
                text = text.split("\n[再巩固]")[0]
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    return text[:80]
        except Exception:
            pass
        try:
            last = self._last_session_event(
                str(getattr(event, "unified_msg_origin", "") or ""))
            if isinstance(last, dict):
                title = str(last.get("title") or "").strip()
                detail = str(last.get("meaning_to_her")
                             or last.get("reflection")
                             or last.get("event") or "").strip()
                text = (title + ("：" + detail if detail else "")).strip()
                text = re.sub(r"\s+", " ", text)
                if text:
                    return text[:80]
        except Exception:
            pass
        try:
            timeline = getattr(core, "self_timeline", {}) if core is not None else {}
            past = timeline.get("past") if isinstance(timeline, dict) else None
            for item in reversed(past or []):
                text = re.sub(r"\s+", " ", str(item or "")).strip()
                if text:
                    return text[:80]
        except Exception:
            pass
        try:
            for item in reversed(list(getattr(core, "autobiography", []) or [])):
                if isinstance(item, dict):
                    text = str(item.get("title") or item.get("meaning") or "").strip()
                    if text:
                        return re.sub(r"\s+", " ", text)[:80]
        except Exception:
            pass
        return ""

    def _continuity_context(self, event, core, user_data, prior_loops=None):
        """Build raw A4 continuity data; returns {} when there is no history."""
        data = user_data if isinstance(user_data, dict) else {}
        absence = data.get("absence") if isinstance(data.get("absence"), dict) else {}
        try:
            gap_days = float(absence.get("gap_days", 0.0) or 0.0)
        except Exception:
            gap_days = 0.0
        if gap_days * 86400.0 < A4_CONTINUITY_GAP_SECONDS:
            return {}
        summary = self._continuity_summary(event, core)
        loops = []
        try:
            source = prior_loops if isinstance(prior_loops, list) else (
                getattr(core, "open_loops", []) if core is not None else [])
            open_loops = []
            for item in (source or []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("status") or "open") != "open":
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                due = str(item.get("due_hint") or "")
                try:
                    seen = float(item.get("last_mentioned_ts")
                                 or item.get("created_ts") or 0.0)
                except Exception:
                    seen = 0.0
                open_loops.append((0 if due in ("soon", "tomorrow") else 1,
                                   -seen, text[:60], due))
            open_loops.sort(key=lambda row: (row[0], row[1]))
            for _rank, _neg_ts, text, due in open_loops[:A4_CONTINUITY_MAX_LOOPS]:
                loops.append({"text": text, "due_hint": due})
        except Exception:
            loops = []
        relationship = data.get("relationship") if isinstance(data.get("relationship"), dict) else {}
        state = relationship.get("state") if isinstance(relationship.get("state"), dict) else {}
        rel = {}
        if state:
            for key in ("closeness", "conflict", "repair"):
                try:
                    rel[key] = round(max(0.0, min(1.0, float(state.get(key, 0.0) or 0.0))), 3)
                except Exception:
                    pass
            repair_state = relationship.get("repair_state")
            if isinstance(repair_state, dict):
                phase = str(repair_state.get("phase") or "stable")
                if phase and phase != "stable":
                    rel["phase"] = phase
            bucket = str(absence.get("bucket") or "")
            if bucket and bucket != "same_day":
                rel["absence"] = bucket
        if not summary and not loops and not rel:
            return {}
        return {"summary": summary, "loops": loops, "relationship": rel}

    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        if not self.enabled or not self.inject_intent:
            return
        await self._ensure_profile(event)
        core = self._core(event)
        # A4: capture open loops from *before* this turn so the continuity
        # opener cannot echo a loop created by the current message.
        _prior_open_loops = [dict(x) for x in (getattr(core, "open_loops", []) or [])
                             if isinstance(x, dict)]
        text = str(getattr(event, "message_str", "") or "").strip()
        if not text:
            text = str(getattr(req, "prompt", "") or "")
        if not text:
            for item in reversed(getattr(req, "contexts", []) or []):
                if isinstance(item, dict) and item.get("role") == "user":
                    c = item.get("content")
                    if isinstance(c, str):
                        text = c
                        break
        # The core must observe the incoming message; otherwise v/a/stress and
        # fallback labels only change when the model emits a hidden <biocore> tag.
        _query_vec = None
        if text and self.memory_dedup_embedding:
            try:
                _query_vec = await self._embed_text(text)
            except Exception:
                _query_vec = None
        if text:
            core.observe(text, embedding=_query_vec)
        _user_data = self._touch_user(event, core)
        _continuity = {}
        try:
            _continuity = self._continuity_context(event, core, _user_data,
                                                   prior_loops=_prior_open_loops)
        except Exception as exc:
            logger.warning("[biocore] continuity context failed: %s", exc)
            _continuity = {}
        try:
            self._record_continuity_feedback(event, _continuity)
        except Exception:
            pass
        _img = await self._image_context(event)
        _voice = await self._voice_context(event)
        _mem = await self._memory_recall(event, text, core, _img, vec=_query_vec, voice=_voice)
        try:
            _recent_turns = [str(h.get("text") or "") for h in (core.history or [])[-6:]]
            core.bind_goal_context(memory_text=_mem, self_model=self.self_model,
                                   recent=_recent_turns, text=text)
        except Exception:
            pass
        _events = self._event_context(event)
        # L-T02..L-T12: one bounded strategy/cause/receipt token, plus optional
        # proposal-only LLM refinements (each function default OFF).
        _events_raw = self._event_archive(9)
        _strategy_hint = ""
        try:
            _strategy_hint = await self._maybe_llm_hints(
                event, core, _user_data, _events_raw,
                getattr(self, "_last_memory_meta", {}) or {}, text)
        except Exception as exc:
            logger.warning("[biocore] strategy hint failed: %s", exc)
        try:
            await self._maybe_tom_probe(event, core, text, _user_data,
                                        getattr(self, "_last_memory_meta", {}) or {})
        except Exception as exc:
            logger.warning("[biocore] tom probe call failed: %s", exc)
        _kb = ""
        if getattr(self, "kb_enabled", False) and getattr(self, "kb_names", None) and self._usable_memory_text(text):
            try:
                _r = await asyncio.wait_for(
                    self.context.kb_manager.retrieve(query=text, kb_names=self.kb_names, top_m_final=3),
                    timeout=10.0)
                _kb = str((_r or {}).get("context_text") or "").strip()
            except Exception as exc:
                logger.warning("[biocore] kb retrieve failed: %s", exc)
        _base = str(getattr(req, "system_prompt", "") or "")
        _sid, _sname = self._speaker(event)
        _speaker = (("%s（%s）" % (_sname or "未知", _sid)) if _sid else (_sname or ""))
        _compact = interpretation.render_compact(
            core,
            _mem.replace("[BioCore Memory]", "").strip(),
            _events.replace("[BioCore Events]", "").strip(),
            self.self_model,
            _user_data,
            _img.replace("[BioCore Image]", "").strip(),
            _kb,
            _speaker,
            _voice,
            memory_meta=getattr(self, "_last_memory_meta", {}) or {},
            open_loops=getattr(core, "open_loops", None),
            open_loops_due=sum(
                1 for _loop in (getattr(core, "open_loops", None) or [])
                if isinstance(_loop, dict)
                and str(_loop.get("status") or "open") == "open"
                and str(_loop.get("due_hint") or "") in ("soon", "tomorrow")),
            answer_confidence=(getattr(self, "_last_memory_meta", {}) or {}).get("answer_confidence"),
            strategy_hint=_strategy_hint,
            continuity=_continuity,
        ).strip()
        if _compact:
            # Keep the system prompt stable (prefix-cache friendly) and attach
            # the transient intent to this user turn instead of persisting it.
            parts = getattr(req, "extra_user_content_parts", None)
            if isinstance(parts, list):
                parts.append({"type": "text", "text": _compact})
            else:
                req.system_prompt = (_base + "\n\n" + _compact).strip()

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        if not self.enabled:
            return
        core = self._core(event)
        _reply = str(getattr(response, "completion_text", "") or "")
        _clean, _meta = interpretation.parse_response(_reply)
        if _meta:
            core.apply_affect(_meta)
            try:
                response.completion_text = _clean
                chain = getattr(response, "result_chain", None)
                if chain is not None and getattr(chain, "chain", None):
                    for comp in chain.chain:
                        if hasattr(comp, "text"):
                            comp.text = _clean
            except Exception:
                pass
        _reply = _clean
        try:
            core.record_reply(_reply, _meta)
        except Exception:
            pass
        try:
            if _reply:
                asyncio.create_task(self._remember(event, _reply, "assistant", core))
        except Exception:
            pass
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            key = str(getattr(event, "unified_msg_origin", "default") or "default")
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:80]
            (STATE_DIR / (safe + ".json")).write_text(
                json.dumps(core.snapshot(), ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
        # L-T01/L-T08/L-T12: background proposal-only tasks. They self-check
        # the per-function switch + cooldown, so default OFF means zero calls.
        try:
            asyncio.create_task(self._maybe_relationship_impression(event, core))
            asyncio.create_task(self._maybe_diary(event, core))
            asyncio.create_task(self._maybe_relationship_narrative(event, core))
        except Exception:
            pass
