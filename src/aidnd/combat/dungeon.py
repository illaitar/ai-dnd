"""Процедурное логово: раскладка препятствий (стены) под тактическую сетку Encounter + волны врагов.

Наследует дух старого battlemap.py (архетип + клеточный автомат), но говорит на языке НОВОГО
движка: не террейн-коды, а множество непроходимых клеток obstacles. Каверны (лесные/болотные/
пещерные логова) — клеточный автомат; руины/городские — редкие столбы-опоры. Детерминировано по
(seed, env). Волны: CR-бюджет режется на 2-3 накатывающие группы (то же pick_encounter по среде).

Key functions
-------------
obstacles(w, h, env, seed) -> set : Generate dungeon obstacles; ensures playable layout.
waves(cr_budget, env, seed, n=2, max_units=4) -> list : Split CR budget into n enemy waves.
"""

from __future__ import annotations

from random import Random

from .encounters import pick_encounter

# среды, которым идёт органичная каверна (иначе — руинные столбы)
_CAVE_ENV = ("cave", "underdark", "swamp", "forest", "grassland", "hill", "coast",
             "пещер", "лес", "болот", "холм")


def _archetype(env: str) -> str:
    e = (env or "").lower()
    return "cave" if any(k in e for k in _CAVE_ENV) else "ruin"


def _cave(w: int, h: int, rng: Random, fill: float = 0.48) -> set:
    """Клеточный автомат: рандом-стены → сглаживание по соседям (границы считаем стенами)."""
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
                            walls += 1                     # за краем — тоже стена
                nxt[y][x] = 1 if walls >= 5 else 0
        grid = nxt
    return {(x, y) for y in range(h) for x in range(w) if grid[y][x]}


def _ruin(w: int, h: int, rng: Random) -> set:
    """Руина: редкие столбы-опоры кластерами (укрытия, а не сплошные стены)."""
    out: set = set()
    for _ in range(rng.randint(3, 5)):
        cx, cy = rng.randrange(3, w - 3), rng.randrange(1, h - 1)
        for _ in range(rng.randint(1, 3)):
            out.add((max(2, min(w - 3, cx + rng.randint(-1, 1))),
                     max(0, min(h - 1, cy + rng.randint(-1, 1)))))
    return out


def obstacles(w: int, h: int, env: str, seed: str) -> set:
    """Непроходимые клетки логова. Края (колонки спавна) свободны; сквозь центр — чистый коридор,
    чтобы карта всегда проходима (иначе стороны не сойдутся). Плотность ограничена."""
    rng = Random(f"dungeon|{seed}|{env}")
    obs = _cave(w, h, rng) if _archetype(env) == "cave" else _ruin(w, h, rng)
    obs = {(x, y) for (x, y) in obs if 2 <= x <= w - 3}     # спавн-края (0-1 и w-2..w-1) свободны
    corridor = h // 2
    obs = {(x, y) for (x, y) in obs if y != corridor}       # сквозной проход — бойцы всегда сойдутся
    cap = (w * h) // 4                                       # не заваливать сетку стенами
    if len(obs) > cap:
        obs = set(rng.sample(sorted(obs), cap))
    return obs


def waves(cr_budget: float, env: str, seed: str, n: int = 2, max_units: int = 4) -> list:
    """Разбить CR-бюджет логова на n накатов (первый — сразу, остальные при зачистке)."""
    n = max(1, min(3, int(n)))
    per = cr_budget / n
    out = []
    for i in range(n):
        foes = pick_encounter(per + 0.01, env, seed=f"wave|{seed}|{i}", max_units=max_units)
        if foes:
            out.append(foes)
    return out or [pick_encounter(cr_budget + 0.01, env, seed=f"wave|{seed}|0", max_units=max_units)]
