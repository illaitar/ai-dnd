"""World assembly: first settlement, pool fill, and the top-level `_play` entry point.

Key functions
-------------
_settle_fresh(city) -> tuple : First settlement of a world — families, homes, jobs, placements.
_fill_from_pool(city, keynode, kps) -> tuple : Populate the crowd from the NPC bank — restore
    stored placements or settle fresh.
_play() -> tuple : Ensure the world exists (generate once) and sync it to current game time.
"""

from __future__ import annotations

import random

from aidnd.citygraph import CityParams, generate, visual
from aidnd.server.play.mechanics.items import _seed_item_pool

from ..session.persist import _pool, _store
from ..session.state import _S, _wid
from .geom import _build_geom
from .jobs import _assign_key_buildings, _plan_jobs
from .person import _person_from_row
from .population import _households, _reclass_note, _restore_placed
from .ties import _weave_locals, _weave_ties


def _settle_fresh(city):
    """First settlement of a world: shuffle the pool, group adults into families (one house each),
    house each dependent with their family head, plan jobs by venue gravity, and place everyone.
    Returns (people, spot) and writes placements so re-entry restores the same people."""
    store = _store()
    rng = random.Random(f"settle|{_wid()}")
    rows = _pool().list_people(limit=100000)
    rng.shuffle(rows)
    houses = sorted({h.node for h in city.houses.values()})  # dedup by node — one family, one house
    rng.shuffle(houses)
    hi = iter(houses)
    adults = [r for r in rows if not (r.get("mech") or {}).get("dependent")]
    deps = [r for r in rows if (r.get("mech") or {}).get("dependent")]  # D2: children/elders
    home_of = {}                                         # D1: a family lives in ONE house
    for hh in _households(adults, rng):                  # split adults into families (by surname)
        home = next(hi, None) or rng.choice(houses)
        for pid in hh:
            home_of[pid] = home
    for r in deps:                                       # D2: dependent → their family head's house
        head = (r.get("mech") or {}).get("head")
        home_of[r["id"]] = home_of.get(head) or (next(hi, None) or rng.choice(houses))
    roles = {r["id"]: r["role"] for r in rows}
    jobs = _plan_jobs(city, home_of, roles)              # venue gravity + reclassification
    people, spot = {}, {}
    for r in rows:
        pid = r["id"]
        home = home_of[pid]
        work, override = jobs.get(pid, (None, None))
        node = (city.key_buildings[work].node if work else home)  # a venue worker stands there
        p = _person_from_row(r, home, work)
        if override:
            _reclass_note(p, p.role)
            p.role = override
        people[pid] = p
        spot[pid] = node
        store.place_person(_wid(), pid, node, home, work)
    return people, spot


def _fill_from_pool(city, keynode, kps):
    """Populate the crowd from the NPC BANK (worldgen.people): if the world was already settled,
    restore stored placements (re-planning jobs, topping up new dependents); otherwise settle it
    fresh. Empty bank = broken data supply → hard error (we never build a world without people)."""
    if _pool().people_count() == 0:
        raise RuntimeError("банк NPC (worlds.db:people) пуст — мир не построить; проверь поставку пулов")
    store = _store()
    placed = {pl["npc_id"]: pl for pl in store.placements_for(_wid())}
    if placed and not all(
        pl["node"] in city._xy and pl["home"] in city._xy  # noqa: SLF001
        for pl in placed.values()
    ):
        store.clear_placements(_wid())  # city graph changed — stale nodes; re-place (memory kept)
        placed = {}
    if placed:
        people, spot = _restore_placed(city, placed)
        if people:
            return people, spot
    return _settle_fresh(city)


def _play():
    if _S["city"] is None:
        params = CityParams(seed=_S["seed"], key_buildings=12, river=True, walls=True, segment=16)
        city = generate(params)
        _assign_key_buildings(city)  # user's world: buildings from POOL, no LLM
        _seed_item_pool()  # world items pool (seed-set, data)
        xy = {n.id: (n.x, n.y) for n in city.nodes()}
        keynode = {
            bid: kb.node for bid, kb in city.key_buildings.items()
        }  # building → NEAREST point (door)
        kps = city.key_points()
        people, spot = _fill_from_pool(city, keynode, kps)  # only bank; empty bank = error
        n2b = {}  # node-point → building (key before homes)
        for bid, kb in city.key_buildings.items():
            n2b.setdefault(kb.node, bid)
        for hid, ho in city.houses.items():  # residential houses also enterable (fact sheet from pool)
            n2b.setdefault(ho.node, hid)
        start_bid = next(
            (p.work for p in people.values() if p.role == "трактирщик" and p.work), None
        )
        start = keynode.get(start_bid) or kps[0]
        if start_bid and not _store().flag_get(_wid(), f"seen|{start_bid}"):
            _store().flag_set(_wid(), f"seen|{start_bid}")  # only the STARTING tavern is pre-known
        _weave_ties(people)  # person ties → real pool people
        _weave_locals(people)  # local-tavern regulars → mild mutual acquaintance
        row = _store().get_pc(_wid()) or {}  # player position SURVIVES restart/deploy
        saved_loc = row.get("loc")
        if saved_loc in xy:
            start = saved_loc
        # cache the geom (the ~1s visual() SVG render) in live.db — deterministic by seed, so a
        # server restart / cold start reads it back instead of re-rendering 5k+ SVG elements.
        # v3: the client never gets the 5k-element SVG — the visual ships as phase PNGs + ID-map.
        import json as _json

        from .mappng import build_map_rasters, map_file

        _wg = _wid()
        _gc = (
            _store().flag_get(_wg, "geom")
            if _store().flag_get(_wg, "geom_seed") == f"{_S['seed']}|v3"
            else None
        )
        if _gc:
            geom = _json.loads(_gc)
            geom["_xy"] = {int(k): v for k, v in geom["_xy"].items()}  # JSON stringified int node-ids
            if map_file(_wg, "day.png") is None:  # raster files lost (fresh checkout) — re-render
                geom["map"] = build_map_rasters(_wg, visual(params), ver=str(_S["seed"]))
                _store().flag_set(_wg, "geom", _json.dumps(geom))
        else:
            vis = visual(params)
            geom = _build_geom(city, xy, n2b, vis)
            geom.pop("svg", None)  # raster world: SVG stays a build-time artifact
            geom["map"] = build_map_rasters(_wg, vis, fresh=True, ver=str(_S["seed"]))
            _store().flag_set(_wg, "geom_seed", f"{_S['seed']}|v3")
            _store().flag_set(_wg, "geom", _json.dumps(geom))
        _S.update(
            city=city,
            people=people,
            crof=spot,
            cr2b=n2b,
            loc=start,
            geom=geom,
            keynode=keynode,
            kps=kps,
        )
        if saved_loc in xy and row.get("inside") in n2b.values():
            _S["inside"], _S["room"] = row["inside"], row.get("room")
            _S["zone"] = row.get("zone")             # and place in hall — also position
    from ..world import _apply_routine
    _apply_routine()  # spots = f(time): daily schedule
    return _S["city"], _S["people"], _S["crof"], _S["cr2b"], _S["loc"]
