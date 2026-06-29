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
from .models import User
from .routes_auth import CurrentUser

router = APIRouter(tags=["citydebug"])
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_ALLOWED = {"kleit@yandex.ru"}
_CACHE: dict[tuple, object] = {}


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


@router.get("/api/citydebug/route")
def citydebug_route(_: Owner, a: str, b: str, seed: int = 7, key_buildings: int = 8,
                    river: bool = True, walls: bool = True,
                    segment: float | None = None) -> dict:
    city = _city(seed, key_buildings, river, walls, segment)

    def parse(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return v

    r = city.route(parse(a), parse(b))
    return {"found": r.found, "nodes": r.nodes, "edges": [list(e) for e in r.edges],
            "crossroads": r.crossroads, "length": round(r.length, 1),
            "signs": [{"building": s.building, "name": s.name, "at_node": s.at_node,
                       "crossroad": s.crossroad} for s in r.signs]}
