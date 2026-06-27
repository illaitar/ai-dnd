"""Агентность NPC: переход СОБЕСЕДНИК → ВАЖНЫЙ/ДЕЯТЕЛЬНЫЙ (свои планы, действия вне рутины).

Лестница «жизни» NPC:
  фон-заглушка (citypop)  →  собеседник (материализован, насыщен)  →  ВАЖНЫЙ ДЕЯТЕЛЬ (эта подсистема).

Важный деятель получает Agenda (цель + мотив + план из шагов по местам) и ДЕЙСТВУЕТ по плану, а не по
дефолтной рутине дом↔работа: каждый день продвигает шаг, идёт в место шага, преследует цель. Это каркас —
точки расширения помечены TODO (LLM-генерация замысла, реальные эффекты шагов, авто-промоушн режиссёром).

Состояние рантайм-зависимое → персистится явно (как cases/dungeon_status): world.agendas[npc_id].
"""

from __future__ import annotations

from ..world.environment import day_number

# архетипы замыслов по профессии/фракции (офлайн-шаблон; с моделью — заменить LLM-генерацией)
_ARCHETYPES = {
    "merchant": ("прибрать к рукам торговлю в городе", "жажда наживы",
                 ["building:barthens_provisions", "building:lionshield_coster", "place:phandalin_square",
                  "building:adventurers_guild"]),
    "лавочник": ("выжать конкурентов и поднять цены", "жажда наживы",
                 ["building:lionshield_coster", "place:phandalin_square", "building:stonehill_inn"]),
    "thug": ("провернуть дельце и подмять район", "власть и страх",
             ["building:sleeping_giant", "building:tresendar_manor", "place:phandalin_square"]),
    "guard": ("навести в городе порядок по-своему", "долг (или тщеславие)",
              ["building:townmaster_hall", "place:phandalin_square", "building:stonehill_inn"]),
    "priest": ("укрепить веру и влияние святилища", "вера",
               ["building:shrine_of_luck", "place:phandalin_square", "building:stonehill_inn"]),
    "guildmaster": ("расширить власть гильдии", "амбиции",
                    ["building:adventurers_guild", "place:phandalin_square", "building:townmaster_hall"]),
}
_DEFAULT = ("устроить свои дела и подняться", "личные амбиции",
            ["place:phandalin_square", "building:stonehill_inn", "building:barthens_provisions"])


def is_active(world, npc: str) -> bool:
    return npc in (getattr(world, "agendas", None) or {})


def agenda_of(world, npc: str) -> dict | None:
    return (getattr(world, "agendas", None) or {}).get(npc)


_STEP_ACTIONS = ["rumor", "economic", "recruit", "threaten"]


def _public(world) -> list:
    from .citypop import CityPopulation
    return CityPopulation._public_places(world)


def _gen_agenda(world, npc, model=None) -> dict:
    """Замысел важного NPC: цель + мотив + план-шаги с ДЕЙСТВИЯМИ. LLM (роль agenda) с фоллбэком на шаблон."""
    from ..world.components import Persona
    p = world.ecs.get(npc, Persona)
    pubs = [(pid, world.spatial.places[pid].name) for pid in _public(world)
            if pid in world.spatial.places]
    if model is not None and pubs:                          # LLM-замысел
        from ..inference.agents import forge_agenda
        brief = (f"{p.name}, {getattr(p, 'profession', None) or p.archetype}, фракция "
                 f"{p.faction or 'нет'}, черты {', '.join((p.traits or [])[:3])}")
        out = forge_agenda(model, brief, [nm for _, nm in pubs])
        if out and out.get("plan"):
            name2id = {nm: pid for pid, nm in pubs}
            plan = []
            for st in out["plan"][:4]:
                pid = name2id.get(st.get("place", "")) or pubs[0][0]
                plan.append({"place": pid, "action": st.get("action", "rumor"),
                             "summary": (st.get("summary") or "").strip(), "done": False})
            if plan:
                return {"goal": out.get("goal", ""), "motive": out.get("motive", ""), "plan": plan,
                        "step": 0, "since_day": day_number(world.clock.tick), "active": True}
    # шаблон-фоллбэк (офлайн/сбой): архетип по профессии + действия по кругу
    key = (getattr(p, "profession", None) or getattr(p, "archetype", "") or "").lower()
    goal, motive, places = _ARCHETYPES.get(key, _DEFAULT)
    nm = p.name if p else "Некто"
    plan = [{"place": pl, "action": _STEP_ACTIONS[i % len(_STEP_ACTIONS)],
             "summary": f"{nm} тянет своё: {goal}", "done": False} for i, pl in enumerate(places)]
    return {"goal": goal, "motive": motive, "plan": plan, "step": 0,
            "since_day": day_number(world.clock.tick), "active": True}


def promote_to_active(world, npc: str, model=None) -> dict | None:
    """СОБЕСЕДНИК → ВАЖНЫЙ ДЕЯТЕЛЬ: дать замысел и включить агентность (действует вне рутины).
    Триггеры (точки расширения): решение режиссёра, повторное вовлечение игрока, роль в квесте."""
    from ..world.components import Persona
    if world.ecs.get(npc, Persona) is None:
        return None
    if not hasattr(world, "agendas") or world.agendas is None:
        world.agendas = {}
    if npc in world.agendas:
        return world.agendas[npc]
    ag = _gen_agenda(world, npc, model)
    world.agendas[npc] = ag
    from .facts import teach_personal_fact  # замысел живёт в памяти (раскроется доверенному)
    teach_personal_fact(world, npc, {"fact": f"Втайне задумал: {ag['goal']} ({ag['motive']}).",
                                     "topic": "plans", "tags": ["замысел", "план"], "trust": 0.7})
    return ag


def active_place(world, npc: str) -> str | None:
    """Где важный NPC СЕЙЧАС по своему плану (перекрывает дефолтную рутину). None — нет замысла."""
    ag = agenda_of(world, npc)
    if not ag or not ag.get("active") or not ag.get("plan"):
        return None
    step = min(ag["step"], len(ag["plan"]) - 1)
    return ag["plan"][step]["place"]


def advance_agendas(world) -> list:
    """Продвинуть планы важных NPC (раз в день): применить ЭФФЕКТ текущего шага (молва/удар по торговле)
    и перейти к следующему. Возвращает события для журнала/вестей."""
    events = []
    for npc, ag in (getattr(world, "agendas", None) or {}).items():
        if not ag.get("active") or not ag.get("plan"):
            continue
        step = ag["plan"][min(ag["step"], len(ag["plan"]) - 1)]
        note = _apply_step(world, npc, step)
        step["done"] = True
        if note:
            events.append({"npc": npc, "note": note})
        ag["step"] += 1
        if ag["step"] >= len(ag["plan"]):                  # план пройден — цикл (или завершение/новый замысел)
            ag["step"] = 0
            for st in ag["plan"]:
                st["done"] = False
    return events


def _apply_step(world, npc, step) -> str | None:
    """РЕАЛЬНЫЙ эффект шага на мир: молва (всегда) + удар по снабжению для economic/sabotage (цены прыгают)."""
    from ..world.components import Persona
    p = world.ecs.get(npc, Persona)
    name = p.name if p else "Некто"
    summ = step.get("summary") or f"{name} что-то затевает"
    from .facts import register_rumor
    register_rumor(world, summ, ["слух", "замысел"], npc)
    if step.get("action") in ("economic", "sabotage"):
        from .. import config
        per_day = (24 * 60) // max(1, config.SIM_MINUTES_PER_TICK)
        until = world.clock.tick + 3 * per_day
        world.commit("set_flag", "agency", payload={"flag": f"disrupt:goods:{until}"})
    return summ


def maybe_promote(world, model=None, cap: int = 6, per_day: int = 2) -> list:
    """Авто-промоушн (режиссёр): главы фракций становятся важными деятелями со своими планами — по
    несколько в день, пока не наберётся cap. Стражу не трогаем (у неё свой институт). → имена новых.
    Точка расширения: + повторное вовлечение игрока (talk≥N) и роль в квесте."""
    agendas = getattr(world, "agendas", None) or {}
    if len(agendas) >= cap:
        return []
    promoted = []
    for fac in world.factions.values():
        if len(promoted) >= per_day or len(getattr(world, "agendas", {})) >= cap:
            break
        leader = getattr(fac, "leader", None)
        if leader and leader not in (getattr(world, "agendas", None) or {}) \
           and getattr(fac, "kind", "") != "watch" and promote_to_active(world, leader, model):
            promoted.append(leader)
    return promoted
