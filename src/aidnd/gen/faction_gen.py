"""Пер-мирная генерация фракций (док 01 + main §14).

Как и NPC: детерминированный пре-ген из сида (набор архетипов, отношения, контроль
территорий) + ленивое LLM-обогащение (имя/описание/цели) событием faction_enrich,
которое переживает сейв/лоад и реплей. Членство/репутация — рантайм-события.
"""

from __future__ import annotations

import random

from ..rules.factions import ARCHETYPE_RELATIONS, FACTION_ARCHETYPES
from ..world.components import Faction, Persona
from .seeds import subseed

# гражданская «обвязка» города: кто чем заправляет (для слежки/экономики)
_CONTROL = {
    "merchant_guild": "building:barthens_provisions",
    "watch": "building:townmaster_hall",
    "temple": "building:shrine_of_luck",
    "thieves_guild": "building:sleeping_giant",
    "aristocracy": "building:edermath_orchard",
    "arcane": None,
}
# профессия NPC → членство в гражданской фракции (наполняет фракции людьми)
PROF_FACTION = {
    "merchant": "faction:merchant_guild", "guard": "faction:watch",
    "priest": "faction:temple", "innkeeper": "faction:merchant_guild",
}


def generate_factions(world, profile_name: str = "phandalin", model=None) -> list[str]:
    """Детерминированно набрать гражданские фракции мира из пула архетипов."""
    rng = random.Random(subseed(world.seed, "factions", profile_name))
    core = ["merchant_guild", "watch"]
    extra = rng.sample(["thieves_guild", "temple", "aristocracy", "arcane"], 2)
    kinds = core + extra
    made = []
    for kind in kinds:
        fid = f"faction:{kind}"
        made.append(fid)
        if world.ecs.get(fid, Faction):                  # идемпотентно (повторный build)
            continue
        arc = FACTION_ARCHETYPES[kind]
        controls = [_CONTROL[kind]] if _CONTROL.get(kind) else []
        fac = Faction(name=arc["name"], kind=kind, blurb=arc["blurb"],
                      goals=list(arc["goals"]), values=list(arc["values"]),
                      emblem=arc["emblem"], ranks=list(arc["ranks"]),
                      join_min_rep=arc["join_min_rep"], controls=controls, joinable=True)
        world.ecs.spawn(fid)
        world.ecs.add(fid, fac)
        world.factions[fid] = fac
        for c in controls:
            world.commit("kg_add", "worldgen", payload={"s": fid, "r": "controls", "o": c})
    # взаимные отношения по архетипам (только между присутствующими)
    for kind in kinds:
        fac = world.ecs.get(f"faction:{kind}", Faction)
        for okind, val in ARCHETYPE_RELATIONS.get(kind, {}).items():
            ofid = f"faction:{okind}"
            if world.ecs.get(ofid, Faction):
                fac.relations[ofid] = val
    return made


def assign_faction_members(world) -> None:
    """Раздать беспартийных NPC в гражданские фракции по профессии."""
    for npc in world.npcs():
        persona = world.ecs.get(npc, Persona)
        if not persona or persona.faction:
            continue
        fid = PROF_FACTION.get(persona.profession)
        fac = world.ecs.get(fid, Faction) if fid else None
        if fac:
            persona.faction = fid
            if npc not in fac.members:
                fac.members.append(npc)


def enrich_faction(world, fid: str, model=None) -> dict:
    """Лениво обогатить фракцию LLM (имя/описание/цели) и зафиксировать событием."""
    fac = world.ecs.get(fid, Faction)
    if not fac:
        return {}
    if fac.enriched:
        return {"id": fid, "recorded": True}
    out = None
    if model is not None and getattr(model, "available", lambda: False)():
        from ..inference.agents import forge_faction
        out = forge_faction(model, fac)
    payload = {"id": fid}
    if out:
        payload.update({k: out[k] for k in ("name", "blurb", "goals", "values") if out.get(k)})
    world.commit("faction_enrich", "lore", payload=payload)
    return {"id": fid, "recorded": False}
