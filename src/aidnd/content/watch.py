"""Городская стража: патрули с маршрутами и ростером; отклик на беспорядки (этап 1).

Стража — симулируемый институт, а не случайное появление. Ростер: капитан + стражники + дознаватель
(реальные NPC, насыщаются LLM). Два патруля с маршрутами по местам города и темпом; позиция патруля —
ДЕТЕРМИНИРОВАННАЯ функция времени (реплей-сейф, без состояния). При драке/беспорядке в городе отвечает
БЛИЖАЙШИЙ патруль; время прихода = расстояние до места (а не «раунд 5 рандомом»).
"""

from __future__ import annotations

WATCH = "faction:watch"
HQ = "building:townmaster_hall"                 # штаб стражи (пока при ратуше)
CAPTAIN = "npc:watch_captain"
INVESTIGATOR = "npc:watch_investigator"

# патрули: маршрут (список мест-узлов) + темп (тиков на отрезок) + состав (NPC)
PATROLS = [
    {"id": "patrol:market", "name": "патруль Рыночного квартала", "pace": 4,
     "route": ["place:phandalin_square", "building:stonehill_inn", "building:notice_board",
               "building:barthens_provisions", "building:townmaster_hall"],
     "members": ["npc:watch_brann", "npc:watch_ketra"]},
    {"id": "patrol:outskirts", "name": "патруль Окраин", "pace": 4,
     "route": ["place:phandalin_square", "building:shrine_of_luck", "building:sleeping_giant",
               "building:adventurers_guild", "building:lionshield_coster"],
     "members": ["npc:watch_orin", "npc:watch_dell"]},
]

# ростер: id, имя, роль-архетип, стат-блок, черты
ROSTER = [
    (CAPTAIN, "Капитан Норвейн", "captain", "srd:veteran", ["дисциплинированный", "справедливый"]),
    ("npc:watch_brann", "Бранн", "guard", "srd:thug", ["крепкий", "немногословный"]),
    ("npc:watch_ketra", "Кетра", "guard", "srd:thug", ["зоркая", "бойкая"]),
    ("npc:watch_orin", "Орин", "guard", "srd:thug", ["ворчливый", "опытный"]),
    ("npc:watch_dell", "Делл", "guard", "srd:thug", ["молодой", "рьяный"]),
    (INVESTIGATOR, "Дознаватель Мэлла", "investigator", "srd:veteran", ["проницательная", "недоверчивая"]),
]


def register_watch(world) -> None:
    """Зарегистрировать фракцию стражи + ростер (капитан, стражники, дознаватель)."""
    from ..world.components import Faction
    from .phandalin import _add_npc
    if WATCH not in world.factions:
        world.ecs.spawn(WATCH)
        fac = Faction(name="Городская стража", kind="watch", controls=[HQ], joinable=True)
        world.ecs.add(WATCH, fac)
        world.factions[WATCH] = fac
    for nid, name, arch, sb, traits in ROSTER:
        _add_npc(world, nid, name, arch, sb, faction=WATCH, profession="guard",
                 works_at=HQ, lives_in=HQ, place=HQ, traits=list(traits))


def patrol_place(patrol: dict, tick: int) -> str:
    """Где патруль СЕЙЧАС — детерминированно по времени (цикл по маршруту)."""
    r = patrol["route"]
    return r[(tick // max(1, patrol["pace"])) % len(r)]


def patrol_size(patrol: dict, world) -> int:
    """Сколько стражников в патруле сейчас живы."""
    return sum(1 for m in patrol["members"] if world.is_alive(m))
