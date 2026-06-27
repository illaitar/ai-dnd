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


def _gen_agenda(world, npc, model=None) -> dict:
    """Замысел важного NPC: цель + мотив + план-шаги по местам. TODO(LLM): заменить шаблон ролью 'agenda'
    (богатые цели/враги/ставки из персоны, фракции, отношений и текущих событий мира)."""
    from ..world.components import Persona
    p = world.ecs.get(npc, Persona)
    key = (getattr(p, "profession", None) or getattr(p, "archetype", "") or "").lower()
    goal, motive, places = _ARCHETYPES.get(key, _DEFAULT)
    # с моделью — здесь будет LLM-замысел; пока богатим шаблон именем/фракцией
    plan = [{"place": pl, "intent": f"шаг к цели «{goal}»", "done": False} for pl in places]
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


def advance_agendas(world) -> None:
    """Продвинуть планы важных NPC (раз в день): отметить текущий шаг сделанным, перейти к следующему.
    TODO: реальные эффекты шага (слух/сделка/угроза/вербовка) + ветвление плана от исхода и мира."""
    for ag in (getattr(world, "agendas", None) or {}).values():
        if not ag.get("active") or not ag.get("plan"):
            continue
        ag["plan"][min(ag["step"], len(ag["plan"]) - 1)]["done"] = True
        ag["step"] += 1
        if ag["step"] >= len(ag["plan"]):                  # план пройден — цикл (или завершение/новый замысел)
            ag["step"] = 0
            for st in ag["plan"]:
                st["done"] = False
