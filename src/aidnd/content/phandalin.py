"""Авторский манифест мира: вертикальный срез LMoP (main §1, §14, док 01 §2).

Phandalin как социальный хаб (тиры L0-L3) + Cragmaw Hideout как боевое подземелье.
Сборка по манифесту предгенерации (док 01 §2): здания → население → экономика и
лут → фракции → квесты → окружение.
"""

from __future__ import annotations

from .. import ids
from ..gen.item_gen import spawn_item
from ..gen.npc_gen import CharacterGenerator, SettlementProfile
from ..inventory.container import Container
from ..rules.srd import get_stat_block
from ..world import World
from ..world.components import (
    Faction,
    LODState,
    Persona,
    Profession,
    Relationships,
    Stats5e,
)
from ..world.spatial import Place
from .srd_data import register_item_templates

REGION = "region:phandalin"


# --------------------------------------------------------------------------- #
#  Пространственная иерархия                                                   #
# --------------------------------------------------------------------------- #
def _build_places(world: World) -> None:
    sp = world.spatial
    sp.add_place(Place(REGION, "region", "Окрестности Фэндалина"))
    sp.add_place(Place("settlement:phandalin", "settlement", "Фэндалин", parent=REGION))
    for d in ("market", "residential", "outskirts"):
        sp.add_place(Place(f"district:{d}", "district", d, parent="settlement:phandalin"))

    buildings = [
        ("building:stonehill_inn", "Постоялый двор «Каменный Холм»", "market",
         ["inn", "serve", "drink", "eat", "residential"]),
        ("building:barthens_provisions", "Лавка Бартена", "market", ["shop", "work"]),
        ("building:lionshield_coster", "Львинощит Костер", "market", ["shop", "work"]),
        ("building:townmaster_hall", "Ратуша", "market", ["townhall", "work"]),
        ("building:shrine_of_luck", "Святилище Удачи", "market", ["shrine", "work"]),
        ("building:sleeping_giant", "Таверна «Спящий великан»", "outskirts",
         ["inn", "drink"]),
        ("building:tresendar_manor", "Поместье Тресендар (укрытие Красных плащей)",
         "outskirts", ["manor", "hideout"]),
        ("building:edermath_orchard", "Сад Эдермата", "outskirts", ["farm", "work", "residential"]),
        ("building:alderleaf_farm", "Ферма Олдерлиф", "outskirts", ["farm", "work", "residential"]),
    ]
    for bid, name, district, affs in buildings:
        sp.add_place(Place(bid, "building", name, parent="settlement:phandalin",
                           district=district, affordances=affs))
        world.commit("kg_add", "worldgen", payload={"s": bid, "r": "located_in", "o": f"district:{district}"})

    # карта по сторонам света: рыночная площадь — хаб, здания вокруг по компасу.
    # ВАЖНО (док §3.4): вложенность Region→Settlement→Square задаётся через
    # parent/children, а НЕ порталами — порталы это рёбра ПРОХОДИМОСТИ (ходьбы),
    # чтобы hops/AOI не смешивали «шаг в регион» с «шагом в лавку».
    sq = "place:phandalin_square"
    sp.add_place(Place(sq, "room", "Рыночная площадь",
                       parent="settlement:phandalin", district="market"))
    compass = {
        "north": "building:stonehill_inn",
        "east": "building:barthens_provisions",
        "west": "building:lionshield_coster",
        "south": "building:townmaster_hall",
        "northeast": "building:shrine_of_luck",
        "southwest": "building:sleeping_giant",
        "southeast": "building:tresendar_manor",
        "northwest": "building:edermath_orchard",
    }
    for direction, bid in compass.items():
        sp.link(sq, direction, bid)
    sp.link("building:sleeping_giant", "south", "building:alderleaf_farm")  # за «Спящим великаном»

    # --- региональный слой странствий ------------------------------------- #
    # Из города «наружу» в дикие земли, оттуда — к сайтам по СТОРОНАМ СВЕТА
    # (направления берутся из ground-truth REGION_SITES, чтобы карта и движок
    # совпадали). Дойдя до сайта, игрок сверяет купленные наводки с реальностью.
    from ..world.spatial import DIR_ALIASES
    from .region import REGION_SITES
    wilds = "place:phandalin_wilds"
    sp.add_place(Place(wilds, "wilds", "Окрестные дикие земли", parent=REGION,
                       ambiance="простор пустошей и холмов под открытым небом"))
    sp.link(sq, "out", wilds)                               # покинуть городские стены

    # Логово Крэгмо: подход (site) на западе + пещера Кларга (бой) вглубь
    sp.add_place(Place("site:cragmaw_hideout", "site", "Логово Крэгмо", parent=REGION))
    sp.add_place(Place("place:cragmaw_klarg_cave", "room", "Пещера Кларга",
                       parent="site:cragmaw_hideout", affordances=["combat"]))
    sp.link(wilds, "west", "site:cragmaw_hideout")
    sp.link("site:cragmaw_hideout", "deeper", "place:cragmaw_klarg_cave")

    # прочие сайты региона — достижимые узлы по своим сторонам света
    for key in ("cragmaw_castle", "wave_echo_cave", "wyvern_tor", "thundertree", "old_owl_well"):
        s = REGION_SITES[key]
        sp.add_place(Place(s["place"], "site", s["label"], parent=REGION,
                           affordances=["combat"], ambiance=s["terrain"]))
        sp.link(wilds, DIR_ALIASES.get(s["direction"], "out"), s["place"])


# --------------------------------------------------------------------------- #
#  NPC                                                                         #
# --------------------------------------------------------------------------- #
def _add_npc(world: World, npc_id: str, name: str, archetype: str, stat_ref: str,
             race: str = "human", faction: str | None = None, traits=None,
             voice=None, profession: str | None = None, works_at: str | None = None,
             lives_in: str | None = None, place: str | None = None,
             knowledge=None, secrets=None, epithet=None) -> str:
    world.ecs.spawn(npc_id)
    sb = get_stat_block(stat_ref)
    persona = Persona(
        name=name, archetype=archetype, race=race, profession=profession,
        traits=list(traits or []), voice=voice, stat_block_ref=stat_ref,
        faction=faction, epithet=epithet, knowledge=list(knowledge or []),
        secrets=list(secrets or []), enriched=bool(voice))
    from .knowledge import inherit_knowledge
    inherit_knowledge(persona, profession, faction)
    world.ecs.add(npc_id, persona)
    world.ecs.add(npc_id, Stats5e(
        str_=sb.str_, dex=sb.dex, con=sb.con, int_=sb.int_, wis=sb.wis, cha=sb.cha,
        max_hp=sb.hp, hp=sb.hp, ac_base=sb.ac, proficiency=sb.proficiency, speed=sb.speed,
        proficient_skills=list(sb.skills), proficient_saves=list(sb.saves)))
    world.ecs.add(npc_id, LODState(tier=0))
    world.ecs.add(npc_id, Relationships())
    world.name_registry.add(name)
    if profession:
        world.ecs.add(npc_id, Profession(job=profession, workplace_ref=works_at, residence_ref=lives_in))
        world.commit("kg_set", "worldgen", payload={"s": npc_id, "r": "profession", "o": profession})
    if works_at:
        world.commit("kg_set", "worldgen", payload={"s": npc_id, "r": "works_at", "o": works_at})
    if lives_in:
        world.commit("kg_set", "worldgen", payload={"s": npc_id, "r": "lives_in", "o": lives_in})
    if faction:
        world.commit("kg_add", "worldgen", payload={"s": npc_id, "r": "member_of", "o": faction})
    pos_place = place or lives_in or "building:stonehill_inn"
    world.commit("set_position", "worldgen", target=npc_id,
                 payload={"region": REGION, "place": pos_place})
    return npc_id


def _build_named_npcs(world: World) -> None:
    _add_npc(world, "npc:toblen_stonehill", "Toblen Stonehill", "innkeeper", "srd:commoner",
             profession="innkeeper", works_at="building:stonehill_inn",
             lives_in="building:stonehill_inn", place="building:stonehill_inn",
             traits=["welcoming", "gossipy"], voice="говорит тепло, любит поболтать",
             knowledge=[{"fact": "Redbrands shake down merchants", "topic": "redbrands",
                         "disclosure_gate": {"trust": 0.2}}])
    _add_npc(world, "npc:linene_graywind", "Linene Graywind", "merchant", "srd:commoner",
             profession="merchant", works_at="building:lionshield_coster",
             lives_in="building:lionshield_coster", place="building:lionshield_coster",
             traits=["shrewd", "worried"],
             knowledge=[{"fact": "a wagon of Lionshield goods was stolen near the trail",
                         "topic": "lionshield", "disclosure_gate": {"trust": 0.1},
                         "unlocks_quest": "quest:lionshield_goods"}])
    _add_npc(world, "npc:harbin_wester", "Harbin Wester", "townmaster", "srd:commoner",
             profession="guard", works_at="building:townmaster_hall",
             lives_in="building:townmaster_hall", place="building:townmaster_hall",
             traits=["timid", "bureaucratic"],
             knowledge=[{"fact": "orcs raid from Wyvern Tor", "topic": "wyvern_tor",
                         "disclosure_gate": {"trust": 0.1}, "unlocks_quest": "quest:wyvern_tor_orcs"}])
    _add_npc(world, "npc:sister_garaele", "Sister Garaele", "priest", "srd:acolyte",
             race="half-elf", faction="faction:harpers", profession="priest",
             works_at="building:shrine_of_luck", lives_in="building:shrine_of_luck",
             place="building:shrine_of_luck", traits=["earnest", "secretive"])
    _add_npc(world, "npc:daran_edermath", "Daran Edermath", "retired_adventurer", "srd:veteran",
             profession="farmhand", works_at="building:edermath_orchard",
             lives_in="building:edermath_orchard", place="building:edermath_orchard",
             traits=["honest", "vigilant"], faction="faction:lords_alliance")
    _add_npc(world, "npc:halia_thornton", "Halia Thornton", "guildmaster", "srd:thug",
             faction="faction:zhentarim", profession="merchant",
             works_at="building:townmaster_hall", lives_in="building:townmaster_hall",
             place="building:townmaster_hall", traits=["ambitious", "manipulative"],
             secrets=[{"fact": "I run the Zhentarim cell here",
                       "reveal_conditions": ["trust>0.6"], "consequence_tags": ["faction"]}])
    _add_npc(world, "npc:sildar_hallwinter", "Sildar Hallwinter", "knight", "srd:veteran",
             faction="faction:lords_alliance", traits=["noble", "weary"],
             place="building:stonehill_inn")
    _add_npc(world, "npc:gundren_rockseeker", "Gundren Rockseeker", "prospector", "srd:commoner",
             race="dwarf", traits=["excitable", "secretive"], place="place:cragmaw_klarg_cave")
    # антагонист — социальный босс Redbrand Hideout
    _add_npc(world, "npc:iarno_glasstaff", "Iarno Albrek", "mage", "srd:mage",
             faction="faction:redbrands", epithet="Glasstaff",
             place="building:tresendar_manor", traits=["smug", "cowardly"],
             secrets=[{"fact": "I lead the Redbrands for the Black Spider",
                       "reveal_conditions": ["defeated"], "consequence_tags": ["main_plot"]}])


def _build_encounter(world: World) -> list[str]:
    """Боевой энкаунтер Cragmaw Hideout: Klarg + 2 гоблина (main §1)."""
    klarg = _add_npc(world, "npc:klarg", "Klarg", "bugbear_boss", "srd:bugbear",
                     faction="faction:cragmaw", place="place:cragmaw_klarg_cave",
                     traits=["brutal", "proud"])
    g1 = _add_npc(world, "npc:goblin_1", "Гоблин-страж", "goblin", "srd:goblin",
                  faction="faction:cragmaw", place="place:cragmaw_klarg_cave")
    g2 = _add_npc(world, "npc:goblin_2", "Гоблин-лучник", "goblin", "srd:goblin",
                  faction="faction:cragmaw", place="place:cragmaw_klarg_cave")
    # экип монстров (оружие для урона)
    spawn_item(world, "tmpl:morningstar", None, owner="npc:klarg", source="authored",
               instance_id="it:klarg_morningstar")
    world.items["it:klarg_morningstar"].equipped_slot = "main_hand"
    for g in (g1, g2):
        iid = f"it:{ids.name_of(g)}_scimitar"
        spawn_item(world, "tmpl:scimitar", None, owner=g, source="authored", instance_id=iid)
        world.items[iid].equipped_slot = "main_hand"
    return [klarg, g1, g2]


# --------------------------------------------------------------------------- #
#  Фракции, фиксированный лут, экономика                                       #
# --------------------------------------------------------------------------- #
def _build_factions(world: World) -> None:
    for fid, name, controls in [
        ("faction:redbrands", "Красные плащи", ["building:tresendar_manor"]),
        ("faction:cragmaw", "Гоблины Крэгмо", ["site:cragmaw_hideout"]),
        ("faction:lords_alliance", "Союз Лордов", []),
        ("faction:harpers", "Арфисты", []),
        ("faction:zhentarim", "Жентарим", []),
    ]:
        world.ecs.spawn(fid)
        world.ecs.add(fid, Faction(name=name, controls=list(controls)))
        for c in controls:
            world.commit("kg_add", "worldgen", payload={"s": fid, "r": "controls", "o": c})


def _build_fixed_loot(world: World) -> None:
    # Staff of Defense на Glasstaff (док 03 §3)
    spawn_item(world, "tmpl:staff_of_defense", None, owner="npc:iarno_glasstaff",
               source="authored", instance_id="it:staff_of_defense")
    world.commit("kg_add", "worldgen", payload={"s": "it:staff_of_defense", "r": "owned_by", "o": "npc:iarno_glasstaff"})
    # сундук Klarg + украденные товары Lionshield (квестовый крючок, док 03 §12)
    chest = Container("container:klarg_chest", owner_ref=None, kind="chest",
                      items=[])
    world.containers["container:klarg_chest"] = chest
    spawn_item(world, "tmpl:cp", "container:klarg_chest", qty=600, source="authored",
               instance_id="it:klarg_cp")
    spawn_item(world, "tmpl:potion_healing", "container:klarg_chest", qty=2, source="authored",
               instance_id="it:klarg_potions")
    # карта Gundren — ключ к Wave Echo Cave (квестовый предмет, док 03 §10)
    spawn_item(world, "tmpl:gundren_map", "container:klarg_chest", source="authored",
               instance_id="it:gundren_map")
    # украденный ящик Lionshield с провенансом владельца (квестовый крючок, док 03 §12)
    spawn_item(world, "tmpl:supply_crate", "container:klarg_chest", source="authored",
               instance_id="it:lionshield_crate")
    world.items["it:lionshield_crate"].custom_name = "ящик с клеймом Львинощит Костер"
    world.commit("kg_add", "worldgen", payload={"s": "it:lionshield_crate", "r": "was_owned_by", "o": "npc:linene_graywind"})


def _build_shops(world: World) -> None:
    shops = [
        ("shop:barthen", "npc:linene_graywind", ("gear", "consumable"),
         [("tmpl:rations", 20), ("tmpl:torch", 30), ("tmpl:potion_healing", 3),
          ("tmpl:dagger", 4)]),
        ("shop:lionshield", "npc:linene_graywind", ("weapon", "armor"),
         [("tmpl:shortsword", 2), ("tmpl:leather", 2), ("tmpl:shield", 3),
          ("tmpl:chain_shirt", 1)]),
    ]
    for sid, owner, deals, stock in shops:
        shop = Container(sid, owner_ref=owner, kind="shop", deals_in=deals, buy_rate=0.5)
        world.containers[sid] = shop
        world.wallets[owner] = {"gp": 200}
        for tmpl, qty in stock:
            spawn_item(world, tmpl, sid, qty=qty, source="pregen")


# --------------------------------------------------------------------------- #
#  Игрок                                                                       #
# --------------------------------------------------------------------------- #
def _create_pc(world: World) -> str:
    pc = "pc:hero"
    world.player_id = pc
    world.ecs.spawn(pc)
    world.ecs.add(pc, Persona(name="Герой", archetype="fighter", race="human",
                              voice="игрок", enriched=True))
    world.ecs.add(pc, Stats5e(str_=16, dex=14, con=14, int_=10, wis=12, cha=10,
                              proficiency=2, level=3, max_hp=28, hp=28, ac_base=10,
                              proficient_skills=["athletics", "perception", "intimidation"],
                              proficient_saves=["str", "con"]))
    world.ecs.add(pc, LODState(tier=3))
    world.commit("set_position", "worldgen", target=pc,
                 payload={"region": REGION, "place": "building:stonehill_inn"})
    # инвентарь и экип
    carry = Container("carry:hero", owner_ref=pc, kind="carry")
    world.containers["carry:hero"] = carry
    world.wallets[pc] = {"gp": 25, "sp": 30}
    for tmpl, slot, iid in [("tmpl:longsword", "main_hand", "it:hero_sword"),
                            ("tmpl:chain_shirt", "armor", "it:hero_armor"),
                            ("tmpl:shield", "off_hand", "it:hero_shield")]:
        spawn_item(world, tmpl, "carry:hero", owner=pc, source="authored", instance_id=iid)
        world.items[iid].equipped_slot = slot
    spawn_item(world, "tmpl:potion_healing", "carry:hero", qty=2, owner=pc,
               source="authored", instance_id="it:hero_potions")
    return pc


# --------------------------------------------------------------------------- #
#  Сборка                                                                      #
# --------------------------------------------------------------------------- #
def phandalin_profile() -> SettlementProfile:
    return SettlementProfile(
        name="phandalin", target_population=45,
        profession_dist={"farmhand": 0.3, "miner": 0.25, "merchant": 0.1, "laborer": 0.15,
                         "guard": 0.05, "hunter": 0.1, "none": 0.05},
        race_dist={"human": 0.6, "halfling": 0.15, "dwarf": 0.15, "half-elf": 0.1},
        age_mean=35, age_std=14)


def build_world(seed: int = 1337, roster_size: int = 12, model=None) -> World:
    """Строит мир по манифесту предгенерации (док 01 §2)."""
    world = World(seed=seed)
    register_item_templates(world)
    _build_places(world)              # 1. building graph
    from .maps import attach_battlemaps
    attach_battlemaps(world)          # боевые карты на узлы графа локаций
    _build_named_npcs(world)          # 2a. named population
    _build_encounter(world)           # 2b. encounter NPCs
    _build_factions(world)            # 5. factions
    _build_fixed_loot(world)          # 4. fixed loot
    _build_shops(world)               # 3. economy
    _create_pc(world)
    # 2c. pregen roster поверх зданий (демография)
    if roster_size > 0:
        CharacterGenerator(world, model=model).generate_roster(phandalin_profile(), roster_size)
    return world
