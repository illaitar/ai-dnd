"""«Бумажный» рендер плана локации: пергамент + чернильный дрожащий штрих + Dyson-хэтчинг +
глифы мебели + нумерация зон с легендой (эстетика one-page-dungeon / старых D&D-модулей).

Чистый SVG (feTurbulence для бумаги и пятен, никакого canvas). Дрожь штриха — сидированная
(один и тот же дом всегда нарисован одинаково). Геометрию даёт floorplan.plan_location;
здесь — только красота поверх готовых координат.
"""

from __future__ import annotations

import hashlib
import math
import random

CELL = 22
INK = "#3b3021"
PAPER = "#eadfc4"
FAINT = "#3b3021"


def _rng(key: str) -> random.Random:
    return random.Random(int(hashlib.md5(("art|" + key).encode()).hexdigest()[:8], 16))


# ── дрожащие примитивы (rough.js-стиль, сидированно) ────────────────────────

def _wob(pts, rng, w=1.0):
    """Полилиния с дрожью: сегменты дробятся, точки смещаются. Возвращает d-атрибут path."""
    out = []
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        seg = max(2, int(math.hypot(x2 - x1, y2 - y1) / 14))
        for k in range(seg):
            t = k / seg
            px = x1 + (x2 - x1) * t + rng.uniform(-w, w)
            py = y1 + (y2 - y1) * t + rng.uniform(-w, w)
            out.append((px, py))
    out.append(pts[-1])
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in out)


def _stroke(out, pts, rng, width=1.1, w=1.0, close=False, passes=1, opacity=1.0):
    p = list(pts) + ([pts[0]] if close else [])
    for _ in range(passes):
        out.append(f'<path d="{_wob(p, rng, w)}" fill="none" stroke="{INK}" '
                   f'stroke-width="{width}" stroke-linecap="round" opacity="{opacity}"/>')


def _wrect(out, x, y, w, h, rng, width=1.1, wob=0.9, opacity=1.0):
    _stroke(out, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], rng,
            width=width, w=wob, close=True, opacity=opacity)


def _wcircle(out, cx, cy, r, rng, width=1.1, fill="none", opacity=1.0):
    pts = []
    n = max(8, int(r))
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r * rng.uniform(0.93, 1.07)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + " Z"
    out.append(f'<path d="{d}" fill="{fill}" stroke="{INK}" stroke-width="{width}" opacity="{opacity}"/>')


def _hatch_segments(out, segs, rng):
    """Dyson-хэтчинг: короткие штрихи наружу вдоль сегментов ((x1,y1),(x2,y2),(nx,ny))."""
    for (x1, y1), (x2, y2), (nx, ny) in segs:
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 4:
            continue
        dx, dy = (x2 - x1) / L, (y2 - y1) / L
        step = 4.6
        k = 3.0
        while k < L - 2:
            if rng.random() > 0.16:
                ln = rng.uniform(5, 12)
                a = rng.uniform(-0.28, 0.28)
                hx = nx * math.cos(a) - ny * math.sin(a)
                hy = nx * math.sin(a) + ny * math.cos(a)
                sx, sy = x1 + dx * k, y1 + dy * k
                out.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{sx + hx * ln:.1f}" '
                           f'y2="{sy + hy * ln:.1f}" stroke="{INK}" stroke-width="0.7" opacity="0.55"/>')
            k += step * rng.uniform(0.8, 1.3)


def _outline_segs(pts_px):
    """Полигон (CW) → сегменты с внешними нормалями."""
    segs = []
    n = len(pts_px)
    for i in range(n):
        x1, y1 = pts_px[i]
        x2, y2 = pts_px[(i + 1) % n]
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1:
            continue
        dx, dy = (x2 - x1) / L, (y2 - y1) / L
        segs.append(((x1, y1), (x2, y2), (dy, -dx)))
    return segs


# ── глифы мебели (чернильные, вид сверху) ───────────────────────────────────

def _stools(out, cx, cy, r, rng, n):
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.3, 0.3)
        _wcircle(out, cx + r * math.cos(a), cy + r * math.sin(a), 3.1, rng, width=0.9)


def _g_table(out, r, rng, dice=False):
    cx, cy = r["cx"], r["cy"]
    _wcircle(out, cx, cy, 10.5, rng, width=1.3)
    _wcircle(out, cx, cy, 8.6, rng, width=0.6, opacity=0.5)
    _stools(out, cx, cy, 15.5, rng, rng.randint(2, 4))
    if dice:
        for _ in range(2):
            _wrect(out, cx + rng.uniform(-5, 3), cy + rng.uniform(-5, 3), 3.4, 3.4, rng, width=0.7)


def _g_bar(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    vert = h >= w
    if vert:
        bx, bw = x + 4, w * 0.48
        _wrect(out, bx, y + 4, bw, h - 8, rng, width=1.4)
        for i in range(1, 4):
            _stroke(out, [(bx + bw * i / 4, y + 6), (bx + bw * i / 4, y + h - 6)], rng, width=0.5, opacity=0.4)
        for i in range(2 + int(h / 34)):
            _wcircle(out, bx + bw / 2 + rng.uniform(-3, 3), y + 10 + i * 16 + rng.uniform(-2, 2), 2.1, rng, width=0.7)
            _wcircle(out, x + w - 6, y + 9 + i * 15, 3.0, rng, width=0.9)
    else:
        bh = h * 0.48
        _wrect(out, x + 4, y + 4, w - 8, bh, rng, width=1.4)
        for i in range(2 + int(w / 34)):
            _wcircle(out, x + 10 + i * 16, y + 4 + bh / 2, 2.1, rng, width=0.7)
            _wcircle(out, x + 9 + i * 15, y + h - 6, 3.0, rng, width=0.9)


def _g_hearth(out, r, rng, left_wall):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    cx = x + (5 if left_wall else w - 5)
    cy = y + h / 2
    _wrect(out, x + 2, y + 3, w - 4, h - 6, rng, width=1.3)
    fx = x + w / 2
    flame = [(fx - 5, cy + 5), (fx - 2, cy - 4), (fx, cy + 2), (fx + 2, cy - 5), (fx + 5, cy + 5)]
    _stroke(out, flame, rng, width=1.0, w=0.8)
    for i in range(4):                                       # тепло-штрихи
        a = -math.pi / 2 + (i - 1.5) * 0.5
        sx = fx + math.cos(a) * 10
        sy = cy + math.sin(a) * 10
        _stroke(out, [(sx, sy), (sx + math.cos(a) * 5, sy + math.sin(a) * 5)], rng, width=0.6, opacity=0.5)
    _ = cx


def _g_workshop(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    _wrect(out, x + 3, y + h - 13, w - 6, 10, rng, width=1.2)   # верстак
    ax, ay = x + w * 0.35, y + h * 0.34                          # наковальня
    _stroke(out, [(ax - 6, ay + 4), (ax + 6, ay + 4), (ax + 4, ay), (ax + 7, ay - 3),
                  (ax - 3, ay - 3), (ax - 4, ay)], rng, width=1.1, close=True, w=0.5)
    _stroke(out, [(x + w * 0.7, y + 8), (x + w * 0.7 + 7, y + 13)], rng, width=1.0)  # молот
    _wrect(out, x + w * 0.7 + 5, y + 11, 4, 4, rng, width=0.9)


def _g_altar(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    _wrect(out, x + w / 2 - 12, y + 4, 24, h - 10, rng, width=1.3)
    _stroke(out, [(x + w / 2 - 12, y + h - 6), (x + w / 2 - 8, y + h - 2), (x + w / 2 + 8, y + h - 2),
                  (x + w / 2 + 12, y + h - 6)], rng, width=0.8)
    for dx in (-16, 16):
        _wcircle(out, x + w / 2 + dx, y + 8, 1.6, rng, width=0.8)
        _stroke(out, [(x + w / 2 + dx, y + 5), (x + w / 2 + dx, y + 3)], rng, width=0.7)


def _g_pews(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    rows = max(2, int(h / 16))
    for i in range(rows):
        yy = y + 6 + i * (h - 10) / rows
        _wrect(out, x + 5, yy, w - 10, 5, rng, width=0.9)


def _g_bed(out, r, rng, small=False):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    bx, by, bw, bh = x + 3, y + 3, w - 6, h - 6
    if small:
        bw, bh = min(bw, 18), min(bh, 30)
    _wrect(out, bx, by, bw, bh, rng, width=1.2)
    _wrect(out, bx + 2, by + 2, bw - 4, bh * 0.22, rng, width=0.8)      # подушка
    for i in range(2):                                                   # одеяло
        yy = by + bh * (0.5 + i * 0.18)
        _stroke(out, [(bx + 1, yy), (bx + bw - 1, yy)], rng, width=0.6, opacity=0.55)


def _g_shelves(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    _wrect(out, x + 2, y + 3, w - 4, h - 6, rng, width=1.1)
    for i in range(1, 3):
        yy = y + 3 + (h - 6) * i / 3
        _stroke(out, [(x + 3, yy), (x + w - 3, yy)], rng, width=0.7)
        for j in range(max(1, int(w / 9))):
            _wcircle(out, x + 6 + j * 8, yy - 3, 1.5, rng, width=0.6)


def _g_storage(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    _wcircle(out, x + w * 0.3, y + h * 0.62, min(w, h) * 0.2, rng, width=1.1)      # бочка
    _wcircle(out, x + w * 0.3, y + h * 0.62, min(w, h) * 0.09, rng, width=0.6)
    bx = x + w * 0.62
    _wrect(out, bx, y + h * 0.42, min(w, h) * 0.36, min(w, h) * 0.36, rng, width=1.0)  # ящик
    _stroke(out, [(bx, y + h * 0.42), (bx + min(w, h) * 0.36, y + h * 0.42 + min(w, h) * 0.36)],
            rng, width=0.6, opacity=0.6)


def _g_desk(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    _wrect(out, x + 5, y + 6, w * 0.5, 12, rng, width=1.1)
    _wcircle(out, x + 5 + w * 0.25, y + 26, 3.4, rng, width=0.9)
    px, py = x + w * 0.68, y + 8                                        # бумага
    out.append(f'<g transform="rotate(9 {px} {py})">')
    _wrect(out, px, py, 9, 12, rng, width=0.7)
    out.append("</g>")


def _g_cell(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    for i in range(1, 5):                                               # решётка по входной стене
        xx = x + w * i / 5
        _stroke(out, [(xx, y + h - 7), (xx, y + h - 1)], rng, width=1.2)
    _wrect(out, x + 4, y + 5, w - 8, 6, rng, width=0.9)                 # лежак


def _g_bath(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    cx, cy = x + w / 2, y + h / 2
    _wcircle(out, cx, cy, min(w, h) * 0.36, rng, width=1.3)
    for i in range(2):
        yy = cy - 3 + i * 5
        _stroke(out, [(cx - 8, yy), (cx - 3, yy + 2), (cx + 2, yy - 1), (cx + 7, yy + 1)],
                rng, width=0.6, opacity=0.7)


def _g_stall(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    for i in range(3):
        xx = x + 4 + i * (w - 8) / 2
        _stroke(out, [(xx, y + 4), (xx, y + h - 4)], rng, width=1.1)
    _stroke(out, [(x + 3, y + h * 0.4), (x + w - 3, y + h * 0.4)], rng, width=0.8)
    for _ in range(5):                                                  # сено
        sx, sy = x + rng.uniform(8, w - 8), y + h - rng.uniform(6, 12)
        _stroke(out, [(sx - 3, sy), (sx + 3, sy - 2)], rng, width=0.5, opacity=0.6)


def _g_well(out, r, rng):
    cx, cy = r["cx"], r["cy"]
    _wcircle(out, cx, cy, 9, rng, width=1.3)
    _wcircle(out, cx, cy, 5.5, rng, width=0.8)
    _stroke(out, [(cx - 12, cy), (cx + 12, cy)], rng, width=0.9)


def _g_post(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    _wrect(out, x + 5, y + 5, w - 10, h - 12, rng, width=1.2)
    for i in range(3):
        px, py = x + 9 + i * (w - 22) / 2, y + 9 + (i % 2) * 4
        out.append(f'<g transform="rotate({rng.uniform(-8, 8):.0f} {px} {py})">')
        _wrect(out, px, py, 6, 8, rng, width=0.6)
        out.append("</g>")


GLYPHS = {
    "tables": lambda o, r, g, ctx: _g_table(o, r, g),
    "games": lambda o, r, g, ctx: _g_table(o, r, g, dice=True),
    "bar": lambda o, r, g, ctx: _g_bar(o, r, g),
    "counter": lambda o, r, g, ctx: _g_bar(o, r, g),
    "hearth": lambda o, r, g, ctx: _g_hearth(o, r, g, ctx.get("left", True)),
    "workshop": lambda o, r, g, ctx: _g_workshop(o, r, g),
    "altar": lambda o, r, g, ctx: _g_altar(o, r, g),
    "pews": lambda o, r, g, ctx: _g_pews(o, r, g),
    "beds": lambda o, r, g, ctx: _g_bed(o, r, g, small=ctx.get("small", False)),
    "shelves": lambda o, r, g, ctx: _g_shelves(o, r, g),
    "storage": lambda o, r, g, ctx: _g_storage(o, r, g),
    "private": lambda o, r, g, ctx: _g_desk(o, r, g),
    "cell": lambda o, r, g, ctx: _g_cell(o, r, g),
    "bath": lambda o, r, g, ctx: _g_bath(o, r, g),
    "yard": lambda o, r, g, ctx: _g_stall(o, r, g),
    "stalls": lambda o, r, g, ctx: _g_post(o, r, g),
    "well": lambda o, r, g, ctx: _g_well(o, r, g),
    "post": lambda o, r, g, ctx: _g_post(o, r, g),
}


# ── сборка листа ─────────────────────────────────────────────────────────────

def _defs(seed: int) -> str:
    return f"""<defs>
<filter id="grain" x="0" y="0" width="100%" height="100%">
  <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="{seed % 97}" result="n"/>
  <feColorMatrix in="n" type="matrix" values="0 0 0 0 0.23 0 0 0 0 0.19 0 0 0 0 0.13 0 0 0 0.14 0"/>
  <feComposite operator="over" in2="SourceGraphic"/>
</filter>
<filter id="stains" x="0" y="0" width="100%" height="100%">
  <feTurbulence type="fractalNoise" baseFrequency="0.012 0.016" numOctaves="3" seed="{seed % 51}" result="n"/>
  <feColorMatrix in="n" type="matrix" values="0 0 0 0 0.35 0 0 0 0 0.27 0 0 0 0 0.14 0 0 0 0.16 0"/>
  <feComposite operator="over" in2="SourceGraphic"/>
</filter>
</defs>"""


def paper_svg(plan: dict, data: dict, seed_key: str = "") -> str:
    """План (floorplan.plan_location) → пергаментный лист с глифами, хэтчингом и легендой."""
    rng = _rng(seed_key or plan.get("name", ""))
    seed = int(hashlib.md5((seed_key or "x").encode()).hexdigest()[:6], 16)
    fl = plan["floors"][0]
    back_h = fl.get("back", {}).get("h", 0)
    up = plan["floors"][1] if len(plan["floors"]) > 1 else None

    main_w = fl["w"] * CELL
    main_h = (fl["h"] + back_h) * CELL
    up_w = (up["w"] * CELL + 24) if up else 0
    pad = 30
    title_h = 26
    legend_zones = (fl.get("back", {}).get("rooms", []) + fl["zones"]
                    + (up["zones"] if up else []))
    # легенда: группы схлопываем («столы 2-9»), якоря поимённо
    legend, seen_groups = [], set()
    for i, r in enumerate(legend_zones):
        base = r["name"].split(" ")[0]
        grp = base if sum(1 for q in legend_zones if q["name"].split(" ")[0] == base) > 2 else None
        if grp:
            if grp in seen_groups:
                continue
            seen_groups.add(grp)
            idxs = [j + 1 for j, q in enumerate(legend_zones) if q["name"].split(" ")[0] == base]
            legend.append(f"{idxs[0]}–{idxs[-1]} — {base} ×{len(idxs)}")
        else:
            legend.append(f"{i + 1} — {r['name']}" + (" 🔒" if r.get("lock") else ""))
    legend_h = 14 * ((len(legend) + 1) // 2) + 10

    W = pad * 2 + main_w + up_w
    H = pad * 2 + title_h + main_h + legend_h
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%">',
           _defs(seed),
           f'<rect width="{W}" height="{H}" fill="{PAPER}"/>',
           f'<rect width="{W}" height="{H}" fill="{PAPER}" filter="url(#stains)"/>',
           f'<rect width="{W}" height="{H}" fill="none" filter="url(#grain)"/>']
    # рамка листа
    _wrect(out, 6, 6, W - 12, H - 12, rng, width=1.0, wob=0.7, opacity=0.5)
    # титул
    name = data.get("name") or plan.get("name") or ""
    out.append(f'<text x="{W / 2}" y="{pad - 6 + 14}" text-anchor="middle" font-size="14" '
               f'font-family="Georgia, serif" font-style="italic" fill="{INK}">{name}</text>')

    ox, oy = pad, pad + title_h
    hall_oy = oy + back_h * CELL

    def px(r, o_y):
        return {"px": ox + r["x"] * CELL, "py": o_y + r["y"] * CELL,
                "pw": r["w"] * CELL, "ph": r["h"] * CELL,
                "cx": ox + (r["x"] + r["w"] / 2) * CELL, "cy": o_y + (r["y"] + r["h"] / 2) * CELL}

    # сетка внутри футпринта (едва заметная)
    outline_px = [(ox + x * CELL, hall_oy + y * CELL) for x, y in fl.get("outline", [])]
    if outline_px:
        pid = f"clip{seed % 9999}"
        out.append(f'<clipPath id="{pid}"><polygon points="'
                   + " ".join(f"{x},{y}" for x, y in outline_px) + '"/></clipPath>')
        g = [f'<g clip-path="url(#{pid})" opacity="0.12">']
        for gx in range(0, fl["w"] + 1):
            g.append(f'<line x1="{ox + gx * CELL}" y1="{hall_oy}" x2="{ox + gx * CELL}" '
                     f'y2="{hall_oy + fl["h"] * CELL}" stroke="{FAINT}" stroke-width="0.5"/>')
        for gy in range(0, fl["h"] + 1):
            g.append(f'<line x1="{ox}" y1="{hall_oy + gy * CELL}" x2="{ox + fl["w"] * CELL}" '
                     f'y2="{hall_oy + gy * CELL}" stroke="{FAINT}" stroke-width="0.5"/>')
        out.append("".join(g) + "</g>")

    # хэтчинг наружу + стены (двойной штрих); при пристройке верх зала не хэтчим —
    # штрихуем внешний контур БЛОКА пристройки
    hall = fl.get("hall") or {"x": 0, "w": fl["w"]}
    has_back = bool(fl.get("back", {}).get("rooms"))
    bx0, bx1 = ox + hall["x"] * CELL, ox + (hall["x"] + hall["w"]) * CELL
    if outline_px:
        segs = _outline_segs(outline_px)
        if has_back:
            segs = [s for s in segs
                    if not (abs(s[0][1] - hall_oy) < 1 and abs(s[1][1] - hall_oy) < 1
                            and min(s[0][0], s[1][0]) >= bx0 - 1
                            and max(s[0][0], s[1][0]) <= bx1 + 1)]
            segs += [((bx0, oy), (bx1, oy), (0, -1)),
                     ((bx0, hall_oy), (bx0, oy), (-1, 0)),
                     ((bx1, oy), (bx1, hall_oy), (1, 0))]
        _hatch_segments(out, segs, rng)
        _stroke(out, outline_px, rng, width=2.3, w=1.1, close=True)
        _stroke(out, outline_px, rng, width=1.0, w=1.3, close=True, opacity=0.55)
    # пристройки: свой блок стен над залом + перегородки + дверные проёмы с дугой
    rooms = fl.get("back", {}).get("rooms", [])
    if rooms:
        bx0, bx1 = ox + hall["x"] * CELL, ox + (hall["x"] + hall["w"]) * CELL
        _stroke(out, [(bx0, oy), (bx1, oy), (bx1, hall_oy), (bx0, hall_oy)], rng,
                width=2.0, w=1.0, close=True)
        for r in rooms[:-1]:
            xx = ox + (r["x"] + r["w"]) * CELL
            _stroke(out, [(xx, oy + 2), (xx, hall_oy - 2)], rng, width=1.6)
        for r in rooms:
            dx = ox + r["door_x"] * CELL + CELL // 2
            out.append(f'<line x1="{dx - 7}" y1="{hall_oy}" x2="{dx + 7}" y2="{hall_oy}" '
                       f'stroke="{PAPER}" stroke-width="4"/>')
            out.append(f'<path d="M {dx - 7} {hall_oy} A 14 14 0 0 1 {dx + 7} {hall_oy + 14}" '
                       f'fill="none" stroke="{INK}" stroke-width="0.7" opacity="0.7"/>')

    # окна: двойные засечки в стене
    win = fl.get("windows")
    wx0, wx1 = ox + hall["x"] * CELL, ox + (hall["x"] + hall["w"]) * CELL
    for k in range(2, fl["h"] - 2, 3):
        for side_x, on in ((wx0, win in ("left", "both")), (wx1, win in ("right", "both"))):
            if not on:
                continue
            y1 = hall_oy + k * CELL + 4
            out.append(f'<line x1="{side_x - 3}" y1="{y1}" x2="{side_x + 3}" y2="{y1}" '
                       f'stroke="{INK}" stroke-width="1.4"/>')
            out.append(f'<line x1="{side_x - 3}" y1="{y1 + 9}" x2="{side_x + 3}" y2="{y1 + 9}" '
                       f'stroke="{INK}" stroke-width="1.4"/>')

    # вход: проём + дуга
    d = fl.get("door")
    if d:
        dx = ox + d["x"] * CELL + CELL // 2
        dy = hall_oy + fl["h"] * CELL
        out.append(f'<line x1="{dx - 10}" y1="{dy}" x2="{dx + 10}" y2="{dy}" '
                   f'stroke="{PAPER}" stroke-width="5"/>')
        out.append(f'<path d="M {dx - 10} {dy} A 20 20 0 0 1 {dx + 10} {dy - 20}" '
                   f'fill="none" stroke="{INK}" stroke-width="0.8" opacity="0.75"/>')

    # лестница
    if fl.get("stairs"):
        sx, sy = fl["stairs"]
        x0, y0 = ox + sx * CELL, hall_oy + sy * CELL
        _wrect(out, x0, y0, 2 * CELL - 2, 2 * CELL - 2, rng, width=1.1)
        for k in range(1, 5):
            _stroke(out, [(x0 + 2, y0 + k * 8), (x0 + 2 * CELL - 4, y0 + k * 8)], rng, width=0.8)

    # глифы зон + номера
    num = 1
    for r in rooms:
        ctx = {"left": True, "small": True}
        rr = px(r, oy)
        GLYPHS.get(r["kind"], lambda *a: None)(out, rr, rng, ctx)
        _wcircle(out, rr["px"] + 8, rr["py"] + 8, 6, rng, width=0.8, fill=PAPER)
        out.append(f'<text x="{rr["px"] + 8}" y="{rr["py"] + 11}" text-anchor="middle" '
                   f'font-size="8" font-family="Georgia, serif" fill="{INK}">{num}</text>')
        if r.get("lock"):
            out.append(f'<text x="{rr["px"] + rr["pw"] - 10} " y="{rr["py"] + 12}" font-size="8">🔒</text>')
        num += 1
    mid_x = ox + (hall["x"] + hall["w"] / 2) * CELL
    for r in fl["zones"]:
        rr = px(r, hall_oy)
        ctx = {"left": rr["cx"] < mid_x, "small": False}
        GLYPHS.get(r["kind"], lambda *a: None)(out, rr, rng, ctx)
        _wcircle(out, rr["px"] + 7, rr["py"] + 7, 6, rng, width=0.8, fill=PAPER)
        out.append(f'<text x="{rr["px"] + 7}" y="{rr["py"] + 10}" text-anchor="middle" '
                   f'font-size="8" font-family="Georgia, serif" fill="{INK}">{num}</text>')
        num += 1

    # 2-й этаж — отдельный блок справа
    if up:
        ux = pad + main_w + 24
        uy = hall_oy
        upts = [(ux, uy), (ux + up["w"] * CELL, uy), (ux + up["w"] * CELL, uy + up["h"] * CELL),
                (ux, uy + up["h"] * CELL)]
        _hatch_segments(out, _outline_segs(upts), rng)
        _stroke(out, upts, rng, width=2.0, w=1.0, close=True)
        out.append(f'<text x="{ux}" y="{uy - 6}" font-size="10" font-family="Georgia, serif" '
                   f'font-style="italic" fill="{INK}">2-й этаж</text>')
        for r in up["zones"]:
            rr = {"px": ux + r["x"] * CELL, "py": uy + r["y"] * CELL,
                  "pw": r["w"] * CELL, "ph": r["h"] * CELL,
                  "cx": ux + (r["x"] + r["w"] / 2) * CELL, "cy": uy + (r["y"] + r["h"] / 2) * CELL}
            if r["x"] > 0:
                _stroke(out, [(rr["px"], uy + 2), (rr["px"], uy + up["h"] * CELL - 2)], rng, width=1.4)
            _g_bed(out, rr, rng, small=True)
            out.append(f'<line x1="{rr["px"] + rr["pw"] / 2 - 6}" y1="{uy + up["h"] * CELL}" '
                       f'x2="{rr["px"] + rr["pw"] / 2 + 6}" y2="{uy + up["h"] * CELL}" '
                       f'stroke="{PAPER}" stroke-width="4"/>')
            _wcircle(out, rr["px"] + 7, rr["py"] + 7, 6, rng, width=0.8, fill=PAPER)
            out.append(f'<text x="{rr["px"] + 7}" y="{rr["py"] + 10}" text-anchor="middle" '
                       f'font-size="8" font-family="Georgia, serif" fill="{INK}">{num}</text>')
            num += 1

    # легенда двумя колонками
    ly0 = oy + main_h + 14
    col_w = (W - pad * 2) / 2
    for i, line in enumerate(legend):
        lx = pad + (i % 2) * col_w
        ly = ly0 + (i // 2) * 14
        out.append(f'<text x="{lx}" y="{ly}" font-size="9.5" font-family="Georgia, serif" '
                   f'font-style="italic" fill="{INK}" opacity="0.9">{line}</text>')
    out.append("</svg>")
    return "".join(out)
