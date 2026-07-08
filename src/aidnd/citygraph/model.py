"""Public city graph data types. Data only, no logic — this is what the external world sees.

Graph nodes: crossroad (street network node), point (inserted when dividing road into ~equal
segments), bridge (node on a crossing), gate (in wall), interior (interior — building or sub-building).
Edges are typed: road (road↔road), door (interior↔road point — this is entry/exit),
internal (interior↔sub-building, e.g. stairs to basement).
Houses — second layer: each house is anchored to the nearest road point (door) and to one crossroad.

Key functions
-------------
NodeKind : StrEnum of node types (CROSSROAD, POINT, BRIDGE, GATE, INTERIOR).
Node : graph node with position and kind; immutable.
Edge : connection between two nodes; may represent road, door, or internal passage.
House : anchored to nearest road point and assigned to one crossroad for zoning.
KeyBuilding : landmark building with name, position, and interior entrance node.
Route : result of pathfinding (found, steps, crossroads, signs, landmarks, bearing).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class NodeKind(enum.StrEnum):
    CROSSROAD = "crossroad"   # street network node (crossroad/road vertex)
    POINT = "point"           # division point along road (equal segments)
    BRIDGE = "bridge"         # node on a crossing over river
    GATE = "gate"             # gate in fortification wall
    INTERIOR = "interior"     # building interior / sub-building (basement, etc.)


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
    bridge: bool = False      # edge-crossing over river
    kind: str = "road"        # road | door (entry/exit) | internal (between sub-buildings)


@dataclass
class House:
    """House (second layer). node — nearest road point (door); crossroad — exactly one
    crossroad to which the house is assigned (division of houses by key points)."""
    id: str
    x: float
    y: float
    node: int
    crossroad: int
    building: str | None = None   # id of key building if house contains it


@dataclass
class KeyBuilding:
    id: str
    name: str
    x: float
    y: float
    node: int                 # door — nearest road point
    crossroad: int            # crossroad to which it is assigned (for house division)
    house: str                # id of containing house
    kind: str = ""
    interior: int = -1        # interior node in graph: entry/exit via door edge to node


@dataclass(frozen=True)
class Sign:
    """Sign: key building you pass by on the route (link to it)."""
    building: str
    name: str
    at_node: int
    crossroad: int


@dataclass(frozen=True)
class Move:
    """Legal transition from a node. kind: road | enter | exit | internal."""
    to: int
    kind: str
    heading: str | None = None   # bearing (N/NE/…) for road transitions
    name: str | None = None      # name of building/sub-building for enter/exit/internal


@dataclass(frozen=True)
class Step:
    """Typed route step."""
    frm: int
    to: int
    kind: str                    # road | enter | exit | internal
    heading: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class Nearby:
    """Nearest landmark building (its 'entity')."""
    id: str
    name: str
    dist: float


@dataclass
class Route:
    """Result of A→B passage. steps — typed steps (entry/exit explicitly marked);
    crossroads — key points in passage order; signs — links to key buildings along the route.
    bearing — compass direction start→finish; near_target — key building nearest to target (except it);
    landmarks — landmarks at target (river|wall|gate|bridge)."""
    found: bool
    nodes: list[int] = field(default_factory=list)
    edges: list[tuple[int, int]] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    crossroads: list[int] = field(default_factory=list)
    length: float = 0.0
    signs: list[Sign] = field(default_factory=list)
    bearing: str | None = None
    near_target: Nearby | None = None
    landmarks: list[str] = field(default_factory=list)
