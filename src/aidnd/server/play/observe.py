"""Домен ОСМОТР (/look) — распил world.py. Восприятие снимает туман; affordances из society-каталога."""

from __future__ import annotations

import random

from fastapi import Request

from .core import _PC_CAP, _S, PB, _gt, _gt_add, _pc_hp, _store, _wid, router
from .items import _pc_coins
from .world import _look_key, _looked_level, _play, _scene_dict


@router.post("/api/play/look")
async def look(request: Request):
    """Осмотреться: бросок d20+Wis против DC — снимает туман (людей/ёмкости различаешь)."""
    city, people, crof, cr2b, loc = _play()
    inside = _S.get("inside")
    key = _look_key(loc, inside)
    n = int(_store().flag_get(_wid(), f"lookn|{key}") or 0) + 1
    _store().flag_set(_wid(), f"lookn|{key}", str(n))
    roll = random.Random(f"look|{key}|{n}").randint(1, 20)
    mod = _PC_CAP.mod("wis")
    total = roll + mod
    lvl = 2 if total >= PB["look_good"] else 1 if total >= PB["look_dc"] else 0
    prev = _looked_level(loc, inside)
    _S.setdefault("looked", {})[key] = max(prev, lvl, 1 if total >= PB["look_dc"] else prev)
    _gt_add(PB["give_min"])
    sc = _scene_dict(city, people, crof, cr2b, loc)
    dice = {"die": 20, "roll": roll, "mod": mod, "total": total, "dc": PB["look_dc"],
            "ok": total >= PB["look_dc"], "label": "Внимательность (Wis)"}
    narr = ("Ты оглядываешься, но взгляд скользит мимо: толком ничего не разобрал." if total < PB["look_dc"]
            else "Ты внимательно оглядываешься по сторонам." if total < PB["look_good"]
            else "От твоего взгляда мало что ускользает.")
    return {**sc, "dice": dice, "narr": [narr], "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}
