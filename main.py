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
IMAGE_SERVICE_PORT = 8091
IMAGE_SERVICE_HEALTH = "http://127.0.0.1:8091/v1/models"
LLAMA_SERVER = Path(r"C:\Users\Administrator\Desktop\deepseek\llamacpp\llama-server.exe")
LLAMA_MODEL = Path(r"C:\Users\Administrator\Desktop\deepseek\_minicpm47_heretic_gguf\MiniCPM-V-4.7-1B-Heretic.Q4_K_M.gguf")
LLAMA_MMPROJ = Path(r"C:\Users\Administrator\Desktop\deepseek\_minicpm47_heretic_gguf\mmproj-Q8_0.gguf")
IMAGE_CACHE_PATH = DATA_DIR / "image_cache.json"
EVENT_ARCHIVE_DIR = DATA_DIR / "archives"
EVENT_SESSION_DIR = EVENT_ARCHIVE_DIR / "sessions"
EVENT_ARCHIVE_PATH = EVENT_ARCHIVE_DIR / "events.jsonl"
USER_DIR = DATA_DIR / "users"
SELF_MODEL_PATH = DATA_DIR / "self_model.json"
INSIGHT_ARCHIVE_PATH = EVENT_ARCHIVE_DIR / "insights.jsonl"
EMBED_CACHE = {}

DEFAULT_PROFILE = {
    "O": 0.62, "C": 0.55, "E": 0.44, "A": 0.42, "N": 0.40,
    "stress_reactivity": 0.45, "recovery_rate": 0.62,
    "social_baseline": 0.44, "energy_baseline": 0.55,
    "curiosity_baseline": 0.60, "safety_baseline": 0.55,
    "da_baseline": 0.55, "oa_baseline": 0.40, "ht_baseline": 0.35,
    "autonomy_gain": 1.0, "baseline_v": 0.05, "baseline_a": 0.40,
    "learning_rate": 0.06,
}

# ACT-R retrieval constants (Anderson & Reder 1999; partial matching per
# Anderson 1994). Keeping them in one named place makes scoring tunable.
ACT_R_DECAY = 0.5
RETRIEVAL_THRESHOLD = 0.25
PARTIAL_MATCH_THRESHOLD = 0.35

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
                "goal_focus": self.goal_focus,
                "coping": round(float((self.appraisal or {}).get("coping", 0.5)), 3),
                "event_anchors": list(self.event_anchors)[-5:],
                "opponent": dict(self.opponent),
                "autobiography": list(self.autobiography)[-8:],
                "regulation_stats": dict(self.regulation_stats),
                "attention": round(float(self.attention), 3),
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


@register("astrbot_plugin_biocore", "local", "Standalone BioCore emotion layer", "1.2.5")
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
        self.first_run_persona_compile = bool(self.config.get("first_run_persona_compile", True))
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
        self.self_model = self._load_self_model()
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
                logger.info("[biocore] loaded profile %s", PROFILE_PATH)
        except Exception as exc:
            logger.warning("[biocore] profile load failed: %s", exc)

    async def _persona_text(self, event) -> str:
        try:
            pm = self.context.persona_manager
            p = await pm.get_default_persona_v3(getattr(event, "unified_msg_origin", None))
            if isinstance(p, dict):
                return str(p.get("prompt") or p.get("system_prompt") or "")
            return str(getattr(p, "prompt", "") or getattr(p, "system_prompt", "") or "")
        except Exception as exc:
            logger.warning("[biocore] persona read failed: %s", exc)
            return ""

    async def _compile_profile(self, event):
        text = await self._persona_text(event)
        if not text:
            self.profile = dict(DEFAULT_PROFILE)
            self.persona_text = ""
            try:
                PROFILE_PATH.write_text(json.dumps(
                    {"persona": "", "profile": self.profile},
                    ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:
                pass
            return
        try:
            provider = await self.context.get_using_provider_async(getattr(event, "unified_msg_origin", ""))
            if provider is None:
                self.profile = dict(DEFAULT_PROFILE)
                return
            system = "你是人格参数编译器。只输出 JSON，不要解释。"
            prompt = text + """

返回 JSON：
{"O":0-1,"C":0-1,"E":0-1,"A":0-1,"N":0-1,
 "stress_reactivity":0-1,"recovery_rate":0-1,
 "social_baseline":0-1,"energy_baseline":0-1,
 "curiosity_baseline":0-1,"safety_baseline":0-1,
 "da_baseline":0-1,"oa_baseline":0-1,"ht_baseline":0-1,
 "autonomy_gain":0-1.5,"baseline_v":-1..1,"baseline_a":0-1,
 "learning_rate":0.01-0.12}
只输出 JSON。"""
            resp = await provider.text_chat(prompt=prompt, system_prompt=system)
            raw = str(getattr(resp, "completion_text", "") or "")
            lo, hi = raw.find("{"), raw.rfind("}")
            if lo >= 0 and hi > lo:
                data = json.loads(raw[lo:hi + 1])
                merged = dict(DEFAULT_PROFILE)
                for k in merged:
                    if k in data:
                        merged[k] = _clip(data[k], -1 if k == "baseline_v" else 0,
                                          1.5 if k == "autonomy_gain" else 1)
                self.profile = merged
            else:
                self.profile = dict(DEFAULT_PROFILE)
        except Exception as exc:
            logger.warning("[biocore] persona compile failed: %s", exc)
            self.profile = dict(DEFAULT_PROFILE)
        self.persona_text = text
        try:
            PROFILE_PATH.write_text(json.dumps(
                {"persona": self.persona_text, "profile": self.profile},
                ensure_ascii=False, indent=1), encoding="utf-8")
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
                for key in ("proactive_reply", "memory_dedup_embedding", "inject_intent", "kb_enabled"):
                    if key in d and key not in self.config:
                        setattr(self, key, bool(d[key]))
                if isinstance(d.get("kb_names"), list) and "kb_names" not in self.config:
                    self.kb_names = [str(x) for x in d.get("kb_names") if str(x).strip()]
        except Exception as exc:
            logger.warning("[biocore] settings load failed: %s", exc)

    def _save_settings(self):
        try:
            self._settings_path().write_text(json.dumps({
                "proactive_reply": bool(self.proactive_reply),
                "memory_dedup_embedding": bool(self.memory_dedup_embedding),
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

    @staticmethod
    def _image_health_ok() -> bool:
        try:
            req = urllib.request.Request(IMAGE_SERVICE_HEALTH, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                return 200 <= int(resp.status) < 300
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
        if self._image_health_ok():
            return True
        if self._image_service_lock is None:
            self._image_service_lock = asyncio.Lock()
        async with self._image_service_lock:
            if self._image_health_ok():
                self._image_last_used = time.time()
                return True
            try:
                if not LLAMA_SERVER.is_file() or not LLAMA_MODEL.is_file():
                    logger.warning("[biocore] image service files missing")
                    return False
                args = [str(LLAMA_SERVER), "-m", str(LLAMA_MODEL)]
                if LLAMA_MMPROJ.is_file():
                    args += ["--mmproj", str(LLAMA_MMPROJ)]
                args += ["--host", "127.0.0.1", "--port", str(IMAGE_SERVICE_PORT),
                         "-ngl", "99", "-c", "8192", "-np", "1", "-lm", "none",
                         "-cram", "0", "-ctxcp", "0", "--no-warmup"]
                flags = 0x08000000 if os.name == "nt" else 0
                self._image_proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                                    stderr=subprocess.DEVNULL,
                                                    creationflags=flags)
                logger.info("[biocore] image service starting pid=%s", self._image_proc.pid)
                for _ in range(60):
                    if self._image_health_ok():
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
            d["interactions"] = int(d.get("interactions", 0) or 0) + 1
            d["last_seen"] = time.time()
            d.setdefault("first_seen", time.time())
            try:
                _ct = float(getattr(core, "trust", 0.5)) if core is not None else 0.5
                d["trust"] = round(0.7 * float(d.get("trust", 0.5) or 0.5) + 0.3 * _ct, 3)
            except Exception:
                d["trust"] = d.get("trust", 0.5)
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

    def _maybe_periodic_reflection(self, event, core) -> None:
        try:
            if time.time() - float(getattr(self, "_last_reflection", 0.0)) < float(getattr(self, "reflection_interval_hours", 6)) * 3600:
                return
            self._last_reflection = time.time()
            asyncio.create_task(self._archive_cross_event_insight(event, core))
        except Exception:
            pass

    async def _archive_cross_event_insight(self, event, core):
        events = self._event_archive(6)
        if len(events) < 3:
            return
        try:
            provider = await self.context.get_using_provider_async(
                getattr(event, "unified_msg_origin", "") or "")
            if provider is None:
                return
            prompt = interpretation.insight_prompt(events)
            resp = await provider.text_chat(prompt=prompt)
            raw = str(getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {}
            insight = str(data.get("insight") or "").strip()[:500]
            if insight:
                self._append_insight({"ts": time.time(), "insight": insight,
                                      "emotion": str(core.labels.get("emotion") or "neutral") if core else "neutral"})
                try:
                    if core is not None:
                        tree = getattr(core, "reflection_tree", None)
                        if not isinstance(tree, dict):
                            tree = {"roots": [], "count": 0}
                        node = {"ts": time.time(), "insight": insight,
                                "emotion": str(core.labels.get("emotion") or "neutral"), "children": []}
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
                logger.info("[biocore] cross-event insight archived")
        except Exception as exc:
            logger.warning("[biocore] cross-event insight failed: %s", exc)

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

    async def _archive_ranked_events(self, event, core, entries):
        if not entries:
            return
        try:
            provider = await self.context.get_using_provider_async(
                getattr(event, "unified_msg_origin", "") or "")
            if provider is None:
                return
            texts = []
            source_ts = []
            attachments = []
            for e in entries[-24:]:
                t = str(e.get("text", "")).strip()
                cap = str(e.get("image_caption", "") or "").strip()
                if cap:
                    t = (t + "\n[图片内容] " + cap).strip() if t else ("[图片内容] " + cap)
                if t:
                    texts.append(t)
                    try:
                        _ts = float(e.get("ts", 0) or 0)
                    except Exception:
                        _ts = 0.0
                    if _ts > 0:
                        source_ts.append(_ts)
                try:
                    attachments.extend(e.get("attachments") or [])
                except Exception:
                    pass
            if not texts:
                return
            prompt = interpretation.event_ranking_prompt(texts)
            resp = await provider.text_chat(prompt=prompt)
            raw = str(getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\[.*\]", raw, re.S)
            if not m:
                return
            items = json.loads(m.group(0))
            if not isinstance(items, list):
                return
            ranked = []
            for ev in items:
                if not isinstance(ev, dict):
                    continue
                try:
                    imp = float(ev.get("importance", 0) or 0)
                except Exception:
                    imp = 0.0
                emo = str(ev.get("emotion") or "neutral")
                body = str(ev.get("event") or "").strip()
                if imp < 0.6 or emo == "neutral" or not body:
                    continue
                ranked.append((imp, ev))
            ranked.sort(key=lambda x: x[0], reverse=True)
            for imp, ev in ranked[:3]:
                _title = str(ev.get("title") or "重要事件").strip()[:80]
                _body = str(ev.get("event") or "").strip()[:600]
                _meaning = str(ev.get("meaning_to_her") or "").strip()[:400]
                _reflection = str(ev.get("reflection") or "").strip()[:400]
                _prov = self._event_provenance(event, entries, ts=time.time())
                _check = self._source_check(_body, texts, provenance=_prov, record_ts=_prov.get("ts"))
                _ekey = self._normalize_event_key(ev.get("event_key") or _title, _title)
                _ev_vec = None
                try:
                    _ev_vec = await self._embed_text(_body)
                except Exception:
                    _ev_vec = None
                record = {
                    "id": "evt_" + str(int(time.time())) + "_" + str(abs(hash(_title + _body)) % 100000),
                    "ts": time.time(),
                    "session": str(getattr(event, "unified_msg_origin", "") or ""),
                    "title": _title,
                    "event": _body,
                    "event_key": _ekey,
                    "centrality": round(max(0.0, min(1.0, float(ev.get("centrality", imp) or imp))), 3),
                    "central_details": str(ev.get("central_details") or _body)[:400],
                    "peripheral_details": str(ev.get("peripheral_details") or "")[:300],
                    "central_weight": round(0.4 + 0.6 * max(0.0, min(1.0, float(ev.get("centrality", imp) or imp))), 3),
                    "peripheral_weight": round(max(0.05, 0.6 * (1.0 - max(0.0, min(1.0, float(ev.get("centrality", imp) or imp))))), 3),
                    "peripheral_retention": round(max(0.05, 1.0 - max(0.0, min(1.0, float(ev.get("centrality", imp) or imp)))), 3),
                    "meaning_to_her": _meaning,
                    "reflection": _reflection,
                    "emotion": str(ev.get("emotion") or "neutral"),
                    "importance": round(imp, 3),
                    "appraisal": dict(core.appraisal) if core is not None else {},
                    "confidence": round(max(0.2, min(1.0, 0.55 + 0.45 * float(_check.get("overlap", 0)))), 3),
                    "source_count": len(texts),
                    "source_check": _check,
                    "provenance": _prov,
                    "attachments": attachments[:20],
                    "modalities": sorted(set(["图片"] if any(a.get("type") == "image" for a in attachments) else [])),
                    "recall_count": 0,
                    "last_recall": time.time(),
                    "strength": round(imp, 3),
                    "source_texts": texts[:12],
                }
                # MemoryBank time window: source entries' earliest / latest ts.
                _valid_ts = sorted(source_ts)
                if _valid_ts:
                    record["time_span"] = {
                        "start_ts": round(_valid_ts[0], 3),
                        "end_ts": round(_valid_ts[-1], 3),
                        "span_seconds": round(_valid_ts[-1] - _valid_ts[0], 3),
                    }
                    record["summary_window"] = {
                        "earliest_ts": round(_valid_ts[0], 3),
                        "latest_ts": round(_valid_ts[-1], 3),
                        "source_count": len(texts),
                    }
                _dup = self._find_duplicate_event(record.get("session") or "", _ekey, _body,
                                                  record.get("ts") or time.time())
                if _dup is not None:
                    record["duplicate_of"] = str(_dup.get("id") or "")
                    self._merge_archive_duplicate(_dup, record)
                    continue
                _bnd = self._event_boundary(record.get("session") or "", _body, record.get("ts") or time.time())
                record["boundary_score"] = _bnd.get("boundary_score", 0.0)
                record["parent_event_id"] = _bnd.get("parent_event_id", "")
                if _ev_vec:
                    record["event_embedding"] = [round(float(x), 5) for x in _ev_vec]
                self._append_event_archive(record)
                if core is not None:
                    core.remember_event(str(record.get("event_key") or _title), _title,
                                        _meaning, _reflection, embedding=_ev_vec)
                self._update_self_narrative(_title, _reflection or _meaning)
                logger.info("[biocore] ranked event archived: %s imp=%.2f", _title, imp)
        except Exception as exc:
            logger.warning("[biocore] ranked event extraction failed: %s", exc)

    async def _archive_strong_event(self, event, core, texts, summary, attachments=None):
        if core is None:
            return
        intensity = float(core._intensity())
        strong = (intensity >= 0.35 or abs(float(core.v)) >= 0.40 or
                  float(core.a) >= 0.75 or float(core.stress) >= 0.65 or
                  (abs(float(core.v)) >= 0.28 and float(core.a) >= 0.60))
        if not strong or not texts:
            return
        try:
            provider = await self.context.get_using_provider_async(
                getattr(event, "unified_msg_origin", "") or "")
            if provider is None:
                return
            prompt = interpretation.event_summary_prompt(texts)
            resp = await provider.text_chat(prompt=prompt)
            raw = str(getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {}
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
            _dup = self._find_duplicate_event(record.get("session") or "", _ekey, ev,
                                              record.get("ts") or time.time())
            if _dup is not None:
                record["duplicate_of"] = str(_dup.get("id") or "")
                self._merge_archive_duplicate(_dup, record)
                return
            _bnd = self._event_boundary(record.get("session") or "", ev, record.get("ts") or time.time())
            record["boundary_score"] = _bnd.get("boundary_score", 0.0)
            record["parent_event_id"] = _bnd.get("parent_event_id", "")
            self._append_event_archive(record)
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
        if not await self._ensure_image_service():
            return ""
        self._image_last_used = time.time()
        cache = self._load_image_cache()
        missing = [r for r in refs if _sha256(r) not in cache]
        if missing:
            try:
                cfg = self.context.get_config()
                provider_settings = cfg.get("provider_settings", {}) if isinstance(cfg, dict) else {}
                provider_id = str(provider_settings.get("default_image_caption_provider_id") or "exusiai-img")
                prompt = str(provider_settings.get("image_caption_prompt") or
                             "请客观描述这张图片，供角色扮演聊天使用。")
                provider = self.context.get_provider_by_id(provider_id)
                if provider is not None:
                    for ref in missing[:3]:
                        try:
                            resp = await provider.text_chat(prompt=prompt, image_urls=[ref])
                            caption = str(getattr(resp, "completion_text", "") or "").strip()
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
                register("/astrbot_plugin_biocore/page/consolidate", self.page_consolidate, ["POST"],
                         "BioCore memory consolidation")
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

    async def page_status(self):
        cores = []
        for key, core in list(self.cores.items())[:20]:
            cores.append({
                "key": key,
                "snapshot": core.snapshot(),
                "intent": {**core.intent(), "plan": interpretation.plan(core)},
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
                    })
                except Exception:
                    continue
        return {"status": "ok", "data": {
            "enabled": self.enabled,
            "inject_intent": self.inject_intent,
            "proactive_reply": self.proactive_reply,
            "memory_dedup_embedding": self.memory_dedup_embedding,
            "persona_loaded": bool(self.persona_text),
            "profile": self.profile or dict(DEFAULT_PROFILE),
            "api_config": self._public_api_config(),
            "memory": self._memory_stats(),
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
        if key not in ("proactive_reply", "memory_dedup_embedding", "inject_intent"):
            return {"status": "error", "message": "unknown setting"}
        setattr(self, key, bool(data.get("value")))
        self._save_settings()
        await self._persist_plugin_config({key: bool(getattr(self, key))})
        logger.info("[biocore] setting %s=%s", key, getattr(self, key))
        return {"status": "ok", "data": {"key": key, "value": getattr(self, key)}}

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
                return d
        except Exception:
            pass
        return {"entries": []}

    def _save_memory(self, event, doc):
        try:
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

    def _memory_tau(self, core) -> float:
        profile = self.profile or DEFAULT_PROFILE
        recovery = float(profile.get("recovery_rate", 0.62) or 0.62)
        stress = float(getattr(core, "stress", 0.1)) if core is not None else 0.1
        trust = float(getattr(core, "trust", 0.5)) if core is not None else 0.5
        days = 2.0 + 14.0 * recovery
        days *= max(0.25, 1.0 - 0.55 * stress)
        days *= 0.8 + 0.4 * trust
        return max(3600.0, days * 86400.0)

    def _memory_score(self, core, entry: dict, cosine: float) -> float:
        importance = float(entry.get("importance", 0.5) or 0.5)
        age = max(0.0, time.time() - float(entry.get("ts", 0) or 0))
        # ACT-R-style power-law recency rather than pure exponential.
        age_days = age / 86400.0
        recency = 1.0 / math.pow(1.0 + max(0.0, age_days) * 0.35, 0.55)
        # biological emphasis: salient/trusted memories survive longer
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
        # MemoryBank retention probability R = exp(-t/S)
        try:
            stability = max(0.2, float(entry.get("stability_days", 1.0) or 1.0))
        except Exception:
            stability = 1.0
        retention = math.exp(-age_days / stability)
        # ACT-R base-level activation for a single trace: B = ln(t^-d).
        try:
            _d = ACT_R_DECAY
            _b = math.log(max(1e-9, (age_days + 0.05) ** (-_d)))
            base = 1.0 / (1.0 + math.exp(-(_b + 1.0)))
        except Exception:
            base = 0.5
        return (cosine * (0.40 + 0.60 * importance) * recency
                * (0.65 + 0.35 * retention)
                * (0.85 + 0.15 * base)
                * (1.0 + 0.10 * math.log1p(max(0, recall_count)))
                * due
                * (1.0 + 0.05 * math.log1p(max(0, assoc))))

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
            provider = await self.context.get_using_provider_async(
                getattr(event, "unified_msg_origin", "") or "")
            if provider is None:
                return
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
                    await self._archive_cross_event_insight(event, core)
                return
            changed = False
            for group in groups:
                texts = [str(entries[i].get("text", "")).strip() for i in group if str(entries[i].get("text", "")).strip()]
                if len(texts) < 2:
                    continue
                prompt = ("把下面这些长期记忆合并成一条不超过 180 字的中文摘要。"
                          "保留人物、关系、偏好、承诺、事件和情绪变化；不要编造；只输出摘要。\n\n" + "\n".join("- " + t[:500] for t in texts))
                try:
                    resp = await provider.text_chat(prompt=prompt)
                    summary = str(getattr(resp, "completion_text", "") or "").strip()
                except Exception as exc:
                    logger.warning("[biocore] memory summary failed: %s", exc)
                    summary = ""
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
                entries.append({"text": summary[:1200], "role": "summary", "vector": vec,
                                "ts": now, "hits": 1, "importance": importance,
                                "last_used": now, "summary_id": _sum_id,
                                "provenance": _summary_prov})
                changed = True
            if changed:
                await self._archive_ranked_events(event, core, entries)
                await self._archive_cross_event_insight(event, core)
                self._trim_memory(doc, core)
                self._save_memory(event, doc)
                logger.info("[biocore] memory consolidated groups=%s entries=%s", len(groups), len(entries))
        finally:
            self._consolidating = False

    async def _memory_recall(self, event, text: str, core=None, extra: str = "", vec=None, voice: str = "") -> str:
        if not self.memory_dedup_embedding or not self._usable_memory_text(text):
            return ""
        if vec is None:
            vec = await self._embed_text(text)
        if not vec:
            return ""
        doc = self._load_memory(event)
        entries = doc.get("entries")
        if not isinstance(entries, list):
            entries = []
            doc["entries"] = entries
        scored = []
        duplicate = None
        now = time.time()
        _just_restabilized = set()
        for e in entries:
            if e.get("summarized"):
                continue
            if self._restabilize_if_expired(e, now):
                _just_restabilized.add(id(e))
            cosine = self._cosine(vec, e.get("vector") or [])
            score = self._memory_score(core, e, cosine)
            if cosine >= 0.93:
                duplicate = e
            # ACT-R partial matching + retrieval threshold (named constants).
            if cosine >= PARTIAL_MATCH_THRESHOLD and score >= RETRIEVAL_THRESHOLD:
                scored.append((score, e))
        if duplicate is not None:
            duplicate["ts"] = now
            duplicate["last_used"] = now
            duplicate["hits"] = int(duplicate.get("hits", 0)) + 1
            _sid, _sname = self._speaker(event)
            if _sid:
                duplicate["sender_id"] = _sid
            if _sname:
                duplicate["sender_name"] = _sname
            if extra:
                duplicate["image_caption"] = str(extra).strip()[:1600]
            if voice:
                duplicate["voice_text"] = str(voice).strip()[:1200]
            duplicate["provenance"] = self._memory_provenance(event, now)
        else:
            _sid, _sname = self._speaker(event)
            entries.append({"text": text[:1200], "role": "user", "vector": vec,
                            "ts": now, "hits": 1,
                            "sender_id": _sid, "sender_name": _sname,
                            "attachments": self._attachments_from_messages(event),
                            "image_caption": str(extra or "").strip()[:1600],
                            "voice_text": str(voice or "").strip()[:1200],
                            "provenance": self._memory_provenance(event, now),
                            "importance": self._memory_importance(core, "user"),
                            "last_used": now, "next_review_ts": now + 86400, "review_count": 0})
            self._trim_memory(doc, core)
        self._save_memory(event, doc)
        self._schedule_consolidation(event, core)
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:self._memory_top_k(core)]
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
                _eid = self._sha256(str(e.get("text", ""))[:300])[:12]
                e["id"] = _eid
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
        try:
            self._save_memory(event, doc)
        except Exception:
            pass
        lines = []
        for score, e in top:
            role = "用户" if e.get("role") != "assistant" else "你"
            if e.get("role") != "assistant":
                who = str(e.get("sender_name") or e.get("sender_id") or "").strip()
                if who:
                    role = who
            snippet = str(e.get("text", "")).strip().replace("\n", " ")
            if snippet:
                lines.append("- %s：%s" % (role, snippet[:240]))
        if not lines:
            return ""
        return "\n".join(lines)

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
            if e.get("summarized"):
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
        self._trim_memory(doc, core)
        self._save_memory(event, doc)
        self._schedule_consolidation(event, core)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        if not self.enabled or not self.inject_intent:
            return
        await self._ensure_profile(event)
        core = self._core(event)
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
        self._maybe_periodic_reflection(event, core)
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
        req.system_prompt = (_base + "\n\n" + interpretation.render_compact(
            core,
            _mem.replace("[BioCore Memory]", "").strip(),
            _events.replace("[BioCore Events]", "").strip(),
            self.self_model,
            _user_data,
            _img.replace("[BioCore Image]", "").strip(),
            _kb,
            _speaker,
            _voice,
        )).strip()

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
