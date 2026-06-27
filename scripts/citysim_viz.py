"""Визуализация stateful-ABM города за сутки → gif/mp4.

Тот же движок, что в игре (content/citysim.CitySim): у каждого жителя нужды (энергия/голод/общение), он
решает, куда идти, по полезности места + времени суток. Эмерджентно: утром на работу, в обед/вечер в
таверны, ночью по домам — и всё непрерывно, вразнобой. Цвет точки = доминирующая нужда/занятие.

Запуск:  .venv/bin/python scripts/citysim_viz.py [seed] [out.gif]
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from aidnd.bootstrap import new_session  # noqa: E402
from aidnd.content.citysim import CitySim, phase  # noqa: E402
from aidnd.content.watch import patrols_of  # noqa: E402
from aidnd.gen.citymap import _blds, _citygen, _town_nodes  # noqa: E402

W, H, MPT = 980, 700, 10
try:
    FONT = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 16)
except Exception:
    FONT = ImageFont.load_default()

_KIND = {"inn": "inn", "drink": "tavern", "serve": "tavern", "shop": "shop", "shrine": "shrine",
         "guild": "shop", "townhall": "shop", "farm": "shop", "work": "shop"}


def classify(affs):
    for a in affs:
        if a in _KIND:
            return _KIND[a]
    return "shop"


def build():
    s = new_session(seed=SEED, roster_size=12, use_model=False)
    w = s.world
    g = s._city_graph()
    m = _citygen().build_city(int(w.seed), W, H, buildings=_blds(_town_nodes(w)), key_houses=[])
    inter = {it["i"]: (it["x"], it["y"]) for it in g.intersections}
    cx, cy = m.get("CX", W / 2), m.get("CY", H / 2)
    # публичные места: игровые здания + площадь
    places = {}
    for b in g.buildings:
        affs = list(getattr(w.spatial.places.get(b["id"]), "affordances", []) or [])
        places[b["id"]] = {"kind": classify(affs), "xy": (b["x"], b["y"])}
    places["place:phandalin_square"] = {"kind": "square", "xy": (cx, cy)}
    pubs = list(places)
    work_pool = [p for p in pubs if places[p]["kind"] in ("inn", "tavern", "shop", "shrine")]
    # агенты: 2–4 на дом, дом — координата дома, работа — игровое место (или нет)
    rng = random.Random(w.seed ^ 0xABBA)
    houses = [(hit["x"], hit["y"]) for hit in m.get("hits", []) if hit.get("house")]
    agents = []
    for i, (hx, hy) in enumerate(houses):
        for k in range(rng.randint(2, 4)):
            agents.append({"id": f"a{i}_{k}", "home_xy": (hx, hy), "home_place": None,
                           "work": rng.choice(work_pool) if (work_pool and rng.random() < 0.7) else None})
    sim = CitySim(places, agents, seed=int(w.seed), mpt=MPT)
    return s, g, m, inter, places, sim, (cx, cy)


def place_xy_fn(places, center):
    def f(place, agent):
        if place is None:
            return agent["home_xy"] or center
        return places[place]["xy"]
    return f


# --------------------------------------------------------------------------- #
def base_layer(m):
    img = Image.new("RGB", (W, H), (16, 18, 22))
    d = ImageDraw.Draw(img)
    wall = m.get("wall_poly") or []
    if len(wall) > 2:
        d.polygon([(p[0], p[1]) for p in wall], fill=(26, 28, 33), outline=(70, 60, 44))
    river = m.get("river_pts") or []
    if len(river) > 1:
        d.line([(p[0], p[1]) for p in river], fill=(40, 70, 110), width=int(m.get("river_w", 14)))
    for hit in m.get("hits", []):
        x, y, r = hit["x"], hit["y"], max(2, hit.get("r", 4) * 0.7)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(90, 80, 64) if hit.get("landmark") else (52, 50, 48))
    return img


def tint(img, minute):
    day = max(0.0, math.sin((minute / 60.0 - 6) / 24 * 2 * math.pi))
    ov = Image.new("RGB", (W, H), (10, 14, 40))
    return Image.blend(ov, img, 0.45 + 0.5 * day)


# цвет точки по доминирующей нужде/занятию
def acolor(a, minute=720):
    if a["place"] is None and not a["transit"]:
        return (90, 110, 200)                                 # дома — синий
    if phase(minute) == "night":                              # ночью на ногах — лунный (совы/в пути)
        return (120, 210, 230)
    if a["transit"]:
        return (235, 235, 235)                                # в пути — белый
    n = a["needs"]
    if n["hunger"] > 0.6:
        return (235, 150, 70)                                 # голодный — оранжевый
    if n["social"] > 0.6:
        return (210, 90, 180)                                 # тянет к людям — розовый
    return (240, 214, 120)                                    # при деле — жёлтый


def frame(sim, base, places, pxy, patrol_pos, minute):
    img = tint(base.copy(), minute)
    d = ImageDraw.Draw(img)
    for aid, a in sim.agents.items():
        if a["transit"] is None and a["place"] is None:       # дома ночью — приглушить (точка на доме)
            pass
        x, y = sim.xy_at(aid, pxy)
        c = acolor(a, minute)
        d.ellipse([x - 1.7, y - 1.7, x + 1.7, y + 1.7], fill=c)
    for x, y in patrol_pos:                                   # стража — красные, крупнее
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(225, 70, 60), outline=(255, 200, 190))
    hh = f"{minute // 60:02d}:{minute % 60:02d}"
    out = sum(1 for a in sim.agents.values() if a["place"] is not None or a["transit"])
    d.rectangle([10, 10, 320, 38], fill=(0, 0, 0))
    d.text((18, 15), f"Фэндалин · {hh} · {phase(minute)} · на ногах: {out}", fill=(240, 230, 200), font=FONT)
    d.rectangle([W - 360, 10, W - 10, 38], fill=(0, 0, 0))
    for i, (col, lab) in enumerate([((90, 110, 200), "дома"), ((240, 214, 120), "при деле"),
                                    ((235, 150, 70), "голод"), ((210, 90, 180), "к людям"),
                                    ((225, 70, 60), "стража")]):
        bx = W - 352 + i * 70
        d.ellipse([bx, 18, bx + 8, 26], fill=col)
        d.text((bx + 11, 15), lab, fill=(220, 220, 220), font=FONT)
    return img


def patrol_positions(s, places, minute):
    out = []
    for p in patrols_of(s.world):
        route = p["route"]
        leg = 9.0
        pos = (minute % (leg * len(route))) / leg
        i = int(pos) % len(route)
        a = places.get(route[i], {}).get("xy") or (W / 2, H / 2)
        b = places.get(route[(i + 1) % len(route)], {}).get("xy") or (W / 2, H / 2)
        t = pos - int(pos)
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        for k, _m in enumerate(p["members"]):
            out.append((x + (k - 0.5) * 6, y + (k - 0.5) * 6))
    return out


def main():
    global SEED
    SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "citysim.gif")
    s, g, m, inter, places, sim, center = build()
    pxy = place_xy_fn(places, center)
    print(f"seed {SEED}: агентов {len(sim.agents)}, патрулей {len(patrols_of(s.world))}. ABM-симуляция суток…")
    base = base_layer(m)
    frames = []
    for t in range(1, 145):                                   # сутки по тикам (mpt=10 → 144 тика)
        sim.advance(t)
        minute = (t * MPT) % 1440
        frames.append(frame(sim, base, places, pxy, patrol_positions(s, places, minute), minute))
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=90, loop=0, optimize=True)
    print(f"gif: {out} ({len(frames)} кадров)")
    import shutil
    import subprocess
    if shutil.which("ffmpeg"):
        mp4 = out.replace(".gif", ".mp4")
        subprocess.run(["ffmpeg", "-y", "-i", out, "-movflags", "faststart", "-pix_fmt", "yuv420p",
                        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", mp4], capture_output=True, check=False)
        print(f"mp4: {mp4}")


if __name__ == "__main__":
    main()
