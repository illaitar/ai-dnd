"""План локации v2: LLM решает ВКУС (пресет data["layout"]), код — ГЕОМЕТРИЮ с гарантиями.

Гарантии кода (docs/locations.md): мебель на выровненной сетке слотов (ряды, не россыпь);
главный проход от входа через зал; свободная клетка перед КАЖДОЙ дверью (пристройки,
лестница); финальная BFS-проверка достижимости. Спот-зоны («у окна», «в тёмном углу»)
раздаются по слотам МАТЧИНГОМ предпочтений — семантика спота = функция расстояния до
окна/угла/очага/лестницы, а не жёсткая точка.

Пресет layout (LLM-роль layout_architect, клампится enum'ами, кэш в пуле):
  windows: left|right|both|none · bar_wall: left|right · tables: rows|perimeter|mixed ·
  density: airy|normal|packed
"""

from __future__ import annotations

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


def clamp_layout(d: dict | None) -> dict:
    """Пресет от LLM → строго в enum'ы (принцип 2: LLM предлагает, код клампит)."""
    d = d if isinstance(d, dict) else {}
    return {k: (d.get(k) if d.get(k) in LAYOUT_ENUMS[k] else v)
            for k, v in LAYOUT_DEFAULTS.items()}


# ── геометрия ────────────────────────────────────────────────────────────────

def _slot_grid(w: int, h: int, blocked: set, aisle_x: int, density: str,
               size: tuple[int, int] = (2, 2)) -> list[tuple[int, int]]:
    """Выровненные слоты под мебель: колонки с шагом, ряды с шагом — РЯДЫ, не россыпь."""
    zw, zh = size
    step_x = zw + (2 if density == "airy" else 1)
    step_y = zh + (2 if density == "airy" else 1 if density == "normal" else 0)
    slots = []
    for y in range(2, h - 1 - zh, step_y):
        for x in range(2, w - 1 - zw, step_x):
            cells = {(x + i, y + j) for i in range(zw) for j in range(zh)}
            if any(c in blocked for c in cells):
                continue
            if any(abs(cx - aisle_x) < 1 for cx in range(x, x + zw)):    # главный проход свят
                continue
            slots.append((x, y))
    return slots


def _pref(spot_name: str, slot: tuple[int, int], w: int, h: int, pois: dict,
          windows: str) -> float:
    """Скор слота для спота: чем МЕНЬШЕ, тем лучше (расстояние до сути спота)."""
    x, y = slot
    n = spot_name.lower()

    def dist(p):
        return abs(x - p[0]) + abs(y - p[1]) if p else 99

    win_x = {"left": 1, "right": w - 2, "both": 1, "none": None}[windows]
    if "у окна" in n:
        return abs(x - win_x) if win_x is not None else 50
    if "тёмном углу" in n or "дальнем углу" in n:      # дальний от входа угол НЕоконной стороны
        cx = w - 3 if windows in ("left", "both") else 1
        return abs(x - cx) + y
    if "посреди" in n:
        return abs(x - w // 2) + abs(y - h // 2)
    if "у двери" in n or "у входа" in n or "у ворот" in n:
        return dist(pois.get("door"))
    if "под лестницей" in n:
        return dist(pois.get("stairs"))
    if "у очага" in n or "у печи" in n:
        return dist(pois.get("hearth"))
    if "у бочек" in n:
        return dist(pois.get("storage_door"))
    if "у стены" in n or "за ширмой" in n or "крайн" in n or "тёмное" in n:
        return min(x - 1, (w - 2) - x)                  # к любой боковой стене
    return abs(y - h // 2)                              # номерные — просто ровным рядом


def plan_location(data: dict) -> dict:
    """Фактшит (+data['layout']) → план. Детерминирован; проходы и двери гарантированы."""
    zones = data.get("zones") or []
    lay = clamp_layout(data.get("layout"))
    back = [z for z in zones if z["kind"] in ("private", "storage", "cell")]
    upstairs = [z for z in zones if z["kind"] == "beds" and z.get("lockable")]
    hall_z = [z for z in zones if z not in back and z not in upstairs]
    groups = [z for z in hall_z if z.get("group")]
    anchors = [z for z in hall_z if not z.get("group")]

    w, h = HALL.get(str(data.get("size")), HALL["medium"])
    w = max(w, 7 + 3 * min(len(groups) // 2 + 1, 4))    # столам нужны ряды — ширим зал
    aisle_x = w // 2
    blocked: set = set()
    pois: dict = {"door": (aisle_x, h - 2)}
    rects: list[dict] = []

    def put(z, x, y, zw, zh, lock=False):
        blocked.update((x + i, y + j) for i in range(zw) for j in range(zh))
        rects.append({"id": z["id"], "name": z["name"], "kind": z["kind"], "x": x, "y": y,
                      "w": zw, "h": zh, "post": z.get("post"), "lock": lock,
                      "fixed": sum(1 for o in z.get("objects") or [] if o.get("fixed")),
                      "loose": sum(1 for o in z.get("objects") or [] if not o.get("fixed"))})

    # двери пристроек — на верхней стене; клетка перед каждой дверью свободна
    doors_back = []
    if back:
        n = len(back)
        rw = max(2, w // n)
        for i, z in enumerate(back):
            x0 = i * rw
            ww = rw if i < n - 1 else w - rw * (n - 1)
            dx = min(w - 2, x0 + ww // 2)
            doors_back.append({"x": dx, "zone": z["id"]})
            blocked.add((dx, 1))                        # зазор перед дверью
            if z["kind"] == "storage" and "storage_door" not in pois:
                pois["storage_door"] = (dx, 1)
    for c in range(aisle_x, aisle_x + 1):               # главный проход: вход → верхняя стена
        blocked.update((c, yy) for yy in range(1, h - 1))
    aisle_cells = {(aisle_x, yy) for yy in range(1, h - 1)}

    # крупные якоря: стойка вдоль стены пресета, очаг напротив, лестница в углу
    side = {"left": 1, "right": w - 3}
    for z in anchors:
        k = z["kind"]
        if k in ("bar", "counter"):
            bx = side[lay["bar_wall"]]
            bh_ = max(3, (h - 4) // 2)
            put(z, bx, 2, 2, bh_)
        elif k == "hearth":
            hx = side["right" if lay["bar_wall"] == "left" else "left"]
            put(z, hx, h // 2 - 1, 2, 2)
            pois["hearth"] = (hx, h // 2)
        elif k in ("workshop", "bath"):
            put(z, side[lay["bar_wall"]], h - 4, 3, 2)
        elif k == "altar":
            put(z, max(1, w // 2 - 3), 1, 3, 2)         # слева от прохода у дальней стены
        elif k == "pews":
            put(z, max(1, w // 2 - 4), 4, 3, min(4, h - 6))
        elif k == "shelves":
            put(z, side["right" if lay["bar_wall"] == "left" else "left"], 2, 1, min(4, h - 4))
        elif k in ("well", "post"):
            put(z, w // 2 + 1, h // 2 - 1, 2, 2)
        elif k == "door":
            put(z, aisle_x + 1, h - 3, 1, 1)
    if upstairs:
        sx = w - 3 if lay["bar_wall"] == "left" else 1
        pois["stairs"] = (sx, h - 3)
        blocked.update((sx + i, h - 3 + j) for i in range(2) for j in range(2))
        apx = sx + 2 if sx == 1 else sx - 1             # подход к лестнице — со свободной стороны
        pois["stairs_approach"] = (apx, h - 3)
        blocked.add((apx, h - 3))

    # групповые инстансы: сетка слотов → матчинг предпочтений спотов (жадный)
    zsize = (1, 2) if (groups and groups[0]["kind"] == "beds") else (2, 2)
    slots = _slot_grid(w, h, blocked, aisle_x, lay["density"], zsize)
    if lay["tables"] == "perimeter":                    # периметр: центр зала — только танцы
        slots = [s for s in slots if s[0] <= 3 or s[0] >= w - 3 - zsize[0] or s[1] <= 3]
    free = list(slots)
    unplaced = []
    for z in groups:
        if not free:
            unplaced.append(z)
            continue
        best = min(free, key=lambda s: _pref(z["name"], s, w, h, pois, lay["windows"]))
        free.remove(best)
        put(z, best[0], best[1], zsize[0], zsize[1])
    for z in unplaced:                                  # слоты кончились → плотный скан (мимо прохода)
        zw, zh = zsize
        spot = next(((x, y) for y in range(2, h - 1 - zh) for x in range(1, w - 1 - zw)
                     if all((x + i, y + j) not in blocked
                            for i in range(zw) for j in range(zh))
                     and not any(abs(cx - aisle_x) < 1 for cx in range(x, x + zw))), None)
        if spot:
            put(z, spot[0], spot[1], zw, zh)

    floors = [{"label": "", "w": w, "h": h, "zones": rects, "aisle": sorted(aisle_cells),
               "door": {"x": aisle_x, "y": h - 1}, "windows": lay["windows"],
               "stairs": pois.get("stairs"), "stairs_approach": pois.get("stairs_approach")}]
    if back:
        n = len(back)
        rw = max(2, w // n)
        rooms = []
        for i, z in enumerate(back):
            rooms.append({"id": z["id"], "name": z["name"], "kind": z["kind"],
                          "x": i * rw, "y": 0, "w": rw if i < n - 1 else w - rw * (n - 1),
                          "h": 3, "post": z.get("post"), "lock": bool(z.get("lockable")),
                          "door_x": doors_back[i]["x"],
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
    """BFS от входа: достижимы ли все двери пристроек и лестница (гарантия «не заставлено»)."""
    fl = plan["floors"][0]
    w, h = fl["w"], fl["h"]
    occ = {(r["x"] + i, r["y"] + j) for r in fl["zones"]
           for i in range(r["w"]) for j in range(r["h"])}
    start = (fl["door"]["x"], h - 2)
    seen, queue = {start}, [start]
    while queue:
        x, y = queue.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 1 <= nx <= w - 2 and 1 <= ny <= h - 2 and (nx, ny) not in occ and (nx, ny) not in seen:
                seen.add((nx, ny))
                queue.append((nx, ny))
    targets = [(r["door_x"], 1) for r in fl.get("back", {}).get("rooms", [])]
    if fl.get("stairs"):
        targets.append(tuple(fl.get("stairs_approach") or
                             (fl["stairs"][0] - 1, fl["stairs"][1])))
    return all(t in seen for t in targets)


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
        out.append(f'<rect x="{ox}" y="{oy}" width="{bw}" height="{bh}" fill="none" '
                   f'stroke="#5b6578" stroke-width="2" rx="3"/>')
        if fl.get("back"):
            for r in fl["back"]["rooms"]:
                _rect_svg(r, ox, oy, out)
                dx = ox + r["door_x"] * CELL             # дверь пристройки — проём в её стене
                out.append(f'<line x1="{dx - 6}" y1="{oy + back_h}" x2="{dx + 6}" y2="{oy + back_h}" '
                           f'stroke="#12151c" stroke-width="4"/>')
            out.append(f'<line x1="{ox}" y1="{oy + back_h}" x2="{ox + bw}" y2="{oy + back_h}" '
                       f'stroke="#3a4356" stroke-width="2"/>')
        hall_oy = oy + back_h
        # окна — штрихи на оконной стене; проход — едва заметная дорожка
        win = fl.get("windows")
        hh = fl["h"] * CELL
        if win in ("left", "both"):
            for k in range(2, fl["h"] - 2, 3):
                out.append(f'<line x1="{ox}" y1="{hall_oy + k * CELL}" x2="{ox}" '
                           f'y2="{hall_oy + (k + 1) * CELL}" stroke="#5aa0ff" stroke-width="3" opacity=".7"/>')
        if win in ("right", "both"):
            for k in range(2, fl["h"] - 2, 3):
                out.append(f'<line x1="{ox + bw}" y1="{hall_oy + k * CELL}" x2="{ox + bw}" '
                           f'y2="{hall_oy + (k + 1) * CELL}" stroke="#5aa0ff" stroke-width="3" opacity=".7"/>')
        if fl.get("aisle"):
            ax = fl["aisle"][0][0]
            out.append(f'<rect x="{ox + ax * CELL + 6}" y="{hall_oy + CELL}" width="{CELL - 12}" '
                       f'height="{(fl["h"] - 2) * CELL}" fill="#dfe5ef" fill-opacity=".03"/>')
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
            out.append(f'<line x1="{dx - 9}" y1="{oy + bh}" x2="{dx + 9}" y2="{oy + bh}" '
                       f'stroke="#12151c" stroke-width="5"/>')
            out.append(f'<text x="{dx - 10}" y="{oy + bh - 4}" font-size="8" fill="#8b96ab">вход</text>')
        oy += bh + gap
    out.append("</svg>")
    return "".join(out)
