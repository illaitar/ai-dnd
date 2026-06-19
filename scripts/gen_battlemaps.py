"""Генератор ОРИГИНАЛЬНЫХ боевых карт: терраин (JSON) + его визуализация (PNG).

Источник истины — сетка терраина; PNG рисуется ИЗ неё, поэтому стены/вода на
картинке точно совпадают с боевой механикой. Тактический бой (как в Baldur's
Gate) читает JSON: проходимость, стоимость движения, перекрытие линии видимости,
укрытие, высота, поверхности, зоны спавна.

Карты LMoP проприетарны Wizards of the Coast — рисуем свои (open-license проекта),
заменяются дропом файлов с теми же именами.

Запуск:  .venv/bin/python scripts/gen_battlemaps.py
Вывод:   src/aidnd/server/web/maps/<name>.png  +  <name>.json
"""

from __future__ import annotations

import hashlib
import json
import os
import random

from PIL import Image, ImageDraw, ImageFont


def _stable_seed(name: str) -> int:
    """Стабильный сид имени (blake2b) — генерация карт воспроизводима между запусками."""
    return int(hashlib.blake2b(name.encode()).hexdigest()[:8], 16)

CELL = 28
COLS, ROWS = 24, 18
OUT = os.path.join(os.path.dirname(__file__), "..", "src", "aidnd", "server", "web", "maps")

# коды терраина
FLOOR, WALL, WATER, RUBBLE, COVER, HIGH = ".", "#", "~", "^", "o", "H"

PALETTE = {
    "cave": {FLOOR: (104, 90, 66), WALL: (30, 26, 22), WATER: (40, 78, 110),
             RUBBLE: (84, 74, 58), COVER: (70, 60, 44), HIGH: (126, 110, 80)},
    "manor": {FLOOR: (96, 86, 70), WALL: (44, 40, 46), WATER: (50, 70, 96),
              RUBBLE: (78, 70, 58), COVER: (96, 64, 44), HIGH: (112, 100, 82)},
    "town": {FLOOR: (66, 74, 52), WALL: (74, 60, 48), WATER: (50, 80, 110),
             RUBBLE: (96, 82, 60), COVER: (88, 70, 52), HIGH: (84, 92, 64)},
}


TEXDIR = os.path.join(os.path.dirname(__file__), "textures")
# kind -> (floor_tex, wall_tex). CC0-текстуры Poly Haven (public domain).
TEXSETS = {
    "cave": ("cave_floor", "cave_wall"),
    "manor": ("manor_floor", "manor_wall"),
    "town": ("town_ground", "manor_wall"),
}


def _font(size):
    for p in ("/System/Library/Fonts/Supplemental/Georgia.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _noise(rng, base, amt=8):
    return tuple(max(0, min(255, c + rng.randint(-amt, amt))) for c in base)


def _load_tex(name):
    path = os.path.join(TEXDIR, f"{name}.png")
    return Image.open(path).convert("RGB") if os.path.exists(path) else None


def _tile_full(tex, w, h):
    """Бесшовно замостить текстуру на всё полотно (w×h)."""
    out = Image.new("RGB", (w, h))
    tw, th = tex.size
    for ox in range(0, w, tw):
        for oy in range(0, h, th):
            out.paste(tex, (ox, oy))
    return out


def _shade(img, value, box):
    """Наложить полупрозрачную тень/свет (value<0 темнее, >0 светлее) на область."""
    overlay = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]),
                        (255, 255, 255, max(0, value)) if value > 0 else (0, 0, 0, -value))
    img.paste(Image.alpha_composite(img.convert("RGBA").crop(box), overlay).convert("RGB"),
              (box[0], box[1]))


def _blank():
    return [[WALL for _ in range(COLS)] for _ in range(ROWS)]


# --------------------------------------------------------------------------- #
#  Терраин                                                                     #
# --------------------------------------------------------------------------- #
MIN_CAVE_REGION = 60        # минимум проходимых клеток в пещере (для простора боя)


def _cave_automaton(seed):
    rng = random.Random(seed)
    f = [[rng.random() < 0.45 for _ in range(COLS)] for _ in range(ROWS)]
    for _ in range(5):
        nf = [[False] * COLS for _ in range(ROWS)]
        for y in range(ROWS):
            for x in range(COLS):
                if x in (0, COLS - 1) or y in (0, ROWS - 1):
                    continue
                n = sum(f[yy][xx] for yy in range(y - 1, y + 2) for xx in range(x - 1, x + 2)
                        if not (xx == x and yy == y))
                nf[y][x] = n >= 5 or (f[y][x] and n >= 4)
        f = nf
    return f, rng


def _largest_floor_size(f) -> int:
    seen, best = set(), 0
    for sy in range(ROWS):
        for sx in range(COLS):
            if (sx, sy) in seen or not f[sy][sx]:
                continue
            comp, stack = 0, [(sx, sy)]
            seen.add((sx, sy))
            while stack:
                x, y = stack.pop()
                comp += 1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < COLS and 0 <= ny < ROWS and (nx, ny) not in seen and f[ny][nx]):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            best = max(best, comp)
    return best


def terrain_cave(seed):
    # детерминированный ретрай по сиду, пока пещера не станет достаточно просторной
    f, rng, best_f, best_size = None, None, None, -1
    for attempt in range(12):
        cand, crng = _cave_automaton(seed + attempt * 7919)
        size = _largest_floor_size(cand)
        if size > best_size:
            best_f, best_size, f, rng = cand, size, cand, crng
        if size >= MIN_CAVE_REGION:
            f, rng = cand, crng
            break
    f = f if f is not None else best_f
    grid = _blank()
    floor_cells = []
    for y in range(ROWS):
        for x in range(COLS):
            if f[y][x]:
                grid[y][x] = FLOOR
                floor_cells.append((x, y))
    # подземный ручей (вода) кляксой
    if floor_cells:
        wc = rng.choice(floor_cells)
        for (x, y) in floor_cells:
            if (x - wc[0]) ** 2 + (y - wc[1]) ** 2 <= rng.randint(5, 10):
                grid[y][x] = WATER
    # немного завалов и сталагмитов-укрытий
    for (x, y) in rng.sample(floor_cells, max(1, len(floor_cells) // 14)):
        if grid[y][x] == FLOOR:
            grid[y][x] = rng.choice([RUBBLE, COVER])
    # высокий уступ
    if floor_cells:
        hx, hy = rng.choice(floor_cells)
        for (x, y) in floor_cells:
            if abs(x - hx) <= 1 and abs(y - hy) <= 1 and grid[y][x] == FLOOR:
                grid[y][x] = HIGH
    return _finish(grid, floor_cells, "Пещера Кларга — Логово Крэгмо")


def terrain_manor(seed):
    rng = random.Random(seed)
    grid = _blank()
    rooms = []
    for _ in range(6):
        rw, rh = rng.randint(4, 7), rng.randint(3, 5)
        rx, ry = rng.randint(1, COLS - rw - 1), rng.randint(1, ROWS - rh - 1)
        rooms.append((rx, ry, rw, rh))
        for y in range(ry, ry + rh):
            for x in range(rx, rx + rw):
                grid[y][x] = FLOOR
    for i in range(len(rooms) - 1):
        ax, ay = rooms[i][0] + rooms[i][2] // 2, rooms[i][1] + rooms[i][3] // 2
        bx, by = rooms[i + 1][0] + rooms[i + 1][2] // 2, rooms[i + 1][1] + rooms[i + 1][3] // 2
        for x in range(min(ax, bx), max(ax, bx) + 1):
            grid[ay][x] = FLOOR
        for y in range(min(ay, by), max(ay, by) + 1):
            grid[y][bx] = FLOOR
    floor_cells = [(x, y) for y in range(ROWS) for x in range(COLS) if grid[y][x] == FLOOR]
    # мебель-укрытия
    for (x, y) in rng.sample(floor_cells, max(1, len(floor_cells) // 12)):
        grid[y][x] = COVER
    floor_cells = [(x, y) for y in range(ROWS) for x in range(COLS) if grid[y][x] == FLOOR]
    return _finish(grid, floor_cells, "Поместье Тресендар — укрытие Красных плащей")


def terrain_town(seed):
    rng = random.Random(seed)
    grid = [[FLOOR for _ in range(COLS)] for _ in range(ROWS)]
    # здания по углам (стены/укрытия)
    for (bx, by, bw, bh) in [(1, 1, 5, 4), (COLS - 6, 1, 5, 4),
                             (1, ROWS - 5, 5, 4), (COLS - 6, ROWS - 5, 5, 4)]:
        for y in range(by, by + bh):
            for x in range(bx, bx + bw):
                grid[y][x] = WALL
    # бочки/телеги-укрытия у дороги
    floor_cells = [(x, y) for y in range(ROWS) for x in range(COLS) if grid[y][x] == FLOOR]
    for (x, y) in rng.sample(floor_cells, 6):
        grid[y][x] = COVER
    floor_cells = [(x, y) for y in range(ROWS) for x in range(COLS) if grid[y][x] == FLOOR]
    return _finish(grid, floor_cells, "Рыночная площадь Фэндалина")


PASSABLE = (FLOOR, WATER, RUBBLE, HIGH)


def _largest_region(grid):
    """4-связная крупнейшая проходимая область; остальные пятна → стена."""
    seen = set()
    best = []
    for sy in range(ROWS):
        for sx in range(COLS):
            if (sx, sy) in seen or grid[sy][sx] not in PASSABLE:
                continue
            comp, stack = [], [(sx, sy)]
            seen.add((sx, sy))
            while stack:
                x, y = stack.pop()
                comp.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < COLS and 0 <= ny < ROWS and (nx, ny) not in seen
                            and grid[ny][nx] in PASSABLE):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            if len(comp) > len(best):
                best = comp
    keep = set(best)
    for y in range(ROWS):
        for x in range(COLS):
            if grid[y][x] in PASSABLE and (x, y) not in keep:
                grid[y][x] = WALL
    return best


def _finish(grid, floor_cells, title):
    """Оставляет одну связную область, назначает спавны, собирает метаданные."""
    region = _largest_region(grid)
    passable = sorted(region, key=lambda c: c[0] + c[1])
    party = passable[:4]                          # ближе к «входу» (левый-верх)
    # враги — с дальнего конца, но НЕ пересекаясь с зоной партии (на тесных картах)
    pset = set(party)
    enemies = [c for c in reversed(passable) if c not in pset][:6]
    water = [[x, y] for y in range(ROWS) for x in range(COLS) if grid[y][x] == WATER]
    return {
        "title": title, "cols": COLS, "rows": ROWS, "cell": CELL,
        "terrain": ["".join(row) for row in grid],
        "party_spawn": [list(c) for c in party],
        "enemy_spawn": [list(c) for c in enemies],
        "surfaces": ([{"type": "water", "cells": water}] if water else []),
    }


# --------------------------------------------------------------------------- #
#  Рендер PNG из терраина                                                      #
# --------------------------------------------------------------------------- #
def render(meta, kind, seed):
    """Рендер из терраина с тайлингом CC0-текстур + теневые края для глубины."""
    rng = random.Random(seed ^ 0xABCD)
    pal = PALETTE[kind]
    W, H = COLS * CELL, ROWS * CELL
    grid = meta["terrain"]
    fname, wname = TEXSETS.get(kind, ("cave_floor", "cave_wall"))
    ftex, wtex = _load_tex(fname), _load_tex(wname)
    img = _tile_full(ftex, W, H) if ftex else Image.new("RGB", (W, H), pal[FLOOR])
    wall_layer = (Image.eval(_tile_full(wtex, W, H), lambda p: int(p * 0.42))
                  if wtex else Image.new("RGB", (W, H), pal[WALL]))

    def box(x, y):
        return (x * CELL, y * CELL, (x + 1) * CELL, (y + 1) * CELL)

    # стены — наложить текстуру стены на стенные клетки
    for y in range(ROWS):
        for x in range(COLS):
            if grid[y][x] == WALL:
                b = box(x, y)
                img.paste(wall_layer.crop(b), (b[0], b[1]))

    d = ImageDraw.Draw(img, "RGBA")
    for y in range(ROWS):
        for x in range(COLS):
            c = grid[y][x]
            b = box(x, y)
            if c == WALL:
                d.rectangle([b[0], b[1], b[2] - 1, b[3] - 1], outline=(8, 6, 4, 200))
                d.line([b[0], b[1], b[2], b[1]], fill=(120, 110, 96, 60))   # верхний блик камня
            elif c == WATER:
                reg = img.crop(b)
                img.paste(Image.blend(reg, Image.new("RGB", reg.size, (38, 86, 140)), 0.55),
                          (b[0], b[1]))
                d.line([b[0] + 3, b[1] + CELL // 2, b[2] - 3, b[1] + CELL // 2],
                       fill=(150, 200, 230, 80))
            elif c == HIGH:
                _shade(img, 34, list(b))
                d.line([b[0], b[1], b[2], b[1]], fill=(255, 245, 210, 160), width=2)
            elif c == RUBBLE:
                for _ in range(5):
                    rx, ry = rng.randint(b[0], b[2] - 3), rng.randint(b[1], b[3] - 3)
                    d.ellipse([rx, ry, rx + 3, ry + 3], fill=(28, 24, 20, 170))
            elif c == COVER:
                m = 4
                bx = [b[0] + m, b[1] + m, b[2] - m, b[3] - m]
                d.rectangle(bx, fill=(112, 78, 44, 255), outline=(38, 24, 12, 255), width=2)
                d.line([bx[0], bx[1], bx[2], bx[3]], fill=(64, 42, 22, 200))
                d.line([bx[2], bx[1], bx[0], bx[3]], fill=(64, 42, 22, 200))
                d.line([bx[0], bx[1] + 2, bx[2], bx[1] + 2], fill=(156, 112, 66, 180))

    # тени глубины у стен (свет сверху-слева)
    for y in range(ROWS):
        for x in range(COLS):
            if grid[y][x] == WALL:
                continue
            b = box(x, y)
            if y > 0 and grid[y - 1][x] == WALL:
                d.rectangle([b[0], b[1], b[2], b[1] + 6], fill=(0, 0, 0, 95))
            if x > 0 and grid[y][x - 1] == WALL:
                d.rectangle([b[0], b[1], b[0] + 6, b[3]], fill=(0, 0, 0, 80))

    # тонкая сетка
    for x in range(COLS + 1):
        d.line([(x * CELL, 0), (x * CELL, H)], fill=(0, 0, 0, 45))
    for y in range(ROWS + 1):
        d.line([(0, y * CELL), (W, y * CELL)], fill=(0, 0, 0, 45))

    # мягкая виньетка для атмосферы
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([int(-W * 0.18), int(-H * 0.18), int(W * 1.18), int(H * 1.18)],
                                fill=255)
    img = Image.composite(img, Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.4), vig)

    # заголовок
    d2 = ImageDraw.Draw(img, "RGBA")
    f = _font(18)
    tw = d2.textlength(meta["title"], font=f)
    d2.rectangle([5, 5, 16 + tw, 32], fill=(0, 0, 0, 175))
    d2.text((11, 8), meta["title"], fill=(232, 220, 192), font=f)
    return img


MAPS = {
    "cragmaw_hideout": ("cave", terrain_cave),
    "redbrand_hideout": ("manor", terrain_manor),
    "phandalin": ("town", terrain_town),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, (kind, fn) in MAPS.items():
        seed = _stable_seed(name) & 0xFFFF
        meta = fn(seed)
        render(meta, kind, seed).save(os.path.join(OUT, f"{name}.png"))
        with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as fp:
            json.dump(meta, fp, ensure_ascii=False)
        print(f"  {name}: {COLS}x{ROWS}, party_spawn={len(meta['party_spawn'])}, "
              f"enemy_spawn={len(meta['enemy_spawn'])}, water={len(meta['surfaces'][0]['cells']) if meta['surfaces'] else 0}")


if __name__ == "__main__":
    main()
