"""Procedural dungeon: obstacle layout (walls) for Encounter tactical grid + enemy waves.

Inherits the spirit of old battlemap.py (archetype + cellular automaton) but speaks in the NEW
engine language: not terrain codes, but a set of impassable obstacles cells. Caverns (forest/marsh/
cave dungeons) — cellular automaton; ruins/urban — rare support pillars. Deterministic by
(seed, env). Waves: CR budget is split into 2-3 rolling groups (same pick_encounter by env).

Key functions
-------------
obstacles(w, h, env, seed) -> set : Generate dungeon obstacles; ensures playable layout.
waves(cr_budget, env, seed, n=2, max_units=4) -> list : Split CR budget into n enemy waves.
"""

from __future__ import annotations

from random import Random

from .encounters import pick_encounter

# Environments with organic caves (otherwise — ruin pillars)
_CAVE_ENV = ("cave", "underdark", "swamp", "forest", "grassland", "hill", "coast",
             "пещер", "лес", "болот", "холм")


def _archetype(env: str) -> str:
    e = (env or "").lower()
    return "cave" if any(k in e for k in _CAVE_ENV) else "ruin"


def _cave(w: int, h: int, rng: Random, fill: float = 0.48) -> set:
    """Cellular automaton: random walls → smoothing by neighbors (boundaries counted as walls)."""
    grid = [[1 if rng.random() < fill else 0 for _ in range(w)] for _ in range(h)]
    for _ in range(3):
        nxt = [[grid[y][x] for x in range(w)] for y in range(h)]
        for y in range(h):
            for x in range(w):
                walls = 0
                for ny in (y - 1, y, y + 1):
                    for nx in (x - 1, x, x + 1):
                        if (nx, ny) == (x, y):
                            continue
                        if not (0 <= nx < w and 0 <= ny < h) or grid[ny][nx]:
                            walls += 1                     # Beyond edge — also a wall
                nxt[y][x] = 1 if walls >= 5 else 0
        grid = nxt
    return {(x, y) for y in range(h) for x in range(w) if grid[y][x]}


def _ruin(w: int, h: int, rng: Random) -> set:
    """Ruin: rare support pillars in clusters (shelters, not solid walls)."""
    out: set = set()
    for _ in range(rng.randint(3, 5)):
        cx, cy = rng.randrange(3, w - 3), rng.randrange(1, h - 1)
        for _ in range(rng.randint(1, 3)):
            out.add((max(2, min(w - 3, cx + rng.randint(-1, 1))),
                     max(0, min(h - 1, cy + rng.randint(-1, 1)))))
    return out


def obstacles(w: int, h: int, env: str, seed: str) -> set:
    """Impassable dungeon cells. Edges (spawn columns) are clear; through center — clean corridor,
    so the map is always passable (otherwise sides won't meet). Density is limited."""
    rng = Random(f"dungeon|{seed}|{env}")
    obs = _cave(w, h, rng) if _archetype(env) == "cave" else _ruin(w, h, rng)
    obs = {(x, y) for (x, y) in obs if 2 <= x <= w - 3}     # Spawn edges (0-1 and w-2..w-1) are clear
    corridor = h // 2
    obs = {(x, y) for (x, y) in obs if y != corridor}       # Through passage — combatants always meet
    cap = (w * h) // 4                                       # Don't fill grid with walls
    if len(obs) > cap:
        obs = set(rng.sample(sorted(obs), cap))
    return obs


def waves(cr_budget: float, env: str, seed: str, n: int = 2, max_units: int = 4) -> list:
    """Split dungeon CR budget into n waves (first — immediately, rest on clearance)."""
    n = max(1, min(3, int(n)))
    per = cr_budget / n
    out = []
    for i in range(n):
        foes = pick_encounter(per + 0.01, env, seed=f"wave|{seed}|{i}", max_units=max_units)
        if foes:
            out.append(foes)
    return out or [pick_encounter(cr_budget + 0.01, env, seed=f"wave|{seed}|0", max_units=max_units)]
