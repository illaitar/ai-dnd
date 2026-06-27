"""Процедурная генерация боевой карты под описание локации.

Из (тип места, аффордансы, имя, фичи-из-описания) детерминированно строит тактическую сетку
террейн-кодов: размер и форма под архетип, фичи из описания (лотки/колодец/очаг → cover/water/high).

Архетипы города/зданий — шаблонная макро-структура (улицы, периметр-стены, фасады) + клеточный
автомат для органичных краёв; пещеры/дикие земли — клеточный автомат целиком; раскладка укрытий —
WFC-подобный рост кластеров (укрытия группируются естественно, а не рассыпаны). Детерминированно по
(seed, place) → одна и та же карта, кэш, реплей-сейф.

Коды: . пол  # стена  ~ вода  ^ щебень  o укрытие  H высота (см. combat/grid.py).
"""

from __future__ import annotations

import random

from ..combat.grid import COVER, FLOOR, HIGH, RUBBLE, WALL, WATER, BattleGrid
from .seeds import subseed

# архетип → (cols, rows)
SIZE = {
    "intersection": (20, 16), "shop": (16, 12), "tavern": (18, 14), "hall": (20, 15),
    "shrine": (16, 14), "house": (14, 11), "square": (24, 18), "cave": (20, 16),
    "wilds": (22, 16), "generic": (16, 12),
}
_ROLE = {"cover": COVER, "water": WATER, "high": HIGH, "rubble": RUBBLE}

# дефолтные фичи архетипа (когда LLM недоступен): роль → сколько
_DEFAULTS = {
    "intersection": [("cover", 5), ("rubble", 2)],
    "shop": [("cover", 6)], "tavern": [("cover", 7)], "hall": [("high", 4), ("cover", 2)],
    "shrine": [("high", 2), ("cover", 3)], "house": [("cover", 4)],
    "square": [("water", 1), ("cover", 5)], "cave": [("rubble", 6), ("water", 2)],
    "wilds": [("cover", 5), ("water", 3), ("rubble", 3)], "generic": [("cover", 4)],
}


def classify(kind: str, affordances, name: str = "") -> str:
    """Архетип боевой карты по типу места и аффордансам."""
    aff = set(affordances or [])
    nm, kd = (name or "").lower(), (kind or "").lower()
    if "shop" in aff:
        return "shop"
    if {"serve", "drink"} & aff:
        return "tavern"
    if "townhall" in aff:
        return "hall"
    if "shrine" in aff:
        return "shrine"
    if "площад" in nm or "рынок" in nm or "market" in kd:    # площадь раньше доски (на ней есть доска)
        return "square"
    if "board" in aff or "перекрёст" in nm or "улиц" in nm:
        return "intersection"
    if "lair" in kd or "пещер" in nm or "логов" in nm or "cave" in nm:
        return "cave"
    if kd in ("wilds", "site"):
        return "wilds"
    if kd in ("room", "house") or "residential" in aff or "дом" in nm:
        return "house"
    return "generic"


def _blank(cols: int, rows: int, ch: str) -> list[list[str]]:
    return [[ch] * cols for _ in range(rows)]


def _floor_cells(g, code=FLOOR) -> list[tuple]:
    return [(x, y) for y in range(len(g)) for x in range(len(g[0])) if g[y][x] == code]


# --------------------------------------------------------------------------- #
#  Клеточный автомат (органичные формы: каверны, неровные края застройки)      #
# --------------------------------------------------------------------------- #
def _cellular(g, rng, fill=0.45, iters=4, born=5, survive=4) -> None:
    """Классический CA пещер: рандом-заполнение стенами → сглаживание по числу соседей-стен.
    Меняет g на месте в области пола (стены-периметр не трогаем)."""
    rows, cols = len(g), len(g[0])
    for y in range(1, rows - 1):
        for x in range(1, cols - 1):
            g[y][x] = WALL if rng.random() < fill else FLOOR
    for _ in range(iters):
        snap = [row[:] for row in g]
        for y in range(1, rows - 1):
            for x in range(1, cols - 1):
                w = sum(snap[y + dy][x + dx] == WALL
                        for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx or dy))
                if snap[y][x] == WALL:
                    g[y][x] = WALL if w >= survive else FLOOR
                else:
                    g[y][x] = WALL if w >= born else FLOOR


def _largest_region(g) -> set:
    """Наибольшая связная область пола (4-связность) — остальное зашьём стенами."""
    rows, cols = len(g), len(g[0])
    seen, best = set(), set()
    for sy in range(rows):
        for sx in range(cols):
            if g[sy][sx] != FLOOR or (sx, sy) in seen:
                continue
            stack, region = [(sx, sy)], set()
            while stack:
                x, y = stack.pop()
                if (x, y) in seen or not (0 <= x < cols and 0 <= y < rows) or g[y][x] != FLOOR:
                    continue
                seen.add((x, y))
                region.add((x, y))
                stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
            if len(region) > len(best):
                best = region
    return best


# --------------------------------------------------------------------------- #
#  Макро-структура по архетипам                                                #
# --------------------------------------------------------------------------- #
def _building(cols, rows, rng, arch):
    """Интерьер здания: периметр-стены + дверь + пол; колонны для зала/святилища."""
    g = _blank(cols, rows, WALL)
    for y in range(1, rows - 1):
        for x in range(1, cols - 1):
            g[y][x] = FLOOR
    door = rng.randint(2, cols - 3)                      # дверной проём в нижней стене
    g[rows - 1][door] = FLOOR
    if arch in ("hall", "shrine"):                       # ряды колонн
        for cy in (rows // 3, 2 * rows // 3):
            for cx in range(cols // 4, cols - cols // 4 + 1, max(3, cols // 4)):
                g[cy][cx] = WALL
    floor = _floor_cells(g)
    party = [c for c in floor if c[1] >= rows - 3]
    enemy = [c for c in floor if c[1] <= 2]
    return g, floor, party, enemy


def _intersection(cols, rows, rng, arch=None):
    """Перекрёсток: две улицы крестом (пол) + угловые здания (стены) с неровными краями."""
    g = _blank(cols, rows, FLOOR)
    vx0, vx1 = cols // 2 - 3, cols // 2 + 2               # вертикальная улица
    hy0, hy1 = rows // 2 - 2, rows // 2 + 2               # горизонтальная улица
    for y in range(rows):
        for x in range(cols):
            if not (vx0 <= x <= vx1 or hy0 <= y <= hy1):
                g[y][x] = WALL                            # угловые кварталы
    for y in range(rows):                                # неровный край застройки у улиц
        for x in range(cols):
            if g[y][x] == WALL and rng.random() < 0.12:
                near = any(g[y + dy][x + dx] == FLOOR for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                           if 0 <= y + dy < rows and 0 <= x + dx < cols)
                if near:
                    g[y][x] = RUBBLE
    floor = _floor_cells(g)
    party = [c for c in floor if c[1] >= rows - 3 and vx0 <= c[0] <= vx1]
    enemy = [c for c in floor if c[1] <= 2 and vx0 <= c[0] <= vx1]
    return g, floor, party, enemy


def _square(cols, rows, rng, arch=None):
    """Площадь: открытое поле + фасады зданий по краям (с проёмами улиц) + центр под фичу."""
    g = _blank(cols, rows, FLOOR)
    gx0, gx1 = cols // 2 - 2, cols // 2 + 2
    gy0, gy1 = rows // 2 - 2, rows // 2 + 2
    for x in range(cols):                                # верх/низ — фасады, кроме проёма улицы
        if not gx0 <= x <= gx1:
            for d in (0, 1):
                g[d][x] = g[rows - 1 - d][x] = WALL
    for y in range(rows):                                # бока — фасады, кроме проёма
        if not gy0 <= y <= gy1:
            for d in (0, 1):
                g[y][d] = g[y][cols - 1 - d] = WALL
    floor = _floor_cells(g)
    party = [c for c in floor if c[1] >= rows - 4]
    enemy = [c for c in floor if c[1] <= 3]
    return g, floor, party, enemy


def _organic(cols, rows, rng, arch):
    """Пещера/дикие земли: клеточный автомат целиком, оставляем наибольшую каверну."""
    g = _blank(cols, rows, WALL)
    _cellular(g, rng, fill=0.45, iters=4)
    region = _largest_region(g)
    for y in range(rows):
        for x in range(cols):
            g[y][x] = FLOOR if (x, y) in region else WALL
    floor = sorted(region, key=lambda c: c[1])
    party = floor[-min(len(floor), 12):]                 # нижняя часть каверны
    enemy = floor[:min(len(floor), 12)]                  # верхняя часть
    return g, floor, party, enemy


def _open(cols, rows, rng, arch=None):
    """Generic: открытое поле со стенами по периметру."""
    g = _blank(cols, rows, FLOOR)
    for x in range(cols):
        g[0][x] = g[rows - 1][x] = WALL
    for y in range(rows):
        g[y][0] = g[y][cols - 1] = WALL
    floor = _floor_cells(g)
    party = [c for c in floor if c[1] >= rows - 3]
    enemy = [c for c in floor if c[1] <= 2]
    return g, floor, party, enemy


_BUILDERS = {"shop": _building, "tavern": _building, "hall": _building, "shrine": _building,
             "house": _building, "intersection": _intersection, "square": _square,
             "cave": _organic, "wilds": _organic}


# --------------------------------------------------------------------------- #
#  Раскладка фич: WFC-подобный рост кластеров (естественные группы укрытий)    #
# --------------------------------------------------------------------------- #
def _spaced(c, used, gap=1) -> bool:
    return all(abs(c[0] - u[0]) > gap or abs(c[1] - u[1]) > gap for u in used)


def _place_features(g, floor, features, rng) -> None:
    """Расставить фичи (cover/water/high/rubble) кластерами-«ростом»: ставим зерно и доращиваем
    соседними клетками (WFC-идея — клетка выбирается по соседям), чтобы группы были связными."""
    rows, cols = len(g), len(g[0])
    open_now = lambda: [(x, y) for (x, y) in floor if g[y][x] == FLOOR]
    used: set = set()
    for role, n in features:
        ch = _ROLE.get(role, COVER)
        budget = max(0, min(int(n), 9))
        cells = open_now()
        if not cells:
            break
        # предпочтение размещения: вода — к центру, укрытие/щебень — ближе к стенам
        cx, cy = cols / 2, rows / 2
        if ch == WATER:
            cells.sort(key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)
        else:
            def wallness(c):
                return -sum(g[c[1] + dy][c[0] + dx] == WALL
                            for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                            if 0 <= c[1] + dy < rows and 0 <= c[0] + dx < cols)
            cells.sort(key=wallness)
        placed = 0
        while placed < budget and cells:
            seed = next((c for c in cells if _spaced(c, used, 1)), cells[0])
            cluster = [seed]
            csize = 1 + (rng.randint(0, 2) if ch in (COVER, RUBBLE) else 0)  # вода/высота — точечно
            frontier = [seed]
            while len(cluster) < min(csize, budget - placed) and frontier:
                fx, fy = frontier.pop()
                nbrs = [(fx + dx, fy + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                        if 0 <= fx + dx < cols and 0 <= fy + dy < rows
                        and g[fy + dy][fx + dx] == FLOOR and (fx + dx, fy + dy) not in cluster]
                rng.shuffle(nbrs)
                if nbrs:
                    cluster.append(nbrs[0])
                    frontier.append(nbrs[0])
            for (x, y) in cluster:
                g[y][x] = ch
                used.add((x, y))
                placed += 1
            cells = [c for c in open_now() if _spaced(c, used, 1)]


def _pick_spawns(g, zone, rng, n) -> list:
    """n свободных клеток пола в зоне (с разбросом), сортируя по краю поля."""
    cands = [(x, y) for (x, y) in zone if g[y][x] == FLOOR]
    rng.shuffle(cands)
    out: list = []
    for c in cands:
        if all(abs(c[0] - o[0]) + abs(c[1] - o[1]) > 1 for o in out):
            out.append(c)                                # кортежи (движок кладёт спавны в set)
        if len(out) >= n:
            break
    if not out and cands:
        out = list(cands[:n])
    return out


def generate(seed: int, place_id: str, kind: str, affordances=None, name: str = "",
             features: list | None = None, cell: int = 28) -> BattleGrid:
    """Боевая сетка под место. features — [{role, n}] из описания (LLM); None → дефолты архетипа."""
    arch = classify(kind, affordances, name)
    cols, rows = SIZE.get(arch, SIZE["generic"])
    rng = random.Random(subseed(seed, "battlemap", place_id))
    g, floor, party_zone, enemy_zone = _BUILDERS.get(arch, _open)(cols, rows, rng, arch)
    feats = [(f.get("role", "cover"), f.get("n", 1)) for f in features] if features \
        else _DEFAULTS.get(arch, _DEFAULTS["generic"])
    _place_features(g, floor, feats, rng)
    party = _pick_spawns(g, party_zone, rng, 4)
    enemy = _pick_spawns(g, enemy_zone, rng, 6)
    bg = BattleGrid(cols, rows, cell, ["".join(r) for r in g], party, enemy)
    bg.archetype = arch
    return bg
