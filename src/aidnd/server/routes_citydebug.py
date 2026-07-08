"""City debug graph: page + API. Access only by owner (via email).

External code sees only aidnd.citygraph (City/CityParams) — generation details don't flow here.
Cities are deterministic by parameters, so we maintain a small process cache to prevent
route requests from rebuilding the city from scratch.

Key functions
-------------
citydebug_page() -> HTMLResponse : Serve the city debug visualization page.
citydebug_generate() -> dict : Generate city debug data with configurable parameters.
citydebug_route() -> dict : Compute pathfinding route between two city nodes.
citydebug_location() -> dict : Get location card with exits, landmarks, and nearby
    buildings.
citydebug_building() -> dict : Get building details, enrichment data, and graph facts.
citydebug_citysvg() -> dict : Render city as SVG (same visual as in-game map).
citydebug_pool() -> dict : Browse building pool from worlds.db (zone furnishing).
citydebug_dungeonart() -> dict : Generate dungeon by seed/environment and return SVG.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from ..citygraph import CityParams, generate
from ..citygraph.generate import _citygen
from ..worldgen import LLMEnricher, WorldStore, building_ctx
from .models import User
from .routes_auth import CurrentUser

router = APIRouter(tags=["citydebug"])
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_ALLOWED = {"kleit@yandex.ru"}
_CACHE: dict[tuple, object] = {}
_MODEL = None
_STORE = None


def _model():
    global _MODEL
    if _MODEL is None:
        from ..inference import ModelManager
        _MODEL = ModelManager()
    return _MODEL


def _store() -> WorldStore:
    global _STORE
    if _STORE is None:
        _STORE = WorldStore()
    return _STORE


if os.environ.get("AIDND_OPEN_PLAY"):                    # dev mode: bench without login (like /play)
    def _gate() -> User | None:
        return None
else:
    def _gate(user: CurrentUser) -> User | None:
        if user.email not in _ALLOWED:
            raise HTTPException(403, "дебаг-граф доступен только владельцу")
        return user


Owner = Annotated[User | None, Depends(_gate)]


def _city(seed: int, key_buildings: int, river: bool, walls: bool, segment):
    seg = None if segment in (None, "", 0, 0.0) else round(float(segment), 2)
    key = (int(seed), int(key_buildings), bool(river), bool(walls), seg)
    city = _CACHE.get(key)
    if city is None:
        if len(_CACHE) > 24:
            _CACHE.clear()
        city = generate(CityParams(seed=key[0], key_buildings=key[1],
                                   river=key[2], walls=key[3], segment=key[4]))
        _CACHE[key] = city
    return city


@router.get("/citydebug")
def citydebug_page(_: Owner) -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "citydebug.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@router.get("/api/citydebug/generate")
def citydebug_generate(_: Owner, seed: int = 7, key_buildings: int = 8,
                       river: bool = True, walls: bool = True,
                       segment: float | None = None) -> dict:
    return _city(seed, key_buildings, river, walls, segment).debug_data()


def _parse(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


@router.get("/api/citydebug/route")
def citydebug_route(_: Owner, a: str, b: str, seed: int = 7, key_buildings: int = 8,
                    river: bool = True, walls: bool = True,
                    segment: float | None = None) -> dict:
    r = _city(seed, key_buildings, river, walls, segment).route(_parse(a), _parse(b))
    return {"found": r.found, "nodes": r.nodes, "length": round(r.length, 1),
            "crossroads": r.crossroads, "bearing": r.bearing, "landmarks": r.landmarks,
            "near_target": ({"id": r.near_target.id, "name": r.near_target.name,
                             "dist": r.near_target.dist} if r.near_target else None),
            "steps": [{"frm": s.frm, "to": s.to, "kind": s.kind, "heading": s.heading,
                       "name": s.name} for s in r.steps],
            "signs": [{"building": s.building, "name": s.name} for s in r.signs]}


@router.get("/api/citydebug/node")
def citydebug_node(_: Owner, node: int, seed: int = 7, key_buildings: int = 8,
                   river: bool = True, walls: bool = True,
                   segment: float | None = None) -> dict:
    """Legal transitions from a node (entrance/exit/road with heading) — "where can I go from here"."""
    city = _city(seed, key_buildings, river, walls, segment)
    return {"node": node, "kind": str(city.node_kind(node) or ""),
            "moves": [{"to": m.to, "kind": m.kind, "heading": m.heading, "name": m.name}
                      for m in city.exits(node)]}


@router.get("/api/citydebug/location")
def citydebug_location(_: Owner, node: int, seed: int = 7, key_buildings: int = 8,
                       river: bool = True, walls: bool = True,
                       segment: float | None = None) -> dict:
    """Location card: node name/type + legal exits + nearby buildings + landmarks."""
    city = _city(seed, key_buildings, river, walls, segment)
    if node not in city._xy:                                  # noqa: SLF001 — debug
        return {"node": node, "exists": False}
    x, y = city._xy[node]                                     # noqa: SLF001
    name = next((kb.name for kb in city.key_buildings.values() if node in (kb.node, kb.interior)), None)
    near = sorted(((((kb.x - x) ** 2 + (kb.y - y) ** 2) ** 0.5, kb)
                   for kb in city.key_buildings.values() if kb.interior != node),
                  key=lambda t: t[0])[:5]
    return {"node": node, "exists": True, "kind": str(city.node_kind(node) or ""), "name": name,
            "landmarks": city._landmarks_at(node),           # noqa: SLF001
            "moves": [{"to": m.to, "kind": m.kind, "heading": m.heading, "name": m.name}
                      for m in city.exits(node)],
            "nearby": [{"id": kb.id, "name": kb.name, "dist": round(d, 1)} for d, kb in near]}


@router.get("/api/citydebug/citysvg")
def citydebug_citysvg(_: Owner, seed: int = 7, key_buildings: int = 8, river: bool = True,
                      walls: bool = True, segment: float | None = None) -> dict:
    """Actual city visuals (same as in-game map) — SVG render from generator."""
    p = CityParams(seed=seed, key_buildings=key_buildings, river=river, walls=walls).normalized()
    cg = _citygen()
    m = cg.build_city(p.seed, p.width, p.height, buildings=[], key_houses=[])
    return {"svg": cg.render_svg(m, chrome=True, marks=False, interactive=False)}


@router.get("/api/citydebug/building")
def citydebug_building(_: Owner, bid: str, seed: int = 7, key_buildings: int = 8, river: bool = True,
                       walls: bool = True, segment: float | None = None) -> dict:
    """Building (any — ALL structures are houses; key ones just have a sign): graph facts + factsheet of characteristics.
    First from world DB (if params matched), else lazy generation (cache on city)."""
    city = _city(seed, key_buildings, river, walls, segment)
    is_key = bid in city.key_buildings
    if is_key:
        idx, node, sign = list(city.key_buildings).index(bid), city.key_buildings[bid].node, city.key_buildings[bid].name
    elif bid in city.houses:
        idx, node, sign = 0, city.houses[bid].node, None
    else:
        return {"error": "нет такого здания"}
    data = None
    wid = _store().find_world(seed, key_buildings, river, walls, segment)
    if wid:
        row = _store().get_building(wid, bid)
        if row:
            data, sign = row["data"], row["sign"]
    if data is None:                                         # not in DB — generate lazily (cache on city)
        cache = city.__dict__.setdefault("_enrich", {})
        if bid not in cache:
            enr = LLMEnricher(_model())            # LLM only — no fallbacks
            cache[bid] = enr.describe_building(building_ctx(city, bid, is_key, idx)) or {}
        data = cache[bid]
    landmarks = city._landmarks_at(node) if node in city._xy else []   # noqa: SLF001
    return {"id": bid, "is_key": is_key, "node": node, "kind": str(city.node_kind(node) or ""),
            "world": wid, "sign": sign, "landmarks": landmarks, "data": data,
            "exits": [{"kind": mv.kind, "heading": mv.heading, "name": mv.name} for mv in city.exits(node)]}


@router.get("/api/citydebug/pool")
def citydebug_pool(_: Owner, kind: str = "key", furnished: bool = True) -> dict:
    """Building POOL browser (worlds.db): list for debugging zone furnishing (docs/locations.md step 1)."""
    rows = _store().pool_buildings(kind)
    out = []
    for r in rows:
        zs = r["data"].get("zones") or []
        if furnished and not zs:
            continue
        out.append({"id": r["id"], "btype": r["btype"], "name": r["data"].get("name") or r["btype"],
                    "zones": len(zs), "objects": sum(len(z.get("objects") or []) for z in zs)})
    return {"total": len(rows), "furnished": out}


@router.get("/citydebug/plans")
def citydebug_plans_page(_: Owner) -> HTMLResponse:
    """Gallery of paper floor plans of all furnished pool buildings — taste test of render."""
    with open(os.path.join(WEB_DIR, "plansdebug.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@router.get("/citydebug/dungeons")
def citydebug_dungeons_page(_: Owner) -> HTMLResponse:
    """Gallery of dungeon skeletons — test bench for cyclic generation (stage A)."""
    with open(os.path.join(WEB_DIR, "dungeonsdebug.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@router.get("/api/citydebug/dungeonart")
def citydebug_dungeonart(_: Owner, seed: str, env: str = "Ruin") -> dict:
    """Dungeon by seed: skeleton + interior + brief from pool (deterministic, no LLM at runtime)."""
    import random as _random

    from ..worldgen.dungeongen import dungeon_svg, generate
    briefs = [r["data"] for r in _store().pool_buildings("dungeon") if r["btype"] == env]
    brief = (_random.Random(f"pickbrief|{seed}").choice(briefs)) if briefs else None
    d = generate(seed, env=env, cr=1.5, brief=brief)
    return {"seed": seed, "metrics": d["metrics"], "name": d.get("name"),
            "floors": d.get("floors", 1), "dtype": d.get("dtype_name"),
            "locks": sum(1 for e in d["edges"] if e["kind"] == "locked"),
            "secrets": sum(1 for e in d["edges"] if e["kind"] == "secret"),
            "svg": "".join(dungeon_svg(d, f"Подземелье «{seed}»", floor=f)
                           for f in range(d.get("floors", 1)))}


@router.get("/api/citydebug/planart")
def citydebug_planart(_: Owner, bid: str) -> dict:
    """Paper (parchment) render of pool building floor plan."""
    from ..worldgen.floorart import paper_svg
    from ..worldgen.floorplan import plan_location
    for kind in ("key", "res"):
        for r in _store().pool_buildings(kind):
            if r["id"] == bid and r["data"].get("zones"):
                plan = plan_location(r["data"], seed_key=bid)
                return {"id": bid, "svg": paper_svg(plan, r["data"], seed_key=bid)}
    return {"error": "нет такого здания в пуле (или не обставлено)"}


@router.get("/api/citydebug/poolbuilding")
def citydebug_poolbuilding(_: Owner, bid: str) -> dict:
    """Complete factsheet of pool building — with zones, furnishing objects, and floor plan SVG."""
    from ..worldgen.floorplan import plan_location, plan_svg
    for kind in ("key", "res"):
        for r in _store().pool_buildings(kind):
            if r["id"] == bid:
                svg = plan_svg(plan_location(r["data"], seed_key=bid)) if r["data"].get("zones") else None
                return {"id": r["id"], "kind": r["kind"], "btype": r["btype"],
                        "data": r["data"], "plan": svg}
    return {"error": "нет такого здания в пуле"}


@router.get("/api/citydebug/subspace")
def citydebug_subspace(_: Owner, building: str, name: str = "Подвал", seed: int = 7,
                       key_buildings: int = 8, river: bool = True, walls: bool = True,
                       segment: float | None = None) -> dict:
    """Add a sub-building (basement, etc.) to a building/interior; returns updated map data."""
    city = _city(seed, key_buildings, river, walls, segment)
    node = city.add_subspace(_parse(building), name)
    return {"added": node, "data": city.debug_data()}
