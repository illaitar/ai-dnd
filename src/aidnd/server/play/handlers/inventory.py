"""Домен ПРЕДМЕТЫ (/loot /inspect /inventory /commission /repair /use /give) — распил world.py."""

from __future__ import annotations

import hashlib
import random

from fastapi import Request

from aidnd.items import craft as item_craft
from aidnd.items import inspect as item_inspect
from aidnd.items import repair as item_repair
from aidnd.items import use as item_use
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    _gt,
    _gt_add,
    _in_room,
    _pc_remember,
    _spurns,
    _store,
    _tokens_ru,
    _wid,
    router,
)
from aidnd.server.play.engine.world import _play
from aidnd.server.play.handlers.freeform import _attempt
from aidnd.server.play.mechanics.items import (
    _CRAFT,
    _cont_holder,
    _forge,
    _item_card,
    _known,
    _npc_cap,
    _pc_coins,
    _pc_key_for,
)


@router.post("/api/play/loot")
async def loot(request: Request):
    _city, _people, _crof, cr2b, loc = _play()
    name = (await request.json()).get("container")
    bid = _S.get("inside")  # ёмкости — только ВНУТРИ здания
    if not bid:
        return {"error": "сначала войди внутрь"}
    bd = _store().get_building(_wid(), bid)
    full = next(
        (x for x in ((bd or {}).get("data", {}).get("containers") or []) if x["name"] == name), None
    )
    if not full:
        return {"error": "нет такой ёмкости"}
    rooms = (bd or {}).get("data", {}).get("sub_rooms") or []
    if not _in_room(full.get("where", ""), _S.get("room"), rooms):  # ёмкость в другом помещении
        holder_room = next(
            (r["name"] for r in rooms if _tokens_ru(r["name"]) & _tokens_ru(full.get("where", ""))),
            None,
        )
        return {
            "error": f"отсюда не дотянуться — она в «{holder_room}»"
            if holder_room
            else "отсюда не дотянуться — она в другом помещении"
        }
    unlocked = None
    if full.get("access") == "locked":
        key = _pc_key_for(name)
        if not key:
            return {"error": "заперто — нужен ключ"}
        unlocked = key["name"]
    holder = _cont_holder(bid, name)
    if not _store().flag_get(_wid(), f"seeded|{holder}"):
        for i, s in enumerate(full.get("contents") or []):  # первое касание: содержимое → ёмкость
            it = _forge(f"{_wid()}|{bid}|{name}|{i}", "misc", s, f"{name} ({full['kind']})")
            _store().inv_add(_wid(), it["id"], holder=holder)
        _store().flag_set(_wid(), f"seeded|{holder}")
    rows = _store().inventory(_wid(), holder)
    _gt_add(PB["loot_min"])
    if not rows:
        return {"container": name, "items": [], "empty": True, "unlocked": unlocked, "gt": _gt()}
    out = []
    for r in rows:  # обшарить = забрать всё (перенос, не копия)
        it = _store().get_item(r["item_id"])
        if it:
            _store().inv_move(_wid(), it["id"], "pc")
            out.append(_item_card(it, set(r["known"])))
    _pc_remember(
        f"обшарил «{name}» в «{(bd or {}).get('sign') or 'здании'}»: "
        + ", ".join(i["name"] for i in out),
        0.3,
    )
    return {"container": name, "items": out, "unlocked": unlocked, "gt": _gt()}


@router.post("/api/play/inspect")
async def inspect_item(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    iid, via, npc = b.get("item"), b.get("via", "appraise"), b.get("npc")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    known = next(
        (set(r["known"]) for r in _store().inventory(_wid()) if r["item_id"] == iid), set()
    )
    if npc and via == "expert" and npc in people:
        cap, observer, by = _npc_cap(people[npc]), npc, people[npc].name
    else:
        cap, observer, by = _PC_CAP, "pc", "ты"
    res = item_inspect(it, cap, via, observer=observer, known=known)
    known |= {h["prop"] for h in res["revealed"]}
    _store().inv_set_known(_wid(), iid, known)
    return {
        "item": _item_card(it, known),
        "via": via,
        "by": by,
        "revealed": [h["fact"] for h in res["revealed"] if h.get("fact")],
        "hints": res["hints"],
    }


@router.get("/api/play/inventory")
def inventory():
    _play()
    out = []
    for r in _store().inventory(_wid()):
        it = _store().get_item(r["item_id"])
        if it:
            out.append(_item_card(it, set(r["known"])))
    return {"items": out}


@router.post("/api/play/commission")
async def commission(request: Request):
    """Заказать вещь у NPC-ремесленника: его МАСТЕРСТВО решает исход (качество/клеймо/брак/прочность)."""
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    rec = _CRAFT.get(p.role)
    if not rec:
        return {"error": f"{p.name} не берётся за ремесло"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}

    n = len(_store().inventory(_wid()))
    rep = random.Random(f"skill|{npc}").randint(
        -1, 3
    )  # у каждого мастера своя рука (мир разнороден)
    it = item_craft(
        _npc_cap(p),
        rec,
        seed=f"{npc}|{rec.name}|{n}",
        maker={"id": npc, "name": p.name},
        reputation=rep,
    )
    it["id"] = "it:" + hashlib.md5(f"comm|{npc}|{n}".encode()).hexdigest()[:10]
    _store().save_item(it)
    _store().inv_add(_wid(), it["id"])
    return {"item": _item_card(it, set()), "maker": p.name, "recipe": rec.name}


@router.post("/api/play/repair")
async def repair_item(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    iid, npc = b.get("item"), b.get("npc")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    p = people.get(npc)
    if not p or p.role not in _CRAFT:
        return {"error": "он не мастер"}
    if not it.get("durability"):
        return {"error": "чинить нечего"}
    res = item_repair(it, _npc_cap(p), seed=f"rep|{iid}|{npc}", station=_CRAFT[p.role].station)
    if not res.get("ok"):
        return {"error": res.get("reason", "не чинится")}
    _store().save_item(it)
    return {"item": _item_card(it, _known(iid)), "note": res.get("note"), "by": p.name}


@router.post("/api/play/use")
async def use_item(request: Request):
    _play()
    iid = (await request.json()).get("item")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    if not it.get("durability"):
        return {"error": "нечего испытывать"}
    ev = item_use(it, 1)
    _store().save_item(it)
    return {"item": _item_card(it, _known(iid)), "event": ev}


@router.post("/api/play/give")
async def give_item(request: Request):
    """Отдать вещь собеседнику (дар или исполнение уговора) — через единый резолвер."""
    _play()
    b = await request.json()
    res = _attempt({"verb": "give", "npc": b.get("npc"), "item": b.get("item")}, {})
    return {**res, "gt": _gt(), "coins": _pc_coins()}
