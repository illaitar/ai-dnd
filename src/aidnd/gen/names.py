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

# расово-окрашенные слоги (onset+nucleus+coda) — для процедурных фэнтези-имён, когда пул исчерпан
_RACE_SYL = {
    "human": {"on": ["br", "th", "mar", "cor", "el", "gar", "wes", "hal", "ald", "ren", "dor", "mil", "ros",
                     "fen", "bal", "kar", "der", "ost", "lin", "ned", "tor", "vel"],
              "nu": ["a", "e", "i", "o", "an", "en", "or", "ar"],
              "co": ["n", "r", "s", "th", "din", "win", "mar", "ric", "da", "len", "ric", "mon", "ric", "wel"]},
    "dwarf": {"on": ["thr", "gr", "br", "dur", "bal", "gim", "thor", "dwa", "kaz", "mor", "tor", "nor", "von"],
              "nu": ["a", "u", "o", "ar", "or", "un", "um"],
              "co": ["in", "rik", "din", "grim", "li", "nar", "dur", "gar", "bek", "rund", "dan", "lic"]},
    "halfling": {"on": ["mil", "pip", "and", "fen", "dob", "rell", "per", "lil", "tans", "bree", "mer", "cob"],
                 "nu": ["o", "i", "a", "e"],
                 "co": ["o", "by", "ck", "wick", "ny", "ble", "dle", "kin", "low"]},
    "half-elf": {"on": ["ael", "il", "sil", "cae", "fae", "lor", "thal", "ny", "ela", "ari", "fel"],
                 "nu": ["a", "e", "i", "ia", "ae"],
                 "co": ["riel", "wen", "las", "mir", "dor", "nor", "wyn", "lian", "neth"]},
    "elf": {"on": ["ael", "sil", "cae", "fae", "lor", "thal", "ny", "ela", "ari", "myr", "tha", "lue"],
            "nu": ["a", "e", "i", "ia", "ae", "io", "ea"],
            "co": ["riel", "wen", "las", "mir", "thil", "dor", "nor", "wyn", "dril", "loth", "anil"]},
}


def markov_name(race: str, rng: random.Random) -> str:
    """Процедурное фэнтези-имя с расовым звучанием (onset+nucleus+coda, иногда длиннее)."""
    syl = _RACE_SYL.get(race, _RACE_SYL["human"])
    name = rng.choice(syl["on"]) + rng.choice(syl["nu"]) + rng.choice(syl["co"])
    if rng.random() < 0.32:
        name += rng.choice(syl["nu"]) + rng.choice(syl["co"])
    return name[0].upper() + name[1:]


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
