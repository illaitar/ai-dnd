"""NPC characteristics: deterministic spread around role (data, not code magic).

Base — "commoner" spread 8..15 (3d6-style with smoothing), on top — role offsets
(blacksmith — strength, wise woman — wisdom). Same (pid, seed) → same numbers: bank can be
migrated/regenerated without drift. Persons/portraits not affected.

Key functions
-------------
roll_abilities(role: str, rng: Random) -> dict : Generate role-biased ability
  scores (6..17) with 4d6 distribution.
"""

from __future__ import annotations

from random import Random

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")

# role → offsets (roll addition, clipped to 6..17); role substring — as _TYPE_ROLE
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
    """3d6-like roll (average ~10.5, tails rarer) + role offset, clipped 6..17."""
    bias = next((b for key, b in ROLE_BIAS.items() if key in (role or "").lower()), {})
    out = {}
    for ab in ABILITIES:
        base = sum(sorted(rng.randint(1, 6) for _ in range(4))[1:])   # 4d6 without worst
        out[ab] = max(6, min(17, base + bias.get(ab, 0) - 2))         # −2: commoner, not hero
    return out
