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
    "info_guild": None,                              # действует в тени, без фиксированной территории
}
# канонические лидеры сюжетных фракций (остальным лидер ставится из членов / заметного NPC)
_CANON_LEADER = {
    "faction:redbrands": "npc:iarno_glasstaff",
    "faction:cragmaw": "npc:klarg",
    "faction:temple": "npc:sister_garaele",
    "faction:lords_alliance": "npc:sildar_hallwinter",
    # info_guild НЕ канонизируем на Халию: она агент Жентарима (persona.faction=zhentarim) —
    # иначе лидер инфо-гильдии числился бы в чужой фракции. Лидера даст фоллбэк (когерентно).
}
# профессия NPC → членство в гражданской фракции (наполняет фракции людьми)
PROF_FACTION = {
    "merchant": "faction:merchant_guild", "guard": "faction:watch",
    "priest": "faction:temple", "innkeeper": "faction:merchant_guild",
}


def generate_factions(world, profile_name: str = "phandalin", model=None) -> list[str]:
    """Детерминированно набрать гражданские фракции мира из пула архетипов."""
    rng = random.Random(subseed(world.seed, "factions", profile_name))
    core = ["merchant_guild", "watch", "info_guild"]      # info_guild теперь всегда в городе
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


def fill_faction_leaders(world) -> None:
    """Проставить лидеров фракциям: канонический (Glasstaff/Klarg/Halia) → первый член →
    детерминированный заметный беспартийный NPC. Закрывает дыру (leader=None у всех)."""
    used = {getattr(f, "leader", None) for f in world.factions.values() if getattr(f, "leader", None)}
    spare = None                                          # ленивый пул заметных беспартийных (для тайных фракций)
    for fid, fac in world.factions.items():
        if getattr(fac, "leader", None):
            continue
        leader = _CANON_LEADER.get(fid)
        if not (leader and world.ecs.get(leader, Persona)):
            leader = next((m for m in (getattr(fac, "members", None) or []) if m not in used), None)
        if not leader:
            if spare is None:                            # беспартийные: сперва заметные, затем любые
                unaff = [n for n in sorted(world.npcs())
                         if (p := world.ecs.get(n, Persona)) and not getattr(p, "faction", None)]
                notable = [n for n in unaff if (world.ecs.get(n, Persona).archetype
                           or world.ecs.get(n, Persona).profession or "").lower() not in _GENERIC_ROLE]
                spare = notable + [n for n in unaff if n not in notable]
            leader = next((n for n in spare if n not in used), None)
        if not leader:
            continue
        fac.leader = leader
        used.add(leader)
        if leader not in fac.members:
            fac.members.append(leader)
        per = world.ecs.get(leader, Persona)
        if per and not per.faction:
            per.faction = fid


_GENERIC_ROLE = {"", "none", "miner", "farmhand", "commoner", "townsfolk", "labourer"}


def enrich_all(world, charts, model, progress=None) -> int:
    """Жадно обогатить мир на старте: ВСЕ фракции (имя/цели/ценности) + заметные NPC (voice/traits).
    progress(done, total, label) — для ползунка загрузки. Возвращает total."""
    factions = list(world.factions.keys())
    leaders = {getattr(f, "leader", None) for f in world.factions.values()}
    npcs = []
    for nid in world.npcs():
        per = world.ecs.get(nid, Persona)
        if not per or getattr(per, "enriched", False):
            continue
        role = (getattr(per, "archetype", "") or getattr(per, "profession", "") or "").lower()
        if nid in leaders or role not in _GENERIC_ROLE:   # лидеры + неброские горожане
            npcs.append(nid)
    total = len(factions) + len(npcs)
    done = 0
    if progress:
        progress(0, total, "Оживляю мир…")
    conc = model.enrich_concurrency() if model is not None and hasattr(model, "enrich_concurrency") else 1
    from .parallel import pmap
    fac_out = pmap(factions, lambda fid: faction_fetch(world, fid, model), conc)  # фракции — ПАРАЛЛЕЛЬНО
    for fid, out in zip(factions, fac_out):              # apply последовательно → детерминизм/replay
        faction_apply(world, fid, out)
        done += 1
        if progress:
            progress(done, total, f"Фракция: {world.factions[fid].name}")
    fetched = pmap(npcs, charts.enrich_fetch, conc)      # заметные NPC (вкл. стражу) — ПАРАЛЛЕЛЬНО
    for nid, res in zip(npcs, fetched):                  # apply ПОСЛЕДОВАТЕЛЬНО → детерминизм/replay
        charts.enrich_apply(nid, res)
        done += 1
        if progress:
            per = world.ecs.get(nid, Persona)
            progress(done, total, f"Персонаж: {getattr(per, 'name', nid)}")
    return total


def faction_fetch(world, fid: str, model=None) -> dict | None:
    """Только МОДЕЛЬ-вызов forge_faction (для ПАРАЛЛЕЛЬНОГО enrich). None — пропуск/нет модели."""
    fac = world.ecs.get(fid, Faction)
    if not fac or fac.enriched or model is None or not getattr(model, "available", lambda: False)():
        return None
    from ..inference.agents import forge_faction
    return forge_faction(model, fac)


def faction_apply(world, fid: str, out: dict | None) -> None:
    """Зафиксировать обогащение фракции событием (apply ПОСЛЕДОВАТЕЛЬНО → детерминизм/replay)."""
    fac = world.ecs.get(fid, Faction)
    if not fac or fac.enriched:
        return
    payload = {"id": fid}
    if out:
        payload.update({k: out[k] for k in ("name", "blurb", "goals", "values") if out.get(k)})
    world.commit("faction_enrich", "lore", payload=payload)


def enrich_faction(world, fid: str, model=None) -> dict:
    """Лениво обогатить ОДНУ фракцию (fetch+apply) — для точечного вызова вне массового enrich."""
    fac = world.ecs.get(fid, Faction)
    if not fac:
        return {}
    if fac.enriched:
        return {"id": fid, "recorded": True}
    faction_apply(world, fid, faction_fetch(world, fid, model))
    return {"id": fid, "recorded": False}


# ---------------------------------------------------------------------------- #
#  Память руководителя: знание об организации (структура/подразделения) + люди  #
# ---------------------------------------------------------------------------- #
def _pname(world, pid: str) -> str:
    p = world.spatial.places.get(pid)
    return p.name if p else pid


def _nname(world, nid: str) -> str:
    per = world.ecs.get(nid, Persona)
    return per.name if per else nid


def seed_leader_knowledge(world) -> None:
    """В память РУКОВОДИТЕЛЯ каждой фракции — знание об организации и поимённо о подчинённых.

    Обкатано на городской страже (капитан знает гарнизон, число патрулей, их маршруты и состав,
    дознавателей), затем — на ВСЕ фракции (лидер знает, что возглавляет, что под контролем, своих людей).
    Чувствительные оперативные детали (маршруты патрулей) — с высоким порогом доверия для раскрытия."""
    from ..content.facts import teach_personal_fact
    for fid, fac in world.factions.items():
        leader = getattr(fac, "leader", None)
        if not leader or world.ecs.get(leader, Persona) is None:
            continue
        members = [m for m in (getattr(fac, "members", None) or []) if m != leader]
        for item in _leader_facts(world, fid, fac, leader, members):
            teach_personal_fact(world, leader, item)


def _leader_facts(world, fid: str, fac, leader: str, members: list) -> list[dict]:
    name = getattr(fac, "name", fid)
    facts: list[dict] = []
    controls = [_pname(world, c) for c in (getattr(fac, "controls", None) or [])]
    org = f"Я возглавляю «{name}»" + (f"; под нашим присмотром: {', '.join(controls)}" if controls else "")
    facts.append({"fact": org + ".", "topic": "factions", "tags": ["организация", fid], "trust": 0.15})
    if members:
        names = [_nname(world, m) for m in members]
        shown = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
        facts.append({"fact": f"Под моим началом в «{name}»: {shown}.",
                      "topic": "factions", "tags": ["подчинённые", "люди", fid], "trust": 0.3})
    if fid == "faction:watch":
        facts += _watch_facts(world)
    return facts


def _watch_facts(world) -> list[dict]:
    from ..content.watch import patrols_of
    pats = patrols_of(world)
    garr = getattr(world, "watch_garrison", 0)
    out = [{"fact": f"Городская стража держит около {garr} человек; по городу ходят {len(pats)} патрулей.",
            "topic": "watch", "tags": ["стража", "патрули", "гарнизон"], "trust": 0.2}]
    for p in pats:                                          # оперативные детали — порог выше (не для встречного)
        route = " → ".join(_pname(world, x) for x in p["route"])
        mem = ", ".join(_nname(world, m) for m in p["members"])
        out.append({"fact": f"{p['name'].capitalize()} обходит: {route}; в нём {mem}.",
                    "topic": "watch", "tags": ["патруль", "маршрут", p["id"]], "trust": 0.45})
    invs = getattr(world, "watch_investigators", []) or []
    if invs:
        out.append({"fact": f"Дознаватели под моим началом: {', '.join(_nname(world, i) for i in invs)}.",
                    "topic": "watch", "tags": ["дознаватели", "стража"], "trust": 0.3})
    return out
