"""Дебаг-граф города: страница + API. Доступ только для владельца (по email).

Внешний код видит лишь aidnd.citygraph (City/CityParams) — детали генерации сюда не текут.
Города детерминированы по параметрам, поэтому держим маленький процессный кэш, чтобы
запрос маршрута не пересобирал город заново.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from ..citygraph import CityParams, generate
from ..citygraph.generate import _citygen
from ..worldgen import LLMEnricher, StubEnricher, WorldStore, building_ctx
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


def _gate(user: CurrentUser) -> User:
    if user.email not in _ALLOWED:
        raise HTTPException(403, "дебаг-граф доступен только владельцу")
    return user


Owner = Annotated[User, Depends(_gate)]


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
    """Легальные переходы из узла (заход/выход/дорога с румбом) — «куда отсюда можно пойти»."""
    city = _city(seed, key_buildings, river, walls, segment)
    return {"node": node, "kind": str(city.node_kind(node) or ""),
            "moves": [{"to": m.to, "kind": m.kind, "heading": m.heading, "name": m.name}
                      for m in city.exits(node)]}


@router.get("/api/citydebug/location")
def citydebug_location(_: Owner, node: int, seed: int = 7, key_buildings: int = 8,
                       river: bool = True, walls: bool = True,
                       segment: float | None = None) -> dict:
    """Карточка локации: имя/вид узла + легальные выходы + ближайшие здания + ориентиры."""
    city = _city(seed, key_buildings, river, walls, segment)
    if node not in city._xy:                                  # noqa: SLF001 — дебаг
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
    """Реальный городской визуал (тот же, что на карте игры) — SVG-рендер генератора."""
    p = CityParams(seed=seed, key_buildings=key_buildings, river=river, walls=walls).normalized()
    cg = _citygen()
    m = cg.build_city(p.seed, p.width, p.height, buildings=[], key_houses=[])
    return {"svg": cg.render_svg(m, chrome=True, marks=False, interactive=False)}


@router.get("/api/citydebug/building")
def citydebug_building(_: Owner, bid: str, seed: int = 7, key_buildings: int = 8, river: bool = True,
                       walls: bool = True, segment: float | None = None) -> dict:
    """Здание (любое — ВСЕ строения это дома; ключевые лишь с вывеской): графо-факты + фактшит характеристик.
    Сначала из БД мира (если параметры совпали), иначе ленивая генерация (кэш на городе)."""
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
    if data is None:                                         # нет в БД — генерим лениво (кэш на городе)
        cache = city.__dict__.setdefault("_enrich", {})
        if bid not in cache:
            mdl = _model()
            enr = LLMEnricher(mdl) if mdl.available() else StubEnricher()
            cache[bid] = enr.describe_building(building_ctx(city, bid, is_key, idx)) or {}
        data = cache[bid]
    landmarks = city._landmarks_at(node) if node in city._xy else []   # noqa: SLF001
    return {"id": bid, "is_key": is_key, "node": node, "kind": str(city.node_kind(node) or ""),
            "world": wid, "sign": sign, "landmarks": landmarks, "data": data,
            "exits": [{"kind": mv.kind, "heading": mv.heading, "name": mv.name} for mv in city.exits(node)]}


@router.get("/api/citydebug/subspace")
def citydebug_subspace(_: Owner, building: str, name: str = "Подвал", seed: int = 7,
                       key_buildings: int = 8, river: bool = True, walls: bool = True,
                       segment: float | None = None) -> dict:
    """Добавить под-здание (подвал и т.п.) к зданию/нутру; возвращает обновлённые данные карты."""
    city = _city(seed, key_buildings, river, walls, segment)
    node = city.add_subspace(_parse(building), name)
    return {"added": node, "data": city.debug_data()}
