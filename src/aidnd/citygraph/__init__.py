"""Граф города как самодостаточный модуль.

Публичный контракт — и только он виден снаружи:
    from aidnd.citygraph import generate, CityParams
    city = generate(CityParams(seed=7, key_buildings=8, river=True, walls=True))
    route = city.route("key:1", "key:2")     # реберные переходы + ключевые точки + вывески

Детали генерации (Вороной), разбиения дорог, привязки домов — приватны и наружу не текут.

Key functions
-------------
generate(params: CityParams) -> City : procedurally generate a city graph with
    streets, buildings, and key landmarks.
City.route(start_key: str, end_key: str) -> Route : find path between named
    locations with edge transitions and key points.
CityParams : configuration for city generation (seed, building count, river,
    walls).
Route : represents a path between locations with transitions and signage.
visual(city: City) -> str : render city graph as visual representation.
"""

from __future__ import annotations

from .generate import generate, visual
from .graph import City
from .model import Edge, House, KeyBuilding, Node, NodeKind, Route, Sign
from .params import CityParams

__all__ = ["generate", "visual", "City", "CityParams", "Route", "Sign",
           "Node", "Edge", "House", "KeyBuilding", "NodeKind"]
