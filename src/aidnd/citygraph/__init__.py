"""Граф города как самодостаточный модуль.

Публичный контракт — и только он виден снаружи:
    from aidnd.citygraph import generate, CityParams
    city = generate(CityParams(seed=7, key_buildings=8, river=True, walls=True))
    route = city.route("key:1", "key:2")     # реберные переходы + ключевые точки + вывески

Детали генерации (Вороной), разбиения дорог, привязки домов — приватны и наружу не текут.
"""

from __future__ import annotations

from .generate import generate, visual
from .graph import City
from .model import Edge, House, KeyBuilding, Node, NodeKind, Route, Sign
from .params import CityParams

__all__ = ["generate", "visual", "City", "CityParams", "Route", "Sign",
           "Node", "Edge", "House", "KeyBuilding", "NodeKind"]
