"""Пространственная модель как ГРАФ СВЯЗНОСТИ локаций (main §3.4, §10 портальная навигация).

Тайл-грид и координаты намеренно НЕ используются: мир представлен информационно —
локации это узлы, связи (порталы) это рёбра. Навигация и «близость» считаются по
графу (число переходов), а не по клеткам. Это портальная навигация уровня
Building/Room из диздока; боевых тайлов нет.

Иерархия: Region → Settlement/Site → Building → Room. Рёбра-порталы задают, куда
можно пройти. AOI и salience считаются по дистанции в этом графе.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

# Стороны света (y растёт на юг) + вертикаль/вход-выход для не-компасных переходов.
DIRECTIONS = {
    "north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0),
    "northeast": (1, -1), "northwest": (-1, -1), "southeast": (1, 1), "southwest": (-1, 1),
}
# раскладка координат для мини-карты: компас + не-компасные рёбра (out/in/вглубь...)
# чтобы узлы вроде диких земель и подземелий тоже получали координаты (не выпадали).
LAYOUT_OFFSETS = {
    **DIRECTIONS, "out": (0, 3), "in": (0, -3), "deeper": (2, 2), "back": (-2, -2),
    "up": (-1, -2), "down": (1, 2),
}
DIR_RU = {
    "north": "север", "south": "юг", "east": "восток", "west": "запад",
    "northeast": "северо-восток", "northwest": "северо-запад",
    "southeast": "юго-восток", "southwest": "юго-запад",
    "up": "вверх", "down": "вниз", "in": "внутрь", "out": "наружу",
    "deeper": "вглубь", "back": "назад",
}
OPPOSITE = {
    "north": "south", "south": "north", "east": "west", "west": "east",
    "northeast": "southwest", "southwest": "northeast",
    "northwest": "southeast", "southeast": "northwest",
    "up": "down", "down": "up", "in": "out", "out": "in",
    "deeper": "back", "back": "deeper",
}
# распознавание ввода игрока → каноническая сторона света
DIR_ALIASES = {
    "север": "north", "north": "north", "n": "north", "северн": "north",
    "юг": "south", "south": "south", "s": "south", "южн": "south",
    "восток": "east", "east": "east", "e": "east", "восточн": "east",
    "запад": "west", "west": "west", "w": "west", "западн": "west",
    "северо-восток": "northeast", "св": "northeast", "northeast": "northeast",
    "северо-запад": "northwest", "сз": "northwest", "northwest": "northwest",
    "юго-восток": "southeast", "юв": "southeast", "southeast": "southeast",
    "юго-запад": "southwest", "юз": "southwest", "southwest": "southwest",
    "вверх": "up", "наверх": "up", "up": "up", "вниз": "down", "down": "down",
    "внутрь": "in", "наружу": "out", "вглубь": "deeper", "глубже": "deeper",
    "назад": "back", "обратно": "back",
}


@dataclass
class Place:
    """Узел графа локаций."""

    place_id: str
    kind: str                       # region | settlement | site | building | room
    name: str
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    district: str | None = None
    affordances: list[str] = field(default_factory=list)  # smart-object аффордансы
    portals: list[str] = field(default_factory=list)      # смежные place_id (ненаправленно)
    exits: dict = field(default_factory=dict)             # направление -> place_id (компас и пр.)
    battlemap: str | None = None    # файл боевой карты (визуальная подложка боя)
    ambiance: str | None = None     # короткая физическая атмосфера (для нарратора)
    alterations: list[str] = field(default_factory=list)  # стойкие следы действий (агент последствий)


class SpatialIndex:
    """Граф локаций + индекс «кто где». Без координат — только связность."""

    def __init__(self) -> None:
        self.places: dict[str, Place] = {}
        self._place_of: dict[str, str] = {}                 # eid -> place_id
        self._occupants: dict[str, set[str]] = defaultdict(set)  # place_id -> {eid}

    # --- места и связи ----------------------------------------------------- #
    def add_place(self, place: Place) -> None:
        self.places[place.place_id] = place
        if place.parent and place.parent in self.places:
            parent = self.places[place.parent]
            if place.place_id not in parent.children:
                parent.children.append(place.place_id)

    def link_portal(self, a: str, b: str) -> None:
        if a in self.places and b not in self.places[a].portals:
            self.places[a].portals.append(b)
        if b in self.places and a not in self.places[b].portals:
            self.places[b].portals.append(a)

    def link(self, a: str, direction: str, b: str) -> None:
        """Направленное ребро a --direction--> b и обратное b --opposite--> a.
        Также добавляет ненаправленное смежство (для pathfinding/AOI)."""
        if a in self.places:
            self.places[a].exits[direction] = b
        if b in self.places:
            self.places[b].exits[OPPOSITE.get(direction, direction)] = a
        self.link_portal(a, b)

    def affordances_at(self, place_id: str) -> list[str]:
        p = self.places.get(place_id)
        return p.affordances if p else []

    def connections(self, place_id: str) -> list[str]:
        """Локации, в которые можно пройти напрямую (рёбра графа связности)."""
        p = self.places.get(place_id)
        return list(p.portals) if p else []

    def exits_of(self, place_id: str) -> dict:
        """Направление -> соседний place_id (компас и пр.) для текущего узла."""
        p = self.places.get(place_id)
        return dict(p.exits) if p else {}

    def direction_to(self, place_id: str, neighbor: str) -> str | None:
        """Направление от place_id к соседу (если задано направленным ребром)."""
        for d, dest in self.exits_of(place_id).items():
            if dest == neighbor:
                return d
        return None

    def layout(self, root: str) -> dict:
        """BFS-раскладка координат по рёбрам (компас + out/in/вглубь) — для мини-карты."""
        coords = {root: (0, 0)}
        q = deque([root])
        while q:
            cur = q.popleft()
            cx, cy = coords[cur]
            for d, dest in self.exits_of(cur).items():
                if dest in coords or d not in LAYOUT_OFFSETS:
                    continue
                dx, dy = LAYOUT_OFFSETS[d]
                coords[dest] = (cx + dx, cy + dy)
                q.append(dest)
        return coords

    # --- «кто где» --------------------------------------------------------- #
    def update_position(self, eid: str, place_id: str) -> None:
        old = self._place_of.get(eid)
        if old:
            self._occupants[old].discard(eid)
        self._place_of[eid] = place_id
        self._occupants[place_id].add(eid)

    def remove(self, eid: str) -> None:
        old = self._place_of.pop(eid, None)
        if old:
            self._occupants[old].discard(eid)

    def place_of(self, eid: str) -> str | None:
        return self._place_of.get(eid)

    def occupants(self, place_id: str) -> set[str]:
        return set(self._occupants.get(place_id, set()))

    # --- граф: дистанция и окрестность (для AOI/salience, док 08 §7) ------- #
    def hops_between(self, a: str, b: str, limit: int = 12) -> int | None:
        """Число переходов между локациями по графу порталов (BFS). None — нет пути."""
        if a == b:
            return 0
        if a not in self.places or b not in self.places:
            return None
        seen = {a}
        q = deque([(a, 0)])
        while q:
            cur, d = q.popleft()
            if d >= limit:
                continue
            for nxt in self.places[cur].portals:
                if nxt == b:
                    return d + 1
                if nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, d + 1))
        return None

    def path_between(self, a: str, b: str) -> list[str] | None:
        """Кратчайший путь-список узлов от a до b по графу проходимости (BFS).
        None — пути нет. Используется маршрутизацией перемещения (идти к известной
        локации, а не только к прямому соседу)."""
        if a == b:
            return [a]
        if a not in self.places or b not in self.places:
            return None
        prev = {a: None}
        q = deque([a])
        while q:
            cur = q.popleft()
            for nxt in self.places[cur].portals:
                if nxt in prev:
                    continue
                prev[nxt] = cur
                if nxt == b:
                    path = [b]
                    while path[-1] != a:
                        path.append(prev[path[-1]])
                    path.reverse()
                    return path
                q.append(nxt)
        return None

    def neighbors(self, place_id: str, hops: int = 1) -> set[str]:
        """Сущности в локации и в локациях в пределах `hops` переходов (AOI)."""
        out: set[str] = set(self._occupants.get(place_id, set()))
        if place_id not in self.places:
            return out
        seen = {place_id}
        q = deque([(place_id, 0)])
        while q:
            cur, d = q.popleft()
            if d >= hops:
                continue
            for nxt in self.places[cur].portals:
                if nxt not in seen:
                    seen.add(nxt)
                    out |= self._occupants.get(nxt, set())
                    q.append((nxt, d + 1))
        return out

    def connectivity_graph(self) -> dict:
        """Информационное представление связности: узлы + рёбра (для UI/инспектора)."""
        nodes = [{"id": p.place_id, "name": p.name, "kind": p.kind,
                  "district": p.district} for p in self.places.values()]
        edges = set()
        for p in self.places.values():
            for q in p.portals:
                edges.add(tuple(sorted((p.place_id, q))))
        return {"nodes": nodes, "edges": [list(e) for e in sorted(edges)]}
