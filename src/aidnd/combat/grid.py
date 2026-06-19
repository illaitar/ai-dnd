"""Тактическая боевая сетка (док 10 Навигация: A*/JPS на гриде).

Сетка строится из терраина карты (server/web/maps/<name>.json). Даёт всё, что
нужно бою «как в Baldur's Gate»: проходимость, стоимость движения (difficult
terrain), линию видимости, укрытие, высоту, дистанцию в футах (5e), достижимые
клетки за бюджет хода (Дейкстра) и путь A*.

Координаты — (col, row). Бой использует позиции ТОЛЬКО внутри энкаунтера; мировая
навигация остаётся графом связности локаций.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

FLOOR, WALL, WATER, RUBBLE, COVER, HIGH = ".", "#", "~", "^", "o", "H"
PASSABLE = {FLOOR, WATER, RUBBLE, HIGH}
DIFFICULT = {WATER, RUBBLE}        # стоят 10 футов за клетку
FT = 5                             # фут на клетку (5e)


@dataclass
class BattleGrid:
    cols: int
    rows: int
    cell: int
    terrain: list[str]                              # rows of codes
    party_spawn: list[tuple] = field(default_factory=list)
    enemy_spawn: list[tuple] = field(default_factory=list)

    @staticmethod
    def from_meta(meta: dict) -> BattleGrid:
        return BattleGrid(
            cols=meta["cols"], rows=meta["rows"], cell=meta.get("cell", 28),
            terrain=list(meta["terrain"]),
            party_spawn=[tuple(c) for c in meta.get("party_spawn", [])],
            enemy_spawn=[tuple(c) for c in meta.get("enemy_spawn", [])])

    @staticmethod
    def empty(cols=16, rows=12) -> BattleGrid:
        rows_s = ["." * cols for _ in range(rows)]
        g = BattleGrid(cols, rows, 28, rows_s)
        g.party_spawn = [(1, r) for r in range(2, 6)]
        g.enemy_spawn = [(cols - 2, r) for r in range(2, 8)]
        return g

    # --- запросы клеток --------------------------------------------------- #
    def code(self, x: int, y: int) -> str:
        if 0 <= x < self.cols and 0 <= y < self.rows:
            return self.terrain[y][x]
        return WALL

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.cols and 0 <= y < self.rows

    def is_passable(self, x: int, y: int) -> bool:
        return self.code(x, y) in PASSABLE

    def step_cost_ft(self, x: int, y: int) -> int:
        return 10 if self.code(x, y) in DIFFICULT else 5

    def blocks_los(self, x: int, y: int) -> bool:
        return self.code(x, y) == WALL

    def is_cover(self, x: int, y: int) -> bool:
        return self.code(x, y) in (WALL, COVER)

    def elevation(self, x: int, y: int) -> int:
        return 1 if self.code(x, y) == HIGH else 0

    # --- геометрия 5e ----------------------------------------------------- #
    @staticmethod
    def distance_squares(a: tuple, b: tuple) -> int:
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))     # Chebyshev (5-5-5)

    def distance_ft(self, a: tuple, b: tuple) -> int:
        return self.distance_squares(a, b) * FT

    def adjacent(self, a: tuple, b: tuple) -> bool:
        return a != b and self.distance_squares(a, b) == 1

    def neighbors(self, x: int, y: int):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if self.is_passable(nx, ny):
                    yield nx, ny

    # --- движение: достижимость и путь (док 10) --------------------------- #
    def reachable(self, start: tuple, budget_ft: int, occupied: set) -> dict:
        """Дейкстра: {клетка: стоимость_футов} в пределах бюджета. Через занятые
        клетки пройти нельзя (упрощённо). Старт исключён из occupied."""
        occ = occupied - {start}
        dist = {start: 0}
        pq = [(0, start)]
        while pq:
            d, cur = heapq.heappop(pq)
            if d > dist.get(cur, 1e9):
                continue
            for nx, ny in self.neighbors(*cur):
                if (nx, ny) in occ:
                    continue
                nd = d + self.step_cost_ft(nx, ny)
                if nd <= budget_ft and nd < dist.get((nx, ny), 1e9):
                    dist[(nx, ny)] = nd
                    heapq.heappush(pq, (nd, (nx, ny)))
        dist.pop(start, None)
        return dist

    def path(self, start: tuple, goal: tuple, occupied: set) -> list:
        """A* (octile) до goal; путь как список клеток без старта. [] если нет."""
        if not self.is_passable(*goal) or goal in (occupied - {start}):
            return []
        occ = occupied - {start, goal}

        def h(c):
            return self.distance_squares(c, goal) * FT
        openpq = [(h(start), 0, start)]
        came, g = {}, {start: 0}
        while openpq:
            _, cost, cur = heapq.heappop(openpq)
            if cur == goal:
                out = [cur]
                while cur in came:
                    cur = came[cur]
                    out.append(cur)
                return list(reversed(out))[1:]
            for nx, ny in self.neighbors(*cur):
                if (nx, ny) in occ:
                    continue
                ng = cost + self.step_cost_ft(nx, ny)
                if ng < g.get((nx, ny), 1e9):
                    came[(nx, ny)] = cur
                    g[(nx, ny)] = ng
                    heapq.heappush(openpq, (ng + h((nx, ny)), ng, (nx, ny)))
        return []

    # --- линия видимости и укрытие ---------------------------------------- #
    def line(self, a: tuple, b: tuple) -> list:
        """Клетки на линии Брезенхэма от a до b включительно."""
        x0, y0 = a
        x1, y1 = b
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx - dy
        cells = []
        while True:
            cells.append((x0, y0))
            if (x0, y0) == (x1, y1):
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
        return cells

    def has_los(self, a: tuple, b: tuple) -> bool:
        for c in self.line(a, b)[1:-1]:
            if self.blocks_los(*c):
                return False
        return True

    def cover_bonus(self, a: tuple, b: tuple) -> int:
        """Бонус AC за укрытие (5e): половинное +2, три четверти +5."""
        mid = self.line(a, b)[1:-1]
        walls = sum(1 for c in mid if self.code(*c) == WALL)
        covers = sum(1 for c in mid if self.code(*c) == COVER)
        if walls:
            return 5
        if covers:
            return 2
        return 0
