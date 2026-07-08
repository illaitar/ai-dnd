"""MISC domain (/hero /debuglog) — split from world.py. Hero name, downloadable session log.

Key functions
-------------
set_hero(request) -> dict : Set hero name for new world.
debug_log(download, tail) -> Response : Retrieve session debug log (full or tail).
debug_log_clear() -> dict : Clear session debug log.
npc_schedule(npc) -> dict : Get NPC daily schedule from forecast; requires familiarity.
economy_board() -> dict : Show all economy chains and city money supply.
market_board() -> dict : Show goods at current venue; empty if not in shop.
market_buy(request) -> dict : Purchase goods; update supply/price and player coins.
market_sell(request) -> dict : Sell from inventory; update supply/price and coins.
"""

from __future__ import annotations

from fastapi import Request

from aidnd.server.play.engine.core import _pc_name, _pc_save, _pc_set_name, router
from aidnd.server.play.engine.world import _play


@router.post("/api/play/hero")
async def set_hero(request: Request):
    """Set hero name (from landing page) — once per new world; do not overwrite existing name."""
    _play()
    name = (await request.json()).get("name")
    if name and _pc_name() == "Странник":
        _pc_set_name(name)
        _pc_save()
    return {"hero": _pc_name()}


@router.get("/api/play/debuglog")
def debug_log(download: int = 0, tail: int = 0):
    """Detailed session log (all records + full tracebacks). tail=KB — tail only;
    download=1 — as attachment. For debugging from UI."""
    from fastapi.responses import PlainTextResponse

    from aidnd.server.debuglog import read_log

    _play()
    txt = read_log(tail_bytes=(tail * 1024) if tail else None) or "(лог пуст)"
    headers = {"Content-Disposition": 'attachment; filename="play-debug.log"'} if download else {}
    return PlainTextResponse(txt, headers=headers)


@router.post("/api/play/debuglog/clear")
def debug_log_clear():
    """Clear session log (clear button in UI)."""
    from aidnd.server.debuglog import clear_log

    _play()
    clear_log()
    return {"ok": True}


@router.get("/api/play/schedule")
def npc_schedule(npc: str = ""):
    """NPC daily schedule (Bombers' Notebook card): where at each phase — from predict().
    Visible only for familiar (talk); unfamiliar cannot be read (fog of identity)."""
    from aidnd.server.play.engine.core import _S, _met
    from aidnd.server.play.engine.worldsim import forecast, predict
    people = _S.get("people") or {}
    p = people.get(npc)
    if p is None:
        return {"error": "нет такого"}
    if npc not in _met():
        return {"error": "ты его не знаешь — заговори сперва"}
    RU = {"home": "дома", "work": "за работой", "tavern": "в трактире", "temple": "в храме",
          "market": "на рынке", "street": "на улице", "patrol": "в дозоре",
          "prowl": "на промысле", "appointment": "по уговору", "follow": "с тобой", None: "?"}
    fc = forecast(npc)
    return {"npc": npc, "name": p.name, "role": p.role,
            "day": {ph: RU.get(k, k) for ph, k in fc.items()},
            "now": RU.get(predict(npc)["kind"], "?")}


@router.get("/api/play/economy")
def economy_board():
    """Economy dashboard (board/observability): named chains — good/price/stock/
    producers/deficit + city coin M."""
    _play()
    from aidnd.server.play.engine.economy import chains_view, money_supply
    return {"money": money_supply(), "chains": chains_view()}


def _closed_note(bid):
    """If venue closed by hours — return {error: "closed until N"}, else None (open/residence)."""
    from aidnd.server.play.engine.core import _binfo, _gt
    from aidnd.server.play.engine.open_hours import is_open, opens_at
    if not bid:
        return None
    info = _binfo(bid)["kind"] + " " + _binfo(bid)["name"]
    if is_open(info, _gt()):
        return None
    oa = opens_at(info)
    return {"error": f"закрыто{f' — откроется в {oa}:00' if oa is not None else ''}"}


@router.get("/api/play/market")
def market_board():
    """Goods counter HERE (B2): chains whose venue = player building — good/price/stock/
    player inventory qty. Empty if player not in trading venue."""
    _play()
    from aidnd.server.play.engine.core import _S, _binfo, _gt, _store, _wid
    from aidnd.server.play.engine.economy import ensure, market_here
    from aidnd.server.play.engine.open_hours import is_open, opens_at
    ensure()
    bid = _S.get("inside")
    info = (_binfo(bid)["kind"] + " " + _binfo(bid)["name"]) if bid else ""
    return {"goods": market_here(bid), "coins": _store().purse_get(_wid(), "pc"),
            "inside": bool(bid), "open": is_open(info, _gt()), "opens_at": opens_at(info)}


@router.post("/api/play/market/buy")
async def market_buy(request: Request):
    """Buy goods from chain at live price: stock−, price↑, coin pc→producers (M+)."""
    _play()
    from aidnd.server.play.engine.core import _S, _gt, _gt_add
    from aidnd.server.play.engine.economy import player_buy
    b = await request.json()
    closed = _closed_note(_S.get("inside"))
    r = closed or player_buy(_S.get("inside"), b.get("key"), int(b.get("qty", 1)))
    if "error" not in r:
        _gt_add(5)
    return {**r, "gt": _gt()}


@router.post("/api/play/market/sell")
async def market_sell(request: Request):
    """Sell goods from inventory to chain: stock+, price↓, coin producers→pc (M−)."""
    _play()
    from aidnd.server.play.engine.core import _S, _gt, _gt_add
    from aidnd.server.play.engine.economy import player_sell
    b = await request.json()
    closed = _closed_note(_S.get("inside"))
    r = closed or player_sell(_S.get("inside"), b.get("key"), int(b.get("qty", 1)))
    if "error" not in r:
        _gt_add(5)
    return {**r, "gt": _gt()}


@router.get("/api/play/deeds")
def deeds_list(limit: int = 12):
    """World chronicle: latest DEEDS (deeds journal) — raw material for UI chronicle and debug."""
    _play()
    from aidnd.server.play.engine.core import _store, _wid
    return {"deeds": _store().deeds(_wid(), limit=min(int(limit), 50))}


@router.post("/api/play/newworld")
async def new_world():
    """Start a FRESH world from the SAME pools: wipe only this user's runtime (destroy_world) so a
    new city regenerates from the persistent NPC/building/portrait bank in worlds.db. Voluntary
    rebirth — same mechanism as permadeath, minus the death. The frontend reloads to pick up the
    freshly-created world (a new seed → a different town)."""
    _play()
    from aidnd.server.play.engine.core import _SESS, _store, _wid
    wid = _wid()
    if wid == 1:  # dev/open-play shared world: bump the seed so a different town generates
        _store().flag_set(0, "dev_seed", str(int(_store().flag_get(0, "dev_seed") or 1) + 1))
    _store().destroy_world(wid)  # runtime only — worlds.db pools (people/buildings/portraits) untouched
    _SESS.pop(wid, None)         # drop the cached session → next request rebuilds a fresh city from pools
    return {"ok": True, "reload": True}
