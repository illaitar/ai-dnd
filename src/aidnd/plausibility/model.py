"""Мультипликативная модель правдоподобия (док 06).

Два гейта: feasibility (жёсткий бинарный инвариант) и plausibility (мягкий
вероятностный вес). plausibility(T,C) = base_weight(T) × Π modifier_i(T,C).
Значение 1.0 нейтрально, >1 усиливает, <1 подавляет, 0 запрещает.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# калибровка базовой частоты категории (док 06 §4.2)
K_CATEGORY = {"npc": 0.2, "loot": 0.5, "monster": 0.3, "item": 0.4}
P_CAP = 0.95


@dataclass
class SpawnContext:
    location_type: str = "frontier_town"  # frontier_town|dungeon|wilderness|manor|shrine|haunted_ruin
    region_tier: int = 1
    region_tags: list[str] = field(default_factory=list)
    faction_control: str | None = None
    faction_tension: float = 0.0
    world_flags: list[str] = field(default_factory=list)
    time_of_day: str = "day"
    season: str = "spring"
    party_tier: int = 1
    source_cr: float | None = None        # для лута: CR источника
    existing_roles: set[str] = field(default_factory=set)
    existing_counts: dict = field(default_factory=dict)
    search_dc: int = 15


@dataclass
class Candidate:
    template_id: str
    category: str                   # npc|loot|monster|item
    base_weight: float = 1.0
    archetype: str = ""
    rarity: str = "mundane"
    unique_role: str | None = None
    ecology: tuple = ()             # подходящие location_type
    forbidden_in: tuple = ()        # location_type, где запрещён


# --- семейства модификаторов (док 06 §3.1) -------------------------------- #
def _compat(c: Candidate, ctx: SpawnContext) -> float:
    if ctx.location_type in c.forbidden_in:
        return 0.0
    if c.ecology:
        return 2.0 if ctx.location_type in c.ecology else 0.4
    return 1.0


_RARITY_GATE = {1: {"rare": 0.15, "very_rare": 0.0, "legendary": 0.0, "uncommon": 0.5},
                2: {"rare": 0.4, "very_rare": 0.1, "legendary": 0.0},
                3: {"very_rare": 0.4, "legendary": 0.1}}


def _economic(c: Candidate, ctx: SpawnContext) -> float:
    gate = _RARITY_GATE.get(ctx.party_tier, {})
    return gate.get(c.rarity, 1.0)


def _duplication(c: Candidate, ctx: SpawnContext) -> float:
    if c.unique_role and c.unique_role in ctx.existing_roles:
        return 0.0
    n = ctx.existing_counts.get(c.archetype, 0)
    return 1.0 / (1.0 + n)


def _event(c: Candidate, ctx: SpawnContext) -> float:
    if "recent_raid" in ctx.world_flags and c.archetype == "merchant_caravan":
        return 0.3
    if "recent_raid" in ctx.world_flags and c.archetype == "bandit":
        return 1.8
    if "post_redbrand_purge" in ctx.world_flags and c.archetype == "merchant_caravan":
        return 1.4
    if "post_redbrand_purge" in ctx.world_flags and c.archetype == "bandit":
        return 0.2
    return 1.0


_MODIFIERS = [_compat, _economic, _duplication, _event]


def plausibility(c: Candidate, ctx: SpawnContext) -> float:
    w = c.base_weight
    for mod in _MODIFIERS:
        w *= mod(c, ctx)
        if w == 0.0:
            return 0.0
    return w


def feasible(c: Candidate, ctx: SpawnContext) -> bool:
    """Жёсткий гейт: уникальная роль не дублируется, редкость в пределах тира."""
    if c.unique_role and c.unique_role in ctx.existing_roles:
        return False
    if _economic(c, ctx) == 0.0:
        return False
    return True


def sample(cands: list[Candidate], ctx: SpawnContext, rng: random.Random) -> Candidate | None:
    """Sample-режим: взвешенный выбор кандидата по правдоподобию (док 06 §4.1)."""
    pool = [c for c in cands if feasible(c, ctx)]
    weights = [plausibility(c, ctx) for c in pool]
    total = sum(weights)
    if total <= 0:
        return None
    r = rng.random() * total
    acc = 0.0
    for c, wt in zip(pool, weights):
        acc += wt
        if r <= acc:
            return c
    return pool[-1]


def check(c: Candidate, ctx: SpawnContext, rng: random.Random) -> bool:
    """Check-режим: появляется ли конкретный кандидат (док 06 §4.2)."""
    if not feasible(c, ctx):
        return False
    w = plausibility(c, ctx)
    k = K_CATEGORY.get(c.category, 0.3)
    p = min(P_CAP, w / (w + k)) if (w + k) > 0 else 0.0
    return rng.random() <= p


def discover(c: Candidate, ctx: SpawnContext, passive_perception: int,
             player_roll_total: int | None = None) -> bool:
    """Дискавери: существование решает правдоподобие, нахождение — бросок (док 06 §5)."""
    if plausibility(c, ctx) <= 0.0:
        return False
    if passive_perception >= ctx.search_dc:
        return True
    if player_roll_total is not None:
        return player_roll_total >= ctx.search_dc
    return False
