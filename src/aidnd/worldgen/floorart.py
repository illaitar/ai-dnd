"""Paper-rendered location plan: parchment + inky trembling stroke + Dyson-hatching +
furniture glyphs + zone numbering with legend (one-page-dungeon / old D&D modules aesthetic).

Pure SVG (feTurbulence for paper and stains, no canvas). Stroke tremor is seeded
(the same building always drawn identically). Geometry from floorplan.plan_location;
here — only aesthetics over ready coordinates.

Key functions
-------------
paper_svg(plan: dict, data: dict, seed_key: str = "", game: dict | None = None) -> str : Render location plan as parchment map with glyphs and legend.
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


# ── Trembling primitives (rough.js-style, seeded) ────────────────────────

def _wob(pts, rng, w=1.0):
    """Polyline with tremor: segments subdivide, points offset. Returns path d attribute."""
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
    """Dyson-hatching: short strokes outward along segments ((x1,y1),(x2,y2),(nx,ny))."""
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
    """Polygon (CW) → segments with outward normals."""
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


# ── Furniture glyphs (inked, top-down view) ───────────────────────────────────

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
    for i in range(4):                                       # heat-strokes
        a = -math.pi / 2 + (i - 1.5) * 0.5
        sx = fx + math.cos(a) * 10
        sy = cy + math.sin(a) * 10
        _stroke(out, [(sx, sy), (sx + math.cos(a) * 5, sy + math.sin(a) * 5)], rng, width=0.6, opacity=0.5)
    _ = cx


def _g_workshop(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    _wrect(out, x + 3, y + h - 13, w - 6, 10, rng, width=1.2)   # workbench
    ax, ay = x + w * 0.35, y + h * 0.34                          # anvil
    _stroke(out, [(ax - 6, ay + 4), (ax + 6, ay + 4), (ax + 4, ay), (ax + 7, ay - 3),
                  (ax - 3, ay - 3), (ax - 4, ay)], rng, width=1.1, close=True, w=0.5)
    _stroke(out, [(x + w * 0.7, y + 8), (x + w * 0.7 + 7, y + 13)], rng, width=1.0)  # hammer
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
    _wrect(out, bx + 2, by + 2, bw - 4, bh * 0.22, rng, width=0.8)      # pillow
    for i in range(2):                                                   # blanket
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
    _wcircle(out, x + w * 0.3, y + h * 0.62, min(w, h) * 0.2, rng, width=1.1)      # barrel
    _wcircle(out, x + w * 0.3, y + h * 0.62, min(w, h) * 0.09, rng, width=0.6)
    bx = x + w * 0.62
    _wrect(out, bx, y + h * 0.42, min(w, h) * 0.36, min(w, h) * 0.36, rng, width=1.0)  # box
    _stroke(out, [(bx, y + h * 0.42), (bx + min(w, h) * 0.36, y + h * 0.42 + min(w, h) * 0.36)],
            rng, width=0.6, opacity=0.6)


def _g_desk(out, r, rng):
    x, y, w = r["px"], r["py"], r["pw"]
    _wrect(out, x + 5, y + 6, w * 0.5, 12, rng, width=1.1)
    _wcircle(out, x + 5 + w * 0.25, y + 26, 3.4, rng, width=0.9)
    px, py = x + w * 0.68, y + 8                                        # paper
    out.append(f'<g transform="rotate(9 {px} {py})">')
    _wrect(out, px, py, 9, 12, rng, width=0.7)
    out.append("</g>")


def _g_cell(out, r, rng):
    x, y, w, h = r["px"], r["py"], r["pw"], r["ph"]
    for i in range(1, 5):                                               # gate at entrance wall
        xx = x + w * i / 5
        _stroke(out, [(xx, y + h - 7), (xx, y + h - 1)], rng, width=1.2)
    _wrect(out, x + 4, y + 5, w - 8, 6, rng, width=0.9)                 # bunk


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
    for _ in range(5):                                                  # hay
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


# ── Sheet assembly ─────────────────────────────────────────────────────────────

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


def _fillers(out, fl, rng, ox, hall_oy):
    """Habitability: rug at entrance, firewood at hearth, stains/cracks on open floor."""
    occ = {(r["x"] + i, r["y"] + j) for r in fl["zones"]
           for i in range(r["w"]) for j in range(r["h"])}
    d = fl.get("door")
    if d:                                                    # rug at entrance
        cx, cy = ox + d["x"] * CELL + CELL / 2, hall_oy + (fl["h"] - 1.6) * CELL
        _wcircle(out, cx, cy, 8, rng, width=0.8, opacity=0.7)
        _wcircle(out, cx, cy, 5, rng, width=0.5, opacity=0.5)
    hearth = next((r for r in fl["zones"] if r["kind"] == "hearth"), None)
    if hearth:                                               # firewood at hearth
        hx = ox + hearth["x"] * CELL + (hearth["w"] * CELL + 6 if hearth["x"] < fl["w"] / 2
                                        else -10)
        hy = hall_oy + (hearth["y"] + hearth["h"]) * CELL - 6
        for i in range(3):
            _wcircle(out, hx + (i % 2) * 5, hy - i * 4, 2.6, rng, width=0.7, opacity=0.8)
    hall = fl.get("hall") or {"x": 0, "w": fl["w"]}
    for _ in range(3):                                       # floor stains/cracks
        x = rng.randint(hall["x"] + 1, hall["x"] + hall["w"] - 2)
        y = rng.randint(1, fl["h"] - 2)
        if (x, y) in occ:
            continue
        px, py = ox + x * CELL + CELL / 2, hall_oy + y * CELL + CELL / 2
        if rng.random() < 0.5:                               # stain
            _wcircle(out, px, py, rng.uniform(4, 8), rng, width=0.0,
                     fill=INK, opacity=0.05)
        else:                                                # crack
            pts = [(px, py)]
            for _k in range(3):
                pts.append((pts[-1][0] + rng.uniform(-9, 9), pts[-1][1] + rng.uniform(3, 8)))
            _stroke(out, pts, rng, width=0.5, w=0.4, opacity=0.35)


def _npc_markers(out, fl, game, ox, oy, hall_oy):
    """People markers on the plan: circle-initial at their zone; player is bold ring.
    Hall zones drawn from hall_oy, extension rooms from oy (top stripe)."""
    back_ids = {r["id"] for r in fl.get("back", {}).get("rooms", [])}
    zid2rect = {r["id"]: r for r in fl["zones"]}
    zid2rect.update({r["id"]: r for r in fl.get("back", {}).get("rooms", [])})
    by_zone: dict = {}
    for p in game.get("npcs") or []:
        by_zone.setdefault(p.get("zone"), []).append(p)
    for zid, ps in by_zone.items():
        r = zid2rect.get(zid)
        for i, p in enumerate(ps):
            if r:
                base_y = oy if r["id"] in back_ids else hall_oy
                cx = ox + (r["x"] + r["w"] / 2) * CELL + (i - (len(ps) - 1) / 2) * 13
                cy = base_y + (r["y"] + r["h"] - 0.45) * CELL
            else:                                            # no zone — at entrance
                d = fl.get("door") or {"x": 2}
                cx = ox + d["x"] * CELL + CELL / 2 + (i - (len(ps) - 1) / 2) * 13
                cy = hall_oy + (fl["h"] - 2.2) * CELL
            col = p.get("color") or "#7a5a3a"
            sw = 2.4 if p.get("is_player") else 1.1
            out.append(f'<g class="npc" data-pid="{p.get("id", "")}" style="cursor:pointer">'
                       f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="7.5" fill="{PAPER}" '
                       f'stroke="{col}" stroke-width="{sw}"/>'
                       f'<text x="{cx:.0f}" y="{cy + 3:.0f}" text-anchor="middle" font-size="8" '
                       f'font-family="Georgia, serif" fill="{INK}">{p.get("init", "?")}</text>'
                       f'<title>{p.get("name", "")}</title></g>')


def paper_svg(plan: dict, data: dict, seed_key: str = "", game: dict | None = None) -> str:
    """Plan (floorplan.plan_location) → parchment sheet with glyphs, hatching, and legend.
    game (game mode): {npcs: [{id, name, init, color, zone, is_player}], locked_hidden:
    bool, interactive: bool} — people markers, fog on locked, clickable zones."""
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
    # legend: collapse groups (e.g. "tables 2-9"), anchors by name
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
    # sheet frame
    _wrect(out, 6, 6, W - 12, H - 12, rng, width=1.0, wob=0.7, opacity=0.5)
    # title
    name = data.get("name") or plan.get("name") or ""
    out.append(f'<text x="{W / 2}" y="{pad - 6 + 14}" text-anchor="middle" font-size="14" '
               f'font-family="Georgia, serif" font-style="italic" fill="{INK}">{name}</text>')

    ox, oy = pad, pad + title_h
    hall_oy = oy + back_h * CELL

    def px(r, o_y):
        return {"px": ox + r["x"] * CELL, "py": o_y + r["y"] * CELL,
                "pw": r["w"] * CELL, "ph": r["h"] * CELL,
                "cx": ox + (r["x"] + r["w"] / 2) * CELL, "cy": o_y + (r["y"] + r["h"] / 2) * CELL}

    # grid inside footprint (barely visible)
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

    # hatching outward + walls (double stroke); with extension, don't hatch hall top —
    # hatch outer contour of EXTENSION BLOCK
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
    # extensions: own wall block above hall + partitions + doorways with arc
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

    # windows: double marks — ONLY on outer walls (L-wing hall wall is interior)
    win = fl.get("windows")
    wing = fl.get("wing")
    wx0, wx1 = ox + hall["x"] * CELL, ox + (hall["x"] + hall["w"]) * CELL
    for k in range(2, fl["h"] - 2, 3):
        left_ext = not (wing and wing["side"] == "left" and k >= wing["y"])
        right_ext = not (wing and wing["side"] == "right" and k >= wing["y"])
        for side_x, on in ((wx0, win in ("left", "both") and left_ext),
                           (wx1, win in ("right", "both") and right_ext)):
            if not on:
                continue
            y1 = hall_oy + k * CELL + 4
            out.append(f'<line x1="{side_x - 3}" y1="{y1}" x2="{side_x + 3}" y2="{y1}" '
                       f'stroke="{INK}" stroke-width="1.4"/>')
            out.append(f'<line x1="{side_x - 3}" y1="{y1 + 9}" x2="{side_x + 3}" y2="{y1 + 9}" '
                       f'stroke="{INK}" stroke-width="1.4"/>')

    # entrance: opening + arc
    d = fl.get("door")
    if d:
        dx = ox + d["x"] * CELL + CELL // 2
        dy = hall_oy + fl["h"] * CELL
        out.append(f'<line x1="{dx - 10}" y1="{dy}" x2="{dx + 10}" y2="{dy}" '
                   f'stroke="{PAPER}" stroke-width="5"/>')
        out.append(f'<path d="M {dx - 10} {dy} A 20 20 0 0 1 {dx + 10} {dy - 20}" '
                   f'fill="none" stroke="{INK}" stroke-width="0.8" opacity="0.75"/>')

    # stairs
    if fl.get("stairs"):
        sx, sy = fl["stairs"]
        x0, y0 = ox + sx * CELL, hall_oy + sy * CELL
        _wrect(out, x0, y0, 2 * CELL - 2, 2 * CELL - 2, rng, width=1.1)
        for k in range(1, 5):
            _stroke(out, [(x0 + 2, y0 + k * 8), (x0 + 2 * CELL - 4, y0 + k * 8)], rng, width=0.8)

    # zone glyphs + numbers (+game mode: fog on hidden, interactive overlays)
    hidden_zones = set((game or {}).get("hidden_zones") or ())
    interactive = bool((game or {}).get("interactive"))

    def _fog(rr):
        for k in range(0, int(rr["pw"] + rr["ph"]), 7):      # diagonal fog hatching
            x1 = rr["px"] + max(0, k - rr["ph"])
            y1 = rr["py"] + min(k, rr["ph"])
            x2 = rr["px"] + min(k, rr["pw"])
            y2 = rr["py"] + max(0, k - rr["pw"])
            out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                       f'stroke="{INK}" stroke-width="0.5" opacity="0.18"/>')
        out.append(f'<text x="{rr["cx"]:.0f}" y="{rr["cy"] + 4:.0f}" text-anchor="middle" '
                   f'font-size="11">🔒</text>')

    def _overlay(rr, zid, name):
        if interactive:
            out.append(f'<rect class="zone" data-zid="{zid}" x="{rr["px"]}" y="{rr["py"]}" '
                       f'width="{rr["pw"]}" height="{rr["ph"]}" fill="transparent" '
                       f'style="cursor:pointer"><title>{name}</title></rect>')

    num = 1
    for r in rooms:
        rr = px(r, oy)
        if r["id"] in hidden_zones:
            _fog(rr)
        else:
            GLYPHS.get(r["kind"], lambda *a: None)(out, rr, rng, {"left": True, "small": True})
            if r.get("lock"):
                out.append(f'<text x="{rr["px"] + rr["pw"] - 12}" y="{rr["py"] + 12}" font-size="8">🔒</text>')
        _wcircle(out, rr["px"] + 8, rr["py"] + 8, 6, rng, width=0.8, fill=PAPER)
        out.append(f'<text x="{rr["px"] + 8}" y="{rr["py"] + 11}" text-anchor="middle" '
                   f'font-size="8" font-family="Georgia, serif" fill="{INK}">{num}</text>')
        _overlay(rr, r["id"], r["name"])
        num += 1
    mid_x = ox + (hall["x"] + hall["w"] / 2) * CELL
    for r in fl["zones"]:
        rr = px(r, hall_oy)
        GLYPHS.get(r["kind"], lambda *a: None)(out, rr, rng,
                                               {"left": rr["cx"] < mid_x, "small": False})
        _wcircle(out, rr["px"] + 7, rr["py"] + 7, 6, rng, width=0.8, fill=PAPER)
        out.append(f'<text x="{rr["px"] + 7}" y="{rr["py"] + 10}" text-anchor="middle" '
                   f'font-size="8" font-family="Georgia, serif" fill="{INK}">{num}</text>')
        _overlay(rr, r["id"], r["name"])
        num += 1
    _fillers(out, fl, rng, ox, hall_oy)
    if game:
        _npc_markers(out, fl, game, ox, oy, hall_oy)
        if game.get("more"):
            out.append(f'<text x="{ox + 4}" y="{hall_oy + (fl["h"] - 0.4) * CELL}" '
                       f'font-size="9" font-family="Georgia, serif" font-style="italic" '
                       f'fill="{INK}" opacity="0.75">…и ещё {game["more"]} душ в зале</text>')

    # 2nd floor — separate block on the right
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
            if r["id"] in hidden_zones:
                _fog(rr)
            else:
                _g_bed(out, rr, rng, small=True)
            _overlay(rr, r["id"], r["name"])
            out.append(f'<line x1="{rr["px"] + rr["pw"] / 2 - 6}" y1="{uy + up["h"] * CELL}" '
                       f'x2="{rr["px"] + rr["pw"] / 2 + 6}" y2="{uy + up["h"] * CELL}" '
                       f'stroke="{PAPER}" stroke-width="4"/>')
            _wcircle(out, rr["px"] + 7, rr["py"] + 7, 6, rng, width=0.8, fill=PAPER)
            out.append(f'<text x="{rr["px"] + 7}" y="{rr["py"] + 10}" text-anchor="middle" '
                       f'font-size="8" font-family="Georgia, serif" fill="{INK}">{num}</text>')
            num += 1

    # legend in two columns
    ly0 = oy + main_h + 14
    col_w = (W - pad * 2) / 2
    for i, line in enumerate(legend):
        lx = pad + (i % 2) * col_w
        ly = ly0 + (i // 2) * 14
        out.append(f'<text x="{lx}" y="{ly}" font-size="9.5" font-family="Georgia, serif" '
                   f'font-style="italic" fill="{INK}" opacity="0.9">{line}</text>')
    out.append("</svg>")
    return "".join(out)
