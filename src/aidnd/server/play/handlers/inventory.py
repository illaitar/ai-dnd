"""Items domain (/loot /inspect /inventory /commission /repair /use /give) — split from world.py.

Key functions
-------------
loot(request) -> dict : Retrieve items from a container inside buildings.
inspect_item(request) -> dict : Inspect item properties and reveal hidden facts.
inventory() -> dict : Get player inventory with known item properties.
commission(request) -> dict : Commission item crafting from NPC artisans.
repair_item(request) -> dict : Repair durability damage on items.
use_item(request) -> dict : Apply consumable effects or test durability.
give_item(request) -> dict : Gift or trade items to NPCs via unified resolver.
"""

from __future__ import annotations

import random

from fastapi import Request

from aidnd.items import inspect as item_inspect
from aidnd.items import use as item_use
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    _gt,
    _gt_add,
    _in_room,
    _mana,
    _mana_cap,
    _pc_hp,
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
    _ROLE_NODE,
    _apply_consumable,
    _cont_holder,
    _craft_band,
    _forge,
    _item_card,
    _known,
    _npc_cap,
    _pc_coins,
    _pc_key_for,
    _put_graph_item,
)


@router.post("/api/play/loot")
async def loot(request: Request):
    _city, _people, _crof, cr2b, loc = _play()
    name = (await request.json()).get("container")
    bid = _S.get("inside")  # containers - only INSIDE a building
    if not bid:
        return {"error": "сначала войди внутрь"}
    bd = _store().get_building(_wid(), bid)
    full = next(
        (x for x in ((bd or {}).get("data", {}).get("containers") or []) if x["name"] == name), None
    )
    if not full:
        return {"error": "нет такой ёмкости"}
    rooms = (bd or {}).get("data", {}).get("sub_rooms") or []
    if not _in_room(full.get("where", ""), _S.get("room"), rooms):  # container in another room
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
        for i, s in enumerate(full.get("contents") or []):  # first touch: contents → container
            it = _forge(f"{_wid()}|{bid}|{name}|{i}", "misc", s, f"{name} ({full['kind']})")
            _store().inv_add(_wid(), it["id"], holder=holder)
        _store().flag_set(_wid(), f"seeded|{holder}")
    rows = _store().inventory(_wid(), holder)
    _gt_add(PB["loot_min"])
    if not rows:
        return {"container": name, "items": [], "empty": True, "unlocked": unlocked, "gt": _gt()}
    out = []
    for r in rows:  # loot = take all (move, not copy)
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
    known |= {h["prop"] for h in res["revealed"]} | set(res.get("attr_groups", []))
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
    """Commission an item from an NPC artisan: they forge a derivation-graph node; their mastery + a
    roll set the quality (via the same spark ladder as player craft)."""
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    node_id = _ROLE_NODE.get(p.role)
    if not node_id:
        return {"error": f"{p.name} не берётся за ремесло"}
    if _spurns(p):
        return {"error": f"{p.name} не желает иметь с тобой дела"}
    n = len(_store().inventory(_wid()))
    cap = _npc_cap(p)
    roll = random.Random(f"comm|{npc}|{n}").randint(1, 20)
    band = _craft_band(PB["craft_base"] + max(cap.mod("dex"), cap.mod("int")) + roll)
    band = "crude" if band == "waste" else band            # a commission is always delivered (no waste)
    made = _put_graph_item(node_id, band, masterwork=(band == "exquisite"), seed=f"comm|{npc}|{n}")
    return {"item": _item_card(_store().get_item(made), set()), "maker": p.name, "recipe": node_id}


@router.post("/api/play/repair")
async def repair_item(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    iid, npc = b.get("item"), b.get("npc")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    p = people.get(npc)
    if not p or p.role not in _ROLE_NODE:
        return {"error": "он не мастер"}
    if _spurns(p):
        return {"error": f"{p.name} не станет тебе помогать"}
    pr = (it.get("attrs") or {}).get("прочность")
    if pr and pr.get("true", 0) < pr.get("surface", 0):    # a hidden crack → a smith mends it
        pr["true"] = pr["surface"]
        _store().save_item(it)
        return {"item": _item_card(it, _known(iid)), "note": "трещину заделали — как новое", "by": p.name}
    d = it.get("durability")
    if d:                                                  # legacy durability item → restore condition
        d["current"] = d["max"]
        _store().save_item(it)
        return {"item": _item_card(it, _known(iid)), "note": "как новое", "by": p.name}
    return {"error": "чинить нечего"}


@router.post("/api/play/use")
async def use_item(request: Request):
    _play()
    iid = (await request.json()).get("item")
    it = _store().get_item(iid)
    if not it:
        return {"error": "нет предмета"}
    if it.get("kind") == "consumable" or not it.get("durability"):
        fx = _apply_consumable(it)                          # heal / mana from attrs (banded, code-owned)
        _store().inv_move(_wid(), iid, "used")              # drunk/consumed — item is gone
        return {"consumed": True, "name": it["name"], "effects": fx,
                "hp": _pc_hp(), "mana": _mana(), "mana_cap": _mana_cap(), "gt": _gt()}
    ev = item_use(it, 1)
    _store().save_item(it)
    return {"item": _item_card(it, _known(iid)), "event": ev}


@router.post("/api/play/give")
async def give_item(request: Request):
    """Give an item to an interlocutor (gift or fulfillment of a deal) — via unified resolver."""
    _play()
    b = await request.json()
    res = _attempt({"verb": "give", "npc": b.get("npc"), "item": b.get("item")}, {})
    return {**res, "gt": _gt(), "coins": _pc_coins()}
