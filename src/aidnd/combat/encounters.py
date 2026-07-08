"""Assembly of encounters from BESTIARY DATA: CR budget + environment → set of monsters. No
hardcoding of species — what inhabits such an environment will emerge.

Key functions
-------------
pick_encounter(cr_budget: float, env: str, seed: str, max_units: int = 5) -> list : Greedy encounter builder selecting monsters by CR budget and environment.
lair_name(units: list, rng: Random) -> str : Generates lair name from inhabitants.
"""

from __future__ import annotations

from random import Random

from .model import bestiary, from_monster


def pick_encounter(cr_budget: float, env: str, seed: str, max_units: int = 5) -> list:
    """Greedy assembly: species from suitable environment, one by one up to budget (pack of weak or pair of strong)."""
    rng = Random(f"pick|{seed}")
    pool = [m for m in bestiary()
            if m.get("attack") and 0 < m.get("cr", 0) <= max(0.125, cr_budget * 0.75)
            and (not env or env in (m.get("environments") or []))]
    if not pool:
        pool = [m for m in bestiary() if m.get("attack") and 0 < m.get("cr", 0) <= cr_budget]
    if not pool:
        return []
    kind = rng.choice(pool)                                # lair of ONE species (+leader not in v1)
    out, spent, i = [], 0.0, 0
    while spent + kind["cr"] <= cr_budget and len(out) < max_units:
        out.append(from_monster(kind, f"m{i}"))
        spent += kind["cr"]
        i += 1
    return out or [from_monster(kind, "m0")]


def lair_name(units: list, rng: Random) -> str:
    """Lair name from its inhabitants (data, not invention)."""
    if not units:
        return "пустое логово"
    base = units[0].name
    return rng.choice([f"логово: {base.lower()}", f"гнездо ({base.lower()})", f"тропа {base.lower()}"])
