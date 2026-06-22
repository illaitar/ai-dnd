"""GIF-анимация прохождения подземелья: headless-прогон (offline, детерминированно)
снимает карту с туманом/замком/секретом на каждом шаге → docs/assets/dungeon_playthrough.gif

Запуск:  python scripts/gen_dungeon_anim.py
"""

from __future__ import annotations

import contextlib
import io
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aidnd import config  # noqa: E402
from aidnd.bootstrap import new_session  # noqa: E402
from aidnd.gen import dungeon as dg  # noqa: E402
from aidnd.runtime.debug_play import DebugDriver  # noqa: E402

ASSETS = os.path.join(os.path.dirname(__file__), "..", "docs", "assets")
CELL = 14
BG = (18, 16, 14)
C = {dg.WALL: (38, 33, 28), dg.FLOOR: (230, 222, 205), dg.DOOR: (184, 115, 47),
     dg.STAIRS_DN: (85, 102, 170), dg.STAIRS_UP: (85, 102, 170),
     dg.ENTRANCE: (47, 143, 107), dg.PILLAR: (110, 94, 70)}
GRID = (214, 205, 184)
LOCKED_C, OPEN_C, SECRET_C = (192, 71, 59), (120, 150, 90), (124, 92, 230)
PLAYER_C, ENEMY_C, GOLD_C = (60, 130, 230), (200, 70, 55), (220, 170, 60)


def _font(sz):
    for p in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def _floor_img(s, d, fi: int, active: bool) -> Image.Image:
    f = d.floor(fi)
    W, H = f.w * CELL, f.h * CELL
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    flags = s.world.flags
    cur = s.current_place()
    found_secret = any(fl.startswith("secret_found:") for fl in flags)
    locks = s.world.dungeon_locks
    locked_open = all(f"cleared:{r}" in flags for r in locks.values()) if locks else True

    grid = [row[:] for row in f.grid]
    for rid in f.rooms:                                   # туман: не пройденные комнаты — стена
        if f"dseen:{rid}" not in flags:
            for (x, y) in d.rooms[rid].cells:
                grid[y][x] = dg.WALL
    for y in range(f.h):
        for x in range(f.w):
            c = grid[y][x]
            if c == dg.SECRET:
                c = dg.DOOR if found_secret else dg.WALL
            if c == dg.LOCKED:
                col = OPEN_C if locked_open else LOCKED_C
            else:
                col = C.get(c, (38, 33, 28) if c == dg.WALL else (230, 222, 205))
            dr.rectangle([x * CELL, y * CELL, (x + 1) * CELL - 1, (y + 1) * CELL - 1], fill=col)
            if col != C[dg.WALL]:
                dr.rectangle([x * CELL, y * CELL, (x + 1) * CELL - 1, (y + 1) * CELL - 1],
                             outline=GRID, width=1)
    fnt = _font(CELL - 2)
    for rid in f.rooms:
        if f"dseen:{rid}" not in flags:
            continue
        r = d.rooms[rid]
        cx, cy = (r.center[0] + 0.5) * CELL, (r.center[1] + 0.5) * CELL
        hostiles = [n for n in s.world.spatial.occupants(rid)
                    if s._is_hostile(n) and s.world.is_alive(n)]
        if rid == cur:
            dr.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=PLAYER_C, outline=(240, 244, 250), width=2)
        elif hostiles:
            big = r.role == "boss"
            rad = 6 if big else 4
            dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=ENEMY_C)
        elif r.role == "treasure":
            dr.text((cx, cy), "$", fill=GOLD_C, font=fnt, anchor="mm")
        elif r.role == "secret" and found_secret:
            dr.text((cx, cy), "*", fill=SECRET_C, font=fnt, anchor="mm")
    dr.rectangle([0, 0, W - 1, H - 1],
                 outline=(230, 200, 90) if active else (70, 64, 56), width=3 if active else 1)
    lab = _font(13)
    dr.text((6, 4), f"этаж {fi + 1}", fill=(225, 217, 200), font=lab, anchor="lt")
    return img


def frame(s, d, caption: str) -> Image.Image:
    cur = s.current_place()
    active = d.rooms[cur].floor if cur in d.rooms else 0
    panels = [_floor_img(s, d, fi, fi == active) for fi in range(len(d.floors))]
    gap, capH, pad = 16, 44, 12
    body_w = sum(p.width for p in panels) + gap * (len(panels) - 1)
    body_h = max(p.height for p in panels)
    W, H = body_w + pad * 2, body_h + capH + pad
    img = Image.new("RGB", (W, H), BG)
    ImageDraw.Draw(img).text((pad, capH // 2), caption, fill=(238, 228, 208),
                             font=_font(19), anchor="lm")
    x = pad
    for p in panels:
        img.paste(p, (x, capH))
        x += p.width + gap
    return img


def main() -> None:
    s = new_session(seed=config.WORLD_SEED, roster_size=4, use_model=False)
    d = s.world.dungeons["sunless_warren"]
    st = s.world.get_stats(s.player)
    st.max_hp = st.hp = 140                                # переживём прогон ради анимации
    drv = DebugDriver(s, require_model=False)

    by_role: dict = {}
    for rid, r in d.rooms.items():
        by_role.setdefault(r.role, []).append(rid)
    nm = s._place_name
    entrance, boss = d.entrance, d.boss_room
    combat, treasure, secret = by_role["combat"][0], by_role["treasure"][0], by_role["secret"][0]

    frames, durs = [], []

    def snap(cap, ms=1100):
        frames.append(frame(s, d, cap))
        durs.append(ms)

    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):                # глушим болтовню драйвера
        drv._resolve_rolls(s.handle(f"иди в {nm(entrance)}"))
        snap("Спускаемся в Бессолнечную нору", 1300)
        s.handle(f"иди в {nm(boss)}")                      # заперто
        snap("Путь к логову вожака заперт", 1500)
        drv._resolve_rolls(s.handle(f"иди в {nm(combat)}"))
        snap("Логово стражи — засада")
        s.handle("атаковать стража")
        snap("Бой со стражем-ключником", 900)
        if s.combat and s.combat.state.mode == "active":
            drv.fight()
        snap("Страж повержен — замок открылся", 1500)
        drv._resolve_rolls(s.handle(f"иди в {nm(treasure)}"))
        snap("Старая кладовая: сквозит из стены…", 1200)
        for _ in range(10):
            drv._resolve_rolls(s.handle("обыскать комнату"))
            if any(fl.startswith("secret_found:") for fl in s.world.flags):
                break
        snap("Найден тайный ход!", 1500)
        drv._resolve_rolls(s.handle(f"иди в {nm(secret)}"))
        snap("Замурованный тайник — бонус-добыча", 1300)
        drv._resolve_rolls(s.handle(f"иди в {nm(boss)}"))
        snap("Спуск ко второму ярусу, к вожаку", 1100)
        s.handle("атаковать вожака")
        snap("Бой с вожаком", 900)
        if s.combat and s.combat.state.mode == "active":
            drv.fight()
        snap("Вожак повержен — нора зачищена!", 2200)

    boss_npcs = [c.get("npc") for r in d.rooms.values()
                 for c in r.contents if c["kind"] == "boss"]
    if not all(not s.world.is_alive(n) for n in boss_npcs if n):
        raise SystemExit("прохождение не завершилось победой над вожаком — анимация не записана")

    os.makedirs(ASSETS, exist_ok=True)
    path = os.path.join(ASSETS, "dungeon_playthrough.gif")
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durs,
                   loop=0, optimize=True)
    print(f"wrote {os.path.relpath(path)} — {len(frames)} кадров, {frames[0].size}")


if __name__ == "__main__":
    main()
