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
    from aidnd.server.play.engine.worldsim import forecast, predict, transit_of
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
    _t = transit_of(npc)
    now = _t["kind"] if _t else RU.get(predict(npc)["kind"], "?")   # «в пути» while a transit row is live
    return {"npc": npc, "name": p.name, "role": p.role,
            "day": {ph: RU.get(k, k) for ph, k in fc.items()},
            "now": now}


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


@router.get("/api/play/journal")
def journal_endpoint(limit: int = 500):
    """Player chronicle «Хроника → дела»: quest rows grouped into per-quest first-person threads.
    Returns {dela:[{cid,title,giver,status,thread:[{gt,beat,text}]}]}, дела newest-beat-first,
    each thread oldest-beat-first (reads top-to-bottom as a story). No LLM on the read path."""
    _play()
    from aidnd.server.play.engine.core import _store, _wid
    from aidnd.server.play.engine.journal import purge_legacy_once
    wid = _wid()
    purge_legacy_once(wid)                                    # one-shot legacy compost (guard flag)
    rows = _store().journal_list(wid, kind="quest", limit=min(int(limit), 1000))
    cmap = {c["id"]: c for c in _store().contracts(wid)}      # live contracts across ALL statuses
    groups: dict = {}
    for r in rows:
        cid = (r.get("refs") or [None])[0]
        if cid:
            groups.setdefault(cid, []).append(r)
    _KD = {"bring": "добыть", "deliver": "отнести", "visit": "наведаться",
           "befriend": "расположить к себе", "clear": "зачистить"}
    dela = []
    for cid, thread in groups.items():
        thread.sort(key=lambda r: r["gt"])                   # story order
        c = cmap.get(cid) or {}
        giver = c.get("giver_name") or ""
        kind_ru = _KD.get(c.get("kind"), "дело")
        title = (f"{kind_ru} для {giver}" if giver
                 else (thread[0]["text"][:40] if thread else cid))
        dela.append({
            "cid": cid, "title": title, "giver": giver,
            "status": c.get("status", "unknown"),
            "thread": [{"gt": r["gt"], "beat": r["prov"], "text": r["text"]} for r in thread],
        })
    dela.sort(key=lambda g: g["thread"][-1]["gt"] if g["thread"] else 0, reverse=True)
    return {"dela": dela}


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


@router.post("/api/play/debug/skip")
def debug_skip(hours: float = 0.0, to_phase: str = ""):
    """DEV ONLY (AIDND_OPEN_PLAY): fast-forward game time and repopulate the world, so a scene can be
    observed at a busy hour without playing through it. `hours` — advance by N game-hours; `to_phase`
    — advance to the next morning|day|evening|night. Re-runs the routine so NPCs relocate to the new
    time; the next /scene rebuilds presence. No-op (and refused) outside open-play/dev mode."""
    import os

    from aidnd.server.play.engine.core import _S, _gt, _gt_add, _phase
    from aidnd.server.play.engine.world import _apply_routine
    if not os.environ.get("AIDND_OPEN_PLAY"):
        return {"error": "debug skip доступен только в dev-режиме (AIDND_OPEN_PLAY)"}
    _play()
    if to_phase:
        for _ in range(48):                          # up to 24h in 30-min steps until the phase matches
            if _phase() == to_phase:
                break
            _gt_add(30)
    elif hours:
        _gt_add(int(hours * 60))
    _S["routine_key"] = None                         # force the throttled routine to recompute now
    _apply_routine()
    from aidnd import society
    city, crof = _S.get("city"), _S.get("crof") or {}
    taverns = []
    if city is not None:
        from collections import Counter
        pop = Counter(crof.values())
        for bid, kb in city.key_buildings.items():
            data = (_store_dbg(bid) or {})
            if "tavern" in society.kinds_of(data):
                taverns.append({"building": bid, "node": kb.node, "souls": pop.get(kb.node, 0)})
    return {"ok": True, "gt": _gt(), "phase": _phase(),
            "time": f"{_gt() // 60 % 24:02d}:{_gt() % 60:02d}", "taverns": taverns}


def _store_dbg(bid: str) -> dict:
    """Building data for the current world (debug helper for the skip report)."""
    from aidnd.server.play.engine.core import _store, _wid
    return (_store().get_building(_wid(), bid) or {}).get("data") or {}
