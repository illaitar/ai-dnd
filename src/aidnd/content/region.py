"""Истинные факты локаций региона (ground truth) — основа «правдивой» карты.

Карта в голове игрока (world.player_maps) может расходиться с этой правдой:
сведения, купленные у NPC, бывают ложными либо неполными. Истина вскрывается при
посещении (см. gen/mapinfo.verify_on_visit).
"""

from __future__ import annotations

# site_key -> правда о локации
REGION_SITES = {
    "cragmaw_hideout": {
        "label": "Логово Крэгмо", "place": "place:cragmaw_klarg_cave",
        "terrain": "холмы, пещера", "direction": "запад",
        "contents": "багбир Кларг, пленник Гундрен, тайник", "danger": "высокая"},
    "cragmaw_castle": {
        "label": "Замок Крэгмо", "place": "place:cragmaw_castle",
        "terrain": "руины в лесу", "direction": "северо-запад",
        "contents": "Король Грол и карта к руднику", "danger": "высокая"},
    "wave_echo_cave": {
        "label": "Пещера Эха Волн", "place": "place:wave_echo_cave",
        "terrain": "глубокая пещера", "direction": "юго-запад",
        "contents": "Кузня Заклинаний, Нежнар «Чёрный Паук»", "danger": "смертельная"},
    "wyvern_tor": {
        "label": "Вайверн-Тор", "place": "place:wyvern_tor",
        "terrain": "скалистый холм", "direction": "север",
        "contents": "орочий лагерь", "danger": "средняя"},
    "thundertree": {
        "label": "Громовое Древо", "place": "place:thundertree",
        "terrain": "заброшенный город в лесу", "direction": "юг",
        "contents": "дракончик Веномфанг, друид Рейдот", "danger": "высокая"},
    "old_owl_well": {
        "label": "Старый Совиный Колодец", "place": "place:old_owl_well",
        "terrain": "древняя башня", "direction": "северо-восток",
        "contents": "маг Хамун Кост и нежить", "danger": "средняя"},
}

# тема знаний NPC -> о каком сайте он может рассказать
TOPIC_TO_SITE = {
    "cragmaw": "cragmaw_hideout", "gundren": "cragmaw_castle", "wave_echo": "wave_echo_cave",
    "wyvern_tor": "wyvern_tor", "thundertree": "thundertree", "garaele": "old_owl_well",
    "mine": "wave_echo_cave",
}


def site(site_key: str) -> dict | None:
    return REGION_SITES.get(site_key)


def reachable_place_to_site(place_id: str) -> str | None:
    for key, s in REGION_SITES.items():
        if s.get("place") == place_id:
            return key
    return None
