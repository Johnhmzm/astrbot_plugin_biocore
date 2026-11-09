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
