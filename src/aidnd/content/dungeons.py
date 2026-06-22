"""Раскладка сгенерированного подземелья в мир (док 05/07).

Берёт Dungeon из gen.dungeon и вписывает его в спатиал-граф: комнаты → Place,
рёбра door/stairs → порталы, locked → портал с замком (открывается смертью
стража-ключника), secret → СКРЫТЫЙ проход (не в графе, пока не найден). Боссы,
стража и гоблины спавнятся по contents. Всё в пре-гене → детерминированно и
переживает сейв/лоад. LLM здесь не участвует.
"""

from __future__ import annotations

from ..gen.dungeon import DungeonBrief, generate
from ..gen.item_gen import spawn_item
from ..world.spatial import Place

WARREN = "sunless_warren"

_ROLE_NAME = {
    "entrance": "Вход в нору", "hub": "Тоннельная развилка", "combat": "Логово стражи",
    "treasure": "Старая кладовая", "boss": "Логово вожака", "secret": "Замурованный тайник",
    "landing": "Нижний ярус",
}


def default_warren_brief() -> DungeonBrief:
    return DungeonBrief(site_key=WARREN, theme="cave", tier=2, floors=2,
                        faction="faction:cragmaw", boss="npc:warren_chief")


def _room_name(d, rid: str) -> str:
    role = d.rooms[rid].role
    base = _ROLE_NAME.get(role, role)
    same = [r for r in d.rooms if d.rooms[r].role == role]
    return base if len(same) == 1 else f"{base} {same.index(rid) + 1}"


def _spawn_mob(world, npc_id: str, name: str, stat_ref: str, place: str,
               faction: str = "faction:cragmaw", weapon: str = "tmpl:scimitar") -> str:
    from .phandalin import _add_npc
    _add_npc(world, npc_id, name, "monster", stat_ref, faction=faction, place=place)
    if weapon and weapon in world.templates:
        iid = f"it:{npc_id.split(':', 1)[1]}_wpn"
        spawn_item(world, weapon, None, owner=npc_id, source="authored", instance_id=iid)
        world.items[iid].equipped_slot = "main_hand"
    return npc_id


def build_dungeon(world, brief: DungeonBrief, seed: int,
                  link_from: str = "place:phandalin_wilds") -> object:
    d = generate(brief, seed)
    sp = world.spatial
    sk = brief.site_key
    site = f"site:{sk}"
    sp.add_place(Place(site, "site", "Бессолнечная нора", parent="region:phandalin"))

    for rid, r in d.rooms.items():                       # комнаты → узлы графа
        afford = ["combat"] if r.role in ("combat", "boss") else []
        sp.add_place(Place(rid, "room", _room_name(d, rid), parent=site, affordances=afford))

    for a, b, kind in d.edges:                            # рёбра
        if kind == "secret":
            world.dungeon_secrets[a] = b                  # скрыт: в граф НЕ добавляем
        else:                                             # door|locked|stairs — проходимы
            sp.link_portal(a, b)
    sp.link_portal(link_from, d.entrance)                 # вход из диких земель

    guard_room = None                                      # комната-страж: её зачистка откроет замок
    for rid, r in d.rooms.items():                         # наполнение комнат
        for c in r.contents:
            if c["kind"] == "encounter":
                guard_room = rid
                _spawn_mob(world, f"npc:{sk}_keeper", "Страж-ключник норы", "srd:bugbear", rid)
                for i in range(max(0, int(c.get("n", 1)))):
                    _spawn_mob(world, f"npc:{sk}_goblin_{i}", f"Гоблин норы {i + 1}", "srd:goblin", rid)
            elif c["kind"] == "boss":
                npc = c.get("npc") or f"npc:{sk}_chief"
                _spawn_mob(world, npc, "Вожак норы", "srd:bugbear", rid,
                           weapon="tmpl:morningstar")

    for a, b, kind in d.edges:                             # замок открывается зачисткой комнаты-стража
        if kind == "locked" and guard_room:
            world.dungeon_locks[frozenset((a, b))] = guard_room

    world.dungeons[sk] = d
    return d
