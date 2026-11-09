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
        # A slow baseline that the message writes into. The per-tick OU pulls
        # affect back to a target derived from the last appraisal, so a single
        # message never survives; the anchor is what an experience changes.
        self.anchor = {"valence": 0.0, "arousal": 0.5, "stress": 0.0}
        self.commit = {"open": 0.0, "kept": 0.0}
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
        try:
            a = self.anchor
            aff = self.mind.affect
            aff.v = max(-1.0, min(1.0, aff.v + ANCHOR_GAIN * (a["valence"] - aff.v)))
            aff.stress = max(0.0, min(1.0, aff.stress + ANCHOR_GAIN * (a["stress"] - aff.stress)))
        except Exception:
            pass

    def feed(self, text: str, dims: Optional[Dict[str, float]] = None,
             ticks: int = 1) -> Dict[str, float]:
        """Advance the body by one user message."""
        from mindbase.types import Event
        d = dims or {}
        # Tick first, push last. tick() re-derives affect from its target every
        # call, so a push applied before it is erased within the same message
        # (that is how 18 hours of drift vanished on one greeting).
        for _ in range(max(0, int(ticks))):
            self._tick_once()
        if d:
            try:
                self.anchor["valence"] = round(
                    self.anchor["valence"] * (1 - ANCHOR_LEARN)
                    + float(d.get("valence") or 0.0) * ANCHOR_LEARN, 4)
                self.anchor["stress"] = round(
                    self.anchor["stress"] * (1 - ANCHOR_LEARN)
                    + max(0.0, -float(d.get("valence") or 0.0)) * 0.6 * ANCHOR_LEARN, 4)
            except Exception:
                pass
            try:
                kind = str(d.get("commitment") or "none")
                if kind == "made":
                    self.commit["open"] = self.commit["open"] + 1.0
                elif kind == "kept":
                    self.commit["kept"] = self.commit["kept"] + 1.0
                    self.commit["open"] = max(0.0, self.commit["open"] - 1.0)
            except Exception:
                pass
            try:
                self.mind.inject_affect(float(d.get("valence") or 0.0),
                                        float(d.get("arousal") or 0.5),
                                        float(d.get("dominance") or 0.0),
                                        intensity=PUSH_GAIN, blend=PUSH_GAIN)
            except Exception:
                pass
        else:
            self.mind.step(Event(text=str(text or ""), speaker="user",
                                 kind="message", domain="chat"))
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
                "action": str(ai.get("action") or ""),
                "anchor_valence": round(float(self.anchor["valence"]), 4),
                "anchor_stress": round(float(self.anchor["stress"]), 4),
                "commit_open": float(self.commit["open"]),
                "commit_kept": float(self.commit["kept"])}


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
    prompt = ("把这句话评成 6 个维度并判断有没有承诺，只输出 JSON："
              "{\"valence\":-1..1,\"arousal\":0..1,\"dominance\":-1..1,"
              "\"relevance\":0..1,\"social\":-1..1,\"control\":0..1,"
              "\"commitment\":\"none|made|kept\"}。"
              "commitment: made=这句话里立下或接受了某件将来要做的事；"
              "kept=提到某件此前答应的事已经兑现；其余为 none。不要解释。")
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
    if str(data.get("commitment") or "") in ("made", "kept", "none"):
        out["commitment"] = str(data["commitment"])
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
# how hard one message pushes the body: 1.0 = replace, 0.35 = nudge
PUSH_GAIN = float(_os.environ.get("BIOCORE_BODY_PUSH") or 0.35)
ANCHOR_GAIN = float(_os.environ.get("BIOCORE_ANCHOR_GAIN") or 0.04)
ANCHOR_LEARN = float(_os.environ.get("BIOCORE_ANCHOR_LEARN") or 0.25)


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
            body.anchor["valence"] = float(prev.get("anchor_valence") or 0.0)
            body.anchor["stress"] = float(prev.get("anchor_stress") or 0.0)
            body.commit["open"] = float(prev.get("commit_open") or 0.0)
            body.commit["kept"] = float(prev.get("commit_kept") or 0.0)
        except Exception:
            pass
        try:
            body.mind.inject_affect(prev.get("valence", 0.0),
                                    prev.get("arousal", 0.5),
                                    prev.get("dominance", 0.0),
                                    intensity=1.0, blend=1.0)
        except Exception:
            pass
    try:
        replay_mirror(body, store, session_id)
        restore_mb(body, store, session_id)
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


MIRROR_FILE = "mindbase_mirror.json"


def _mirror_path(store, session_id):
    return _body_path(store, session_id).replace(BODY_STATE_FILE, MIRROR_FILE)


def load_mirror(store, session_id):
    """Remembered lines mirrored from the main memory (survives the process)."""
    import json
    try:
        with open(_mirror_path(store, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_mirror(store, session_id, rows, cap: int = 200):
    import json
    import os
    rows = list(rows or [])[-int(cap):]
    path = _mirror_path(store, session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False)
        return True
    except Exception:
        return False


def mirror_recall(store, session_id, lines, valence: float = 0.0):
    """Copy recalled lines into the substrate's own memory.

    The two memories were separate systems that never exchanged anything. The
    substrate memory is not persisted (no restore path), so the mirrored rows
    are kept here and replayed into each fresh body.
    """
    rows = load_mirror(store, session_id)
    seen = {str(r.get("text") or "") for r in rows}
    for line in lines or []:
        text = str(line or "").lstrip("- ").strip()
        if not text or text in seen:
            continue
        rows.append({"text": text[:400], "valence": float(valence or 0.0)})
        seen.add(text)
    save_mirror(store, session_id, rows)
    return len(rows)


def replay_mirror(body, store, session_id, now: float = 0.0) -> int:
    """Write mirrored rows back into a fresh body's memory."""
    rows = load_mirror(store, session_id)
    written = 0
    mem = getattr(body.mind, "memory", None)
    if mem is None or not rows:
        return 0
    for row in rows:
        try:
            mem.write(str(row.get("text") or ""), importance=0.5, rpe=0.1,
                      now=now or float(body.mind.t),
                      valence=float(row.get("valence") or 0.0))
            written += 1
        except Exception:
            continue
    return written


NEEDS_FILE = "mindbase_needs.json"


def _needs_path(store, session_id):
    return _body_path(store, session_id).replace(BODY_STATE_FILE, NEEDS_FILE)


def higher_needs(state, history=None):
    """L3-L5: the needs the substrate's fitness never measured.

    Survival is a gate, not a goal: every organism clears it, so it cannot rank
    anything. These three are what separate alive from living well.
    """
    v = float((state or {}).get("valence") or 0.0)
    s = float((state or {}).get("stress") or 0.0)
    hist = list(history or [])[-12:]
    vals = [float(h.get("valence") or 0.0) for h in hist] or [v]
    mean_v = sum(vals) / len(vals)
    spread = (sum((x - mean_v) ** 2 for x in vals) / len(vals)) ** 0.5
    competence = max(0.0, min(1.0, 0.5 + 0.4 * mean_v - 0.5 * s - 0.3 * spread))
    speaks = sum(1 for h in hist if str(h.get("action") or "") == "speak")
    silences = sum(1 for h in hist if str(h.get("action") or "") == "silence")
    total = max(1, speaks + silences)
    balance = 1.0 - abs(speaks / total - 0.65)
    autonomy = max(0.0, min(1.0, 0.5 * balance + 0.5 * (1.0 - abs(v))))
    opened = float((state or {}).get("commit_open") or 0.0)
    kept = float((state or {}).get("commit_kept") or 0.0)
    meaning = kept / (opened + kept) if (opened + kept) > 0 else 0.5
    return {"competence": round(competence, 4), "autonomy": round(autonomy, 4),
            "meaning": round(meaning, 4)}


def fitness_of(state, history=None, survival=1.0):
    """Survival is a gate; the higher needs decide the ordering."""
    if survival < 0.5:
        return 0.0
    n = higher_needs(state, history)
    return round(0.45 * survival + 0.20 * n["competence"]
                 + 0.20 * n["autonomy"] + 0.15 * n["meaning"], 4)


def load_history(store, session_id):
    import json
    try:
        with open(_needs_path(store, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_history(store, session_id, data):
    import json
    import os
    path = _needs_path(store, session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return True
    except Exception:
        return False


def micro_evolve(store, session_id, state=None, step=0.03):
    """One tiny hill-climb per turn: continuous iteration, no batch run.

    At a few turns a day a real search never collects enough samples, but a
    hill-climb on one bounded knob still improves with one observation per turn.
    """
    hist = load_history(store, session_id)
    rows = list(hist.get("turns") or [])[-24:]
    if state:
        rows.append({"valence": float(state.get("valence") or 0.0),
                     "stress": float(state.get("stress") or 0.0),
                     "action": str(state.get("action") or "")})
    hist["turns"] = rows[-24:]
    fit = fitness_of(state or {}, rows)
    prev = float(hist.get("fitness") or 0.0)
    knob = float(hist.get("noise_amp") or BODY_NOISE_AMP)
    if rows and fit >= prev:
        knob = min(0.6, knob * (1.0 + step))
    else:
        knob = max(0.05, knob * (1.0 - step))
    hist["fitness"] = fit
    hist["noise_amp"] = round(knob, 4)
    hist["needs"] = higher_needs(state or {}, rows)
    save_history(store, session_id, hist)
    out = {"fitness": fit, "noise_amp": round(knob, 4)}
    out.update(hist["needs"])
    return out


def judge_exchange(user_text, reply_text, config=None, timeout=60.0):
    """The brain grades the exchange; the body only consumes the number.

    Reward was hand-written (did the human reply? how fast?). That puts the
    judgement in the harness instead of the model. Here the model reads both
    sides and returns how well the reply met the moment; the biological layer
    never invents its own meaning of success.
    """
    import json as _json
    import re as _re
    import urllib.request as _url
    cfg = dict(config or {})
    base = str(cfg.get("base_url") or "").rstrip("/")
    model = str(cfg.get("model") or "")
    key = str(cfg.get("key") or cfg.get("api_key") or "")
    if not (base and model and key):
        return {}
    prompt = ("判断这一来一回接住没有。只输出 JSON："
              "{\"reward\":-1..1,\"fit\":0..1,\"note\":\"不超过12字\"}。"
              "reward 负=答偏/伤人/答非所问，正=接住了对方真正在意的东西。不要解释。")
    body = _json.dumps({"model": model, "temperature": 0,
                        "messages": [{"role": "system", "content": prompt},
                                     {"role": "user",
                                      "content": "对方说：" + str(user_text or "")[:600]
                                      + chr(10) + "她回：" + str(reply_text or "")[:900]}]}).encode()
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
    for name in ("reward", "fit"):
        if name in data:
            try:
                out[name] = max(-1.0, min(1.0, float(data[name])))
            except Exception:
                continue
    if "note" in data:
        out["note"] = str(data["note"])[:24]
    return out


MB_FILE = "mindbase_mb.json"


def _mb_path(store, session_id):
    return _body_path(store, session_id).replace(BODY_STATE_FILE, MB_FILE)


def load_mb(store, session_id):
    import json
    try:
        with open(_mb_path(store, session_id), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_mb(store, session_id, data):
    import json
    import os
    path = _mb_path(store, session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return True
    except Exception:
        return False


def teach(store, session_id, cue, reward):
    """One teaching trial: DAN writes into the KC->MBON weights.

    This is the layer below the policy table. The policy learns *whether* to
    reach out; the mushroom body learns *which cue* predicts what. Both now
    consume the same number, graded by the model.
    """
    if _IMPORT_ERROR:
        return {}
    body = body_for(store, session_id)
    mb = getattr(body.mind, "mb", None)
    if mb is None:
        return {}
    try:
        out = mb.learn(str(cue or ""), float(reward or 0.0))
    except Exception as exc:
        return {"error": type(exc).__name__}
    try:
        save_mb(store, session_id, {
            "reward": list(getattr(mb.mbon_reward, "w", [])),
            "punish": list(getattr(mb.mbon_punishment, "w", [])),
        })
    except Exception:
        pass
    out = dict(out or {})
    out["cue"] = str(cue or "")[:40]
    return out


def restore_mb(body, store, session_id):
    data = load_mb(store, session_id)
    if not data:
        return 0
    mb = getattr(body.mind, "mb", None)
    if mb is None:
        return 0
    n = 0
    for key, target in (("reward", getattr(mb, "mbon_reward", None)),
                        ("punish", getattr(mb, "mbon_punishment", None))):
        vec = data.get(key)
        if not isinstance(vec, list) or target is None:
            continue
        try:
            if len(vec) == len(target.w):
                target.w = [float(x) for x in vec]
                n += 1
        except Exception:
            continue
    return n


CLOCK_FILE = "mindbase_clock.json"
TICK_SECONDS = 60.0        # one body tick per simulated minute
MAX_CATCHUP_TICKS = 480    # 8 hours: beyond that the gap is a "night", not a gap


def _clock_path(store, session_id):
    return _body_path(store, session_id).replace(BODY_STATE_FILE, CLOCK_FILE)


def _clock_load(store, session_id):
    import json
    try:
        with open(_clock_path(store, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _clock_save(store, session_id, ts):
    import json
    import os
    try:
        path = _clock_path(store, session_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"last_tick": float(ts)}, fh)
        return True
    except Exception:
        return False


def advance(store, session_id, now=None, seed=1):
    """Let time pass while nobody is talking.

    Until now the body only moved when a message arrived, so she had no life
    between conversations: no drift, no settling, no waking up different.
    Ticks are capped and batched -- eight hours is a night, not four hundred
    separate minutes of noise.
    """
    if _IMPORT_ERROR:
        return {}
    import time as _t
    now = float(now if now is not None else _t.time())
    clock = _clock_load(store, session_id)
    last = float(clock.get("last_tick") or 0.0)
    if last <= 0:
        _clock_save(store, session_id, now)
        return {"ticks": 0, "seconds": 0.0}
    elapsed = max(0.0, now - last)
    ticks = int(elapsed // TICK_SECONDS)
    if ticks <= 0:
        return {"ticks": 0, "seconds": round(elapsed, 1)}
    ticks = min(ticks, MAX_CATCHUP_TICKS)
    body = body_for(store, session_id, seed=seed)
    # batched: each tick carries the elapsed share so the noise integrates once
    dt = max(1.0, elapsed / max(1, ticks))
    for _ in range(ticks):
        body._tick_once(dt=min(dt, 600.0))
    state = body.state()
    save_state(store, session_id, state)
    _clock_save(store, session_id, now)
    return {"ticks": ticks, "seconds": round(elapsed, 1), "state": state}
