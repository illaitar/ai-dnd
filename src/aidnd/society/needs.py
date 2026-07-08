"""Needs (urges) — DECLARATIVE catalog. Add a need = add one line to NEEDS.

Model — The Sims "motives" / needs-based utility AI (Zubek; GameAIPro, ch.9 Utility Theory) +
life patterns from agent-based social simulations (Maslow need hierarchy, evolving over time):
each need = number 0..1 ("how much I WANT"), grows naturally over time, is satisfied at places that
"advertise" it (see places.py). A trait amplifies its need (greedy wants money more urgently).

Key functions
   -----------
   Need(...) -> Need : Core dataclass representing one NPC need with growth rate and trait boosting.
   fresh() -> dict : Initialize need levels (0..1) for a new NPC; returns base values.
   pressure(needs, traits) -> dict : Compute effective need pressure with trait boosting.
   advance(needs, minutes, sated) -> dict : Evolve needs over time; sated places reduce them.
   NEEDS : list[Need] : Catalog of 7 game needs with growth rates and trait associations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Need:
    """One need. grow — natural growth of want per hour; trait — trait that amplifies the need;
    start — base level at NPC birth."""
    id: str
    ru: str
    grow: float
    trait: str | None = None
    start: float = 0.2
    desc: str = ""


# ── NEEDS CATALOG (edit here; same 7 ids as in mind.NpcState.needs) ──
NEEDS: list[Need] = [
    Need("hunger",  "голод",     grow=0.055, desc="поесть — трактир, очаг, рынок"),
    Need("fatigue", "усталость", grow=0.045, desc="выспаться — дом, ночлег"),
    Need("social",  "общение",   grow=0.035, trait="sociability", desc="к людям — трактир, площадь"),
    Need("wealth",  "нужда",     grow=0.020, trait="greed",       desc="заработать — работа, промысел"),
    Need("purpose", "смысл",     grow=0.022, trait="ambition",    desc="дело/служение — работа, храм, дозор"),
    Need("comfort", "уют",       grow=0.030, desc="тепло/покой — дом, баня, эль"),
    Need("novelty", "новизна",   grow=0.025, trait="curiosity",   desc="ново — улица, рынок, промысел"),
]

NEED: dict[str, Need] = {n.id: n for n in NEEDS}


def fresh() -> dict:
    """Startup need vector for a new NPC."""
    return {n.id: n.start for n in NEEDS}


def pressure(needs: dict, traits: dict | None = None) -> dict:
    """Pressure of each need = level × trait amplification (greedy tug harder toward money).
    Trait 0.5 is neutral; 1.0 → ×1.5; 0.0 → ×0.5."""
    traits = traits or {}
    out = {}
    for n in NEEDS:
        lvl = needs.get(n.id, n.start)
        amp = 1.0 + (traits.get(n.trait, 0.5) - 0.5) if n.trait else 1.0
        out[n.id] = max(0.0, lvl * amp)
    return out


def advance(needs: dict, minutes: float, sated: dict | None = None) -> dict:
    """Evolve needs over `minutes`. A place where an NPC stands SATISFIES its advertised needs (sated:
    {need: rate/hour}); others grow naturally. Mutates and returns needs."""
    hours = max(0.0, minutes) / 60.0
    sated = sated or {}
    for n in NEEDS:
        cur = needs.get(n.id, n.start)
        rate = sated.get(n.id)
        cur += (-rate if rate else n.grow) * hours
        needs[n.id] = min(1.0, max(0.0, cur))
    return needs
