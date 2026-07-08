"""Routine: NEEDS + character + time → where to go. Emergent, NO role hardcoding.

One NPC step: (1) needs have evolved over elapsed time, dampening at the place where they stood;
(2) from available places (Candidate), select by utility (places.score); close by score —
draw with seeded rng (live variation, but world reproducibility without player).

Location-agnostic: candidates built by adapter (server/play/worldsim), knowing world buildings. Here —
pure selection logic. No server, no DB.

Key functions
-------------
Candidate : dataclass for available NPC location (kind, node, window_kind).
step(...) -> (node, kind) : advance NPC needs and choose next destination.
choose_c(...) -> Candidate : select best candidate by utility, break ties with seeding.
choose(...) -> int : return node of best candidate (backward-compatible wrapper).
explain(...) -> list : diagnostic scoring of candidates for /minddebug.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import needs as _needs
from . import places as _places


@dataclass
class Candidate:
    """Available NPC location: kind (place-kind) + graph node to go to.
    window_kind — whose time window to apply (tavern worker lives by its evening window)."""
    kind: str
    node: int
    window_kind: str | None = None


def step(state, candidates: list, phase: str, minutes: float, here_kind: str | None, rng,
         stay: int | None = None):
    """Advance NPC needs and return (node, kind-of-activity) for direction.
    state — NpcState (needs in .needs, traits in .config.traits); here_kind — place type where they
    stood (dampening needs); candidates — where they CAN go; stay — node where they stood (inertia)."""
    traits = state.config.traits
    sated = _places.PLACE[here_kind].sates if here_kind in _places.PLACE else {}
    _needs.advance(state.needs, minutes, sated)
    c = choose_c(state.needs, traits, candidates, phase, rng, stay=stay)
    return (c.node, c.kind) if c is not None else (None, None)


def choose_c(needs: dict, traits: dict, candidates: list, phase: str, rng, stay: int | None = None):
    """Select best CANDIDATE by utility (close by score — draw by lot). stay — node where stood: light
    inertia against thrashing between equal places (Sims lesson)."""
    pressured = _needs.pressure(needs, traits)
    scored = sorted(((_places.score(c.kind, pressured, traits, phase,
                                    window_kind=c.window_kind)
                      * (1.12 if stay is not None and c.node == stay else 1.0), c)
                     for c in candidates if c.node is not None),
                    key=lambda x: x[0], reverse=True)
    if not scored:
        return None
    best = scored[0][0]
    close = [c for s, c in scored if s >= best * 0.85] or [scored[0][1]]
    return rng.choice(close) if len(close) > 1 else scored[0][1]


def choose(needs: dict, traits: dict, candidates: list, phase: str, rng, stay: int | None = None):
    """Node of best candidate (backward-compatible wrapper)."""
    c = choose_c(needs, traits, candidates, phase, rng, stay=stay)
    return c.node if c is not None else None


def explain(needs: dict, traits: dict, candidates: list, phase: str) -> list:
    """Diagnostics (for /minddebug and tests): [(kind, score)] descending — why they went there."""
    pressured = _needs.pressure(needs, traits)
    return sorted(((c.kind, round(_places.score(c.kind, pressured, traits, phase), 3))
                   for c in candidates if c.node is not None), key=lambda x: x[1], reverse=True)
