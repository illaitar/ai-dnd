"""Ambient sound sources — authored fixed sources + crowd murmur.

Key functions
-------------
load_sound_sources() -> dict
    Authored ambient descriptors (cached): {by_object, by_kind} → {loudness, ambient_ru}.
zone_source(zone) -> dict | None
    Fixed ambient source for a zone: matched by a contained object's kind/name,
    else by the zone's own kind. None if the zone emits nothing authored.
audible_ambient(zones, listener_zone, occupancy) -> list[str]
    Russian ambient phrases the listener can hear.
room_center(zones) -> dict | None
    Fallback listener position for 'just arrived, haven't picked a spot yet' (e.g. still at
    the entrance) — the room's average centroid. None if no zone is placed yet.
"""

import json
import os

from ..core import PB
from .audibility import audibility

_SOURCES: dict | None = None


def load_sound_sources() -> dict:
    """Authored ambient descriptors (cached): {by_object, by_kind} → {loudness, ambient_ru}."""
    global _SOURCES
    if _SOURCES is None:
        p = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "content",
                         "sound_sources.json")
        with open(p, encoding="utf-8") as f:
            _SOURCES = json.load(f)
    return _SOURCES


def zone_source(zone: dict) -> dict | None:
    """Fixed ambient source for a zone: matched by a contained object's kind/name,
    else by the zone's own kind. None if the zone emits nothing authored."""
    cat = load_sound_sources()
    for o in zone.get("objects", []):
        hit = cat["by_object"].get(o.get("kind")) or cat["by_object"].get(o.get("name"))
        if hit:
            return hit
    return cat["by_kind"].get(zone.get("kind"))


def room_center(zones: list[dict]) -> dict | None:
    """Fallback listener position for someone standing at the entrance who hasn't picked a
    spot yet: the average centroid of the room's PLACED zones. None if none are placed."""
    placed = [z for z in zones if "cx" in z and "cy" in z]
    if not placed:
        return None
    return {"id": "__room__", "cx": sum(z["cx"] for z in placed) / len(placed),
            "cy": sum(z["cy"] for z in placed) / len(placed)}


def audible_ambient(zones: list[dict], listener_zone: dict,
                    occupancy: dict) -> list[str]:
    """Russian ambient phrases the listener can hear: authored fixed sources that
    carry to the listener + a crowd-murmur phrase for busy zones. Never masked."""
    out: list[str] = []
    total = sum(occupancy.values()) or 1
    for z in zones:
        src = zone_source(z)
        if src and audibility(listener_zone, z, src["loudness"]):
            out.append(src["ambient_ru"])
        murmur = PB["sound_murmur_k"] * (occupancy.get(z["id"], 0) / total) * z.get("noise", 0.0)
        if murmur and audibility(listener_zone, z, murmur):
            out.append("гул голосов")
    return list(dict.fromkeys(out))                     # dedup, keep order
