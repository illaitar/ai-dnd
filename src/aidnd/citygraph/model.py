"""Публичные дататипы графа города. Только данные, без логики — их и видит внешний мир.

Узлы графа бывают четырёх видов: перекрёсток (узел уличной сети), точка (вставленная при
разбиении дороги на ~равные отрезки), мост (узел на переправе через реку), ворота (в стене).
Дома — второй слой: каждый дом привязан РОВНО к одному перекрёстку (ключевой точке).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class NodeKind(enum.StrEnum):
    CROSSROAD = "crossroad"   # узел уличной сети (перекрёсток/вершина дороги)
    POINT = "point"           # точка-разбиение вдоль дороги (равные отрезки)
    BRIDGE = "bridge"         # узел на переправе через реку
    GATE = "gate"             # ворота в крепостной стене


@dataclass(frozen=True)
class Node:
    id: int
    x: float
    y: float
    kind: NodeKind


@dataclass(frozen=True)
class Edge:
    a: int
    b: int
    length: float
    bridge: bool = False      # ребро-переправа через реку


@dataclass
class House:
    """Дом (второй слой). node — ближайшая точка дороги (дверь); crossroad — РОВНО ОДИН
    перекрёсток, к которому дом приписан (раздел домов по ключевым точкам)."""
    id: str
    x: float
    y: float
    node: int
    crossroad: int
    building: str | None = None   # id ключевого здания, если дом его вмещает


@dataclass
class KeyBuilding:
    id: str
    name: str
    x: float
    y: float
    node: int                 # дверь — точка дороги
    crossroad: int            # перекрёсток, к которому приписано
    house: str                # id дома-носителя
    kind: str = ""


@dataclass(frozen=True)
class Sign:
    """Вывеска: ключевое здание, мимо которого проходишь по маршруту (линк на него)."""
    building: str
    name: str
    at_node: int
    crossroad: int


@dataclass
class Route:
    """Результат прохода А→Б. edges — реберные переходы (каждый — валидное ребро графа);
    crossroads — ключевые точки в порядке прохода; signs — линки на ключевые здания по пути."""
    found: bool
    nodes: list[int] = field(default_factory=list)
    edges: list[tuple[int, int]] = field(default_factory=list)
    crossroads: list[int] = field(default_factory=list)
    length: float = 0.0
    signs: list[Sign] = field(default_factory=list)
