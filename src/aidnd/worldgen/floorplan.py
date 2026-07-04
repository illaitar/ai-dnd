"""План локации: ДЕТЕРМИНИРОВАННАЯ раскладка зон по данным + SVG-рендер (docs/locations.md).

Геометрию решает код, не LLM (как в citygen): kind зоны и её spot-положение («в тёмном
углу», «у окна», «под лестницей») сами говорят планировщику, куда её ставить. Клеточная
сетка: зал по size здания, задние комнаты (private/storage/cell) полосой позади, запираемые
комнаты постоя — отдельным блоком «2-й этаж». Коллизии — поиск ближайшей свободной клетки.
"""

from __future__ import annotations

CELL = 22                                     # px на клетку
HALL = {"small": (11, 8), "medium": (13, 9), "large": (15, 10)}

# kind → (цвет заливки, цвет обводки)
PALETTE = {
    "bar": ("#7c5cff", .18), "tables": ("#5aa0ff", .14), "hearth": ("#ff8a3a", .20),
    "counter": ("#7c5cff", .18), "shelves": ("#3ec06a", .14), "storage": ("#8b96ab", .16),
    "workshop": ("#ff5050", .16), "altar": ("#ffd75a", .18), "pews": ("#5aa0ff", .10),
    "beds": ("#3ec06a", .16), "private": ("#c46bff", .16), "bath": ("#39c6d6", .16),
    "games": ("#ff5050", .14), "door": ("#dfe5ef", .10), "well": ("#39c6d6", .18),
    "post": ("#ffd75a", .18), "stalls": ("#ff8a3a", .14), "yard": ("#9a6", .14),
    "cell": ("#8b96ab", .22),
}

# споты столов/лежанок → якорь в зале (функции от W,H; столбец,строка ЛЕВОГО-ВЕРХА зоны)
_SPOT_ANCHOR = {
    "у окна":        lambda w, h: (1, 2),
    "в тёмном углу": lambda w, h: (w - 3, 1),
    "у очага":       lambda w, h: (w - 6, h // 2 - 1),
    "посреди зала":  lambda w, h: (w // 2 - 1, h // 2 - 1),
    "у двери":       lambda w, h: (w // 2 + 2, h - 3),
    "у стены":       lambda w, h: (w - 3, h // 2 + 2),
    "под лестницей": lambda w, h: (w - 6, h - 3),
    "у бочек":       lambda w, h: (1, 1),
    "у печи":        lambda w, h: (w - 4, h // 2),
    "в дальнем углу": lambda w, h: (1, 1),
    "у входа":       lambda w, h: (w // 2 - 2, h - 3),
    "за ширмой":     lambda w, h: (w - 3, 1),
    "у ворот":       lambda w, h: (w // 2, h - 3),
}


def _anchor_for(zone: dict, w: int, h: int, seq: int) -> tuple[int, int]:
    name = zone["name"].lower()
    for key, fn in _SPOT_ANCHOR.items():
        if key in name:
            return fn(w, h)
    # без спота (номерные секции/стойла/лежанки) — вдоль стен по порядку
    slots = [(1 + 3 * i, 1) for i in range((w - 2) // 3)] + \
            [(1 + 3 * i, h - 3) for i in range((w - 2) // 3)]
    return slots[seq % len(slots)]


def _fits(occ: set, x: int, y: int, zw: int, zh: int, w: int, h: int) -> bool:
    if x < 1 or y < 1 or x + zw > w - 1 or y + zh > h - 1:
        return False
    return all((x + i, y + j) not in occ for i in range(zw) for j in range(zh))


def _place(occ: set, ax: int, ay: int, zw: int, zh: int, w: int, h: int) -> tuple[int, int]:
    """Ближайшая к якорю свободная позиция (кольцевой скан)."""
    for r in range(0, max(w, h)):
        for dx in range(-r, r + 1):
            for dy in (-r, r) if r else (0,):
                for x, y in ((ax + dx, ay + dy), (ax + dy, ay + dx)):
                    if _fits(occ, x, y, zw, zh, w, h):
                        occ.update((x + i, y + j) for i in range(zw) for j in range(zh))
                        return x, y
    return 1, 1                                              # зал переполнен — кладём в угол


def plan_location(data: dict) -> dict:
    """Зоны фактшита → план: rects в клетках. Детерминирован (без RNG)."""
    zones = data.get("zones") or []
    w, h = HALL.get(str(data.get("size")), HALL["medium"])
    hall_kinds = ("bar", "counter", "tables", "hearth", "shelves", "workshop", "altar",
                  "pews", "games", "bath", "beds", "yard", "stalls", "well", "post", "door")
    back = [z for z in zones if z["kind"] in ("private", "storage", "cell") ]
    upstairs = [z for z in zones if z["kind"] == "beds" and z.get("lockable")]
    hall = [z for z in zones if z not in back and z not in upstairs and z["kind"] in hall_kinds]
    # столов много → зал шире
    groups = sum(1 for z in hall if z.get("group"))
    w = max(w, 5 + 2 * min(groups, 6))
    occ: set = set()
    rects = []

    def put(z, x, y, zw, zh):
        rects.append({"id": z["id"], "name": z["name"], "kind": z["kind"], "x": x, "y": y,
                      "w": zw, "h": zh, "post": z.get("post"),
                      "fixed": sum(1 for o in z.get("objects") or [] if o.get("fixed")),
                      "loose": sum(1 for o in z.get("objects") or [] if not o.get("fixed"))})

    seq = 0
    for z in hall:                                           # крупные якоря — по правилам kind
        k = z["kind"]
        if k in ("bar", "counter"):
            zw = max(3, w * 2 // 5)
            x, y = _place(occ, 1, 1, zw, 2, w, h)
            put(z, x, y, zw, 2)
        elif k == "hearth":
            x, y = _place(occ, w - 3, h // 2 - 1, 2, 2, w, h)
            put(z, x, y, 2, 2)
        elif k in ("workshop", "bath"):
            x, y = _place(occ, 1, h // 2 - 1, 3, 2, w, h)
            put(z, x, y, 3, 2)
        elif k == "altar":
            x, y = _place(occ, w // 2 - 1, 1, 3, 2, w, h)
            put(z, x, y, 3, 2)
        elif k == "pews":
            x, y = _place(occ, w // 2 - 2, 4, 4, 3, w, h)
            put(z, x, y, 4, 3)
        elif k == "shelves":
            x, y = _place(occ, 1, 3, 1, min(4, h - 4), w, h)
            put(z, x, y, 1, min(4, h - 4))
        elif k in ("well", "post"):
            x, y = _place(occ, w // 2 - 1, h // 2 - 1, 2, 2, w, h)
            put(z, x, y, 2, 2)
        else:                                                # tables/games/beds/yard/stalls-инстансы
            ax, ay = _anchor_for(z, w, h, seq)
            zw, zh = (2, 2)
            x, y = _place(occ, ax, ay, zw, zh, w, h)
            put(z, x, y, zw, zh)
            seq += 1
    floors = [{"label": "", "w": w, "h": h, "zones": rects,
               "door": {"x": w // 2, "y": h - 1}}]
    if back:                                                 # задние комнаты — полоса позади зала
        n = len(back)
        rw = max(2, w // n)
        row = []
        for i, z in enumerate(back):
            row.append({"id": z["id"], "name": z["name"], "kind": z["kind"],
                        "x": i * rw, "y": 0, "w": rw if i < n - 1 else w - rw * (n - 1),
                        "h": 3, "post": z.get("post"), "lock": bool(z.get("lockable")),
                        "fixed": sum(1 for o in z.get("objects") or [] if o.get("fixed")),
                        "loose": sum(1 for o in z.get("objects") or [] if not o.get("fixed"))})
        floors[0]["back"] = {"h": 3, "rooms": row}
    if upstairs:                                             # запираемые комнаты — второй этаж
        n = len(upstairs)
        rw = 3
        rooms = [{"id": z["id"], "name": z["name"], "kind": z["kind"], "x": i * rw, "y": 0,
                  "w": rw, "h": 3, "lock": True,
                  "fixed": sum(1 for o in z.get("objects") or [] if o.get("fixed")),
                  "loose": sum(1 for o in z.get("objects") or [] if not o.get("fixed"))}
                 for i, z in enumerate(upstairs)]
        floors.append({"label": "2-й этаж", "w": n * rw, "h": 4, "zones": rooms,
                       "corridor": True})
    return {"cell": CELL, "floors": floors, "name": data.get("name") or ""}


def _rect_svg(r: dict, ox: int, oy: int, out: list) -> None:
    color, op = PALETTE.get(r["kind"], ("#8b96ab", .14))
    x, y = ox + r["x"] * CELL, oy + r["y"] * CELL
    w, h = r["w"] * CELL, r["h"] * CELL
    out.append(f'<rect x="{x + 1}" y="{y + 1}" width="{w - 2}" height="{h - 2}" rx="4" '
               f'fill="{color}" fill-opacity="{op}" stroke="{color}" stroke-width="1"/>')
    fit = max(4, int((w - 8) / 5.5))                         # подпись не шире зоны
    label = r["name"] if len(r["name"]) <= fit else r["name"][: fit - 1] + "…"
    out.append(f'<text x="{x + 4}" y="{y + 12}" font-size="8.5" fill="#dfe5ef">{label}'
               + ("&#160;🔒" if r.get("lock") else "") + "</text>")
    if r.get("post"):
        out.append(f'<text x="{x + 4}" y="{y + 22}" font-size="7.5" fill="#8b96ab">пост: {r["post"]}</text>')
    fx, fy = x + 5, y + h - 9                                # мебель: квадратики, утварь: точки
    for i in range(min(r.get("fixed", 0), 6)):
        out.append(f'<rect x="{fx + i * 9}" y="{fy}" width="5" height="5" fill="{color}" fill-opacity=".8"/>')
    for i in range(min(r.get("loose", 0), 8)):
        out.append(f'<circle cx="{fx + 2 + i * 6}" cy="{fy - 5}" r="1.6" fill="#dfe5ef" fill-opacity=".6"/>')


def plan_svg(plan: dict) -> str:
    """План → SVG (тёмная тема стендов)."""
    pad, gap = 10, 14
    blocks = []
    total_w, total_h = 0, 0
    for fl in plan["floors"]:
        bw = fl["w"] * CELL
        bh = fl["h"] * CELL + (fl.get("back", {}).get("h", 0)) * CELL
        blocks.append((fl, bw, bh))
        total_w = max(total_w, bw)
        total_h += bh + gap + 12
    W, H = total_w + pad * 2, total_h + pad * 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'width="100%" style="background:#12151c;border-radius:8px">']
    oy = pad
    for fl, bw, bh in blocks:
        ox = pad
        back_h = fl.get("back", {}).get("h", 0) * CELL
        if fl["label"]:
            out.append(f'<text x="{ox}" y="{oy + 8}" font-size="9" fill="#8b96ab">{fl["label"]}</text>')
            oy += 12
        if fl.get("back"):                                   # полоса задних комнат
            for r in fl["back"]["rooms"]:
                _rect_svg(r, ox, oy, out)
            out.append(f'<line x1="{ox}" y1="{oy + back_h}" x2="{ox + bw}" y2="{oy + back_h}" '
                       f'stroke="#3a4356" stroke-width="2"/>')
        hall_oy = oy + back_h
        out.append(f'<rect x="{ox}" y="{oy}" width="{bw}" height="{bh}" fill="none" '
                   f'stroke="#5b6578" stroke-width="2" rx="3"/>')
        for r in fl["zones"]:
            _rect_svg(r, ox, hall_oy if not fl["label"] else oy, out)
        d = fl.get("door")
        if d:                                                # дверной проём — разрыв в нижней стене
            dx = ox + d["x"] * CELL
            out.append(f'<line x1="{dx - 8}" y1="{oy + bh}" x2="{dx + 8}" y2="{oy + bh}" '
                       f'stroke="#12151c" stroke-width="4"/>')
            out.append(f'<text x="{dx - 8}" y="{oy + bh - 4}" font-size="8" fill="#8b96ab">вход</text>')
        oy += bh + gap
    out.append("</svg>")
    return "".join(out)
