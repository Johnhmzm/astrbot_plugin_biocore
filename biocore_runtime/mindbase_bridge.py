# -*- coding: utf-8 -*-
"""Bridge to the digital-fly substrate (mindbase).

The substrate (mushroom body, survival gauntlet, QD/DE evolution) has lived in
its own package since the start and was never called from this runtime. This
module is the seam: it lets the core run the fly body in an environment and
evolve its genes, without putting any of that on the per-turn path.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence, Tuple

_IMPORT_ERROR = None
try:  # pragma: no cover - import probe
    from mindbase import MindBase, MindConfig
    from mindbase.grid_world import EmbodiedLoop, GridWorld
    from mindbase.experiments import apply_genome, BASE_BOUNDS
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = str(exc)[:200]


def available() -> bool:
    """True when the digital-fly substrate can be imported here."""
    return _IMPORT_ERROR is None


def unavailable_reason() -> str:
    return _IMPORT_ERROR or ""


def run_episode(genome: Optional[Sequence[float]] = None, seed: int = 1,
                steps: int = 40) -> Dict[str, float]:
    """One embodied episode in the grid world; returns the fitness inputs."""
    if _IMPORT_ERROR:
        raise RuntimeError("mindbase unavailable: " + _IMPORT_ERROR)
    mind = MindBase(MindConfig(seed=int(seed)))
    if genome:
        apply_genome(mind, tuple(genome))
    loop = EmbodiedLoop(mind, GridWorld(seed=int(seed), noise=0.1),
                        traits={"hunger_threshold": 0.5, "thirst_threshold": 0.5})
    out = loop.run(steps=int(steps)) if "steps" in loop.run.__code__.co_varnames else loop.run()
    auto = out.get("autonomy") or {}
    return {"energy": float(out.get("energy") or 0.0),
            "viability": float(out.get("viability") or 0.0),
            "initiative": float(auto.get("initiative") or 0.0),
            "ticks": int(out.get("ticks") or 0)}


def fitness(metrics: Dict[str, float]) -> float:
    """Same weights the substrate's own evolution loop uses."""
    return round(0.45 * min(1.0, metrics["energy"])
                 + 0.35 * metrics["initiative"]
                 + 0.20 * metrics["viability"], 4)


def evolve(generations: int = 3, population: int = 6, steps: int = 40,
           seed: int = 1, reward_fn=None) -> Dict[str, object]:
    """Small DE/rand/1/bin over the substrate genes.

    reward_fn(metrics) -> float lets a caller replace the stock fitness (for
    example with a dialogue-derived score) without touching this loop.
    """
    if _IMPORT_ERROR:
        raise RuntimeError("mindbase unavailable: " + _IMPORT_ERROR)
    rnd = random.Random(seed)
    bounds = [(float(lo), float(hi)) for lo, hi in BASE_BOUNDS]
    def rand_vec() -> List[float]:
        return [round(rnd.uniform(lo, hi), 4) for lo, hi in bounds]
    score_of = reward_fn or (lambda m: fitness(m))
    # DE/rand/1/bin needs three distinct donors besides the target
    pop = [rand_vec() for _ in range(max(4, int(population)))]
    best, best_fit = None, -1e9
    history = []
    for gen in range(max(1, generations)):
        fits = []
        for vec in pop:
            try:
                m = run_episode(vec, seed=seed + gen, steps=steps)
                f = float(score_of(m))
            except Exception:
                f = -1.0
            fits.append(f)
        idx = max(range(len(pop)), key=lambda i: fits[i])
        if fits[idx] > best_fit:
            best_fit, best = fits[idx], list(pop[idx])
        history.append({"gen": gen, "best": round(fits[idx], 4),
                        "mean": round(sum(fits) / len(fits), 4)})
        for i in range(len(pop)):
            a, b, c = rnd.sample([j for j in range(len(pop)) if j != i], 3)
            F = 0.5
            trial = []
            for k, (lo, hi) in enumerate(bounds):
                v = pop[a][k] + F * (pop[b][k] - pop[c][k])
                trial.append(round(max(lo, min(hi, v)), 4))
            if fits[i] <= best_fit or rnd.random() < 0.5:
                pop[i] = trial
    return {"best": best, "fitness": best_fit, "history": history,
            "bounds": bounds}


class DialogueBody:
    """One MindBase instance fed by chat turns.

    The substrate appraises structured dimensions, not sentences: text alone
    moved valence by 0.02 across clearly different messages, while the same
    texts with valence/arousal/social/control supplied moved it by 0.09 and
    split stress 0.013 vs 0.128. So the caller must appraise first.
    """

    def __init__(self, seed: int = 1, noise: bool = True):
        if _IMPORT_ERROR:
            raise RuntimeError("mindbase unavailable: " + _IMPORT_ERROR)
        from mindbase import MindBase, MindConfig
        self.mind = MindBase(MindConfig(seed=int(seed)))
        # The substrate ships an endogenous noise source (critical network,
        # 1/f OU, criticality controller) with inject(mind) built for exactly
        # this. Nothing in the runtime ever called it: idle ticks used the
        # 0.03 white noise in affect and drifted 0.035 over 200 steps, with
        # every seed choosing the same action. Wire the real source.
        self.noise = None
        if noise:
            try:
                from mindbase.noise import EndogenousNoise
                self.noise = EndogenousNoise(seed=int(seed))
            except Exception:
                self.noise = None

    def _tick_once(self, dt: float = 60.0) -> None:
        if self.noise is not None:
            try:
                self.noise.step(dt=float(dt))
                # Drives are the integrator; affect is recomputed from its
                # target every tick, so a push there is erased within one
                # step (0.9 -> 0.02). EndogenousNoise.inject writes affect,
                # which is why wiring it changed nothing: the numbers were
                # identical at gain 0.18, 0.6 and 1.2 with 1x and 3x calls.
                nv = float(self.noise.network.last_noise)
                for name in ("energy", "social", "safety", "curiosity"):
                    cur = float(self.mind.drives.values.get(name, 0.5))
                    val = cur + BODY_NOISE_AMP * nv * 0.5
                    self.mind.drives.values[name] = max(0.0, min(1.0, val))
            except Exception:
                pass
        self.mind.tick()

    def feed(self, text: str, dims: Optional[Dict[str, float]] = None,
             ticks: int = 1) -> Dict[str, float]:
        """Advance the body by one user message."""
        from mindbase.types import Event
        d = dims or {}
        ev = Event(text=str(text or ""), speaker="user", kind="message",
                   domain="chat",
                   valence=d.get("valence"), arousal=d.get("arousal"),
                   social=d.get("social"), control=d.get("control"),
                   relevance=d.get("relevance"))
        self.mind.step(ev)
        for _ in range(max(0, int(ticks))):
            self._tick_once()
        return self.state()

    def reply(self, text: str = "", ticks: int = 0) -> Dict[str, float]:
        """Record her own utterance (what she said, not what she heard)."""
        try:
            self.mind.post_reply(str(text or ""))
        except Exception:
            pass
        for _ in range(max(0, int(ticks))):
            self._tick_once()
        return self.state()

    def idle(self, ticks: int = 1) -> Dict[str, float]:
        """Pass time with no input: this is where the noise shows up."""
        for _ in range(max(0, int(ticks))):
            self._tick_once()
        return self.state()

    def state(self) -> Dict[str, float]:
        st = self.mind.unified_state()
        A = st.get("A") or {}
        ai = st.get("active_inference") or {}
        self_ = st.get("self") or {}
        dr = (st.get("drives") or {}).get("values") or {}
        return {"valence": round(float(A.get("valence") or 0.0), 4),
                "arousal": round(float(A.get("arousal") or 0.0), 4),
                "stress": round(float(A.get("stress") or 0.0), 4),
                "mood": round(float(A.get("mood") or 0.0), 4),
                "agency": round(float(self_.get("agency") or 0.0), 4),
                "social_drive": round(float(dr.get("social") or 0.0), 4),
                "action": str(ai.get("action") or "")}


def appraise_text(text: str, config: Optional[Dict[str, object]] = None,
                  timeout: float = 60.0) -> Dict[str, float]:
    """Ask the configured small model for the six dimensions the body needs.

    This is the crossing layer on the way down: language becomes numbers here
    and nowhere else. Failure returns {} so the body keeps its own dynamics.
    """
    cfg = dict(config or {})
    base = str(cfg.get("base_url") or "").rstrip("/")
    model = str(cfg.get("model") or "")
    key = str(cfg.get("key") or cfg.get("api_key") or "")
    if not (base and model and key):
        return {}
    prompt = ("把这句话评成 6 个维度，只输出 JSON：{\"valence\":-1..1,"
              "\"arousal\":0..1,\"dominance\":-1..1,\"relevance\":0..1,"
              "\"social\":-1..1,\"control\":0..1}。不要解释。")
    import json as _json
    import re as _re
    import urllib.request as _url
    body = _json.dumps({"model": model, "temperature": 0,
                        "messages": [{"role": "system", "content": prompt},
                                     {"role": "user", "content": str(text or "")[:1200]}]}).encode()
    req = _url.Request(base + "/chat/completions", data=body,
                       headers={"Authorization": "Bearer " + key,
                                "Content-Type": "application/json"})
    try:
        with _url.urlopen(req, timeout=timeout) as resp:
            raw = _json.loads(resp.read().decode())["choices"][0]["message"]["content"]
        m = _re.search(r"\{.*\}", raw, _re.S)
        data = _json.loads(m.group(0)) if m else {}
    except Exception:
        return {}
    out = {}
    for name in ("valence", "arousal", "dominance", "relevance", "social", "control"):
        if name in data:
            try:
                out[name] = float(data[name])
            except Exception:
                continue
    return out


BODY_STATE_FILE = "mindbase_body.json"
RECALL_DIGEST_FILE = "recall_digest.txt"
import os as _os
# 0.30 is where spontaneous choice appears: at 200 idle ticks, 3 of 12 seeds
# pick silence instead of speak. Below 0.15 every seed does the same thing.
BODY_NOISE_AMP = float(_os.environ.get("BIOCORE_BODY_NOISE_AMP") or 0.30)


def _body_path(store, session_id):
    import os
    import re
    sid = re.sub(r"[^0-9A-Za-z_.-]", "_", str(session_id or "s1"))[:60]
    return os.path.join(str(store), "sessions", sid, BODY_STATE_FILE)


def load_state(store, session_id) -> Dict[str, float]:
    """Read the last persisted body state for one session (may be empty)."""
    import json
    import os
    path = _body_path(store, session_id)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        out = {}
        for key, value in data.items():
            if isinstance(value, (int, float)):
                out[key] = float(value)
            elif key == "action" and isinstance(value, str):
                # the body's decision is a string; dropping it here made every
                # restored turn look like it wanted to speak
                out[key] = value
        return out
    except Exception:
        return {}


def save_state(store, session_id, state: Dict[str, float]) -> bool:
    import json
    import os
    path = _body_path(store, session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def body_for(store, session_id, seed: int = 1) -> "DialogueBody":
    """A body resumed from disk: the process dies every turn, the state does not."""
    body = DialogueBody(seed=seed)
    prev = load_state(store, session_id)
    if prev:
        try:
            body.mind.inject_affect(prev.get("valence", 0.0),
                                    prev.get("arousal", 0.5),
                                    prev.get("dominance", 0.0),
                                    intensity=1.0, blend=1.0)
        except Exception:
            pass
    return body


def save_digest(store, session_id, lines) -> bool:
    """Remember what she just recalled, so it can colour the next turn.

    A separate model call for recalled text would double the per-turn cost.
    Instead the digest rides along with the next turn's own appraisal, which
    is also truer to how memory works: something surfaces, then colours what
    comes after it.
    """
    import os
    path = _body_path(store, session_id).replace(BODY_STATE_FILE, RECALL_DIGEST_FILE)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(str(x) for x in (lines or []))[:600])
        return True
    except Exception:
        return False


def load_digest(store, session_id) -> str:
    import os
    path = _body_path(store, session_id).replace(BODY_STATE_FILE, RECALL_DIGEST_FILE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def turn(store, session_id, text: str, dims: Optional[Dict[str, float]] = None,
         seed: int = 1, with_memory: bool = True) -> Dict[str, float]:
    """One user turn: resume, feed, persist, return the new state."""
    body = body_for(store, session_id, seed=seed)
    state = body.feed(text, dims)
    if with_memory:
        digest = load_digest(store, session_id)
        if digest:
            # what she recalled last turn is still in the room
            state = body.feed(digest, dims, ticks=0)
    save_state(store, session_id, state)
    return state


def state_line(state: Dict[str, float]) -> str:
    """One line of body state for the prompt. Quantities only, no advice."""
    if not state:
        return ""
    v = state.get("valence", 0.0)
    s = state.get("stress", 0.0)
    a = state.get("arousal", 0.0)
    mood = "低落" if v <= -0.15 else ("轻快" if v >= 0.15 else "平稳")
    tension = "紧绷" if s >= 0.25 else ("松弛" if s <= 0.08 else "适中")
    return "【身体】情绪%s（%.2f）· 紧张度%s（%.2f）· 唤醒%.2f" % (mood, v, tension, s, a)
