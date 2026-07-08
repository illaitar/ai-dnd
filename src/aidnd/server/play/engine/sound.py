"""Sound & audibility — pure logic over plain dicts (no server/DB, tested standalone).

Distance is spatial: each zone carries a centroid (cx, cy) from the floorplan;
a sound is heard at a fidelity tier that falls off with centroid distance
(docs/sound-attention.md, Pillar 1). Same shape as convo.py.

Key functions
-------------
audibility(listener_zone, source_zone, loudness, boost=0) -> "L1"|"L2"|"L3"|None
    Fidelity tier of a sound of given loudness for a listener, by centroid distance.
"""

import math

from .core import PB

_TIERS = ("L1", "L2", "L3")


def _dist(a: dict, b: dict) -> float | None:
    """Euclidean distance between zone centroids; None if either is unplaced."""
    if a.get("id") == b.get("id"):
        return 0.0
    if "cx" not in a or "cx" not in b:
        return None
    return math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])


def audibility(listener_zone: dict, source_zone: dict, loudness: float,
               boost: int = 0) -> str | None:
    """Fidelity tier of `loudness` heard from source_zone at listener_zone.

    heard = loudness − sound_k · distance; thresholds t1>t2>t3 pick the tier.
    boost lifts the result by N tiers (the player `listen` primitive). Unplaced
    zone (no centroid) or too-faint → None (inaudible)."""
    d = _dist(listener_zone, source_zone)
    if d is None:
        return None
    heard = loudness - PB["sound_k"] * d
    if heard >= PB["sound_t1"]:
        idx = 0
    elif heard >= PB["sound_t2"]:
        idx = 1
    elif heard >= PB["sound_t3"]:
        idx = 2
    else:
        return None
    return _TIERS[max(0, idx - max(0, boost))]
