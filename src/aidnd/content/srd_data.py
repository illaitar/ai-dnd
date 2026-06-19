"""Контент: шаблоны предметов SRD + авторские предметы LMoP (док 03 §1, §3).

Регистрирует flyweight-шаблоны в world.templates. Механика 5e из SRD 5.1;
именные предметы LMoP — авторский контент.
"""

from __future__ import annotations

from ..inventory.items import ItemTemplate


def _t(tid, name, cat, **kw) -> ItemTemplate:
    return ItemTemplate(template_id=tid, name=name, category=cat, **kw)


TEMPLATES: list[ItemTemplate] = [
    # валюта
    _t("tmpl:cp", "медяки", "currency", stackable=True, max_stack=100000, base_value=1),
    _t("tmpl:sp", "серебро", "currency", stackable=True, max_stack=100000, base_value=10),
    _t("tmpl:gp", "золото", "currency", stackable=True, max_stack=100000, base_value=100),
    # оружие (base_stats.weapon_key → rules.WEAPONS)
    _t("tmpl:dagger", "кинжал", "weapon", weight=1, base_value=200,
       base_stats={"weapon_key": "dagger", "slot": "main_hand"}, tags=("finesse", "light")),
    _t("tmpl:shortsword", "короткий меч", "weapon", weight=2, base_value=1000,
       base_stats={"weapon_key": "shortsword", "slot": "main_hand"}, tags=("finesse", "martial")),
    _t("tmpl:longsword", "длинный меч", "weapon", weight=3, base_value=1500,
       base_stats={"weapon_key": "longsword", "slot": "main_hand"}, tags=("martial",)),
    _t("tmpl:mace", "булава", "weapon", weight=4, base_value=500,
       base_stats={"weapon_key": "mace", "slot": "main_hand"}),
    _t("tmpl:scimitar", "скимитар", "weapon", weight=3, base_value=2500,
       base_stats={"weapon_key": "scimitar", "slot": "main_hand"}, tags=("finesse", "martial")),
    _t("tmpl:morningstar", "моргенштерн", "weapon", weight=4, base_value=1500,
       base_stats={"weapon_key": "morningstar", "slot": "main_hand"}, tags=("martial",)),
    _t("tmpl:shortbow", "короткий лук", "weapon", weight=2, base_value=2500,
       base_stats={"weapon_key": "shortbow", "slot": "main_hand"}, tags=("ranged", "two_handed")),
    # броня (base_stats.ac, max_dex)
    _t("tmpl:leather", "кожаный доспех", "armor", weight=10, base_value=1000,
       base_stats={"ac": 11, "max_dex": 99, "slot": "armor"}),
    _t("tmpl:studded_leather", "клёпаная кожа", "armor", weight=13, base_value=4500,
       base_stats={"ac": 12, "max_dex": 99, "slot": "armor"}),
    _t("tmpl:chain_shirt", "кольчужная рубаха", "armor", weight=20, base_value=5000,
       base_stats={"ac": 13, "max_dex": 2, "slot": "armor"}),
    _t("tmpl:scale_mail", "чешуйчатый доспех", "armor", weight=45, base_value=5000,
       base_stats={"ac": 14, "max_dex": 2, "slot": "armor"}),
    _t("tmpl:shield", "щит", "armor", weight=6, base_value=1000,
       base_stats={"ac_bonus": 2, "slot": "off_hand"}, tags=("shield",)),
    # расходники
    _t("tmpl:potion_healing", "зелье лечения", "consumable", weight=0.5, base_value=5000,
       rarity="common", stackable=True, max_stack=10,
       base_stats={"heal": "2d4+2"}),
    _t("tmpl:rations", "паёк", "consumable", weight=2, base_value=50, stackable=True, max_stack=10),
    _t("tmpl:torch", "факел", "gear", weight=1, base_value=1, stackable=True, max_stack=20),
    # магические (SRD-пул, rarity-гейт)
    _t("tmpl:cloak_of_protection", "плащ защиты", "magic", weight=1, base_value=350000,
       rarity="uncommon", attunement=True, base_stats={"slot": "cloak", "ac_bonus": 1}),
    _t("tmpl:wand_magic_missiles", "жезл волшебных снарядов", "magic", weight=1,
       base_value=200000, rarity="uncommon", base_stats={"slot": "main_hand"}),
    _t("tmpl:boots_striding", "сапоги скорохода", "magic", weight=1, base_value=300000,
       rarity="uncommon", attunement=True, base_stats={"slot": "boots", "speed": 30}),
    # авторские именные предметы LMoP (док 03 §3)
    _t("tmpl:staff_of_defense", "Посох Защиты", "magic", weight=4, base_value=600000,
       rarity="rare", attunement=True, base_stats={"weapon_key": "quarterstaff",
       "slot": "main_hand", "ac_bonus": 1}, tags=("martial", "named")),
    _t("tmpl:mace_plus1_lightbringer", "Светоносец", "magic", weight=4, base_value=500000,
       rarity="uncommon", base_stats={"weapon_key": "mace", "slot": "main_hand",
       "attack_bonus": 1}, tags=("holy", "named")),
    _t("tmpl:spider_staff", "Посох Паука", "magic", weight=4, base_value=500000,
       rarity="rare", attunement=True, base_stats={"weapon_key": "quarterstaff",
       "slot": "main_hand", "attack_bonus": 1}, tags=("named",)),
    _t("tmpl:gauntlets_ogre_power", "Перчатки Огрской Силы", "magic", weight=2,
       base_value=300000, rarity="uncommon", attunement=True,
       base_stats={"slot": "gloves"}, tags=("named",)),
    # квестовые
    _t("tmpl:gundren_map", "карта Gundren к Wave Echo Cave", "gear", weight=0,
       base_value=0, tags=("undroppable", "unsellable", "quest_bound", "named")),
    _t("tmpl:supply_crate", "ящик припасов", "gear", weight=20, base_value=500,
       tags=("quest_bound",)),
]


def register_item_templates(world) -> None:
    for tmpl in TEMPLATES:
        world.templates[tmpl.template_id] = tmpl
