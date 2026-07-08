"""Society: NPC routine from NEEDS (utility-model, not hardcoded roles). Declarative catalogs —
needs.py (needs) and places.py (place-satisfiers); routine.py — destination choice.

    from aidnd.society import Need, NEEDS, PlaceKind, PLACES, advertises, Candidate, step

Key functions
-------------
Need : represents single need (hunger, fatigue, social, wealth, purpose, comfort, novelty).
NEEDS : list[Need] : all needs in the NPC motivation system.
PlaceKind : dataclass for place type with satisfaction rates and availability windows.
PLACES : list[PlaceKind] : all place types in the world.
advertises(building: dict) -> dict : aggregate needs a building can satisfy.
Candidate : dataclass for NPC destination option (place kind + graph node).
step(state, candidates, ...) -> (node, kind) : advance NPC needs and choose destination.
"""

from __future__ import annotations

from .needs import NEED, NEEDS, Need, advance, fresh, pressure
from .places import PLACE, PLACES, PlaceKind, advertises, affinity, kinds_of, score
from .routine import Candidate, choose, explain, step

__all__ = ["Need", "NEEDS", "NEED", "fresh", "pressure", "advance",
           "PlaceKind", "PLACES", "PLACE", "kinds_of", "advertises", "affinity", "score",
           "Candidate", "step", "choose", "explain"]
