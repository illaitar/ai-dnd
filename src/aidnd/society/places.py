"""Places-as-need-satisfiers — DECLARATIVE, MODULAR catalog. Adding a place type that
satisfies a need = adding one PlaceKind to PLACES.

A place "advertises" needs (advertised actions, The Sims): sates = {need: satiation rate/hour}.
Where an NPC goes = utility: time-of-day window × character-driven pull × Σ(advertisement × need pressure).
`detect` links the CATALOG with real-world buildings: by type/services from fact-sheet we determine which
place-kinds a building implements (and thus which needs it satisfies). Single source of truth for both
routine (where to go) and scene (which needs to satisfy, standing here).

Key functions
-------------
PlaceKind : dataclass for place type with need rates, time window, and trait affinity weights.
kinds_of(building: dict) -> list[str] : detect which place-kinds a building implements.
advertises(building: dict) -> dict : aggregate need satiation this building offers.
affinity(kind: str, traits: dict) -> float : compute NPC attraction to place type.
score(kind: str, pressured: dict, traits: dict, phase: str, ...) -> float : compute visit utility.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PHASES = ("morning", "day", "evening", "night")


@dataclass(frozen=True)
class PlaceKind:
    """Place type. sates — which needs and satiation rate; window — suitability by time-of-day phase;
    likes — character-driven pull (trait→weight, applied as 1+Σ weight·(trait−0.5)); detect — words
    in building type/services that mark this place; gate — who considers this at all (any|job|guard|
    rogue); mobile — place not tied to a building (street/patrol/prowl — a point on the graph)."""
    id: str
    ru: str
    sates: dict = field(default_factory=dict)
    window: dict = field(default_factory=dict)
    likes: dict = field(default_factory=dict)
    detect: tuple = ()
    gate: str = "any"
    mobile: bool = False


# ── PLACE CATALOG (edit here) ──
PLACES: list[PlaceKind] = [
    PlaceKind("home", "дом", sates={"fatigue": 0.16, "comfort": 0.07},
              window={"morning": 0.5, "day": 0.25, "evening": 0.75, "night": 1.0},
              likes={"sociability": -0.8}),                 # introvert drawn home
    PlaceKind("work", "работа", sates={"wealth": 0.13, "purpose": 0.08},
              window={"morning": 1.0, "day": 1.0, "evening": 0.2, "night": 0.03},
              likes={"ambition": 0.6, "lawful": 0.4}, gate="job"),
    PlaceKind("appointment", "встреча по уговору",
              sates={"purpose": 0.3, "social": 0.15},
              window={"morning": 1.0, "day": 1.0, "evening": 1.0, "night": 1.0},
              likes={"honesty": 0.8, "loyalty": 0.6}),
    PlaceKind("tavern", "трактир", sates={"hunger": 0.17, "social": 0.15, "comfort": 0.09},
              window={"morning": 0.1, "day": 0.4, "evening": 1.0, "night": 0.15},
              likes={"sociability": 1.0},
              detect=("трактир", "таверн", "постоял", "кабак", "eat", "drink", "lodging")),
    PlaceKind("temple", "храм", sates={"purpose": 0.13, "comfort": 0.05},
              window={"morning": 0.8, "day": 0.45, "evening": 0.5, "night": 0.05},
              likes={"loyalty": 0.7, "honesty": 0.5, "malice": -0.6},
              detect=("храм", "часовн", "свят", "алтар", "pray")),
    PlaceKind("market", "рынок", sates={"novelty": 0.11, "social": 0.06, "wealth": 0.03},
              window={"morning": 0.4, "day": 1.0, "evening": 0.25, "night": 0.03},
              likes={"curiosity": 0.8},
              detect=("лавк", "рынок", "склад", "оружейн", "кузн", "мастерск", "trade")),
    PlaceKind("street", "улица", sates={"novelty": 0.08, "social": 0.05},
              window={"morning": 0.45, "day": 0.7, "evening": 0.4, "night": 0.05},
              likes={"curiosity": 0.6}, mobile=True),
    PlaceKind("patrol", "дозор", sates={"purpose": 0.14, "wealth": 0.04},
              window={"morning": 0.7, "day": 1.0, "evening": 0.9, "night": 0.55},
              likes={"lawful": 0.6, "bravery": 0.4}, gate="guard", mobile=True),
    PlaceKind("prowl", "промысел", sates={"wealth": 0.13, "novelty": 0.08},
              window={"morning": 0.3, "day": 0.5, "evening": 0.85, "night": 1.0},
              likes={"greed": 0.7, "malice": 0.6, "honesty": -0.7}, gate="rogue", mobile=True),
]

PLACE: dict[str, PlaceKind] = {p.id: p for p in PLACES}


def _blob(building: dict) -> str:
    """String for detect matching: type + name + services from building fact-sheet."""
    d = building or {}
    return " ".join([str(d.get("type", "")), str(d.get("name", "")),
                     " ".join(d.get("services") or [])]).lower()


def kinds_of(building: dict) -> list[str]:
    """Which place-kinds a building implements (by detect). Empty → satisfies no specific needs."""
    blob = _blob(building)
    return [p.id for p in PLACES if p.detect and any(k in blob for k in p.detect)]


def advertises(building: dict) -> dict:
    """What a building satisfies: union of sates across all place-kinds it implements (max per need).
    SINGLE SOURCE for routine and scene (replaces hardcoded _live_affordances)."""
    out: dict = {}
    for kid in kinds_of(building):
        for need, rate in PLACE[kid].sates.items():
            out[need] = max(out.get(need, 0.0), rate)
    return out


def affinity(kind: str, traits: dict) -> float:
    """NPC pull to a place by character: 1 + Σ weight·(trait−0.5), not below 0.1."""
    pk = PLACE[kind]
    return max(0.1, 1.0 + sum(w * (traits.get(t, 0.5) - 0.5) for t, w in pk.likes.items()))


def score(kind: str, pressured: dict, traits: dict, phase: str,
          window_kind: str | None = None) -> float:
    """Utility = time-of-day window × character pull × Σ(advertisement × pressure).
    window_kind: window taken from DIFFERENT type (tavern worker — from tavern window)."""
    pk = PLACE[kind]
    wk = PLACE.get(window_kind) if window_kind else None
    pull = sum(rate * pressured.get(need, 0.0) for need, rate in pk.sates.items())
    return (wk or pk).window.get(phase, 0.2) * affinity(kind, traits) * pull
