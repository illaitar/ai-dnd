"""Location plan v3: footprint + cost function + simulated annealing (docs/locations.md).

Division by research (Make It Home, LayoutVLM): LLM/data provide FLAVOR and RELATIONSHIPS
(preset layout, spots "by window"/"in dark corner", privacy zones) — CODE solves geometry
with optimizer and provides guarantees.

Structure:
- FOOTPRINT: deterministic archetype by building seed — rectangular hall or L (hall+alcove-wing);
  outline polygon drawn by walls. (Future hook: worlds can provide rasterized polygon of real house
  from city map.)
- ANCHORS (counter/hearth/workshop/altar/stairs) — by rules per preset, frozen.
- GROUPS (tables/beds/stalls) — on GRID lattice (rows guaranteed by construction),
  layout on lattice searched by simulated annealing (Metropolis) with terms:
  spot preference · privacy↔distance-from-aisle · sparseness · clearance.
- GUARANTEES: main aisle and cell before each door reserved; final
  reachable() (BFS). Solved OFFLINE (pool/lazy materialization), runtime only renders.

Key functions
-------------
clamp_layout(d) -> dict : Validate and clamp layout parameters to allowed enums.
canonical_footprint(size, seed_key) -> dict : Generate deterministic building shape.
plan_location(data, seed_key) -> dict : Assemble location floor plan from zone data.
reachable(plan) -> bool : Verify all critical doors and stairs are accessible (BFS).
canonical_mask_from(fl) -> set : Extract interior cell mask from saved floor layout.
plan_svg(plan) -> str : Render location plan as SVG visualization.
"""

from __future__ import annotations

import hashlib
import math
import random

CELL = 22
HALL = {"small": (11, 8), "medium": (13, 9), "large": (15, 10)}

LAYOUT_DEFAULTS = {"windows": "left", "bar_wall": "left", "tables": "rows", "density": "normal"}
LAYOUT_ENUMS = {"windows": ("left", "right", "both", "none"), "bar_wall": ("left", "right"),
                "tables": ("rows", "perimeter", "mixed"), "density": ("airy", "normal", "packed")}

PALETTE = {
    "bar": ("#7c5cff", .18), "tables": ("#5aa0ff", .14), "hearth": ("#ff8a3a", .20),
    "counter": ("#7c5cff", .18), "shelves": ("#3ec06a", .14), "storage": ("#8b96ab", .16),
    "workshop": ("#ff5050", .16), "altar": ("#ffd75a", .18), "pews": ("#5aa0ff", .10),
    "beds": ("#3ec06a", .16), "private": ("#c46bff", .16), "bath": ("#39c6d6", .16),
    "games": ("#ff5050", .14), "door": ("#dfe5ef", .10), "well": ("#39c6d6", .18),
    "post": ("#ffd75a", .18), "stalls": ("#ff8a3a", .14), "yard": ("#9a6", .14),
    "cell": ("#8b96ab", .22),
}

# weights for cost function terms (layout taste, not gameplay)
W_PREF, W_PRIV, W_SPREAD, W_CLEAR = 1.0, 2.5, 1.6, 3.0
ANNEAL_ITERS, T0, T1 = 4000, 1.2, 0.02


def clamp_layout(d: dict | None) -> dict:
    d = d if isinstance(d, dict) else {}
    return {k: (d.get(k) if d.get(k) in LAYOUT_ENUMS[k] else v)
            for k, v in LAYOUT_DEFAULTS.items()}


def _seed_int(key: str) -> int:
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)


# ── footprint: rectangular hall OR L (hall + alcove-wing) ──────────────────

def canonical_footprint(size: str, seed_key: str) -> dict:
    """Deterministic shape archetype. mask — cells INSIDE (interior), outline — wall polygon."""
    w, h = HALL.get(str(size), HALL["medium"])
    rng = random.Random(_seed_int("fp|" + seed_key))
    wing = None
    if rng.random() < 0.45:                                  # L: alcove-wing right or left
        ww = rng.randint(4, 5)
        wh = rng.randint(3, 4)
        side = rng.choice(("right", "left"))
        wing = {"side": side, "w": ww, "h": wh, "y": h - wh}  # wing at lower edge
    mask = {(x, y) for x in range(1, w - 1) for y in range(1, h - 1)}
    ox = 0
    if wing:
        if wing["side"] == "right":
            mask |= {(x, y) for x in range(w - 1, w - 1 + wing["w"])
                     for y in range(wing["y"] + 1, h - 1)}
            outline = [(0, 0), (w, 0), (w, wing["y"]), (w + wing["w"], wing["y"]),
                       (w + wing["w"], h), (0, h)]
            total_w = w + wing["w"]
        else:                                                # wing on left → shift hall right
            ox = wing["w"]
            mask = {(x + ox, y) for x, y in mask}
            mask |= {(x, y) for x in range(1, ox + 1) for y in range(wing["y"] + 1, h - 1)}
            outline = [(ox, 0), (ox + w, 0), (ox + w, h), (0, h), (0, wing["y"]),
                       (ox, wing["y"])]
            total_w = w + wing["w"]
    else:
        outline = [(0, 0), (w, 0), (w, h), (0, h)]
        total_w = w
    return {"hall": {"x": ox, "w": w, "h": h}, "wing": wing, "mask": mask,
            "outline": outline, "W": total_w, "H": h}


# ── spot semantics as continuous cost (lower is better) ──────────

def _pref(spot_name: str, pos: tuple[int, int], fp: dict, pois: dict, windows: str) -> float:
    x, y = pos
    hall = fp["hall"]
    hx0, hx1, hh = hall["x"], hall["x"] + hall["w"], hall["h"]
    n = spot_name.lower()

    def dist(p):
        return abs(x - p[0]) + abs(y - p[1]) if p else 30
    win_x = {"left": hx0 + 1, "right": hx1 - 2, "both": hx0 + 1, "none": None}[windows]
    if "у окна" in n:
        return abs(x - win_x) if win_x is not None else 15
    if "тёмном углу" in n or "дальнем углу" in n:
        cx = hx1 - 3 if windows in ("left", "both") else hx0 + 1
        return abs(x - cx) + y
    if "посреди" in n:
        return abs(x - (hx0 + hall["w"] // 2)) + abs(y - hh // 2)
    if "у двери" in n or "у входа" in n or "у ворот" in n:
        return dist(pois.get("door"))
    if "под лестницей" in n:
        return dist(pois.get("stairs"))
    if "у очага" in n or "у печи" in n:
        return dist(pois.get("hearth"))
    if "у бочек" in n:
        return dist(pois.get("storage_door"))
    if "у стены" in n or "за ширмой" in n or "крайн" in n or "тёмное" in n:
        return min(abs(x - hx0), abs(hx1 - 2 - x))
    return abs(y - hh // 2) * 0.5                            # numbered rooms — straight middle row


# ── cost function for group layout on lattice ─────────────────────────────────

def _cost(assign: dict, groups: list[dict], fp: dict, pois: dict, windows: str,
          aisle_x: int, occupied_free: set) -> float:
    c = 0.0
    poss = list(assign.values())
    for z in groups:
        x, y = assign[z["id"]]
        c += W_PREF * _pref(z["name"], (x, y), fp, pois, windows)
        # privacy ↔ distance from aisle/door: private tables far away
        d_aisle = min(abs(x - aisle_x), abs(x + 1 - aisle_x)) + max(0, (fp["H"] - 3) - y) * 0.3
        want = 1.0 + z.get("privacy", 0.3) * 7.0
        c += W_PRIV * abs(d_aisle - want) * 0.5
    for i, a in enumerate(poss):                             # sparseness: don't clump together
        for b in poss[i + 1:]:
            d = abs(a[0] - b[0]) + abs(a[1] - b[1])
            if d < 3:
                c += W_SPREAD * (3 - d)
            if a[0] == b[0] or a[1] == b[1]:                 # row discipline: shared axes — reward
                c -= 0.55
    for x, y in poss:                                        # clearance: free neighbor
        if not any((x + dx, y + dy) in occupied_free
                   for dx, dy in ((-1, 0), (2, 0), (0, -1), (0, 2))):
            c += W_CLEAR
    return c


def _lattice(fp: dict, blocked: set, aisle_x: int, density: str,
             zsize: tuple[int, int], pitches=None) -> list[tuple[int, int]]:
    """Slot grid over entire footprint (including wing) — rows guaranteed by construction."""
    zw, zh = zsize
    pitch_x = pitches[0] if pitches else zw + (2 if density == "airy" else 1)
    pitch_y = pitches[1] if pitches else zh + (2 if density == "airy" else 1 if density == "normal" else 0)
    slots = []
    xs = range(1, fp["W"] - 1)
    for y in range(2, fp["H"] - zh, pitch_y):
        for x in xs:
            if (x - 1) % pitch_x:
                continue
            cells = {(x + i, y + j) for i in range(zw) for j in range(zh)}
            if not cells <= fp["mask"] or cells & blocked:
                continue
            if any(abs(cx - aisle_x) < 1 for cx in range(x, x + zw)):
                continue
            slots.append((x, y))
    return slots


def _anneal(groups: list[dict], slots: list[tuple[int, int]], fp: dict, pois: dict,
            windows: str, aisle_x: int, rng: random.Random) -> dict:
    """Simulated annealing on lattice: move to free slot or swap two groups."""
    assign = {}
    free = list(slots)
    for z in groups:                                         # initialization — greedy by spot
        if not free:
            break
        best = min(free, key=lambda s: _pref(z["name"], s, fp, pois, windows))
        free.remove(best)
        assign[z["id"]] = best
    placed = [z for z in groups if z["id"] in assign]
    if len(placed) < 2 or not slots:
        return assign
    occ_free = fp["mask"] - set()                            # for clearance: full mask minus anchor-occupied
    cur = _cost(assign, placed, fp, pois, windows, aisle_x, occ_free)
    for it in range(ANNEAL_ITERS):
        t = T0 * (T1 / T0) ** (it / ANNEAL_ITERS)
        cand = dict(assign)
        if free and rng.random() < 0.55:                     # move
            z = rng.choice(placed)
            cand[z["id"]] = rng.choice(free)
        else:                                                # swap
            a, b = rng.sample(placed, 2)
            cand[a["id"]], cand[b["id"]] = cand[b["id"]], cand[a["id"]]
        if len(set(cand.values())) < len(placed):
            continue
        new = _cost(cand, placed, fp, pois, windows, aisle_x, occ_free)
        if new < cur or rng.random() < math.exp((cur - new) / max(t, 1e-6)):
            if free and assign != cand:
                used = set(cand.values())
                free = [s for s in slots if s not in used]
            assign, cur = cand, new
    return assign


# ── plan assembly ────────────────────────────────────────────────────────────

def plan_location(data: dict, seed_key: str = "") -> dict:
    """Factsheet (+layout) → plan: anchors by rules, groups by annealing, guarantees by code.
    Deterministic over (data, seed_key). Solve OFFLINE, cache result."""
    zones = data.get("zones") or []
    lay = clamp_layout(data.get("layout"))
    key = seed_key or f"{data.get('name', '')}|{len(zones)}"
    rng = random.Random(_seed_int("plan|" + key))
    back = [z for z in zones if z["kind"] in ("private", "storage", "cell")]
    upstairs = [z for z in zones if z["kind"] == "beds" and z.get("lockable")]
    hall_z = [z for z in zones if z not in back and z not in upstairs]
    groups = [z for z in hall_z if z.get("group")]
    anchors = [z for z in hall_z if not z.get("group")]

    fp = canonical_footprint(str(data.get("size")), key)
    hall = fp["hall"]
    hx0, hx1, H = hall["x"], hall["x"] + hall["w"], fp["H"]
    aisle_x = hx0 + hall["w"] // 2
    blocked: set = set()
    pois: dict = {"door": (aisle_x, H - 2)}
    rects: list[dict] = []

    def put(z, x, y, zw, zh, lock=False):
        blocked.update((x + i, y + j) for i in range(zw) for j in range(zh))
        rects.append({"id": z["id"], "name": z["name"], "kind": z["kind"], "x": x, "y": y,
                      "w": zw, "h": zh, "post": z.get("post"), "lock": lock,
                      "fixed": sum(1 for o in z.get("objects") or [] if o.get("fixed")),
                      "loose": sum(1 for o in z.get("objects") or [] if not o.get("fixed"))})

    doors_back = []
    if back:                                                 # annexes — strip behind upper wall of hall
        n = len(back)
        rw = max(2, hall["w"] // n)
        for i, z in enumerate(back):
            x0 = hx0 + i * rw
            ww = rw if i < n - 1 else hall["w"] - rw * (n - 1)
            dx = min(hx1 - 2, x0 + ww // 2)
            doors_back.append({"x": dx, "zone": z["id"], "x0": x0, "w": ww})
            blocked.add((dx, 1))
            if z["kind"] == "storage" and "storage_door" not in pois:
                pois["storage_door"] = (dx, 1)
    blocked.update((aisle_x, yy) for yy in range(1, H - 1))  # main aisle is sacred

    side = {"left": hx0 + 1, "right": hx1 - 3}
    for z in anchors:
        k = z["kind"]
        if k in ("bar", "counter"):
            put(z, side[lay["bar_wall"]], 2, 2, max(3, (H - 4) // 2))
        elif k == "hearth":
            hx = side["right" if lay["bar_wall"] == "left" else "left"]
            put(z, hx, H // 2 - 1, 2, 2)
            pois["hearth"] = (hx, H // 2)
        elif k in ("workshop", "bath"):
            put(z, side[lay["bar_wall"]], H - 4, 3, 2)
        elif k == "altar":
            put(z, max(hx0 + 1, aisle_x - 4), 1, 3, 2)
        elif k == "pews":
            put(z, max(hx0 + 1, aisle_x - 4), 4, 3, min(4, H - 6))
        elif k == "shelves":
            put(z, side["right" if lay["bar_wall"] == "left" else "left"], 2, 1, min(4, H - 4))
        elif k in ("well", "post"):
            put(z, aisle_x + 1, H // 2 - 1, 2, 2)
        elif k == "door":
            put(z, aisle_x + 1, H - 3, 1, 1)
    if upstairs:
        sx = hx1 - 3 if lay["bar_wall"] == "left" else hx0 + 1
        pois["stairs"] = (sx, H - 3)
        blocked.update((sx + i, H - 3 + j) for i in range(2) for j in range(2))
        apx = sx + 2 if sx == hx0 + 1 else sx - 1
        pois["stairs_approach"] = (apx, H - 3)
        blocked.add((apx, H - 3))

    zsize = (1, 2) if (groups and groups[0]["kind"] == "beds") else (2, 2)
    slots = _lattice(fp, blocked, aisle_x, lay["density"], zsize)
    if len(slots) < len(groups):                             # tight → compress grid (benches tight)
        slots = _lattice(fp, blocked, aisle_x, lay["density"], zsize,
                         pitches=(zsize[0] + 1, zsize[1]))
    if len(slots) < len(groups):
        slots = _lattice(fp, blocked, aisle_x, lay["density"], zsize,
                         pitches=(zsize[0], zsize[1]))
    if lay["tables"] == "perimeter" and len(slots) >= len(groups) + 2:
        per = [s for s in slots
               if s[0] <= hx0 + 3 or s[0] >= hx1 - 3 - zsize[0] or s[1] <= 3
               or s[0] >= hx1 - 1]                           # wing is entirely suitable
        if len(per) >= len(groups):
            slots = per
    assign = _anneal(groups, slots, fp, pois, lay["windows"], aisle_x, rng)
    for z in groups:
        if z["id"] in assign:
            x, y = assign[z["id"]]
            put(z, x, y, zsize[0], zsize[1])
        else:                                                # overflow — dense scan
            spot = next(((x, y) for y in range(2, fp["H"] - zsize[1])
                         for x in range(1, fp["W"] - zsize[0])
                         if {(x + i, y + j) for i in range(zsize[0]) for j in range(zsize[1])}
                         <= fp["mask"] - blocked
                         and not any(abs(cx - aisle_x) < 1 for cx in range(x, x + zsize[0]))),
                        None)
            if spot:
                put(z, spot[0], spot[1], zsize[0], zsize[1])

    floors = [{"label": "", "w": fp["W"], "h": H, "zones": rects,
               "outline": fp["outline"], "hall": hall, "wing": fp.get("wing"),
               "door": {"x": aisle_x, "y": H - 1}, "aisle_x": aisle_x,
               "windows": lay["windows"], "stairs": pois.get("stairs"),
               "stairs_approach": pois.get("stairs_approach")}]
    if back:
        rooms = []
        for d, z in zip(doors_back, back):
            rooms.append({"id": z["id"], "name": z["name"], "kind": z["kind"],
                          "x": d["x0"], "y": 0, "w": d["w"], "h": 3, "post": z.get("post"),
                          "lock": bool(z.get("lockable")), "door_x": d["x"],
                          "fixed": sum(1 for o in z.get("objects") or [] if o.get("fixed")),
                          "loose": sum(1 for o in z.get("objects") or [] if not o.get("fixed"))})
        floors[0]["back"] = {"h": 3, "rooms": rooms}
    if upstairs:
        rooms = [{"id": z["id"], "name": z["name"], "kind": z["kind"], "x": i * 3, "y": 0,
                  "w": 3, "h": 3, "lock": True,
                  "fixed": sum(1 for o in z.get("objects") or [] if o.get("fixed")),
                  "loose": sum(1 for o in z.get("objects") or [] if not o.get("fixed"))}
                 for i, z in enumerate(upstairs)]
        floors.append({"label": "2-й этаж", "w": len(upstairs) * 3, "h": 4, "zones": rooms})
    return {"cell": CELL, "floors": floors, "name": data.get("name") or "", "layout": lay}


def reachable(plan: dict) -> bool:
    """BFS from entrance over footprint cells: all annex doors and stairs approach reachable."""
    fl = plan["floors"][0]
    mask = canonical_mask_from(fl)
    occ = {(r["x"] + i, r["y"] + j) for r in fl["zones"]
           for i in range(r["w"]) for j in range(r["h"])}
    start = (fl["door"]["x"], fl["h"] - 2)
    seen, queue = {start}, [start]
    while queue:
        x, y = queue.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in mask and (nx, ny) not in occ and (nx, ny) not in seen:
                seen.add((nx, ny))
                queue.append((nx, ny))
    targets = [(r["door_x"], 1) for r in fl.get("back", {}).get("rooms", [])]
    if fl.get("stairs"):
        targets.append(tuple(fl.get("stairs_approach") or
                             (fl["stairs"][0] - 1, fl["stairs"][1])))
    return all(t in seen for t in targets)


def canonical_mask_from(fl: dict) -> set:
    """Interior mask from saved plan (by outline/hall)."""
    hall = fl.get("hall") or {"x": 0, "w": fl["w"], "h": fl["h"]}
    mask = {(x, y) for x in range(hall["x"] + 1, hall["x"] + hall["w"] - 1)
            for y in range(1, fl["h"] - 1)}
    # cells outside hall (wing) recovered from outline polygon (point-in-poly on cells)
    pts = fl.get("outline")
    if pts and len(pts) > 4:
        for x in range(0, fl["w"]):
            for y in range(0, fl["h"]):
                if (x, y) in mask:
                    continue
                cx, cy = x + 0.5, y + 0.5
                inside = False
                for i in range(len(pts)):
                    x1, y1 = pts[i]
                    x2, y2 = pts[(i + 1) % len(pts)]
                    if (y1 > cy) != (y2 > cy) and cx < x1 + (x2 - x1) * (cy - y1) / (y2 - y1):
                        inside = not inside
                if inside and 0 < x < fl["w"] - 0 and 0 < y < fl["h"]:
                    # boundary (cells whose center is inside but at wall) remain interior
                    mask.add((x, y))
    return mask


# ── SVG ──────────────────────────────────────────────────────────────────────

def _rect_svg(r: dict, ox: int, oy: int, out: list) -> None:
    color, op = PALETTE.get(r["kind"], ("#8b96ab", .14))
    x, y = ox + r["x"] * CELL, oy + r["y"] * CELL
    w, h = r["w"] * CELL, r["h"] * CELL
    out.append(f'<rect x="{x + 1}" y="{y + 1}" width="{w - 2}" height="{h - 2}" rx="4" '
               f'fill="{color}" fill-opacity="{op}" stroke="{color}" stroke-width="1">'
               f'<title>{r["name"]}</title></rect>')
    fit = max(3, int((w - 6) / 5.2))
    label = r["name"] if len(r["name"]) <= fit else r["name"][: fit - 1] + "…"
    out.append(f'<text x="{x + 4}" y="{y + 11}" font-size="8" fill="#dfe5ef">{label}'
               + ("&#160;🔒" if r.get("lock") else "") + "</text>")
    if r.get("post") and h >= 40:
        out.append(f'<text x="{x + 4}" y="{y + 21}" font-size="7" fill="#8b96ab">пост: {r["post"]}</text>')
    fx, fy = x + 4, y + h - 8
    for i in range(min(r.get("fixed", 0), 5)):
        out.append(f'<rect x="{fx + i * 8}" y="{fy}" width="4.5" height="4.5" fill="{color}" fill-opacity=".8"/>')
    for i in range(min(r.get("loose", 0), 7)):
        out.append(f'<circle cx="{fx + 2 + i * 5.5}" cy="{fy - 4}" r="1.5" fill="#dfe5ef" fill-opacity=".6"/>')


def plan_svg(plan: dict) -> str:
    pad, gap = 10, 16
    blocks, total_w, total_h = [], 0, 0
    for fl in plan["floors"]:
        bw = fl["w"] * CELL
        bh = (fl["h"] + fl.get("back", {}).get("h", 0)) * CELL
        blocks.append((fl, bw, bh))
        total_w = max(total_w, bw)
        total_h += bh + gap + (12 if fl["label"] else 0)
    W, H = total_w + pad * 2, total_h + pad * 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" '
           f'style="background:#12151c;border-radius:8px">']
    oy = pad
    for fl, bw, bh in blocks:
        ox = pad
        if fl["label"]:
            out.append(f'<text x="{ox}" y="{oy + 8}" font-size="9" fill="#8b96ab">{fl["label"]}</text>')
            oy += 12
        back_h = fl.get("back", {}).get("h", 0) * CELL
        hall_oy = oy + back_h
        if fl.get("outline"):                                # footprint outline (building shape!)
            pts = " ".join(f"{ox + px * CELL},{hall_oy + py * CELL}" for px, py in fl["outline"])
            out.append(f'<polygon points="{pts}" fill="#161a22" stroke="#5b6578" stroke-width="2"/>')
        else:
            out.append(f'<rect x="{ox}" y="{oy}" width="{bw}" height="{bh}" fill="none" '
                       f'stroke="#5b6578" stroke-width="2" rx="3"/>')
        if fl.get("back"):
            hall = fl.get("hall") or {"x": 0, "w": fl["w"]}
            bx0 = ox + hall["x"] * CELL
            bw_h = hall["w"] * CELL
            out.append(f'<rect x="{bx0}" y="{oy}" width="{bw_h}" height="{back_h}" '
                       f'fill="#161a22" stroke="#5b6578" stroke-width="2"/>')
            for r in fl["back"]["rooms"]:
                _rect_svg(r, ox, oy, out)
                dx = ox + r["door_x"] * CELL
                out.append(f'<line x1="{dx - 6}" y1="{oy + back_h}" x2="{dx + 6}" y2="{oy + back_h}" '
                           f'stroke="#12151c" stroke-width="4"/>')
        win = fl.get("windows")
        hall = fl.get("hall") or {"x": 0, "w": fl["w"]}
        wx0 = ox + hall["x"] * CELL
        wx1 = ox + (hall["x"] + hall["w"]) * CELL
        if win in ("left", "both"):
            for k in range(2, fl["h"] - 2, 3):
                out.append(f'<line x1="{wx0}" y1="{hall_oy + k * CELL}" x2="{wx0}" '
                           f'y2="{hall_oy + (k + 1) * CELL}" stroke="#5aa0ff" stroke-width="3" opacity=".7"/>')
        if win in ("right", "both"):
            for k in range(2, fl["h"] - 2, 3):
                out.append(f'<line x1="{wx1}" y1="{hall_oy + k * CELL}" x2="{wx1}" '
                           f'y2="{hall_oy + (k + 1) * CELL}" stroke="#5aa0ff" stroke-width="3" opacity=".7"/>')
        if fl.get("aisle_x") is not None:
            out.append(f'<rect x="{ox + fl["aisle_x"] * CELL + 6}" y="{hall_oy + CELL}" '
                       f'width="{CELL - 12}" height="{(fl["h"] - 2) * CELL}" '
                       f'fill="#dfe5ef" fill-opacity=".03"/>')
        for r in fl["zones"]:
            _rect_svg(r, ox, hall_oy if not fl["label"] else oy, out)
        if fl.get("stairs"):
            sx, sy = fl["stairs"]
            x, y = ox + sx * CELL, hall_oy + sy * CELL
            for k in range(4):
                out.append(f'<line x1="{x}" y1="{y + 4 + k * 9}" x2="{x + 2 * CELL - 4}" '
                           f'y2="{y + 4 + k * 9}" stroke="#8b96ab" stroke-width="2"/>')
            out.append(f'<text x="{x + 2}" y="{y + 2 * CELL - 3}" font-size="7" fill="#8b96ab">лестница</text>')
        d = fl.get("door")
        if d:
            dx = ox + d["x"] * CELL + CELL // 2
            out.append(f'<line x1="{dx - 9}" y1="{hall_oy + fl["h"] * CELL}" x2="{dx + 9}" '
                       f'y2="{hall_oy + fl["h"] * CELL}" stroke="#12151c" stroke-width="5"/>')
            out.append(f'<text x="{dx - 10}" y="{hall_oy + fl["h"] * CELL - 4}" font-size="8" '
                       f'fill="#8b96ab">вход</text>')
        oy += bh + gap
    out.append("</svg>")
    return "".join(out)
