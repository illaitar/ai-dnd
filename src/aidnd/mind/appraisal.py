"""Appraisal: turning percepts/traits into emotion deltas and social readings.

Key functions
-------------
load_race_relations : lazily load + cache the race_relations.json sentiment table.
race_sentiment : how race `a` feels about race `b` (self -> mild positive, else table lookup).
impression : pure appraisal — observer traits x another's visible surface + culture + personal
    history -> an Impression (valence, emotion dims, relationship prior, memorable note).
appraise_present : each tick, apply the impression of everyone present — moves emotion, seeds
    a relationship prior once, remembers a strong first read once.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .model import NpcState
from .world import Body

_RACE_RELATIONS: dict | None = None


@dataclass
class Impression:
    """Result of appraising another's visible surface: a snap first (or renewed) read."""
    valence: float                  # overall like/dislike [-1..1]
    emo: dict                       # dims dict, shaped for tick.appraise()
    prior: dict                     # relationship seed {trust, affinity, fear}
    remember: str | None = None     # short Russian memory note, only when the read is strong


def load_race_relations() -> dict:
    """Load the race_relations.json table once and cache it in a module global."""
    global _RACE_RELATIONS
    if _RACE_RELATIONS is None:
        p = os.path.join(os.path.dirname(__file__), "..", "content", "race_relations.json")
        with open(p, encoding="utf-8") as f:
            _RACE_RELATIONS = json.load(f)
    return _RACE_RELATIONS


def _race_rel() -> dict:
    """Module-cached race_relations table for callers (e.g. decide_hybrid) that just need the
    sentiment table without threading it through their own state."""
    return load_race_relations()


def race_sentiment(race_rel: dict, a: str, b: str) -> float:
    """How race `a` feels about race `b`, in [-1..1].

    A race about itself defaults to a mild positive (in-group bias). An authored
    pair returns its table value. An unlisted pair is neutral (0.0).
    """
    if a == b:
        return 0.15
    return float(race_rel.get(a, {}).get(b, 0.0))


def _tier_a(observer: NpcState, other: Body) -> dict:
    """Trait x surface: how the observer's disposition reads the other's visible surface."""
    t = observer.config.traits
    pride = t.get("pride", 0.5)
    sociability = t.get("sociability", 0.5)
    bravery = t.get("bravery", 0.5)
    malice = t.get("malice", 0.5)
    honesty = t.get("honesty", 0.5)
    revulsion = pride * (1 - other.appearance) * other.squalor
    warmth = sociability * other.charisma
    wary = (1 - bravery) * (1.0 if other.armed() else 0.0)
    contempt = malice * (1 - honesty)
    return {"revulsion": revulsion, "warmth": warmth, "wary": wary, "contempt": contempt}


def _tier_b(observer: NpcState, other: Body, race_rel: dict) -> float:
    """Culture: race sentiment, amplified toward hostility (and softened when malice is low)."""
    malice = observer.config.traits.get("malice", 0.5)
    base = race_sentiment(race_rel, observer.config.race, other.race)
    return base * (0.5 + malice)


def _tier_c(observer: NpcState, other: Body, a: dict, cult: float) -> float:
    """Personal: an existing relationship dominates; else fall back to the trait+culture read."""
    ab = a["warmth"] - a["revulsion"] - a["contempt"] + cult
    rel = observer.relationships.get(other.id)
    if rel is not None:
        return 0.7 * rel.get("affinity", 0.0) + 0.3 * ab
    return ab


def _remember(valence: float, other: Body, revulsion: float, cult: float) -> str | None:
    """A short Russian memory note — only for strong reads (|valence| > 0.5)."""
    if valence <= -0.5:
        if revulsion >= abs(cult) and revulsion > 0.3:
            return "замызганный оборванец у очага"
        if cult < -0.3:
            return f"{other.race} — на дух не переношу"
        return "неприятный тип"
    if valence >= 0.5:
        return "родная душа" if cult < 0 else "приятный собеседник"
    return None


def appraise_present(state: NpcState, world, percept, race_rel: dict, skip_seed_id: str | None = None) -> None:
    """Apply the impression of everyone visibly present this tick.

    Every present other moves emotion each tick (a lingering threat/delight stays felt).
    A relationship prior and the memorable note are seeded only ONCE, on first encounter —
    once `state.relationships` holds an entry for `other.id`, later ticks skip both (personal
    history, once formed, is no longer overwritten by a fresh first-glance read).

    `skip_seed_id` (the player, threaded in from the caller — this module is otherwise
    player-agnostic) never gets a relationship/memory auto-seeded from mere co-presence: a
    stranger stays mechanically a stranger until a REAL interaction (talk/deal/combat) earns
    trust. Emotion still updates each tick either way — only the silent relationship-prior /
    memorable-note seeding is skipped for them.
    """
    from .project import _land  # local import: project imports tick → keep it lazy, no load cycle

    clock = getattr(world, "clock", 0)
    for other in percept.present:
        if other.id == state.config.id:
            continue
        imp = impression(state, other, race_rel)
        seed = None
        if other.id not in state.relationships and other.id != skip_seed_id:
            seed = {"prior": imp.prior, "remember": imp.remember, "clock": clock, "once": True}
        # the flat presence read is the payload (a bare Event carries no appearance/armed/charisma →
        # would DESTROY the tier-a/b/c content); _land is the ONE sink for the mutation (§5-U2).
        _land(state, imp.emo, rel={}, source=other.id, seed=seed)


def impression(observer: NpcState, other: Body, race_rel: dict) -> Impression:
    """Appraise `other`'s visible surface through `observer`'s traits + culture + history.

    Personal > culture > personality: an existing relationship dominates the read; absent
    that, culture (race sentiment) and trait-derived surface reads combine.
    """
    a = _tier_a(observer, other)
    cult = _tier_b(observer, other, race_rel)
    valence = max(-1.0, min(1.0, _tier_c(observer, other, a, cult)))
    emo = {"revulsion": a["revulsion"], "harm": a["wary"], "desert": min(0.0, cult),
           "goal_impact": valence, "intent": False}
    prior = {"affinity": valence, "fear": a["wary"], "trust": max(0.0, a["warmth"] - a["wary"])}
    remember = _remember(valence, other, a["revulsion"], cult)
    return Impression(valence=valence, emo=emo, prior=prior, remember=remember)
