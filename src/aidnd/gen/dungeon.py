"""Генератор подземелий (док 05/07): детерминированно строит многоэтажный данж из
DungeonBrief — граф комнат → тайловые этажи с комнатами РАЗНОЙ ФОРМЫ и СКРЫТЫМИ
комнатами за секретными дверями.

Два слоя (как обсуждали):
  • логика — граф комнат (роли, рёбра door|locked|secret|stairs), на нём держатся
    навигация/бой/квесты/туман;
  • тайлы — раскладка графа на сетку каждого этажа (комнаты вырезаются формой,
    рёбра прорезаются коридорами); это «карта».

Всё сидируется (`subseed(seed,"dungeon",site_key,...)`) → переживает сейв/лоад и
golden-replay. LLM трогает только флавор (имена/описания) — здесь его нет.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .seeds import subseed

# --- тайлы (terrain) ------------------------------------------------------- #
WALL = "#"
FLOOR = "."
DOOR = "+"
LOCKED = "="
SECRET = "%"          # секретная дверь: на карте — стена, пока не найдена
STAIRS_DN = ">"
STAIRS_UP = "<"
ENTRANCE = "E"
PILLAR = "o"          # колонна-препятствие внутри комнаты (непроходимо)
PASSABLE = {FLOOR, DOOR, LOCKED, SECRET, STAIRS_DN, STAIRS_UP, ENTRANCE}

# роли комнат (что в комнате) и формы (как вырезана на тайлах)
ROLES = {"entrance", "hub", "combat", "treasure", "boss", "lore", "secret", "landing"}
SHAPES = {"rect", "hall", "L", "cross", "pillared", "cave", "cavern", "round"}

# тема → пул форм (пещера — органика, склеп/форт — геометрия и т.п.)
THEME_SHAPES = {
    "cave":  ["cave", "cavern", "round", "rect"],
    "mine":  ["cave", "hall", "rect", "L"],
    "crypt": ["rect", "cross", "hall", "pillared"],
    "manor": ["rect", "L", "hall", "pillared"],
    "fort":  ["rect", "L", "cross", "pillared"],
}


@dataclass
class Room:
    rid: str
    role: str
    shape: str
    floor: int
    parent: str | None = None
    entry: str = "door"               # как входят: door|locked|secret|stairs
    secret: bool = False
    cells: set[tuple[int, int]] = field(default_factory=set)  # тайлы пола комнаты
    center: tuple[int, int] = (0, 0)
    contents: list[dict] = field(default_factory=list)        # encounter|treasure|key|boss


@dataclass
class Floor:
    index: int
    w: int
    h: int
    grid: list[list[str]]
    rooms: list[str] = field(default_factory=list)


@dataclass
class Dungeon:
    site_key: str
    theme: str
    tier: int
    floors: list[Floor]
    rooms: dict[str, Room]
    edges: list[tuple[str, str, str]]     # (a, b, kind)
    entrance: str
    boss_room: str

    def floor(self, i: int) -> Floor:
        return self.floors[i]

    def neighbors(self, rid: str) -> list[tuple[str, str]]:
        out = []
        for a, b, k in self.edges:
            if a == rid:
                out.append((b, k))
            elif b == rid:
                out.append((a, k))
        return out


@dataclass
class DungeonBrief:
    site_key: str
    theme: str = "cave"               # cave|mine|crypt|manor|fort
    tier: int = 2
    floors: int = 2
    faction: str | None = None
    boss: str | None = None           # npc-id босса (иначе сгенерируется заглушка)
    objective: str = "clear"          # clear|retrieve|rescue|descend
    key_loot: str = "tmpl:rusty_key"  # предмет-ключ к запертой двери


# --------------------------------------------------------------------------- #
#  1) Логический граф комнат (грамматика lock-and-key)                         #
# --------------------------------------------------------------------------- #
def _plan(brief: DungeonBrief, rng: random.Random) -> tuple[dict[str, Room], list[tuple[str, str, str]]]:
    """Малый MVP-граф: вход→развилка→{ветка-страж(ключ)→сокровищница→СЕКРЕТ, лестница},
    запертая дверь к боссу гейтится ключом (часто на другом этаже)."""
    sk = brief.site_key
    shapes = THEME_SHAPES.get(brief.theme, THEME_SHAPES["cave"])
    boss_shapes = [s for s in ("cavern", "cross", "pillared") if s in SHAPES]

    def shape_for(role: str) -> str:
        if role == "boss":
            return rng.choice(boss_shapes)
        if role in ("entrance", "landing"):
            return rng.choice(["rect", "hall"])
        if role == "secret":
            return rng.choice(["round", "rect"])
        return rng.choice(shapes)

    rooms: dict[str, Room] = {}
    edges: list[tuple[str, str, str]] = []

    def add(role: str, floor: int, parent: str | None, entry: str, secret: bool = False) -> str:
        n = sum(1 for r in rooms.values() if r.role == role)
        rid = f"room:{sk}:{floor}:{role}{n}"
        rooms[rid] = Room(rid=rid, role=role, shape=shape_for(role), floor=floor,
                          parent=parent, entry=entry, secret=secret)
        if parent:
            edges.append((parent, rid, entry))
        return rid

    two = brief.floors >= 2
    boss_floor = 1 if two else 0

    entrance = add("entrance", 0, None, "door")
    hub = add("hub", 0, entrance, "door")
    guard = add("combat", 0, hub, "door")          # тут лежит ключ
    treasure = add("treasure", 0, guard, "door")
    add("secret", 0, treasure, "secret", secret=True)   # СКРЫТАЯ комната за секретной дверью

    if two:
        stairs_room = add("hub", 0, hub, "door")        # ниша с лестницей вниз
        landing = add("landing", 1, None, "door")
        edges.append((stairs_room, landing, "stairs"))
        boss = add("boss", boss_floor, landing, "locked")   # запертая дверь к боссу
    else:
        boss = add("boss", 0, hub, "locked")

    rooms[guard].contents.append({"kind": "key", "item": brief.key_loot})
    rooms[treasure].contents.append({"kind": "treasure", "rank": brief.tier})
    for r in rooms.values():
        if r.secret:
            r.contents.append({"kind": "treasure", "rank": brief.tier + 1, "hidden": True})
    rooms[guard].contents.append({"kind": "encounter", "faction": brief.faction,
                                  "n": 1 + brief.tier // 2})
    rooms[boss].contents.append({"kind": "boss", "npc": brief.boss, "faction": brief.faction})
    return rooms, edges


# --------------------------------------------------------------------------- #
#  2) Раскладка этажа на тайлы: макро-сетка → формы комнат → коридоры/двери     #
# --------------------------------------------------------------------------- #
CW, CH = 9, 7                          # размер макро-ячейки в тайлах


def _carve_shape(grid, shape, inner, rng) -> tuple[set, tuple[int, int]]:
    """Вырезает комнату заданной ФОРМЫ внутри inner=(x0,y0,x1,y1). Возвращает
    множество клеток пола и центр (гарантированно — пол)."""
    x0, y0, x1, y1 = inner
    H, W = len(grid), len(grid[0])
    cells: set[tuple[int, int]] = set()

    def put(x, y):
        if 0 <= x < W and 0 <= y < H and x0 <= x <= x1 and y0 <= y <= y1:
            grid[y][x] = FLOOR
            cells.add((x, y))

    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    if shape == "rect":
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                put(x, y)
    elif shape == "hall":
        if (x1 - x0) >= (y1 - y0):                      # горизонтальный зал
            for y in range(cy, cy + 1 + (1 if (y1 - y0) >= 3 else 0)):
                for x in range(x0, x1 + 1):
                    put(x, y)
        else:
            for x in range(cx, cx + 1 + (1 if (x1 - x0) >= 3 else 0)):
                for y in range(y0, y1 + 1):
                    put(x, y)
    elif shape == "L":
        for y in range(y0, y1 + 1):                     # полный прямоугольник…
            for x in range(x0, x1 + 1):
                put(x, y)
        qx, qy = rng.choice([(x0, y0), (x1, y0), (x0, y1), (x1, y1)])  # …минус угол
        mx, my = (x0 + x1) // 2, (y0 + y1) // 2
        for (x, y) in list(cells):
            if (x <= mx) == (qx <= mx) and (y <= my) == (qy <= my):
                grid[y][x] = WALL
                cells.discard((x, y))
    elif shape == "cross":
        bw = max(1, (x1 - x0) // 3)
        bh = max(1, (y1 - y0) // 3)
        for y in range(y0, y1 + 1):
            for x in range(cx - bw, cx + bw + 1):
                put(x, y)
        for x in range(x0, x1 + 1):
            for y in range(cy - bh, cy + bh + 1):
                put(x, y)
    elif shape == "pillared":
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                put(x, y)
        for y in range(y0 + 1, y1, 2):                  # решётка колонн
            for x in range(x0 + 1, x1, 2):
                if (x, y) != (cx, cy):
                    grid[y][x] = PILLAR
                    cells.discard((x, y))
    else:  # cave | cavern | round — органическая форма по эллипсу
        rx = max(0.5, (x1 - x0) / 2)
        ry = max(0.5, (y1 - y0) / 2)
        fcx, fcy = (x0 + x1) / 2, (y0 + y1) / 2
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if ((x - fcx) / rx) ** 2 + ((y - fcy) / ry) ** 2 <= 1.0:
                    put(x, y)
        if shape != "round":                            # рваные края для пещеры
            erode = 0.30 if shape == "cave" else 0.18
            for (x, y) in list(cells):
                edge = any(grid[y + dy][x + dx] == WALL
                           for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                           if 0 <= y + dy < H and 0 <= x + dx < W)
                if edge and rng.random() < erode:
                    grid[y][x] = WALL
                    cells.discard((x, y))
    if not cells:                                       # страховка
        put(cx, cy)
    center = min(cells, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)
    return cells, center


def _carve_corridor(grid, a_center, b_center, door_char, macro_border) -> None:
    """L-коридор между центрами + дверь нужного типа на границе макро-ячеек."""
    ax, ay = a_center
    bx, by = b_center
    door_cell = None
    axis, bval = macro_border
    for x in range(min(ax, bx), max(ax, bx) + 1):       # горизонтальный сегмент (на y=ay)
        if grid[ay][x] == WALL:
            grid[ay][x] = FLOOR
        if axis == "x" and x == bval:
            door_cell = (x, ay)
    for y in range(min(ay, by), max(ay, by) + 1):       # вертикальный сегмент (на x=bx)
        if grid[y][bx] == WALL:
            grid[y][bx] = FLOOR
        if axis == "y" and y == bval:
            door_cell = (bx, y)
    if door_cell is None:
        door_cell = (bx, ay) if axis == "x" else (ax, by)
    dx, dy = door_cell
    grid[dy][dx] = door_char


def _place_macro(floor_rooms, rooms, anchor, rng) -> dict[str, tuple[int, int]]:
    """BFS-раскладка комнат этажа по макро-ячейкам: ребёнок — в свободную ячейку,
    ортогонально смежную родителю (со слабиной сетки находится всегда)."""
    n = len(floor_rooms)
    gcols = int(math.ceil(math.sqrt(n))) + 1
    placed: dict[str, tuple[int, int]] = {anchor: (0, 0)}
    used = {(0, 0)}
    order = [anchor]
    children: dict[str, list[str]] = {}
    for rid in floor_rooms:
        r = rooms[rid]
        if r.parent in floor_rooms or rid == anchor:
            children.setdefault(r.parent, []).append(rid)
    i = 0
    while i < len(order):
        cur = order[i]; i += 1
        for child in children.get(cur, []):
            px, py = placed[cur]
            opts = [(px + dx, py + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
            free = [c for c in opts if c[0] >= 0 and c[1] >= 0 and c not in used]
            if not free:                                # запасной путь: ближайшая свободная
                cand = [(x, y) for x in range(gcols + 1) for y in range(gcols + 1)
                        if (x, y) not in used]
                free = [min(cand, key=lambda c: abs(c[0] - px) + abs(c[1] - py))]
            cell = rng.choice(free) if len(free) > 1 else free[0]
            placed[child] = cell
            used.add(cell)
            order.append(child)
    return placed


def _layout_floor(idx, floor_rooms, rooms, edges, rng) -> Floor:
    anchor = next(r for r in floor_rooms if rooms[r].parent not in floor_rooms)
    cells_at = _place_macro(floor_rooms, rooms, anchor, rng)
    gx = max(c[0] for c in cells_at.values()) + 1
    gy = max(c[1] for c in cells_at.values()) + 1
    W, H = gx * CW, gy * CH
    grid = [[WALL] * W for _ in range(H)]

    for rid in floor_rooms:                              # вырезаем комнаты формой
        mx, my = cells_at[rid]
        inner = (mx * CW + 1, my * CH + 1, mx * CW + CW - 2, my * CH + CH - 2)
        # лёгкая вариация габаритов комнаты (не на всю ячейку)
        x0, y0, x1, y1 = inner
        x0 += rng.randint(0, 1); y0 += rng.randint(0, 1)
        x1 -= rng.randint(0, 1); y1 -= rng.randint(0, 1)
        cset, center = _carve_shape(grid, rooms[rid].shape, (x0, y0, x1, y1), rng)
        rooms[rid].cells = cset
        rooms[rid].center = center

    for a, b, kind in edges:                             # коридоры/двери (внутри этажа)
        if a not in floor_rooms or b not in floor_rooms:
            continue
        (ax, ay), (bx, by) = cells_at[a], cells_at[b]
        if ax != bx:                                     # горизонтально смежные
            border = ("x", max(ax, bx) * CW)
        else:                                            # вертикально смежные
            border = ("y", max(ay, by) * CH)
        ch = {"locked": LOCKED, "secret": SECRET}.get(kind, DOOR)
        _carve_corridor(grid, rooms[a].center, rooms[b].center, ch, border)

    for rid in floor_rooms:                              # маркеры входа/лестниц
        r = rooms[rid]
        cx, cy = r.center
        if r.role == "entrance":
            grid[cy][cx] = ENTRANCE
        for a, b, kind in edges:
            if kind == "stairs" and a == rid:
                grid[cy][cx] = STAIRS_DN
            if kind == "stairs" and b == rid:
                grid[cy][cx] = STAIRS_UP

    f = Floor(index=idx, w=W, h=H, grid=grid, rooms=list(floor_rooms))
    return f


# --------------------------------------------------------------------------- #
#  Сборка                                                                      #
# --------------------------------------------------------------------------- #
def generate(brief: DungeonBrief, seed: int) -> Dungeon:
    rng = random.Random(subseed(seed, "dungeon", brief.site_key, brief.theme))
    rooms, edges = _plan(brief, rng)
    nfloors = max(r.floor for r in rooms.values()) + 1
    floors = []
    for i in range(nfloors):
        fr = [rid for rid, r in rooms.items() if r.floor == i]
        floors.append(_layout_floor(i, fr, rooms, edges, random.Random(
            subseed(seed, "dungeon", brief.site_key, "floor", str(i))), ))
    entrance = next(r for r, rm in rooms.items() if rm.role == "entrance")
    boss = next(r for r, rm in rooms.items() if rm.role == "boss")
    return Dungeon(site_key=brief.site_key, theme=brief.theme, tier=brief.tier,
                   floors=floors, rooms=rooms, edges=edges, entrance=entrance, boss_room=boss)


# --------------------------------------------------------------------------- #
#  ASCII-дамп (отладка/проверка)                                               #
# --------------------------------------------------------------------------- #
_MARK = {"key": "K", "treasure": "T", "boss": "B", "encounter": "g"}


def render_ascii(d: Dungeon, floor_index: int, reveal_secret: bool = False) -> str:
    f = d.floor(floor_index)
    grid = [row[:] for row in f.grid]
    if not reveal_secret:                                # туман: секрет — глухая стена
        for y in range(f.h):
            for x in range(f.w):
                if grid[y][x] == SECRET:
                    grid[y][x] = WALL
        for rid in f.rooms:
            if d.rooms[rid].secret:
                for (x, y) in d.rooms[rid].cells:
                    grid[y][x] = WALL
    for rid in f.rooms:                                  # маркеры наполнения в центр комнаты
        r = d.rooms[rid]
        if r.secret and not reveal_secret:
            continue
        cx, cy = r.center
        for c in r.contents:
            mk = _MARK.get(c["kind"])
            if mk and grid[cy][cx] in (FLOOR, ENTRANCE):
                grid[cy][cx] = mk
                break
    head = (f"=== {d.site_key} · этаж {floor_index + 1}/{len(d.floors)} "
            f"({d.theme}, tier {d.tier}) ===")
    return head + "\n" + "\n".join("".join(row) for row in grid)


def shapes_used(d: Dungeon) -> dict[str, str]:
    return {rid: r.shape for rid, r in d.rooms.items()}
