"""Симуляция людей по городу за сутки → gif/mp4.

Каждый NPC движется по расписанию (дом↔работа↔дела) вдоль улиц (CityGraph), позиция интерполируется.
Патрули стражи — отдельной индикацией (красные, крупнее), идут по своим маршрутам непрерывно. Фон —
настоящий город (дома/река/стены) из генерации. Этим же движком честно ищется труп: его «находят» только
когда кто-то реально проходит рядом (ночью в глухом углу — почти никто, кроме патруля).

Запуск:  .venv/bin/python scripts/citysim_viz.py [seed] [out.gif]
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from aidnd.bootstrap import new_session  # noqa: E402
from aidnd.content.watch import patrols_of  # noqa: E402
from aidnd.gen.citymap import _blds, _citygen, _town_nodes  # noqa: E402

W, H = 980, 700
SQUARE = "place:phandalin_square"
try:
    FONT = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 16)
except Exception:
    FONT = ImageFont.load_default()


def mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class CitySim:
    def __init__(self, seed: int):
        self.s = new_session(seed=seed, roster_size=24, use_model=False)
        w = self.s.world
        self.g = self.s._city_graph()
        self.m = _citygen().build_city(int(w.seed), W, H, buildings=_blds(_town_nodes(w)), key_houses=[])
        self.inter = {it["i"]: (it["x"], it["y"]) for it in self.g.intersections}
        cx, cy = self.m.get("CX", W / 2), self.m.get("CY", H / 2)
        self.center = (cx, cy)
        # позиции мест: игровые здания из графа, площадь — центр
        self.place_xy = {b["id"]: (b["x"], b["y"]) for b in self.g.buildings}
        self.place_xy[SQUARE] = (cx, cy)
        self.patrols = patrols_of(w)
        self.pop = self._populate()                            # настоящая популяция: 2–4 жителя на дом

    def _populate(self):
        """Расселить город: на каждый дом 2–4 жителя (сидировано). У каждого — дом, место дел и часы.
        Масштабируется от города (больше домов → больше людей), как стража — от размера."""
        import random

        from aidnd.gen.seeds import subseed
        rng = random.Random(subseed(int(self.s.world.seed), "citypop"))
        houses = [(h["x"], h["y"]) for h in self.m.get("hits", []) if h.get("house")]
        gbld = [(b["x"], b["y"], self.g.door.get(b["id"])) for b in self.g.buildings]
        node_cache = {}

        def near(x, y):
            key = (round(x), round(y))
            if key not in node_cache:
                node_cache[key] = self._nearest_node(x, y)
            return node_cache[key]

        pop = []
        for hx, hy in houses:
            hnode = near(hx, hy)
            for _ in range(rng.randint(2, 4)):                # 2–4 жителя на дом
                roll = rng.random()
                if roll < 0.55 and gbld:                      # на работу/торг в игровое здание (тянет к центру)
                    wx, wy, wnode = rng.choice(gbld)
                    wnode = wnode if wnode is not None else near(wx, wy)
                elif roll < 0.8:                              # дела в другом доме города
                    wx, wy = rng.choice(houses); wnode = near(wx, wy)
                else:                                         # работает из дома — почти не выходит
                    wx, wy, wnode = hx, hy, hnode
                path = None if (wx, wy) == (hx, hy) else \
                    [(hx, hy), *[self.inter[n] for n in self.g._bfs_nodes(hnode, wnode)], (wx, wy)]
                pop.append({"home": (hx, hy), "work": (wx, wy), "path": path,
                            "t_out": rng.randint(330, 480), "t_in": rng.randint(990, 1200),
                            "jit": (rng.uniform(-6, 6), rng.uniform(-6, 6))})
        return pop

    # --- геометрия пути ----------------------------------------------------- #
    def _xy(self, place):
        return self.place_xy.get(place, self.center)

    def _nearest_node(self, x, y):
        return min(self.inter, key=lambda i: (self.inter[i][0] - x) ** 2 + (self.inter[i][1] - y) ** 2)

    @staticmethod
    def _along(poly, frac):
        """Точка на доле frac (0..1) длины ломаной."""
        segs = [(poly[i], poly[i + 1]) for i in range(len(poly) - 1)]
        lens = [math.dist(a, b) for a, b in segs]
        total = sum(lens) or 1.0
        target = frac * total
        acc = 0.0
        for (a, b), ln in zip(segs, lens):
            if acc + ln >= target:
                t = (target - acc) / (ln or 1.0)
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            acc += ln
        return poly[-1]

    # --- позиции во времени ------------------------------------------------- #
    def agent_pos(self, a, minute):
        """Где житель в минуту minute: ночью/рано/поздно — дома; днём — на работе; на стыках — в пути."""
        jx, jy = a["jit"]
        if a["path"] is None or minute < a["t_out"] or minute >= a["t_in"] + 30:
            return a["home"][0] + jx, a["home"][1] + jy        # дома
        if minute < a["t_out"] + 30:                           # утренний путь на работу
            return self._along(a["path"], (minute - a["t_out"]) / 30.0)
        if minute < a["t_in"]:                                 # на работе/в делах
            return a["work"][0] + jx, a["work"][1] + jy
        return self._along(a["path"][::-1], (minute - a["t_in"]) / 30.0)   # вечером домой

    def patrol_pos(self, patrol, minute):
        route = patrol["route"]
        leg_dur = 9.0                                          # минут на отрезок маршрута
        period = leg_dur * len(route)
        pos = (minute % period) / leg_dur
        i = int(pos) % len(route)
        a, b = self._xy(route[i]), self._xy(route[(i + 1) % len(route)])
        t = pos - int(pos)
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t

    def watch_members_pos(self, minute):
        out = []
        for p in self.patrols:
            x, y = self.patrol_pos(p, minute)
            for k, _m in enumerate(p["members"]):
                out.append((x + (k - 0.5) * 6, y + (k - 0.5) * 6))
        return out


# --------------------------------------------------------------------------- #
#  Рендер
# --------------------------------------------------------------------------- #
def base_layer(sim):
    """Фон города (рисуем один раз): стены, река, дома, площадь."""
    img = Image.new("RGB", (W, H), (16, 18, 22))
    d = ImageDraw.Draw(img)
    wall = sim.m.get("wall_poly") or []
    if len(wall) > 2:
        d.polygon([(p[0], p[1]) for p in wall], fill=(26, 28, 33), outline=(70, 60, 44))
    river = sim.m.get("river_pts") or []
    if len(river) > 1:
        d.line([(p[0], p[1]) for p in river], fill=(40, 70, 110), width=int(sim.m.get("river_w", 14)))
    for hit in sim.m.get("hits", []):                          # дома
        x, y, r = hit["x"], hit["y"], max(2, hit.get("r", 4) * 0.7)
        c = (90, 80, 64) if hit.get("landmark") else (54, 52, 50)
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    cx, cy = sim.center
    d.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], outline=(120, 110, 80), width=2)
    return img


def tint(img, minute):
    """Лёгкая суточная тонировка: ночью темнее/синее, днём светлее."""
    h = minute / 60.0
    day = max(0.0, math.sin((h - 6) / 24 * 2 * math.pi))      # 0 ночью, ~1 днём
    ov = Image.new("RGB", (W, H), (10, 14, 40))
    return Image.blend(ov, img, 0.45 + 0.5 * day)


def frame(sim, base, minute):
    img = tint(base.copy(), minute)
    d = ImageDraw.Draw(img)
    for a in sim.pop:                                         # горожане — мягкие жёлтые точки
        x, y = sim.agent_pos(a, minute)
        d.ellipse([x - 1.7, y - 1.7, x + 1.7, y + 1.7], fill=(240, 214, 120))
    for x, y in sim.watch_members_pos(minute):                # стража — красные, крупнее, с обводкой
        d.ellipse([x - 4.2, y - 4.2, x + 4.2, y + 4.2], fill=(225, 70, 60), outline=(255, 200, 190))
    hh = f"{int(minute) // 60:02d}:{int(minute) % 60:02d}"
    phase = "ночь" if (minute < 5 * 60 or minute >= 22 * 60) else "утро" if minute < 11 * 60 \
        else "день" if minute < 18 * 60 else "вечер"
    d.rectangle([10, 10, 200, 38], fill=(0, 0, 0))
    d.text((18, 15), f"Фэндалин · {hh} · {phase}", fill=(240, 230, 200), font=FONT)
    d.rectangle([W - 250, 10, W - 10, 38], fill=(0, 0, 0))
    d.ellipse([W - 242, 18, W - 234, 26], fill=(240, 214, 120))
    d.text((W - 228, 15), "горожане", fill=(220, 220, 220), font=FONT)
    d.ellipse([W - 138, 18, W - 130, 26], fill=(225, 70, 60))
    d.text((W - 124, 15), "стража", fill=(220, 220, 220), font=FONT)
    return img


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "citysim.gif")
    sim = CitySim(seed)
    print(f"seed {seed}: горожан {len(sim.pop)}, патрулей {len(sim.patrols)} "
          f"({sum(len(p['members']) for p in sim.patrols)} стражников). Рендер суток…")
    base = base_layer(sim)
    frames = [frame(sim, base, mn) for mn in range(0, 1440, 12)]   # шаг 12 мин → 120 кадров
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=80, loop=0, optimize=True)
    print(f"gif: {out}  ({len(frames)} кадров)")
    # mp4 через ffmpeg (если есть)
    import shutil
    import subprocess
    if shutil.which("ffmpeg"):
        mp4 = out.replace(".gif", ".mp4")
        subprocess.run(["ffmpeg", "-y", "-i", out, "-movflags", "faststart", "-pix_fmt", "yuv420p",
                        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", mp4],
                       capture_output=True, check=False)
        print(f"mp4: {mp4}")


if __name__ == "__main__":
    main()
