"""Offline pool step: tag a deterministic fraction of NPC-pool people with a non-human race.

Gives `race_relations` real targets (орк/дворф/эльф) to react to. Idempotent (skips anyone
already non-human) and deterministic (RNG keyed by pid, not insertion order). Touches only
`persona["race"]` — mech/placements/portraits are re-saved untouched.

Key functions
-------------
seed_races(store, fraction) -> int : Tag ~fraction of the pool's humans with a non-human race.
"""

from __future__ import annotations

import random

from .store import WorldStore

_RACES = ["орк", "дворф", "эльф"]


def seed_races(store: WorldStore, fraction: float = 0.1) -> int:
    """Deterministically tag ~`fraction` of pool people with a non-human race.

    RNG is keyed per-pid (`random.Random(f"race|{pid}")`), so the outcome is stable across
    runs regardless of pool size/order. Idempotent: people whose persona race is already
    non-human are left as-is and don't count toward `fraction` again. Only `persona["race"]`
    changes — role/name/charisma/appearance/mech/portraits/seed are re-saved verbatim.
    """
    made = 0
    for row in store.list_people(limit=100000):
        persona = row["persona"]
        if persona.get("race") in _RACES:
            continue          # already non-human — idempotent skip
        rng = random.Random(f"race|{row['id']}")
        if rng.random() >= fraction:
            continue
        persona = dict(persona)
        persona["race"] = rng.choice(_RACES)
        store.save_person(row["id"], row["role"], row["name"], row["charisma"], row["appearance"],
                          row["mech"], persona, row["portraits"], row["seed"])
        made += 1
    return made
