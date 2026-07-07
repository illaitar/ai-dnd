"""Порт геометрии Watabou One Page Dungeon — 1-в-1 по декомпиляции бандла
(com.watabou.dungeon.*: Room/Planner/grow/createLoop/cleanUp/shapeRooms/Flood) и цитате
автора: «аккреция дерева комнат с частичной зеркальной симметрией, потом циклы».

Ключевые механизмы оригинала (docs/dungeons.md §2):
- комната = прямоугольник с ОСЬЮ и входом на оси; ширины НЕЧЁТНЫЕ; коридор = та же
  комната (узкий класс размера);
- очередь спавна {seed, parent, door, axis, size, mirror}; зеркальные близнецы получают
  ОДИН seed → поддеревья разворачиваются идентично-зеркально (частичная симметрия);
- grow(): группы близнецов синхронно распухают вдоль оси до соприкосновения с соседями —
  секрет плотности и общих стен;
- createLoop(): пары несвязанных комнат с общей стеной ≥3 клеток и графовым расстоянием
  >5 получают дверь в середину стены (машинный jaquaysing);
- cleanUp(): тупиковые коридоры с одной дверью умирают, хвосты подрезаются до двери;
- shapeRooms(): симметричные группы становятся ротондами; Flood(): вода = шум + порог,
  только внутри комнат; колоннады в длинных залах.
Выход — нейтральный формат (rooms/edges/water/columns), драматургию (цель/ключи/секретные
крылья/backdoor) поверх наводит Planner в dungeongen.

Key functions
-------------
Room(...) : Rectangular dungeon room/corridor with axis-aligned door and parent links.
Layout(seed, rooms_target, ...) : Generates dungeon via seeded accretion and growth.
Layout.build(origin) -> bool : Orchestrates accretion, grow, loops, and shaping.
Layout.export() -> dict : Exports neutral format (rooms, edges, water, columns).
layout(seed, ..., origin) -> dict | None : Public API; generates dungeon or None.
"""

from __future__ import annotations

import random

# классы размеров из getRoomSize оригинала: (варианты ширины, (мин, макс) глубины)
SIZES = {0: ((5, 7), (4, 6)),        # комната
         1: ((5, 7, 9), (7, 9)),     # зал
         2: ((3,), (4, 5)),          # короткий коридор
         3: ((3,), (3, 3))}          # клетка-сочленение
GROW_CAP = 10


def _perp(axis, mirror: bool):
    ax, ay = axis
    return (ay, -ax) if not mirror else (-ay, ax)


class Room:
    __slots__ = ("id", "door", "axis", "w", "d", "size", "group", "mirror", "parent",
                 "round", "tags")

    def __init__(self, rid, door, axis, w, d, size, group, mirror, parent):
        self.id = rid
        self.door = door                              # клетка входа (внутри комнаты, на оси)
        self.axis = axis
        self.w = w
        self.d = d
        self.size = size
        self.group = group                            # группа зеркальных близнецов
        self.mirror = mirror
        self.parent = parent
        self.round = False
        self.tags: list = []

    def cells(self, d=None) -> set:
        px, py = _perp(self.axis, False)
        out = set()
        for i in range(d if d is not None else self.d):
            for j in range(-(self.w // 2), self.w // 2 + 1):
                out.add((self.door[0] + self.axis[0] * i + px * j,
                         self.door[1] + self.axis[1] * i + py * j))
        return out

    def row(self, i) -> set:
        px, py = _perp(self.axis, False)
        return {(self.door[0] + self.axis[0] * i + px * j,
                 self.door[1] + self.axis[1] * i + py * j)
                for j in range(-(self.w // 2), self.w // 2 + 1)}


class Layout:
    def __init__(self, seed: str, rooms_target: int = 18, order_p: float = 0.75,
                 corridor_p: float = 0.3, string: bool = False, hall_p: float = 0.15,
                 rotunda_p: float = 0.45, water_p: float = 0.45):
        self.rng = random.Random(f"wtb|{seed}")
        self.rooms: list[Room] = []
        self.occ: dict = {}                           # клетка → id комнаты
        self.blocked: set = set()                     # зона у дверей — не застраивать
        self.doors: list = []                         # {a, b, cells:(ca, cb), kind}
        self.target = rooms_target
        self.order_p = order_p                        # доля симметричных спавнов
        self.corridor_p = corridor_p
        self.string = string                          # цепочка без ветвления
        self.hall_p = hall_p
        self.rotunda_p = rotunda_p
        self.water_p = water_p
        self.groups: dict = {}                        # group → [room ids]

    # ── аккреция: очередь близнецов + ДОБОР случайной комнатой (как у автора:
    # «until end condition we pick one of the rooms and add children») ─────────
    def build(self, origin=(0, 0)) -> bool:
        q = [{"seed": self.rng.random(), "parent": None, "door": tuple(origin),
              "axis": (0, 1), "size": 0, "mirror": False, "group": 0}]
        gid = 1
        guard = 0
        while len(self.rooms) < self.target and guard < self.target * 40:
            guard += 1
            if not q:                                 # дерево заглохло — добираем К ЦЕНТРУ
                cx = sum(c[0] for c in self.occ) / max(1, len(self.occ))
                cy = sum(c[1] for c in self.occ) / max(1, len(self.occ))
                pool = sorted(self.rooms, key=lambda rr: abs(rr.door[0] - cx)
                              + abs(rr.door[1] - cy))[:max(3, len(self.rooms) // 3)]
                r = self.rng.choice(pool)
                rng = random.Random(f"re|{self.rng.random()}")
                q += self._plan_children(rng, r, self.target - len(self.rooms),
                                         force=True)
                for k in q:
                    k.setdefault("group", gid)
                gid += 1
                continue
            task = q.pop(0)
            r = self._place(task)
            if r is None:
                continue
            rng = random.Random(task["seed"])         # ДЕТИ из seed задачи: близнецы
            rng.random()                              # (сдвиг после размерных бросков)
            kids = self._plan_children(rng, r, self.target - len(self.rooms))
            for k in kids:
                if k.get("group") is None or "group" not in k:
                    k["group"] = gid
            gid += 1
            q += kids
        if len(self.rooms) < max(6, self.target // 3):
            return False
        self._grow()
        self._create_loops()
        self._clean_up()
        self._create_loops(min_run=2, min_dist=5)     # добрать петли на выжившей укладке
        self._shape_rooms()
        self.backdoor = None                          # addBackdoor: запасной вход с края
        if self.rng.random() < 0.6 and len(self.rooms) > 6:
            per = [r for r in self.rooms if r.size < 2 and r.id != self.rooms[0].id]
            if per:
                far = max(per, key=lambda rr: abs(rr.door[0]) + abs(rr.door[1]))
                self.backdoor = far.id
        return True

    def _place(self, t) -> Room | None:
        rng = random.Random(t["seed"])
        ws, (dlo, dhi) = SIZES[t["size"]]
        w = rng.choice(ws)
        d = rng.randint(dlo, dhi)
        r = Room(len(self.rooms), t["door"], t["axis"], w, d, t["size"],
                 t["group"], t["mirror"], t["parent"])
        cells = r.cells()
        if any(c in self.occ or c in self.blocked for c in cells):
            for dd in range(d - 1, max(dlo - 2, 1), -1):  # ужаться, но встать
                cells = r.cells(dd)
                if not any(c in self.occ or c in self.blocked for c in cells):
                    r.d = dd
                    break
            else:
                return None
        self.rooms.append(r)
        self.groups.setdefault(r.group, []).append(r.id)
        for c in r.cells():
            self.occ[c] = r.id
        if t["parent"] is not None:                   # дверь к родителю + блок вокруг неё
            back = (t["door"][0] - t["axis"][0], t["door"][1] - t["axis"][1])
            self.doors.append({"a": t["parent"], "b": r.id,
                               "cells": (back, t["door"]), "kind": "door"})
            px, py = _perp(t["axis"], False)
            for j in (-1, 1):
                self.blocked.add((back[0] + px * j, back[1] + py * j))
        return r

    def _plan_children(self, rng, r: Room, budget: int, force: bool = False) -> list:
        """Спавн-паттерны оригинала: симметричная пара по бокам / ребёнок по оси в дальнем
        торце / всё сразу; изредка асимметрия со свежими seed; string — один ребёнок."""
        if budget <= 0:
            return []
        px, py = _perp(r.axis, r.mirror)
        far = (r.door[0] + r.axis[0] * (r.d - 1), r.door[1] + r.axis[1] * (r.d - 1))

        def side_task(sign, seed, mirror, size, t_row):
            edge = r.w // 2 + 1
            cell = (r.door[0] + r.axis[0] * t_row + px * sign * edge,
                    r.door[1] + r.axis[1] * t_row + py * sign * edge)
            return {"seed": seed, "parent": r.id, "door": cell,
                    "axis": (px * sign, py * sign), "size": size, "mirror": mirror}

        def fwd_task(seed, size):
            cell = (far[0] + r.axis[0], far[1] + r.axis[1])
            return {"seed": seed, "parent": r.id, "door": cell, "axis": r.axis,
                    "size": size, "mirror": r.mirror}

        def child_size():
            if r.size >= 2:                           # из коридора чаще комната/зал
                return 0 if rng.random() > 0.25 else 1
            roll = rng.random()
            if roll < self.corridor_p:
                return 2 if rng.random() < 0.7 else 3
            return 1 if roll > 1.0 - self.hall_p else 0

        if self.string:
            return [fwd_task(rng.random(), child_size())]
        out = []
        pattern = rng.random() * (0.85 if force else 1.0)  # добор не имеет права на «лист»
        symmetric = rng.random() < self.order_p
        t_row = rng.randint(1, max(1, r.d - 2))
        if pattern < 0.45:                            # пара по бокам
            size = child_size()
            if symmetric:
                seed = rng.random()                   # ОДИН seed на близнецов
                out = [side_task(+1, seed, r.mirror, size, t_row),
                       side_task(-1, seed, not r.mirror, size, t_row)]
                out[0]["group"] = out[1]["group"] = None
            else:
                out = [side_task(s, rng.random(), r.mirror if s > 0 else not r.mirror,
                                 child_size(), rng.randint(1, max(1, r.d - 2)))
                       for s in (+1, -1) if rng.random() < 0.75]
        elif pattern < 0.7:                           # вперёд по оси
            out = [fwd_task(rng.random(), child_size())]
        elif pattern < 0.85:                          # тройня: пара + вперёд
            size = child_size()
            seed = rng.random()
            out = [side_task(+1, seed, r.mirror, size, t_row),
                   side_task(-1, seed, not r.mirror, size, t_row),
                   fwd_task(rng.random(), child_size())]
            out[0]["group"] = out[1]["group"] = None
        # else: лист (без детей)
        for _i, k in enumerate(out):                   # общая группа для близнецов с 1 seed
            if k.get("group", "x") is None:
                k["group"] = ("twin", k["seed"])
        return out

    # ── grow: близнецы синхронно распухают вдоль оси до соприкосновения ─────
    def _grow(self):
        alive = {g: list(ids) for g, ids in self.groups.items()}
        guard = 0
        while alive and guard < 400:
            guard += 1
            for g in list(alive):
                rs = [self.rooms[i] for i in alive[g]]
                if any(r.d >= GROW_CAP for r in rs):
                    del alive[g]
                    continue
                p_stop = max(0.0, (rs[0].d / max(1, rs[0].w)) - 0.8) * 0.5
                if self.rng.random() < p_stop:
                    del alive[g]
                    continue
                new_rows = [r.row(r.d) for r in rs]
                if any(c in self.occ or c in self.blocked
                       for row in new_rows for c in row):
                    del alive[g]
                    continue
                for r, row in zip(rs, new_rows):
                    r.d += 1
                    for c in row:
                        self.occ[c] = r.id
            if not alive:
                break

    # ── петли: общая стена ≥3 клеток + графовое расстояние >5 → дверь ───────
    def _linked(self) -> set:
        return {frozenset((d["a"], d["b"])) for d in self.doors}

    def _graph_dist(self, src) -> dict:
        adj: dict = {}
        for dr in self.doors:
            adj.setdefault(dr["a"], []).append(dr["b"])
            adj.setdefault(dr["b"], []).append(dr["a"])
        dist, q = {src: 0}, [src]
        qi = 0
        while qi < len(q):
            cur = q[qi]
            qi += 1
            for nb in adj.get(cur, []):
                if nb not in dist:
                    dist[nb] = dist[cur] + 1
                    q.append(nb)
        return dist

    def _shared_runs(self, a: Room, b: Room) -> list:
        """Отрезки общей стены: последовательные пары соседних клеток A|B."""
        ac, bc = a.cells(), b.cells()
        pairs = []
        for (x, y) in ac:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (x + dx, y + dy) in bc:
                    pairs.append(((x, y), (x + dx, y + dy)))
        runs: list = []
        for p in sorted(pairs):
            placed = False
            for run in runs:
                if any(abs(p[0][0] - q[0][0]) + abs(p[0][1] - q[0][1]) == 1 for q in run):
                    run.append(p)
                    placed = True
                    break
            if not placed:
                runs.append([p])
        return runs

    def _create_loops(self, min_run: int = 3, min_dist: int = 6):
        guard = 0
        while guard < 30:
            guard += 1
            linked = self._linked()
            best = None
            for a in self.rooms:
                dist = self._graph_dist(a.id)
                for b in self.rooms:
                    if b.id <= a.id or frozenset((a.id, b.id)) in linked:
                        continue
                    if dist.get(b.id, 99) < min_dist:
                        continue
                    runs = [r_ for r_ in self._shared_runs(a, b) if len(r_) >= min_run]
                    if runs:
                        best = (a.id, b.id, runs[0])
                        break
                if best:
                    break
            if not best:
                return
            a, b, run = best
            mid = run[len(run) // 2]
            self.doors.append({"a": a, "b": b, "cells": mid,
                               "kind": "portcullis" if self.string else "door"})

    # ── cleanup: тупиковые коридоры умирают, хвосты подрезаются ─────────────
    def _clean_up(self):
        changed = True
        while changed:
            changed = False
            deg: dict = {}
            for dr in self.doors:
                deg[dr["a"]] = deg.get(dr["a"], 0) + 1
                deg[dr["b"]] = deg.get(dr["b"], 0) + 1
            for r in list(self.rooms):
                if r.size >= 2 and deg.get(r.id, 0) == 1 and r.parent is not None:
                    self._remove(r)
                    changed = True
        for r in self.rooms:                          # подрезать хвост коридора до двери
            if r.size < 2:
                continue
            rows_with_door = [0]
            for dr in self.doors:
                cell = dr["cells"][0] if self.occ.get(dr["cells"][0]) == r.id \
                    else dr["cells"][1]
                i = (cell[0] - r.door[0]) * r.axis[0] + (cell[1] - r.door[1]) * r.axis[1]
                rows_with_door.append(max(0, i))
            keep = min(r.d, max(rows_with_door) + 1)
            if keep < r.d:
                for i in range(keep, r.d):
                    for c in r.row(i):
                        self.occ.pop(c, None)
                r.d = keep

    def _remove(self, r: Room):
        for c in r.cells():
            self.occ.pop(c, None)
        self.rooms = [x for x in self.rooms if x.id != r.id]
        self.doors = [d for d in self.doors if r.id not in (d["a"], d["b"])]

    # ── формы: ротонды у симметричных групп ─────────────────────────────────
    def _shape_rooms(self):
        deg: dict = {}
        for dr in self.doors:
            deg[dr["a"]] = deg.get(dr["a"], 0) + 1
            deg[dr["b"]] = deg.get(dr["b"], 0) + 1
        for g, _ids in self.groups.items():
            rs = [r for r in self.rooms if r.group == g]
            if not rs:
                continue
            can = all(r.size <= 1 and r.w >= 5 and abs(r.w - r.d) <= 2
                      and deg.get(r.id, 0) <= 2 for r in rs)
            if can and self.rng.random() < self.rotunda_p:
                for r in rs:
                    r.round = True

    # ── экспорт ──────────────────────────────────────────────────────────────
    def export(self) -> dict:
        id_map = {r.id: i for i, r in enumerate(self.rooms)}
        rooms = []
        for r in self.rooms:
            cells = r.cells()
            if r.round:                               # ротонда: круг из клеток
                cx = sum(c[0] for c in cells) / len(cells) + 0.0
                cy = sum(c[1] for c in cells) / len(cells) + 0.0
                rad = min(r.w, r.d) / 2
                cells = {c for c in cells
                         if (c[0] - cx) ** 2 + (c[1] - cy) ** 2 <= rad * rad + 0.6} or cells
            rooms.append({"id": id_map[r.id], "size": r.size, "round": r.round,
                          "tiles": sorted(cells), "axis": list(r.axis),
                          "parent": id_map.get(r.parent), "tags": list(r.tags)})
        edges = [{"a": id_map[d["a"]], "b": id_map[d["b"]],
                  "door": [*d["cells"][0], *d["cells"][1]], "kind": d["kind"],
                  "lock": None, "path": []}
                 for d in self.doors if d["a"] in id_map and d["b"] in id_map]
        # вода: value-шум + порог, только внутри комнат
        water = []
        wseed = self.rng.random()
        if self.rng.random() < self.water_p:
            level = self.rng.uniform(0.62, 0.78)
            for r in rooms:
                for (x, y) in r["tiles"]:
                    n = (random.Random(f"{round(x / 3)}|{round(y / 3)}|{wseed}").random()
                         * 0.6 + random.Random(f"{x}|{y}|{wseed}").random() * 0.4)
                    if n > level:
                        water.append([x, y])
        # колонны: колоннады вдоль длинных залов, кольцо в ротондах
        columns = []
        for r, src in zip(rooms, self.rooms):
            xs = [t[0] for t in r["tiles"]]
            ys = [t[1] for t in r["tiles"]]
            w_ = max(xs) - min(xs) + 1
            h_ = max(ys) - min(ys) + 1
            if r["round"] and min(w_, h_) >= 6:
                cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                for (x, y) in r["tiles"]:
                    if abs(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 - min(w_, h_) / 3.2) < 0.55:
                        columns.append([x, y])
            elif src.size == 1 and max(w_, h_) >= 7 and min(w_, h_) >= 5 \
                    and not r["round"] and self.rng.random() < 0.3:
                horiz = w_ >= h_
                for i in range(min(xs) + 1 if horiz else min(ys) + 1,
                               (max(xs) if horiz else max(ys)), 2):
                    for off in (min(ys) + 1, max(ys) - 1) if horiz \
                            else (min(xs) + 1, max(xs) - 1):
                        columns.append([i, off] if horiz else [off, i])
        return {"rooms": rooms, "edges": edges, "water": water, "columns": columns,
                "backdoor": id_map.get(getattr(self, "backdoor", None))}


def layout(seed: str, rooms_target: int = 18, order_p: float = 0.75,
           corridor_p: float = 0.3, string: bool = False, hall_p: float = 0.15,
           rotunda_p: float = 0.45, water_p: float = 0.45,
           origin=(0, 0)) -> dict | None:
    lay = Layout(seed, rooms_target, order_p, corridor_p, string, hall_p,
                 rotunda_p, water_p)
    return lay.export() if lay.build(origin) else None
