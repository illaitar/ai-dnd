"""Публичные дататипы графа города. Только данные, без логики — их и видит внешний мир.

Узлы графа: перекрёсток (узел уличной сети), точка (вставленная при разбиении дороги на ~равные
отрезки), мост (узел на переправе), ворота (в стене), нутро (interior — здание или под-здание).
Рёбра типизированы: road (дорога↔дорога), door (нутро↔точка дороги — это вход/выход),
internal (нутро↔под-здание, напр. лестница в подвал).
Дома — второй слой: каждый дом привязан к ближайшей точке дороги (двери) и к одному перекрёстку.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class NodeKind(enum.StrEnum):
    CROSSROAD = "crossroad"   # узел уличной сети (перекрёсток/вершина дороги)
    POINT = "point"           # точка-разбиение вдоль дороги (равные отрезки)
    BRIDGE = "bridge"         # узел на переправе через реку
    GATE = "gate"             # ворота в крепостной стене
    INTERIOR = "interior"     # нутро здания / под-здание (подвал и т.п.)


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
    kind: str = "road"        # road | door (вход/выход) | internal (между под-зданиями)


@dataclass
class House:
    """Дом (второй слой). node — ближайшая точка дороги (дверь); crossroad — ровно один
    перекрёёсток, к которому дом приписан (раздел домов по ключевым точкам)."""
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
    node: int                 # дверь — ближайшая точка дороги
    crossroad: int            # перекрёсток, к которому приписано (для раздела домов)
    house: str                # id дома-носителя
    kind: str = ""
    interior: int = -1        # узел-нутро в графе: вход/выход через door-ребро к node


@dataclass(frozen=True)
class Sign:
    """Вывеска: ключевое здание, мимо которого проходишь по маршруту (линк на него)."""
    building: str
    name: str
    at_node: int
    crossroad: int


@dataclass(frozen=True)
class Move:
    """Легальный переход из узла. kind: road | enter | exit | internal."""
    to: int
    kind: str
    heading: str | None = None   # румб (С/СВ/…) для road-переходов
    name: str | None = None      # имя здания/под-здания для enter/exit/internal


@dataclass(frozen=True)
class Step:
    """Типизированный шаг маршрута."""
    frm: int
    to: int
    kind: str                    # road | enter | exit | internal
    heading: str | None = None
    name: str | None = None


@dataclass
class Route:
    """Результат прохода А→Б. steps — типизированные шаги (вход/выход обозначены явно);
    crossroads — ключевые точки в порядке прохода; signs — линки на ключевые здания по пути."""
    found: bool
    nodes: list[int] = field(default_factory=list)
    edges: list[tuple[int, int]] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    crossroads: list[int] = field(default_factory=list)
    length: float = 0.0
    signs: list[Sign] = field(default_factory=list)
