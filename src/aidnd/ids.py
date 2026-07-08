"""Identifier convention (00_Index §4).

Single namespace rule: <type>:<name>. id is unique and stable for the entire
lifespan of the world — an entity is born with an id and retains it forever
(needed for event log, KG, and provenance).

Key functions
-------------
slug(text: str) -> str : normalize arbitrary strings to stable slugs for id assembly.
make(prefix: str, name: str) -> str : build id as "prefix:name", validating prefixes.
kind_of(eid: str) -> str : extract entity type prefix from id.
name_of(eid: str) -> str : extract name portion from id.
is_pc(eid: str) -> bool : determine if id belongs to a player character.
is_npc(eid: str) -> bool : determine if id belongs to an NPC.
"""

from __future__ import annotations

import re

# Type prefixes from 00_Index §4.
PREFIXES = {
    "entity",     # generic entity
    "npc",        # non-player character
    "pc",         # player character
    "it",         # item instance
    "tmpl",       # item template (flyweight)
    "srd",        # reference to SRD content (stat block, spell)
    "place",      # location, region, scene
    "building",   # building
    "room",       # room
    "container",  # container (chest, corpse, shop, ground)
    "faction",    # faction
    "quest",      # quest
    "household",  # household
    "item",       # named authored item
    "shop",       # shop (container with pricing policy)
    "district",   # settlement district
    "corpse",     # corpse as container
    "carry",      # character carry inventory
    "wallet",     # wallet
}

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def slug(text: str) -> str:
    """Normalize arbitrary string to stable slug for id."""
    return _SLUG_RE.sub("_", text.strip().lower()).strip("_")


def make(prefix: str, name: str) -> str:
    """Build id as prefix:name."""
    if prefix not in PREFIXES:
        raise ValueError(f"неизвестный префикс id: {prefix!r}")
    return f"{prefix}:{slug(name)}"


def kind_of(eid: str) -> str:
    """Return type prefix from id (part before colon)."""
    return eid.split(":", 1)[0] if ":" in eid else "entity"


def name_of(eid: str) -> str:
    """Return name from id (part after colon)."""
    return eid.split(":", 1)[1] if ":" in eid else eid


def is_pc(eid: str) -> bool:
    return kind_of(eid) == "pc"


def is_npc(eid: str) -> bool:
    return kind_of(eid) == "npc"
