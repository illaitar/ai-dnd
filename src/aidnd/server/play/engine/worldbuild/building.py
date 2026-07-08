"""Building fact-sheet lookups: keys, sub-rooms, containers, and residential info from the pool.

Key functions
-------------
_building_keys(bid) -> list : Keys to unlock LOCKED containers in building (for owner).
_building_rooms(bid) -> list : Building sub-rooms (mini-graph).
_building_containers(bid, room=None) -> list : Containers of CURRENT room (without contents).
_res_binfo(bid) -> dict | None : Residential building fact sheet, deterministic from pool.
"""

from __future__ import annotations

import random

from ..core import _in_room
from ..session.persist import _pool, _store
from ..session.state import _wid


def _building_keys(bid: str) -> list:
    """Keys to unlock LOCKED containers in building (for owner)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    return [
        {"name": c["key"]["name"], "opens": c["name"], "where": c.get("where", "")}
        for c in (bd["data"].get("containers") or [])
        if c.get("access") == "locked" and c.get("key")
    ]


def _building_rooms(bid: str) -> list:
    """Building sub-rooms (mini-graph): name/kind/access/hidden (hidden visible only on keen inspection)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    return [
        {"name": s["name"], "kind": s.get("kind", "backroom"), "access": s.get("access", "public")}
        for s in (bd["data"].get("sub_rooms") or [])
    ]


def _building_containers(bid: str, room: str | None = None) -> list:
    """Containers of CURRENT room (without contents — opened by interaction)."""
    bd = _store().get_building(_wid(), bid)
    if not bd:
        return []
    rooms = bd["data"].get("sub_rooms") or []
    return [
        {
            "name": c["name"],
            "kind": c["kind"],
            "where": c.get("where", ""),
            "locked": c.get("access") == "locked",
        }
        for c in (bd["data"].get("containers") or [])
        if _in_room(c.get("where", ""), room, rooms)
    ]


_RES_POOL = None


def _res_binfo(bid: str) -> dict | None:
    """Residential building: fact sheet deterministic from pool (no DB write — function of (world, building))."""
    global _RES_POOL
    if _RES_POOL is None:
        _RES_POOL = _pool().pool_buildings("res")
    if not _RES_POOL:
        return None
    return random.Random(f"res|{_wid()}|{bid}").choice(_RES_POOL)["data"]
