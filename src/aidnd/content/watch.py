"""Городская стража: патрули и дознаватели, МАСШТАБИРУЕМЫЕ по размеру города (этап 1).

Стража — симулируемый институт. Ростер и число патрулей/дознавателей зависят от числа зданий города:
больше город → больше стражи. Патрули детерминированно расставлены по маршрутам (позиция = функция
времени, реплей-сейф); при беспорядке отвечает ближайший патруль. Сгенерированные патрули/дознаватели
кладутся на world (watch_patrols / watch_investigators) — детерминированно, пересоздаются на load.
"""

from __future__ import annotations

WATCH = "faction:watch"
HQ = "building:townmaster_hall"                 # штаб стражи (пока при ратуше)
CAPTAIN = "npc:watch_captain"
SQUARE = "place:phandalin_square"

# пулы имён (выбор сидируется) — чтобы ростер любого размера имел разные имена
_GUARD_NAMES = ["Бранн", "Кетра", "Орин", "Делл", "Гарек", "Мира", "Тоск", "Лина", "Фендр", "Сора",
                "Брик", "Эльда", "Корин", "Дарра", "Вост", "Нера", "Хальд", "Тея", "Рогар", "Илса",
                "Морган", "Зейн", "Лотта", "Фрек", "Эдда", "Скай", "Бранд", "Реза"]
_INV_NAMES = ["Мэлла", "Сэрен", "Вика", "Дорн", "Илейн", "Тарвин"]
_GUARD_TRAITS = [["крепкий", "немногословный"], ["зоркая", "бойкая"], ["ворчливый", "опытный"],
                 ["молодой", "рьяный"], ["спокойный", "наблюдательный"], ["рослый", "грубоватый"]]


def town_size(world) -> int:
    """Размер города = число зданий-узлов поселения (масштаб стражи и дознавателей)."""
    return sum(1 for p in world.spatial.places.values()
               if getattr(p, "kind", "") == "building" and getattr(p, "parent", "") == "settlement:phandalin")


def watch_scale(size: int) -> dict:
    """План стражи по размеру города: число патрулей/состав/дознавателей."""
    n_patrols = max(2, min(5, 1 + size // 4))             # ~патруль на 4 здания
    patrol_size = 3 if size >= 14 else 2
    n_investigators = max(1, min(3, 1 + size // 8))        # ~дознаватель на 8 зданий
    return {"n_patrols": n_patrols, "patrol_size": patrol_size, "n_investigators": n_investigators}


def _town_buildings(world) -> list[str]:
    return sorted(pid for pid, p in world.spatial.places.items()
                  if getattr(p, "kind", "") == "building" and getattr(p, "parent", "") == "settlement:phandalin")


def build_watch(world, seed: int) -> dict:
    """Сгенерировать ростер + патрули + дознавателей под размер города (детерминированно по seed)."""
    import random

    from ..gen.seeds import subseed
    rng = random.Random(subseed(seed, "watch", town_size(world)))
    plan = watch_scale(town_size(world))
    names = _GUARD_NAMES[:]
    rng.shuffle(names)
    inv_names = _INV_NAMES[:]
    rng.shuffle(inv_names)
    blds = _town_buildings(world)

    roster = [(CAPTAIN, "Капитан Норвейн", "captain", "srd:veteran", ["дисциплинированный", "справедливый"])]
    patrols, gi = [], 0
    chunks = max(1, len(blds) // plan["n_patrols"]) or 1
    for pi in range(plan["n_patrols"]):
        members = []
        for _ in range(plan["patrol_size"]):
            nm = names[gi % len(names)]
            nid = f"npc:watch_g{gi}"
            roster.append((nid, nm, "guard", "srd:thug", _GUARD_TRAITS[gi % len(_GUARD_TRAITS)]))
            members.append(nid)
            gi += 1
        seg = blds[pi * chunks:(pi + 1) * chunks] or blds[pi % len(blds):pi % len(blds) + 1]
        patrols.append({"id": f"patrol:{pi}", "name": f"патруль №{pi + 1}", "pace": 4,
                        "route": [SQUARE, *seg], "members": members})

    investigators = []
    for ii in range(plan["n_investigators"]):
        nid = f"npc:watch_investigator{'' if ii == 0 else ii}"
        roster.append((nid, f"Дознаватель {inv_names[ii % len(inv_names)]}", "investigator", "srd:veteran",
                       ["проницательная", "недоверчивая"]))
        investigators.append(nid)
    return {"roster": roster, "patrols": patrols, "investigators": investigators}


def register_watch(world, seed: int = 0) -> None:
    """Фракция стражи + сгенерированный под размер города ростер; патрули/дознаватели — на world."""
    from ..world.components import Faction
    from .phandalin import _add_npc
    if WATCH not in world.factions:
        world.ecs.spawn(WATCH)
        fac = Faction(name="Городская стража", kind="watch", controls=[HQ], joinable=True)
        world.ecs.add(WATCH, fac)
        world.factions[WATCH] = fac
    plan = build_watch(world, seed)
    for nid, name, arch, sb, traits in plan["roster"]:
        _add_npc(world, nid, name, arch, sb, faction=WATCH, profession="guard",
                 works_at=HQ, lives_in=HQ, place=HQ, traits=list(traits))
    world.watch_patrols = plan["patrols"]
    world.watch_investigators = plan["investigators"]


def patrol_place(patrol: dict, tick: int) -> str:
    """Где патруль СЕЙЧАС — детерминированно по времени (цикл по маршруту)."""
    r = patrol["route"]
    return r[(tick // max(1, patrol["pace"])) % len(r)]


def patrol_size(patrol: dict, world) -> int:
    return sum(1 for m in patrol["members"] if world.is_alive(m))


def patrols_of(world) -> list:
    return getattr(world, "watch_patrols", []) or []
