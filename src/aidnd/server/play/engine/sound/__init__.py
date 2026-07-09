"""Sound & audibility — pure logic over plain dicts (no server/DB, tested standalone).

Distance is spatial: each zone carries a centroid (cx, cy) from the floorplan;
a sound is heard at a fidelity tier that falls off with centroid distance
(docs/sound-attention.md, Pillar 1). Same shape as convo.py.

Key functions
-------------
audibility(listener_zone, source_zone, loudness, boost=0) -> "L1"|"L2"|"L3"|None
    Fidelity tier of a sound of given loudness for a listener, by centroid distance.
cutout(text, seed) -> str
    L2 'part of a conversation' render (word-masking).
overheard_line(text, tier, zone_name, seed) -> (str, float)
    Display text + memory weight for an overheard line at a tier.
load_sound_sources() -> dict
    Authored ambient descriptors, cached.
zone_source(zone) -> dict | None
    Fixed ambient source for a zone.
audible_ambient(zones, listener_zone, occupancy) -> list[str]
    Russian ambient phrases the listener can hear.
room_center(zones) -> dict | None
    Fallback listener position for someone standing at the entrance, spot not chosen yet.
"""

from .ambient import audible_ambient, load_sound_sources, room_center, zone_source
from .audibility import _TIERS, _dist, audibility
from .fidelity import cutout, overheard_line

__all__ = [
    "audibility",
    "_dist",
    "_TIERS",
    "cutout",
    "overheard_line",
    "load_sound_sources",
    "zone_source",
    "audible_ambient",
    "room_center",
]
