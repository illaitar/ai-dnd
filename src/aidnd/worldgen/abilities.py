"""Характеристики NPC: детерминированный разброс вокруг роли (данные, не магия по коду).

База — «простолюдинский» разброс 8..15 (3d6-стиль со сглаживанием), поверх — смещения роли
(кузнецу — сила, знахарке — мудрость). Один и тот же (pid, seed) → те же цифры: банк можно
мигрировать/перегенерировать без дрейфа. Персон/портретов не касается.

Key functions
-------------
roll_abilities(role: str, rng: Random) -> dict : Generate role-biased ability
  scores (6..17) with 4d6 distribution.
"""

from __future__ import annotations

from random import Random

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")

# роль → смещения (добавка к броску, обрезка в 6..17); подстрока роли — как _TYPE_ROLE
ROLE_BIAS = {
    "кузнец": {"str": 3, "con": 2},
    "оружейник": {"str": 2, "dex": 1, "int": 1},
    "стражник": {"str": 2, "con": 2},
    "охотник": {"dex": 3, "wis": 1},
    "головорез": {"str": 2, "dex": 1},
    "бродяга": {"dex": 2, "con": 1},
    "наёмник": {"str": 2, "dex": 1, "con": 1},
    "трактирщик": {"cha": 2, "con": 1},
    "лавочник": {"cha": 2, "int": 1},
    "знахарка": {"wis": 3, "int": 1},
    "жрец": {"wis": 2, "cha": 1},
    "бард": {"cha": 3, "dex": 1},
    "мельник": {"str": 2, "con": 1},
    "сапожник": {"dex": 2},
    "дубильщик": {"con": 2, "str": 1},
    "писец": {"int": 3},
    "горожанин": {},
}


def roll_abilities(role: str, rng: Random) -> dict:
    """3d6-подобный бросок (среднее ~10.5, хвосты реже) + смещение роли, клип 6..17."""
    bias = next((b for key, b in ROLE_BIAS.items() if key in (role or "").lower()), {})
    out = {}
    for ab in ABILITIES:
        base = sum(sorted(rng.randint(1, 6) for _ in range(4))[1:])   # 4d6 без худшей
        out[ab] = max(6, min(17, base + bias.get(ab, 0) - 2))         # −2: простолюдин, не герой
    return out
