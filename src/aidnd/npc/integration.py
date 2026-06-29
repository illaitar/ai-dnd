"""Подключение модели NPC к движку: NpcState — НАСТОЯЩЕЕ состояние агента, не временный мост.

Строится один раз из профессии (черты детерминированы от seed → переживают перезагрузку без
сейва) и кэшируется на мире (`world.npc_minds`). Живое, меняющееся вне модели (отношения к
игроку, занятость), накладывается при чтении из канонических хранилищ. Арбитр читает это и решает.
Импорты мира ленивые — пакет aidnd.npc остаётся самодостаточным для тестов.
"""

from __future__ import annotations

from .arbiter import choose
from .context import Context
from .state import NpcState, make_state


def _seed(npc) -> int:
    return sum(ord(c) for c in str(npc)) & 0xFFFF


def npc_state(world, npc, player: str = "player") -> NpcState:
    """Состояние NPC из кэша мира (создаётся из профессии при первом обращении).
    Поверх — живые отношения к игроку и занятость (меняются вне модели)."""
    cache = getattr(world, "npc_minds", None)
    if cache is None:
        cache = world.npc_minds = {}
    st = cache.get(npc)
    if st is None:
        from ..world.components import Persona
        persona = world.ecs.get(npc, Persona)
        role = getattr(persona, "profession", None) or "простолюдин"
        faction = getattr(persona, "faction", None) or ""
        st = make_state(name=str(npc), role=role, faction=faction, seed=_seed(npc))
        cache[npc] = st
    from ..world.components import Relationships
    rels = world.ecs.get(npc, Relationships)
    edge = rels.edges.get(player) if rels else None
    if edge is not None:                                        # отношение к игроку — в стейт
        st.relations[player] = {"affinity": getattr(edge, "affinity", 0.0),
                                "trust": getattr(edge, "trust", 0.0),
                                "fear": getattr(edge, "fear", 0.0), "debt": 0}
    ops = (getattr(world, "opinions", None) or {}).get(npc, {})   # граф мнений NPC↔NPC — в стейт
    for b, v in ops.items():
        st.relations.setdefault(b, {"affinity": 0.0, "trust": 0.0, "fear": 0.0, "debt": 0})["affinity"] = v
    busy = getattr(world, "busy", None) or {}
    if busy.get(npc):
        st.needs["purpose"] = 0.7                               # занят заказом → меньше отвлекается
    return st


# скорость роста нужд за тик (динамика, накапливается в NpcState; сбрасывается распорядком/действием)
_NEED_RATE = {"hunger": 0.05, "fatigue": 0.04, "social": 0.03, "purpose": 0.02, "gear": 0.006}


def tick_minds(world, dt: int = 1) -> None:
    """Динамика нужд: голод/усталость/тяга к общению/безделье растут со временем у активных умов.
    Сброс — в распорядке (поел/поспал/выпил). Нужды теперь живут и эволюционируют в NpcState."""
    cache = getattr(world, "npc_minds", None)
    if not cache:
        return
    step = max(1, int(dt))
    for st in cache.values():
        for k, rate in _NEED_RATE.items():
            st.needs[k] = min(1.0, st.needs.get(k, 0.15) + rate * step)


def relax_need(world, npc, need: str, to: float = 0.1) -> None:
    """Сбросить нужду (поел → hunger, поспал → fatigue, пообщался → social) у активного ума."""
    st = (getattr(world, "npc_minds", None) or {}).get(npc)
    if st is not None:
        st.needs[need] = to


def react(world, npc, stim, player: str = "player", rng=None):
    """Выбор способности арбитром по настоящему состоянию NPC. → (cap | None, shortlist)."""
    return choose(npc_state(world, npc, player), Context(stim, world=world), rng)
