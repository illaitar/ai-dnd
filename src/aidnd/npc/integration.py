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
    if edge is not None:
        st.relations[player] = {"affinity": getattr(edge, "affinity", 0.0),
                                "trust": getattr(edge, "trust", 0.0),
                                "fear": getattr(edge, "fear", 0.0), "debt": 0}
    busy = getattr(world, "busy", None) or {}
    st.needs["purpose"] = 0.7 if busy.get(npc) else 0.15        # занят заказом → меньше отвлекается
    return st


def react(world, npc, stim, player: str = "player", rng=None):
    """Выбор способности арбитром по настоящему состоянию NPC. → (cap | None, shortlist)."""
    return choose(npc_state(world, npc, player), Context(stim, world=world), rng)
