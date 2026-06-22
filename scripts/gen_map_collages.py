"""Коллажи карт для README: подземелья (Python/Pillow из gen.dungeon) и город
(PNG-кадры из браузерного генератора склеиваются здесь же — см. stitch_city).

Запуск:  python scripts/gen_map_collages.py dungeons
         python scripts/gen_map_collages.py city  city0.png city1.png ...
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd.gen.dungeon import (  # noqa: E402
    DOOR,
    ENTRANCE,
    FLOOR,
    LOCKED,
    PILLAR,
    SECRET,
    STAIRS_DN,
    STAIRS_UP,
    WALL,
    DungeonBrief,
    generate,
)

ASSETS = os.path.join(os.path.dirname(__file__), "..", "docs", "assets")

BG = (18, 16, 14)
TILE_COLOR = {
    WALL: (38, 33, 28), FLOOR: (230, 222, 205), DOOR: (184, 115, 47),
    LOCKED: (192, 71, 59), SECRET: (124, 92, 230), STAIRS_DN: (85, 102, 170),
    STAIRS_UP: (85, 102, 170), ENTRANCE: (47, 143, 107), PILLAR: (110, 94, 70),
}
GRID_LINE = (214, 205, 184)
ROLE_MARK = {"boss": ("B", (192, 71, 59)), "treasure": ("$", (47, 143, 107)),
             "secret": ("*", (124, 92, 230)), "combat": ("g", (150, 60, 50))}


def _font(size: int):
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_floor(d, fi: int, cell: int = 15, reveal_secret: bool = True) -> Image.Image:
    f = d.floor(fi)
    grid = [row[:] for row in f.grid]
    img = Image.new("RGB", (f.w * cell, f.h * cell), BG)
    dr = ImageDraw.Draw(img)
    for y in range(f.h):
        for x in range(f.w):
            c = grid[y][x]
            if c == SECRET:
                c = DOOR if reveal_secret else WALL
            col = TILE_COLOR.get(c, TILE_COLOR[FLOOR] if c not in TILE_COLOR else (38, 33, 28))
            dr.rectangle([x * cell, y * cell, (x + 1) * cell - 1, (y + 1) * cell - 1], fill=col)
            if col != TILE_COLOR[WALL]:                      # тонкая сетка по полу — «тайлы»
                dr.rectangle([x * cell, y * cell, (x + 1) * cell - 1, (y + 1) * cell - 1],
                             outline=GRID_LINE, width=1)
    fnt = _font(max(10, cell - 3))
    for rid in f.rooms:
        r = d.rooms[rid]
        if r.secret and not reveal_secret:
            continue
        mk = ROLE_MARK.get(r.role)
        if mk:
            cx, cy = r.center
            dr.text(((cx + 0.5) * cell, (cy + 0.5) * cell), mk[0], fill=mk[1],
                    font=fnt, anchor="mm")
    return img


def _label(w: int, text: str, h: int = 26) -> Image.Image:
    img = Image.new("RGB", (w, h), BG)
    ImageDraw.Draw(img).text((8, h // 2), text, fill=(230, 222, 205), font=_font(16), anchor="lm")
    return img


def _panel(d, theme_ru: str) -> Image.Image:
    floor = render_floor(d, 0)
    lab = _label(floor.width, f"{theme_ru} · {len(d.floors)} эт. · комнат {len(d.rooms)}")
    panel = Image.new("RGB", (floor.width, floor.height + lab.height + 6), BG)
    panel.paste(lab, (0, 0))
    panel.paste(floor, (0, lab.height + 6))
    return panel


def _legend(width: int) -> Image.Image:
    items = [((47, 143, 107), "вход"), ((184, 115, 47), "дверь"),
             ((85, 102, 170), "лестница между этажами"), ((124, 92, 230), "секретный ход"),
             (None, "$ сокровища"), (None, "g враги"), (None, "* скрытая комната")]
    h = 30
    img = Image.new("RGB", (width, h), BG)
    dr = ImageDraw.Draw(img)
    fnt = _font(14)
    x = 10
    for col, txt in items:
        if col:
            dr.rectangle([x, h // 2 - 7, x + 14, h // 2 + 7], fill=col, outline=GRID_LINE)
            x += 20
        dr.text((x, h // 2), txt, fill=(225, 217, 200), font=fnt, anchor="lm")
        x += int(dr.textlength(txt, font=fnt)) + 24
    return img


def collage_dungeons() -> str:
    specs = [("cave", "Пещера", 71), ("crypt", "Склеп", 42),
             ("mine", "Рудник", 1337), ("manor", "Усадьба", 2024)]
    panels = []
    for theme, ru, seed in specs:
        d = generate(DungeonBrief(site_key=f"demo_{theme}", theme=theme, tier=3, floors=2,
                                  faction="faction:cragmaw", boss=f"npc:{theme}_boss"), seed)
        panels.append(_panel(d, ru))
    pad, cols = 14, 2
    cw = max(p.width for p in panels)
    rh = [max(panels[r * cols + c].height for c in range(cols) if r * cols + c < len(panels))
          for r in range((len(panels) + cols - 1) // cols)]
    W = cols * cw + (cols + 1) * pad
    leg = _legend(W)
    H = sum(rh) + (len(rh) + 1) * pad + leg.height
    out = Image.new("RGB", (W, H), BG)
    y = pad
    for r in range(len(rh)):
        x = pad
        for c in range(cols):
            i = r * cols + c
            if i < len(panels):
                out.paste(panels[i], (x, y))
            x += cw + pad
        y += rh[r] + pad
    out.paste(leg, (0, H - leg.height))
    os.makedirs(ASSETS, exist_ok=True)
    path = os.path.join(ASSETS, "dungeon_maps.png")
    out.save(path)
    print("wrote", os.path.relpath(path), out.size)
    return path


def stitch_city(frames: list[str]) -> str:
    """Склеивает PNG-кадры городов (экспортированные из браузерного генератора) 2×N."""
    imgs = [Image.open(p).convert("RGB") for p in frames]
    pad, cols = 14, 2
    cw = max(i.width for i in imgs)
    ch = max(i.height for i in imgs)
    rows = (len(imgs) + cols - 1) // cols
    W, H = cols * cw + (cols + 1) * pad, rows * ch + (rows + 1) * pad
    out = Image.new("RGB", (W, H), BG)
    for idx, im in enumerate(imgs):
        r, c = divmod(idx, cols)
        out.paste(im, (pad + c * (cw + pad), pad + r * (ch + pad)))
    os.makedirs(ASSETS, exist_ok=True)
    path = os.path.join(ASSETS, "city_maps.png")
    out.save(path)
    print("wrote", os.path.relpath(path), out.size)
    return path


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dungeons"
    if cmd == "city":
        stitch_city(sys.argv[2:])
    else:
        collage_dungeons()
