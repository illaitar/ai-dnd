"""OBSERVE domain (/look) — world.py slice. Perception removes fog of war; affordances from society catalog.

Key functions
-------------
look(request: Request) -> dict : Perception roll (d20+Wis) against DC to reveal NPCs and containers.
"""

from __future__ import annotations

import random

from fastapi import Request

from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    _gt,
    _gt_add,
    _pc_hp,
    _store,
    _wid,
    router,
)
from aidnd.server.play.engine.loop.tick import _world_tick_fast
from aidnd.server.play.engine.world import (
    _look_key,
    _looked_level,
    _play,
    _scene_dict,
)
from aidnd.server.play.mechanics.items import _pc_coins


@router.post("/api/play/look")
async def look(request: Request):
    """Look closer: a d20+Wis roll for what's HIDDEN (concealed rooms, stashes, a lurker). Basic
    vision — who is in the room and what they do — is never gated; a keen look only adds the hidden."""
    city, people, crof, cr2b, loc = _play()
    inside = _S.get("inside")
    key = _look_key(loc, inside)
    n = int(_store().flag_get(_wid(), f"lookn|{key}") or 0) + 1
    _store().flag_set(_wid(), f"lookn|{key}", str(n))
    roll = random.Random(f"look|{key}|{n}").randint(1, 20)
    mod = _PC_CAP.mod("wis")
    stay = min(6, ((_S.get("live") or {}).get("clock", 0))
               if (_S.get("live") or {}).get("loc") == loc else 0)   # hour in room = got acclimated
    total = roll + mod + stay
    keen = total >= PB["look_good"]
    _S.setdefault("looked", {})[key] = max(_looked_level(loc, inside), 2 if keen else 1)
    _gt_add(PB["give_min"])
    t = _world_tick_fast()                               # the look lands instantly; the room's beat streams via /live
    sc = _scene_dict(city, people, crof, cr2b, loc)
    dice = {
        "die": 20,
        "roll": roll,
        "mod": mod,
        "total": total,
        "dc": PB["look_good"],
        "ok": keen,
        "label": "Внимательность (Wis)",
    }
    narr = (
        "От твоего взгляда мало что ускользает — примечаешь и то, что хотели скрыть."
        if keen
        else "Ты оглядываешься по сторонам: всё на виду, ничего припрятанного в глаза не бросается."
    )
    return {**sc, **t, "dice": dice, "narr": [narr], "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}
