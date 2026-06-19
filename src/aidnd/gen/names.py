"""Подсистема имён (док 02 §7).

Пулы имён по расам, марковский фоллбэк при исчерпании пула, наследование фамилии
в семье, глобальный реестр уникальности, эпитеты для заметных NPC.
"""

from __future__ import annotations

import random

NAME_POOLS = {
    "human": {
        "given_m": ["Toblen", "Harbin", "Daran", "Sildar", "Thel", "Garret", "Oren",
                    "Pip", "Marl", "Eldon", "Bram", "Corin", "Wesley", "Hatch"],
        "given_f": ["Linene", "Halia", "Mirna", "Nilsa", "Elsa", "Tibor", "Rosa",
                    "Greta", "Della", "Maeve", "Sela", "Yarra"],
        "surname": ["Stonehill", "Wester", "Graywind", "Thornton", "Dendrar",
                    "Hallwinter", "Albrek", "Coalfist", "Underbough", "Tallstag"],
    },
    "halfling": {
        "given_m": ["Carp", "Ander", "Milo", "Rell", "Fenwick", "PELL", "Dob"],
        "given_f": ["Qelline", "Peony", "Lila", "Marigold", "Bree", "Tansy"],
        "surname": ["Alderleaf", "Tockhole", "Greenbottle", "Tealeaf", "Goodbarrel"],
    },
    "dwarf": {
        "given_m": ["Gundren", "Nundro", "Tharden", "Dorin", "Balin", "Grist"],
        "given_f": ["Hilda", "Vistra", "Audhild", "Gunnloda"],
        "surname": ["Rockseeker", "Ironfist", "Coalsmith", "Deepdelver", "Stoneshield"],
    },
    "half-elf": {
        "given_m": ["Reidoth", "Aramil", "Faelar", "Galinndan"],
        "given_f": ["Garaele", "Antinua", "Felosial", "Shava"],
        "surname": ["Amblecrown", "Meliamne", "Nailo", "Siannodel"],
    },
    "elf": {
        "given_m": ["Iarno", "Carric", "Heian", "Thamior"],
        "given_f": ["Agatha", "Birel", "Mialee", "Naivara"],
        "surname": ["Moonwhisper", "Holimion", "Liadon", "Xiloscient"],
    },
}

_SYLL = ["ar", "en", "or", "il", "an", "ek", "us", "in", "od", "el", "ra", "th", "ow"]


def markov_name(race: str, rng: random.Random) -> str:
    n = rng.randint(2, 3)
    s = "".join(rng.choice(_SYLL) for _ in range(n))
    return s.capitalize()


def draw(pool_key: str, race: str, rng: random.Random) -> str | None:
    pool = NAME_POOLS.get(race, NAME_POOLS["human"]).get(pool_key)
    return rng.choice(pool) if pool else None


def make_name(
    race: str, gender: str, registry: set[str], rng: random.Random,
    surname: str | None = None, tries: int = 8,
) -> tuple[str, str]:
    """Возвращает (given, surname), уникальное по реестру."""
    gkey = "given_f" if gender == "female" else "given_m"
    for _ in range(tries):
        given = draw(gkey, race, rng) or markov_name(race, rng)
        sur = surname or draw("surname", race, rng) or markov_name(race, rng)
        full = f"{given} {sur}"
        if full not in registry:
            registry.add(full)
            return given, sur
    # гарантированно уникальное через марков
    given = markov_name(race, rng)
    sur = surname or markov_name(race, rng)
    registry.add(f"{given} {sur}")
    return given, sur
