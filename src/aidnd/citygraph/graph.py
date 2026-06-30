"""Граф города и единая система передвижения по нему.

Слой 1 — улицы: перекрёстки (узлы сети) + дороги, разбитые на точки ~равной длины, + мосты, ворота.
Слой 2 — дома: каждый дом приписан РОВНО к одному перекрёстку (ближайшему); дом между двумя
перекрёстками попадает только в один. Ключевые здания селятся в равномерно разнесённые дома.

Передвижение — A* по графу: `route(a, b)` отдаёт реберные переходы, цепочку ключевых точек и
вывески (линки на ключевые здания по пути). Это и есть API, которым пользуются все снаружи;
детали Вороного/SVG сюда не протекают.
"""

from __future__ import annotations

import heapq
import math

from .model import Edge, House, KeyBuilding, Move, Nearby, Node, NodeKind, Route, Sign, Step


def _dist(a: tuple, b: tuple) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _ek(a: int, b: int) -> tuple:
    return (a, b) if a < b else (b, a)


def _dist2_seg(p, a, b) -> float:
    """Квадрат расстояния от точки p до отрезка ab."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return (p[0] - ax) ** 2 + (p[1] - ay) ** 2
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + dx * t, ay + dy * t
    return (p[0] - cx) ** 2 + (p[1] - cy) ** 2


def _dist2_to_polyline(p, pts) -> float:
    if not pts:
        return 1e30
    best = 1e30
    for i in range(len(pts) - 1):
        d = _dist2_seg(p, pts[i], pts[i + 1])
        if d < best:
            best = d
    return best


def _dist2_to_poly(p, poly) -> float:
    """Квадрат расстояния до ЗАМКНУТОГО контура (стены)."""
    if not poly:
        return 1e30
    n, best = len(poly), 1e30
    for i in range(n):
        d = _dist2_seg(p, poly[i], poly[(i + 1) % n])
        if d < best:
            best = d
    return best


class City:
    """Граф города + передвижение. Строится из «сырой» геометрии (см. generate.py)."""

    def __init__(self, params, raw: dict):
        self.params = params
        self._build(raw)
        if params.key_buildings:
            self.assign_key_buildings(params.key_buildings)

    # ----------------------------------------------------- построение ------ #
    def _build(self, raw: dict) -> None:
        src_xy = [(float(x), float(y)) for x, y in raw["nodes"]]
        src_adj = [list(a) for a in raw["adj"]]
        self._interval = self._pick_interval(src_xy, src_adj)
        xy, adj = self._merge_short(src_xy, src_adj, eps=self._interval * 0.5)
        polylines, junctions = self._trace_polylines(adj)
        self._resample(polylines, xy, junctions)
        self.river = dict(raw.get("river") or {})
        self.walls = list(raw.get("walls") or [])
        self._tag_bridges(raw.get("bridges") or [])
        self._tag_gates(raw.get("gates") or [])
        self._partition_houses(raw.get("houses") or [])
        self.key_buildings: dict[str, KeyBuilding] = {}
        self._landmarks = list(raw.get("keys") or [])
        self._interior_name: dict[int, str] = {}             # узел-нутро → имя здания/под-здания
        self._interior_building: dict[int, str | None] = {}  # узел-нутро → id корневого ключевого здания
        self._interior_parent: dict[int, int | None] = {}    # под-здание → родительское нутро

    def _pick_interval(self, xy: list, adj: list) -> float:
        if self.params.segment:
            return float(self.params.segment)
        seg, seen = [], set()
        for i, nbrs in enumerate(adj):
            for j in nbrs:
                e = (i, j) if i < j else (j, i)
                if e in seen or j >= len(xy):
                    continue
                seen.add(e)
                seg.append(_dist(xy[i], xy[j]))
        seg.sort()
        return max(18.0, min(36.0, seg[len(seg) // 2])) if seg else 28.0

    def _merge_short(self, xy: list, adj: list, eps: float):
        """Схлопнуть смежные узлы ближе eps (короткие рёбра Вороного и артефакты округления) —
        без этого равных отрезков не выходит. Union-find ТОЛЬКО по соединённым близким парам."""
        parent = list(range(len(xy)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        e2 = eps * eps
        for a, nbrs in enumerate(adj):
            for b in nbrs:
                if a < b < len(xy) and _dist(xy[a], xy[b]) ** 2 <= e2:
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
        new_xy: dict[int, tuple] = {}
        new_adj: dict[int, set] = {}
        for i in range(len(xy)):
            r = find(i)
            new_xy[r] = xy[r]
            new_adj.setdefault(r, set())
        for a, nbrs in enumerate(adj):
            ra = find(a)
            for b in nbrs:
                if b >= len(xy):
                    continue
                rb = find(b)
                if ra != rb:
                    new_adj[ra].add(rb)
                    new_adj[rb].add(ra)
        return new_xy, new_adj

    def _trace_polylines(self, adj: dict):
        """Развернуть граф в полилинии между РАЗВИЛКАМИ (degree≠2). degree-2 — изгиб внутри дороги."""
        deg = {n: len(nb) for n, nb in adj.items()}
        junctions = {n for n in adj if deg[n] != 2}
        seen = set()

        def ek(a, b):
            return (a, b) if a < b else (b, a)

        polylines = []
        for j in (junctions or set(adj)):              # кольцо без развилок — стартуем откуда угодно
            for nb in adj[j]:
                if ek(j, nb) in seen:
                    continue
                seen.add(ek(j, nb))
                path, prev, cur = [j, nb], j, nb
                while cur not in junctions and deg.get(cur) == 2:
                    nxts = [x for x in adj[cur] if x != prev]
                    if not nxts or ek(cur, nxts[0]) in seen:
                        break
                    seen.add(ek(cur, nxts[0]))
                    prev, cur = cur, nxts[0]
                    path.append(cur)
                polylines.append(path)
        return polylines, junctions

    def _link(self, a: int, b: int, kind: str = "road") -> None:
        if b not in self._adj[a]:
            self._adj[a].append(b)
        if a not in self._adj[b]:
            self._adj[b].append(a)
        self._ekind[_ek(a, b)] = kind

    def _new_node(self, pos: tuple, kind: NodeKind) -> int:
        nid = self._next
        self._next += 1
        self._xy[nid], self._kind[nid], self._adj[nid] = pos, kind, []
        return nid

    def _resample(self, polylines: list, xy: dict, junctions: set) -> None:
        """Полилинии → узлы: развилки=перекрёстки, внутри — точки через РАВНЫЙ интервал по длине дуги."""
        self._xy, self._kind, self._adj, self._ekind, self._next = {}, {}, {}, {}, 0
        cr_map: dict[int, int] = {}

        def crossroad(src):
            if src not in cr_map:
                cr_map[src] = self._new_node(xy[src], NodeKind.CROSSROAD)
            return cr_map[src]

        for pl in polylines:
            pts = [xy[i] for i in pl]
            seglen = [_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
            length = sum(seglen)
            a = crossroad(pl[0])
            b = a if pl[-1] == pl[0] else crossroad(pl[-1])
            if length < 1e-6:
                self._link(a, b)
                continue
            n = max(1, round(length / self._interval))
            prev = a
            for k in range(1, n):
                nid = self._new_node(self._point_at(pts, seglen, length * k / n), NodeKind.POINT)
                self._link(prev, nid)
                prev = nid
            self._link(prev, b)
        self._crossroads = set(cr_map.values())

    @staticmethod
    def _point_at(pts: list, seglen: list, target: float) -> tuple:
        acc = 0.0
        for i in range(len(seglen)):
            if acc + seglen[i] >= target or i == len(seglen) - 1:
                t = (target - acc) / seglen[i] if seglen[i] > 1e-9 else 0.0
                t = max(0.0, min(1.0, t))
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                return (ax + (bx - ax) * t, ay + (by - ay) * t)
            acc += seglen[i]
        return pts[-1]

    def _tag_bridges(self, crosses: list) -> None:
        """Узел у каждой переправы → BRIDGE; рёбра у реки помечаем как мосты."""
        self._bridge_nodes: list[int] = []
        for x, y in crosses:
            nd = self._nearest_node(x, y)
            if nd is not None:
                self._kind[nd] = NodeKind.BRIDGE
                self._bridge_nodes.append(nd)
        self._bridge_edges: set[tuple] = set()
        pts = self.river.get("pts") or []
        w = self.river.get("w", 0) or 0
        if pts and w:
            thr = (w * 1.1) ** 2
            for a, nbrs in self._adj.items():
                for b in nbrs:
                    if b < a:
                        continue
                    mid = ((self._xy[a][0] + self._xy[b][0]) / 2, (self._xy[a][1] + self._xy[b][1]) / 2)
                    if _dist2_to_polyline(mid, pts) <= thr:
                        self._bridge_edges.add((a, b))

    def _tag_gates(self, gates: list) -> None:
        self._gate_nodes: list[int] = []
        for x, y in gates:
            nd = self._nearest_node(x, y)
            if nd is not None and self._kind[nd] != NodeKind.BRIDGE:
                self._kind[nd] = NodeKind.GATE
                self._gate_nodes.append(nd)

    def _partition_houses(self, raw_houses: list) -> None:
        """Раздел домов: дом → ближайшая точка дороги (дверь) И ровно один перекрёсток."""
        self.houses: dict[str, House] = {}
        self._node_houses: dict[int, list[str]] = {}
        self._cr_houses: dict[int, list[str]] = {}
        cr_list = list(self._crossroads)
        for h in raw_houses:
            x, y = float(h["x"]), float(h["y"])
            nd = self._nearest_node(x, y)
            cr = self._nearest_among(x, y, cr_list)
            self.houses[h["id"]] = House(id=h["id"], x=x, y=y, node=nd, crossroad=cr)
            self._node_houses.setdefault(nd, []).append(h["id"])
            self._cr_houses.setdefault(cr, []).append(h["id"])

    # ----------------------------------------------------- геометрия ------- #
    def _nearest_node(self, x: float, y: float, kinds: set | None = None) -> int | None:
        best, bd = None, 1e30
        for i, (nx, ny) in self._xy.items():
            if kinds and self._kind[i] not in kinds:
                continue
            d = (nx - x) ** 2 + (ny - y) ** 2
            if d < bd:
                bd, best = d, i
        return best

    def _nearest_among(self, x: float, y: float, ids: list) -> int | None:
        best, bd = None, 1e30
        for i in ids:
            nx, ny = self._xy[i]
            d = (nx - x) ** 2 + (ny - y) ** 2
            if d < bd:
                bd, best = d, i
        return best

    def _unique_edges(self) -> list[tuple]:
        out, seen = [], set()
        for a, nbrs in self._adj.items():
            for b in nbrs:
                e = (a, b) if a < b else (b, a)
                if e not in seen:
                    seen.add(e)
                    out.append(e)
        return out

    # ----------------------------------------------------- ключевые здания - #
    def assign_key_buildings(self, n: int, names: list[str] | None = None) -> list[KeyBuilding]:
        """Выбрать n равномерно разнесённых домов (farthest-point sampling) и поселить в них
        ключевые здания: каждому — узел-нутро + door-ребро к ближайшей точке дороги (вход/выход).
        Перезаписывает прежнее распределение (вместе с под-зданиями)."""
        self._clear_interiors()
        ids = list(self.houses)
        n = max(0, min(int(n), len(ids)))
        chosen = self._spread_select(ids, n)
        for ho in self.houses.values():
            ho.building = None
        self.key_buildings = {}
        for k, hid in enumerate(chosen):
            ho = self.houses[hid]
            nm = names[k] if names and k < len(names) else f"Здание {k + 1}"
            bid = f"key:{k + 1}"
            ho.building = bid
            interior = self._new_node((ho.x, ho.y), NodeKind.INTERIOR)
            self._link(interior, ho.node, kind="door")        # вход/выход к ближайшей точке дороги
            self._interior_name[interior] = nm
            self._interior_building[interior] = bid
            self._interior_parent[interior] = None
            self.key_buildings[bid] = KeyBuilding(
                id=bid, name=nm, x=ho.x, y=ho.y, node=ho.node,
                crossroad=ho.crossroad, house=hid, interior=interior)
        return list(self.key_buildings.values())

    def add_subspace(self, building, name: str) -> int | None:
        """Добавить под-здание (подвал и т.п.) к ключевому зданию ИЛИ к другому нутру (вложенность).
        Связь — internal-ребро; легальные переходы те же. Возвращает id нового узла-нутра."""
        if building in self.key_buildings:
            parent, root = self.key_buildings[building].interior, building
        elif isinstance(building, int) and self._kind.get(building) == NodeKind.INTERIOR:
            parent, root = building, self._interior_building.get(building)
        else:
            return None
        px, py = self._xy[parent]
        node = self._new_node((px + 6.0, py + 6.0), NodeKind.INTERIOR)
        self._link(parent, node, kind="internal")
        self._interior_name[node] = name
        self._interior_building[node] = root
        self._interior_parent[node] = parent
        return node

    def _clear_interiors(self) -> None:
        for n in list(getattr(self, "_interior_name", {})):
            self._remove_node(n)
        self._interior_name, self._interior_building, self._interior_parent = {}, {}, {}

    def _remove_node(self, n: int) -> None:
        for m in list(self._adj.get(n, [])):
            self._adj[m] = [x for x in self._adj[m] if x != n]
            self._ekind.pop(_ek(n, m), None)
        self._adj.pop(n, None)
        self._xy.pop(n, None)
        self._kind.pop(n, None)

    def _spread_select(self, ids: list, n: int) -> list:
        """Жадная равномерная выборка n точек: каждый раз берём самую далёкую от уже выбранных."""
        if n <= 0 or not ids:
            return []
        if n >= len(ids):
            return list(ids)
        pts = {i: (self.houses[i].x, self.houses[i].y) for i in ids}
        start = min(ids, key=lambda i: (pts[i][0], pts[i][1]))      # детерминированный старт
        chosen = [start]
        chosen_set = {start}
        dist = {i: _dist(pts[i], pts[start]) for i in ids}
        while len(chosen) < n:
            nxt = max((i for i in ids if i not in chosen_set), key=lambda i: dist[i])
            chosen.append(nxt)
            chosen_set.add(nxt)
            for i in ids:
                d = _dist(pts[i], pts[nxt])
                if d < dist[i]:
                    dist[i] = d
        return chosen

    # ----------------------------------------------------- передвижение ---- #
    def _resolve(self, e) -> int | None:
        """Конечная точка: id узла | id дома | id ключевого здания → узел графа.
        Здание → его НУТРО (чтобы маршрут включал выход/вход явными шагами)."""
        if isinstance(e, int):
            return e if e in self._xy else None
        if e in self.key_buildings:
            return self.key_buildings[e].interior
        if e in self.houses:
            return self.houses[e].node
        return None

    def _heading(self, a: int, b: int) -> str:
        """Румб перехода a→b (8 сторон; экран: y вниз, поэтому север = вверх)."""
        ax, ay = self._xy[a]
        bx, by = self._xy[b]
        ang = math.degrees(math.atan2(-(by - ay), bx - ax)) % 360.0
        dirs = ["В", "СВ", "С", "СЗ", "З", "ЮЗ", "Ю", "ЮВ"]
        return dirs[int((ang + 22.5) // 45) % 8]

    def _step(self, u: int, v: int) -> Step:
        k = self._ekind.get(_ek(u, v), "road")
        if k == "door":
            if self._kind[u] == NodeKind.INTERIOR:
                return Step(u, v, "exit", name="на улицу")
            return Step(u, v, "enter", name=self._interior_name.get(v))
        if k == "internal":
            return Step(u, v, "internal", name=self._interior_name.get(v))
        return Step(u, v, "road", heading=self._heading(u, v))

    def exits(self, node: int) -> list[Move]:
        """Легальные переходы из узла, категоризованные: road (с румбом) | enter | exit | internal.
        Это и есть «куда отсюда можно легально пойти» для любой ключевой точки/здания."""
        if node not in self._adj:
            return []
        interior = self._kind.get(node) == NodeKind.INTERIOR
        out = []
        for nb in self._adj[node]:
            k = self._ekind.get(_ek(node, nb), "road")
            if k == "road":
                out.append(Move(to=nb, kind="road", heading=self._heading(node, nb)))
            elif k == "door":
                if interior:
                    out.append(Move(to=nb, kind="exit", name="на улицу"))
                else:
                    out.append(Move(to=nb, kind="enter", name=self._interior_name.get(nb)))
            elif k == "internal":
                out.append(Move(to=nb, kind="internal", name=self._interior_name.get(nb)))
        return out

    def _astar(self, src: int, dst: int) -> list[int]:
        if src == dst:
            return [src]
        tx, ty = self._xy[dst]

        def h(n: int) -> float:
            x, y = self._xy[n]
            return ((x - tx) ** 2 + (y - ty) ** 2) ** 0.5

        openh = [(h(src), 0.0, src)]
        g = {src: 0.0}
        prev = {src: -1}
        while openh:
            _, gn, n = heapq.heappop(openh)
            if n == dst:
                break
            if gn > g.get(n, 1e30):
                continue
            for m in self._adj[n]:
                ng = gn + _dist(self._xy[n], self._xy[m])
                if ng < g.get(m, 1e30):
                    g[m] = ng
                    prev[m] = n
                    heapq.heappush(openh, (ng + h(m), ng, m))
        if dst not in prev:
            return []
        out, n = [], dst
        while n != -1:
            out.append(n)
            n = prev[n]
        return out[::-1]

    def route(self, a, b) -> Route:
        """Проход А→Б по графу (A*). a/b — id узла, дома или ключевого здания."""
        src, dst = self._resolve(a), self._resolve(b)
        if src is None or dst is None:
            return Route(found=False)
        nodes = self._astar(src, dst)
        if not nodes:
            return Route(found=False)
        edges = list(zip(nodes, nodes[1:]))
        steps = [self._step(u, v) for u, v in edges]
        crossroads = [n for n in nodes if self._kind[n] == NodeKind.CROSSROAD]
        length = sum(_dist(self._xy[u], self._xy[v]) for u, v in edges)
        signs = self._signs_along(nodes, a, b)
        start, end = nodes[0], nodes[-1]
        bearing = (self._heading(start, end)
                   if start != end and _dist(self._xy[start], self._xy[end]) > 1e-6 else None)
        return Route(found=True, nodes=nodes, edges=edges, steps=steps, crossroads=crossroads,
                     length=length, signs=signs, bearing=bearing,
                     near_target=self._nearest_other_building(end),
                     landmarks=self._landmarks_at(end))

    def _nearest_other_building(self, node: int) -> Nearby | None:
        """Ближайшее (по прямой) ключевое здание к узлу, КРОМЕ здания самого узла."""
        x, y = self._xy[node]
        self_b = next((bid for bid, kb in self.key_buildings.items() if kb.interior == node), None)
        best, bd = None, 1e30
        for bid, kb in self.key_buildings.items():
            if bid == self_b:
                continue
            d = (kb.x - x) ** 2 + (kb.y - y) ** 2
            if d < bd:
                bd, best = d, kb
        return Nearby(best.id, best.name, round(bd ** 0.5, 1)) if best else None

    def _landmarks_at(self, node: int) -> list[str]:
        """Ориентиры у узла: у реки / у стены / у ворот / у моста (геометрия карты)."""
        x, y = self._xy[node]
        thr = (self._interval * 1.5) ** 2
        tags = []
        pts = self.river.get("pts") or []
        w = self.river.get("w", 0) or 0
        if pts and w and _dist2_to_polyline((x, y), pts) <= (w * 1.6) ** 2:
            tags.append("river")
        if self.walls and _dist2_to_poly((x, y), self.walls) <= thr:
            tags.append("wall")
        if any((self._xy[g][0] - x) ** 2 + (self._xy[g][1] - y) ** 2 <= thr
               for g in getattr(self, "_gate_nodes", [])):
            tags.append("gate")
        if any((self._xy[b][0] - x) ** 2 + (self._xy[b][1] - y) ** 2 <= thr
               for b in getattr(self, "_bridge_nodes", [])):
            tags.append("bridge")
        return tags

    def _signs_along(self, nodes: list[int], a, b) -> list[Sign]:
        """Вывески: ключевые здания, мимо которых реально проходишь (дверь на маршруте ИЛИ дверь в
        пределах ~1.6 отрезка от любой точки пути — «видно с дороги»). В порядке прохода."""
        ends = {a, b}
        nset = set(nodes)
        crset = {n for n in nodes if self._kind[n] == NodeKind.CROSSROAD}
        route_xy = [self._xy[n] for n in nodes]
        idx = {n: i for i, n in enumerate(nodes)}
        radius2 = (self._interval * 1.6) ** 2
        out = []
        for kb in self.key_buildings.values():
            if kb.id in ends or kb.house in ends:
                continue
            on_path = kb.node in nset or kb.crossroad in crset
            if not on_path and not any((rx - kb.x) ** 2 + (ry - kb.y) ** 2 <= radius2
                                       for rx, ry in route_xy):
                continue
            pos = idx.get(kb.node)
            if pos is None:
                pos = min(range(len(nodes)),
                          key=lambda i: (route_xy[i][0] - kb.x) ** 2 + (route_xy[i][1] - kb.y) ** 2)
            out.append((pos, Sign(building=kb.id, name=kb.name, at_node=kb.node, crossroad=kb.crossroad)))
        out.sort(key=lambda t: t[0])
        return [s for _, s in out]

    # ----------------------------------------------------- публичные виды -- #
    def nodes(self) -> list[Node]:
        return [Node(i, x, y, self._kind[i]) for i, (x, y) in self._xy.items()]

    def edges(self) -> list[Edge]:
        return [Edge(a, b, _dist(self._xy[a], self._xy[b]), (a, b) in self._bridge_edges,
                     self._ekind.get((a, b), "road"))
                for a, b in self._unique_edges()]

    def houses_at_crossroad(self, cr: int) -> list[str]:
        """Дома, приписанные к этому перекрёстку (раздел «один перекрёсток на дом»)."""
        return list(self._cr_houses.get(cr, []))

    def node_kind(self, node: int) -> NodeKind | None:
        return self._kind.get(node)

    def key_points(self) -> list[int]:
        """Ключевые точки графа — развилки-перекрёстки (включая узлы мостов/ворот)."""
        return sorted(self._crossroads)

    def stats(self) -> dict:
        kinds = {}
        for k in self._kind.values():
            kinds[k.value] = kinds.get(k.value, 0) + 1
        return {"nodes": len(self._xy), "edges": len(self._unique_edges()),
                "by_kind": kinds, "houses": len(self.houses),
                "key_buildings": len(self.key_buildings), "interval": round(self._interval, 1)}

    def debug_data(self) -> dict:
        """Слоистый JSON для дебаг-визуализации (узлы по видам, рёбра, дома→перекрёсток, река, стены)."""
        return {
            "params": {"seed": self.params.seed, "key_buildings": self.params.key_buildings,
                       "river": self.params.river, "walls": self.params.walls},
            "size": {"w": self.params.width, "h": self.params.height},
            "stats": self.stats(),
            "nodes": [{"id": i, "x": round(x, 1), "y": round(y, 1), "kind": self._kind[i].value,
                       "name": self._interior_name.get(i)}
                      for i, (x, y) in self._xy.items()],
            "edges": [{"a": a, "b": b, "bridge": (a, b) in self._bridge_edges,
                       "kind": self._ekind.get((a, b), "road")}
                      for a, b in self._unique_edges()],
            "houses": [{"id": h.id, "x": round(h.x, 1), "y": round(h.y, 1),
                        "node": h.node, "crossroad": h.crossroad, "building": h.building}
                       for h in self.houses.values()],
            "key_buildings": [{"id": kb.id, "name": kb.name, "x": round(kb.x, 1), "y": round(kb.y, 1),
                               "node": kb.node, "crossroad": kb.crossroad, "house": kb.house,
                               "interior": kb.interior}
                              for kb in self.key_buildings.values()],
            "river": {"pts": [[round(x, 1), round(y, 1)] for x, y in (self.river.get("pts") or [])],
                      "w": self.river.get("w", 0)},
            "walls": [[round(x, 1), round(y, 1)] for x, y in self.walls],
        }
