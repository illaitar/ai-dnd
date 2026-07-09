"""Travel domain (/map /move /enter /exit /room /sign_ack /live) — world.py refactoring. Backbone: graph routing, interrupts.

Key functions
-------------
game_map() -> dict : Returns map SVG, geometry, and player location for UI rendering.
move(request) -> dict : Handle player movement; check path interrupts (signs/events).
enter(request) -> dict : Enter a building; blocks map, starts interior scene.
go_room(request) -> dict : Navigate rooms; gate checks (staff/lock/stealth).
exit_building(request) -> dict : Exit building; return to street view.
live(request) -> dict : Wait action; pass turn to world (NPC tick, time advance).
play_plan() -> dict : Get paper floor plan with NPC positions and zone fog.
play_zone(request) -> dict : Move player to zone within building.
"""

from __future__ import annotations

import random

from fastapi import Request

from aidnd.citygraph.model import NodeKind
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    PLAYER,
    _binfo,
    _city_name,
    _gt,
    _gt_add,
    _here,
    _mark_seen,
    _mt,
    _pc_hp,
    _pc_remember,
    _seen,
    _store,
    _tokens_ru,
    _wid,
    router,
)
from aidnd.server.play.engine.world import (
    _apply_routine,
    _building_rooms,
    _play,
    _scene_dict,
    _world_tick,
)
from aidnd.server.play.mechanics.contracts import _contract_on_move
from aidnd.server.play.mechanics.items import _pc_coins


def _path_interrupt(route_nodes, cr2b, crof, people, to):
    """First obstacle on route (except start/end): sign for unknown key building
    or natural event (NPC with high emotion/agenda). None — path clear."""
    for n in route_nodes[1:]:
        if n == to:
            break
        bid = cr2b.get(n)
        if (
            bid
            and bid.startswith("key:")
            and bid not in _seen()
            and not _store().flag_get(_wid(), f"signskip|{bid}")
        ):
            return {"stop": n, "kind": "sign", "bid": bid, "name": _binfo(bid)["name"]}
        hot = next(
            (
                people[pid]
                for pid in _here(n, crof)
                if max(
                    people[pid].state.emotion.get("anger", 0),
                    people[pid].state.emotion.get("fear", 0),
                )
                >= PB["path_event_dc"]
            ),
            None,
        )
        if hot:
            return {
                "stop": n,
                "kind": "event",
                "text": f"На полпути — {hot.name}: что-то стряслось, стоит вмешаться или пройти мимо.",
            }
    return None


@router.get("/api/play/map")
def game_map():
    city, people, crof, cr2b, loc = _play()
    g = _S["geom"]
    pxy = g["_xy"].get(loc, [0, 0])
    return {
        "viewBox": g["viewBox"],
        "svg": g["svg"],
        "h2n": g["h2n"],
        "points": g["points"],
        "keys": [
            k
            for k in g["keys"]  # fog: known + board (pole visible)
            if k["bid"] in _seen() or k["bid"] == "board:plaza"
        ],
        "loc": loc,
        "player": {"x": pxy[0], "y": pxy[1]},
    }


@router.post("/api/play/move")
async def move(request: Request):
    city, people, crof, cr2b, loc = _play()
    to = (await request.json()).get("to")
    try:
        to = int(to)
    except (TypeError, ValueError):
        return {"error": "туда нельзя"}
    if to not in _S["geom"]["_xy"] or city.node_kind(to) not in (
        NodeKind.CROSSROAD,
        NodeKind.POINT,
        NodeKind.GATE,
        NodeKind.BRIDGE,
    ):
        return {"error": "туда нельзя"}
    xy = _S["geom"]["_xy"]
    r = city.route(loc, to)
    route_nodes = list(r.nodes) if r.found else [loc, to]
    stop = _path_interrupt(route_nodes, cr2b, crof, people, to)
    dest = stop["stop"] if stop else to  # path breaks at obstacle
    seg = route_nodes[: route_nodes.index(dest) + 1] if dest in route_nodes else [dest]
    path = [xy[n] for n in seg if n in xy]
    _S["loc"] = dest
    _S["dlg"] = None  # left — conversation interrupted
    _gt_add(PB["step_min"] * max(1, len(seg) - 1))  # travel time: minutes per step taken
    _apply_routine()  # world may shift phases during travel
    ct_done = _contract_on_move(dest)  # visit-contract: reached — fulfilled
    t = _world_tick()  # world gets turn (turn-based) — rebuilds the live scene at `dest` FIRST,
    sc = _scene_dict(city, people, crof, cr2b, dest)  # so scene/ambient reflect the arrival, not the old spot
    extra = {}
    if stop:
        extra["stopped"] = stop["kind"]
        extra["remaining"] = to
        if stop["kind"] == "sign":
            extra["sign"] = {"bid": stop["bid"], "name": stop["name"]}
        else:
            extra["event"] = stop["text"]
    return {
        **sc,
        **t,
        "path": path,
        "moved": sc["location"]["name"],
        "gt": _gt(),
        "contract_done": ct_done,
        "coins": _pc_coins(),
        **extra,
    }


@router.post("/api/play/sign_ack")
async def sign_ack(request: Request):
    """React to sign: record building on map (record) or skip (signskip)."""
    _play()
    b = await request.json()
    bid, record = b.get("bid"), bool(b.get("record"))
    if record:
        _mark_seen(bid)
    else:
        _store().flag_set(_wid(), f"signskip|{bid}")  # don't interrupt on this sign again
    return {"ok": True}


@router.post("/api/play/enter")
async def enter(request: Request):
    """Enter building at current location. Inside — own "look around", map blocked."""
    city, people, crof, cr2b, loc = _play()
    bid = cr2b.get(loc)
    if not bid:
        return {"error": "тут не во что входить"}
    _S["inside"] = bid
    _S["room"] = None
    _S["zone"] = None
    _S["dlg"] = None  # entered — street conversation interrupted
    _gt_add(PB["give_min"])
    _pc_remember(f"вошёл в {_binfo(bid)['name']}", 0.25)
    t = _world_tick()
    return {
        **_scene_dict(city, people, crof, cr2b, loc),
        **t,
        "gt": _gt(),
        "coins": _pc_coins(),
        "hp": _pc_hp(),
        "city": _city_name(),
    }


@router.post("/api/play/room")
async def go_room(request: Request):
    """Move to sub-room of building (or hall, room=null). Gates: public — free;
    staff — by worker trust OR stealth; locked — by key; hidden — already revealed."""
    city, people, crof, cr2b, loc = _play()
    inside = _S.get("inside")
    if not inside:
        return {"error": "ты не внутри здания"}
    want = (await request.json()).get("room")
    out = {"narr": []}
    if not want:  # return to main hall
        _S["room"] = None
    else:
        room = next((r for r in _building_rooms(inside) if r["name"] == want), None)
        if not room:
            return {"error": "такого помещения тут нет"}
        acc = room["access"]
        if acc in ("staff",):  # staff room — worker trust or stealth
            worker = next(
                (people[pid] for pid in _here(loc, crof) if people[pid].work == inside), None
            )
            trust = worker.state.rel(PLAYER)["trust"] if worker else 0.0
            if trust < 0.3:
                roll = random.Random(f"sneakroom|{inside}|{want}|{_mt()}").randint(1, 20)
                total = roll + _PC_CAP.mod("dex")
                dc = PB["steal_dc_base"]
                out["dice"] = {
                    "die": 20,
                    "roll": roll,
                    "mod": _PC_CAP.mod("dex"),
                    "total": total,
                    "dc": dc,
                    "ok": total >= dc,
                    "label": "Скрытность (Dex) — пройти незаметно",
                }
                if total < dc:
                    out["narr"].append(
                        f"«{want}» — не для чужих. На тебя косятся, пришлось отступить."
                    )
                    return {**out, **_scene_dict(city, people, crof, cr2b, loc), "gt": _gt()}
        elif acc == "locked":  # locked — need this building's key
            bd = _store().get_building(_wid(), inside) or {}
            local = _tokens_ru(_binfo(inside)["name"]) | _tokens_ru(want)
            for cnt in bd.get("data", {}).get("containers") or []:
                local |= _tokens_ru(cnt.get("name", ""))  # owner keys apply across their containers
            has_key = any(
                it
                and it["kind"] == "key"
                and any(
                    m["target"] == "special:opens" and (_tokens_ru(m.get("cond", "")) & local)
                    for m in it.get("mods", [])
                )
                for it in (
                    _store().get_item(r["item_id"]) for r in _store().inventory(_wid(), "pc")
                )
            )
            if not has_key:
                out["narr"].append(f"«{want}» заперто — нужен ключ здешнего хозяина.")
                return {**out, **_scene_dict(city, people, crof, cr2b, loc), "gt": _gt()}
        _S["room"] = want
        out["narr"].append(f"Ты проходишь в: {want}.")
    _S["dlg"] = None  # moved to different room — conversation broken
    _gt_add(PB["give_min"])
    t = _world_tick()  # the room lives — NPCs get their turn, sound surfaces (was missing: dead room)
    return {
        **out,
        **_scene_dict(city, people, crof, cr2b, loc),
        **t,
        "narr": (out.get("narr") or []) + (t.get("narr") or []),
        "gt": _gt(),
        "coins": _pc_coins(),
        "hp": _pc_hp(),
    }


@router.post("/api/play/exit")
async def exit_building(request: Request):
    city, people, crof, cr2b, loc = _play()
    _S["inside"] = None
    _S["zone"] = None
    _S["dlg"] = None  # exited — hall conversation interrupted
    _gt_add(PB["give_min"])
    t = _world_tick()
    return {
        **_scene_dict(city, people, crof, cr2b, loc),
        **t,
        "gt": _gt(),
        "coins": _pc_coins(),
        "hp": _pc_hp(),
        "city": _city_name(),
    }


@router.post("/api/play/live")
async def live(request: Request):
    """Wait button: spend time, give world a turn. (No polling — world is turn-based.)"""
    _play()
    t = _world_tick()
    return {**t, "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}


# ─────────────────────────── BUILDING PLAN (paper, docs/locations.md stage C) ──

def _plan_payload() -> dict:
    """Paper plan of current building with people by zones. No zones (not from debug session) → None."""
    from aidnd.server.play.engine.zones import building_zones
    from aidnd.worldgen.floorart import paper_svg
    from aidnd.worldgen.floorplan import plan_location

    city, people, crof, cr2b, loc = _play()
    bid = _S.get("inside")
    if not bid:
        return {"plan": None}
    data, zones = building_zones(bid)
    if not zones:
        return {"plan": None}
    plan = plan_location(data, seed_key=f"{_wid()}|{bid}")
    here = [pid for pid in _here(loc, crof) if pid != PLAYER]
    here.sort(key=lambda i: (people[i].work != bid, i))      # workers at home — first
    more = 0  # no cap — the building map shows everyone present (basic vision is not gated)
    lv = _S.get("live")
    if lv and lv.get("loc") == loc and lv.get("zonemap"):    # live scene = source of truth for positions
        seats = {p: z for p, z in lv["zonemap"].items() if p in here and z}
        for pid in here:                                     # tail outside LLM core — seating
            if pid not in seats:
                seats.update(_zone_seats(people, [pid], zones, f"seats|{_wid()}|{bid}"))
    else:
        seats = _zone_seats(people, here, zones, f"seats|{_wid()}|{bid}")
    npcs = [{"id": pid, "name": people[pid].name, "init": people[pid].name[:1],
             "zone": seats.get(pid),
             "color": f"hsl({(hash(pid) % 360)} 55% 45%)"} for pid in here]
    npcs.append({"id": "pc", "name": _S.get("pc_name") or "ты", "init": "☉",
                 "zone": _S.get("zone"), "color": "#b08a2e", "is_player": True})
    hidden = [z["id"] for z in zones if z.get("lockable")]  # guest rooms: until uncovered — fog
    svg = paper_svg(plan, data, seed_key=f"{_wid()}|{bid}",
                    game={"npcs": npcs, "hidden_zones": hidden, "interactive": True,
                          "more": more})
    znames = {z["id"]: z["name"] for z in zones}
    return {"plan": svg, "zones": znames, "zone": _S.get("zone"), "gt": _gt()}


def _zone_seats(people, here, zones, seed: str) -> dict:
    """NPC seating by zones: post — by role, others — deterministic by capacity.
    (Temp mechanic until step 2 materialization: then zones become world positions.)"""
    rng = random.Random(seed)
    out, load = {}, {z["id"]: 0 for z in zones}
    posts = [z for z in zones if z.get("post")]
    sit = [z for z in zones
           if z.get("group") or z["kind"] in ("bar", "tables", "hearth", "pews", "games")]
    sit = sit or [z for z in zones if not z.get("lockable")] or zones
    for pid in sorted(here):
        role = (people[pid].role or "").lower()
        zp = next((z for z in posts
                   if z.get("post") and (z["post"] in role or role in z["post"])), None)
        if zp and load[zp["id"]] == 0:
            out[pid] = zp["id"]
            load[zp["id"]] += 1
            continue
        cand = [z for z in sit if load[z["id"]] < z.get("cap", 4) and not z.get("lockable")]
        z = rng.choice(cand or sit)
        out[pid] = z["id"]
        load[z["id"]] += 1
    return out


@router.get("/api/play/plan")
async def play_plan():
    """Plan of current building (parchment, people by zones, fog on locked)."""
    return _plan_payload()


@router.post("/api/play/zone")
async def play_zone(request: Request):
    """Approach zone on plan: player position inside building (time from PB)."""
    b = await request.json()
    zid = str(b.get("zid") or "")
    cur = _plan_payload()
    if not cur.get("plan") or zid not in (cur.get("zones") or {}):
        return {"error": "тут такого места нет"}
    line = _zone_go(zid, cur["zones"][zid])       # move first — then tick — then fresh plan
    t = _world_tick()                             # walking to a table lives: NPCs speak, sound surfaces
    return {**_plan_payload(), **t, "narr": [line, *(t.get("narr") or [])],
            "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}


def _zone_go(zid: str, zname: str) -> str:
    """Move player to zone: position + live scene (body and events) + time + memory."""
    _S["zone"] = zid
    lv = _S.get("live")
    if lv is not None:                          # scene sees stranger's movement
        lv.setdefault("zonemap", {})[PLAYER] = zid
        lv["last"][PLAYER] = f"перешёл — {zname}"
        body = lv["world"].bodies.get(PLAYER)
        znm_place = (lv.get("zone_names") or {}).get(zid)
        if body is not None and znm_place and znm_place in lv["world"].places:
            body.place = znm_place              # player body in scene world (wave 2: zones=places)
    _gt_add(PB["step_min"])
    _pc_remember(f"подошёл: {zname}", 0.1)
    return f"Ты подходишь — {zname}."
