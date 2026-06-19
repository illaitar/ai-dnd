"""Данные SRD 5.1 для детерминированного движка правил (main §7).

Подмножество: модификаторы характеристик, маппинг навык→характеристика,
стат-блоки для горожан и боевых NPC вертикального среза LMoP, оружие.
"""

from __future__ import annotations

from dataclasses import dataclass


def ability_modifier(score: int) -> int:
    """5e: (score - 10) // 2."""
    return (score - 10) // 2


# навык -> характеристика (док config CHECK_GUIDE, SRD)
SKILL_ABILITY = {
    "athletics": "str",
    "acrobatics": "dex", "stealth": "dex", "sleight_of_hand": "dex",
    "arcana": "int", "history": "int", "investigation": "int",
    "nature": "int", "religion": "int",
    "animal_handling": "wis", "insight": "wis", "medicine": "wis",
    "perception": "wis", "survival": "wis",
    "deception": "cha", "intimidation": "cha", "performance": "cha",
    "persuasion": "cha",
}

SOCIAL_SKILLS = {"persuasion", "deception", "intimidation", "performance"}


@dataclass(frozen=True)
class Weapon:
    name: str
    damage: str             # "1d8"
    ability: str            # str | dex
    properties: tuple = ()  # finesse, two_handed, ranged, light ...
    damage_type: str = "slashing"


WEAPONS = {
    "unarmed": Weapon("кулак", "1", "str", damage_type="bludgeoning"),
    "dagger": Weapon("кинжал", "1d4", "dex", ("finesse", "light", "thrown")),
    "shortsword": Weapon("короткий меч", "1d6", "dex", ("finesse", "light")),
    "longsword": Weapon("длинный меч", "1d8", "str"),
    "scimitar": Weapon("скимитар", "1d6", "dex", ("finesse", "light")),
    "mace": Weapon("булава", "1d6", "str", damage_type="bludgeoning"),
    "morningstar": Weapon("моргенштерн", "1d8", "str", damage_type="piercing"),
    "greataxe": Weapon("секира", "1d12", "str", ("two_handed",)),
    "shortbow": Weapon("короткий лук", "1d6", "dex", ("ranged", "two_handed"), "piercing"),
    "light_crossbow": Weapon("лёгкий арбалет", "1d8", "dex", ("ranged",), "piercing"),
    "quarterstaff": Weapon("посох", "1d6", "str", damage_type="bludgeoning"),
}


@dataclass(frozen=True)
class StatBlock:
    """Шаблон стат-блока SRD (flyweight)."""

    ref: str
    name: str
    str_: int = 10
    dex: int = 10
    con: int = 10
    int_: int = 10
    wis: int = 10
    cha: int = 10
    ac: int = 10
    hp: int = 4
    speed: int = 30
    proficiency: int = 2
    cr: float = 0.0
    intelligence_score: int = 10       # для морали (док 09 §9)
    weapon: str = "unarmed"
    skills: tuple = ()
    saves: tuple = ()
    traits: tuple = ()


# Стат-блоки вертикального среза (SRD + статблоки монстров LMoP).
STAT_BLOCKS: dict[str, StatBlock] = {
    "srd:commoner": StatBlock("srd:commoner", "Простолюдин", 10, 10, 10, 10, 10, 10,
                              ac=10, hp=4, cr=0.0),
    "srd:guard": StatBlock("srd:guard", "Стражник", 13, 12, 12, 10, 11, 10,
                           ac=16, hp=11, cr=0.125, weapon="longsword",
                           skills=("perception",)),
    "srd:acolyte": StatBlock("srd:acolyte", "Послушник", 10, 10, 10, 10, 14, 11,
                             ac=10, hp=9, cr=0.25, weapon="mace",
                             skills=("medicine", "religion", "insight")),
    "srd:bandit": StatBlock("srd:bandit", "Бандит", 11, 12, 12, 10, 10, 10,
                            ac=12, hp=11, cr=0.125, weapon="scimitar"),
    "srd:thug": StatBlock("srd:thug", "Громила", 15, 11, 14, 10, 10, 11,
                          ac=11, hp=32, cr=0.5, weapon="mace",
                          skills=("intimidation",)),
    "srd:scout": StatBlock("srd:scout", "Разведчик", 11, 14, 12, 11, 13, 11,
                           ac=13, hp=16, cr=0.5, weapon="shortbow",
                           skills=("nature", "perception", "stealth", "survival")),
    "srd:goblin": StatBlock("srd:goblin", "Гоблин", 8, 14, 10, 10, 8, 8,
                            ac=15, hp=7, speed=30, cr=0.25, intelligence_score=10,
                            weapon="scimitar", skills=("stealth",)),
    "srd:bugbear": StatBlock("srd:bugbear", "Багбир", 15, 14, 13, 8, 11, 9,
                             ac=16, hp=27, cr=1.0, intelligence_score=8,
                             weapon="morningstar", skills=("stealth", "survival")),
    "srd:wolf": StatBlock("srd:wolf", "Волк", 12, 15, 12, 3, 12, 6,
                          ac=13, hp=11, speed=40, cr=0.25, intelligence_score=3,
                          weapon="unarmed", skills=("perception", "stealth")),
    "srd:mage": StatBlock("srd:mage", "Маг", 9, 14, 11, 17, 12, 11,
                          ac=12, hp=40, cr=6.0, intelligence_score=17,
                          weapon="quarterstaff",
                          skills=("arcana", "history"), saves=("int", "wis")),
    "srd:veteran": StatBlock("srd:veteran", "Ветеран", 16, 13, 14, 10, 11, 10,
                             ac=17, hp=58, cr=3.0, weapon="longsword",
                             skills=("athletics", "perception")),
    "srd:drow": StatBlock("srd:drow", "Дроу", 10, 15, 10, 11, 11, 12,
                          ac=15, hp=13, cr=0.25, intelligence_score=11,
                          weapon="shortsword", skills=("perception", "stealth")),
}


def get_stat_block(ref: str) -> StatBlock:
    return STAT_BLOCKS.get(ref, STAT_BLOCKS["srd:commoner"])
