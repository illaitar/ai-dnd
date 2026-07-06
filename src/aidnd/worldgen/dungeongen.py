"""Генератор подземелий — этап A: СКЕЛЕТ (docs/dungeons.md).

Мини-циклическая генерация (Дорманс/Unexplored): данж начинается не с комнаты, а с ПЕТЛИ —
вход и цель делят кольцо на две дуги-маршрута. Словарь циклов (content/cycles.json, данные)
назначает дугам РОЛИ геймплея: короткая опасная против длинной безопасной, ключ на дальней
дуге, скрытый шорткат, окно-предвестие цели. Подциклы и отростки-награды вкладываются в
узлы кольца («jaquaysing» машиной). Lock/key корректны ПО ПОСТРОЕНИЮ (ключ всегда на дуге,
достижимой без замка; ключ вложенного замка — на главном кольце) + BFS-assert
«позиция × ключи». Секретка НИКОГДА не на критпути (цель достижима и без secret-рёбер).
Фильтр качества — метрики Жаке (цикломатика ≥ 2, тупики только с наградой), не прошёл —
следующий под-сид. Детерминизм: всё от seed, ~десятки мс. LLM здесь НЕТ — вкус (история,
палитра, наполнение) придёт брифом в этапе B.
"""

from __future__ import annotations

import json
import math
import os
import random

COARSE_W, COARSE_H = 9, 7          # курс-грид узлов
CELL = 7                           # клетка курс-грида = 7×7 тайлов
NEST_MIN, NEST_MAX = 2, 4          # вложений на данж
RETRY = 4                          # под-сидов до сдачи
_CAVE_ENV = ("cave", "underdark", "swamp", "forest", "пещер", "лес", "болот", "caverns")

_CAT: dict | None = None


def _catalog() -> dict:
    global _CAT
    if _CAT is None:
        p = os.path.join(os.path.dirname(__file__), "..", "content", "cycles.json")
        with open(p, encoding="utf-8") as f:
            _CAT = json.load(f)
    return _CAT


def _pick(rng: random.Random, rows: list) -> dict:
    return rng.choices(rows, weights=[r["w"] for r in rows])[0]


# ── формы комнат на тайлах ───────────────────────────────────────────────────


def _rect_tiles(cx, cy, w, h, ox, oy) -> list:
    x0 = cx * CELL + (CELL - w) // 2 + ox
    y0 = cy * CELL + (CELL - h) // 2 + oy
    return [(x0 + i, y0 + j) for i in range(w) for j in range(h)]


def _cave_tiles(cx, cy, rng) -> list:
    """Пещерный узел: клеточный автомат в 6×6, крупнейшая компонента."""
    w = h = 6
    grid = {(i, j): rng.random() < 0.55 for i in range(w) for j in range(h)}
    for _ in range(3):
        nxt = {}
        for i in range(w):
            for j in range(h):
                n = sum(1 for di in (-1, 0, 1) for dj in (-1, 0, 1)
                        if (di or dj) and grid.get((i + di, j + dj), False))
                nxt[(i, j)] = n >= 4 if grid[(i, j)] else n >= 5
        grid = nxt
    live = {c for c, v in grid.items() if v}
    best: set = set()
    seen: set = set()
    for c in sorted(live):
        if c in seen:
            continue
        comp, todo = set(), [c]
        while todo:
            cur = todo.pop()
            if cur in comp or cur not in live:
                continue
            comp.add(cur)
            todo += [(cur[0] + 1, cur[1]), (cur[0] - 1, cur[1]),
                     (cur[0], cur[1] + 1), (cur[0], cur[1] - 1)]
        seen |= comp
        if len(comp) > len(best):
            best = comp
    if len(best) < 6:                                 # автомат съел всё — честный прямоугольник
        return _rect_tiles(cx, cy, 4, 4, 0, 0)
    x0, y0 = cx * CELL + (CELL - w) // 2, cy * CELL + (CELL - h) // 2
    return [(x0 + i, y0 + j) for (i, j) in sorted(best)]


def _mk_room(rid, cell, kind, env, rng, tags=None) -> dict:
    cx, cy = cell
    cavey = any(k in (env or "").lower() for k in _CAVE_ENV)
    if kind == "goal":
        tiles = _rect_tiles(cx, cy, 5, 5, 0, 0)
    elif kind == "entrance":
        tiles = _rect_tiles(cx, cy, 3, 3, 0, 0)
    elif cavey and rng.random() < 0.55:
        tiles = _cave_tiles(cx, cy, rng)
    else:
        w, h = rng.randint(3, 5), rng.randint(3, 5)
        tiles = _rect_tiles(cx, cy, w, h, rng.randint(-1, 1), rng.randint(-1, 1))
    return {"id": rid, "cell": list(cell), "kind": kind, "tags": list(tags or []),
            "tiles": [list(t) for t in tiles]}


# ── скелет: кольцо + роли дуг + вложения ────────────────────────────────────


def _ring_cells(rng) -> tuple:
    """Кольцо на курс-гриде: периметр прямоугольника, обход по часовой."""
    x0 = rng.randint(1, 2)
    y0 = rng.randint(1, 2)
    x1 = rng.randint(COARSE_W - 3, COARSE_W - 2)
    y1 = rng.randint(COARSE_H - 3, COARSE_H - 2)
    top = [(x, y0) for x in range(x0, x1 + 1)]
    right = [(x1, y) for y in range(y0 + 1, y1 + 1)]
    bottom = [(x, y1) for x in range(x1 - 1, x0 - 1, -1)]
    left = [(x0, y) for y in range(y1 - 1, y0, -1)]
    return top + right + bottom + left


def _attempt(seed: str, env: str) -> dict | None:
    rng = random.Random(f"dgen|{seed}")
    cat = _catalog()
    ring = _ring_cells(rng)
    n = len(ring)
    ei = 0                                            # вход — первый узел (лево-верх)
    gi = n // 2                                       # цель — напротив по кольцу
    arc_a = [ring[i] for i in range(ei, gi + 1)]      # дуга A: вход → цель по часовой
    arc_b = [ring[i % n] for i in range(gi, ei + n + 1)]  # дуга B: цель → вход (продолжение)
    pattern = _pick(rng, cat["cycles"])
    roles = list(pattern["arcs"])
    if "long_safe" in roles and len(arc_a) > len(arc_b):
        roles.reverse()                               # short/long честно по длине дуг

    rooms: list = []
    r_at: dict = {}                                   # cell → room index

    def room(cell, kind="room", tags=None):
        if cell in r_at:
            for t in tags or []:
                if t not in rooms[r_at[cell]]["tags"]:
                    rooms[r_at[cell]]["tags"].append(t)
            return r_at[cell]
        rid = len(rooms)
        rooms.append(_mk_room(rid, cell, kind, env, rng, tags))
        r_at[cell] = rid
        return rid

    edges: list = []
    keys: list = []
    lock_n = 0

    def edge(a, b, kind="door", lock=None):
        edges.append({"a": a, "b": b, "kind": kind, "lock": lock})

    ent = room(ring[ei], "entrance")
    goal = room(ring[gi], "goal")
    for arc, role in ((arc_a, roles[0]), (arc_b, roles[1])):
        prev = None
        for i, cell in enumerate(arc):
            tags = ["danger"] if role == "danger" else (["safe"] if role == "long_safe" else [])
            rid = room(cell, tags=tags)
            if prev is not None:
                kind, lock = "door", None
                if role == "locked_goal" and rooms[rid]["kind"] == "goal":
                    lock_n += 1
                    kind, lock = "locked", f"k{lock_n}"
                if role == "secret" and i == len(arc) // 2:
                    kind = "secret"
                edge(prev, rid, kind, lock)
            prev = rid
        if role == "key_far":
            mid = arc[len(arc) // 2]
            keys.append({"id": None, "room": r_at[mid]})  # id свяжем с замком ниже
    if pattern.get("double_lock"):                    # двойной замок: оба ключа к одной двери
        lock_n += 1
        for e in edges:
            if rooms[e["b"]]["kind"] == "goal" and e["kind"] == "door":
                e["kind"], e["lock"] = "locked", f"k{lock_n}"
                break
    for k in keys:                                    # ключи получают id существующих замков
        k["id"] = f"k{lock_n}" if lock_n else None
    keys = [k for k in keys if k["id"]]
    if lock_n and not keys:                           # замок без ключа с дуги — ключ на кольце
        spot = rng.choice([c for c in ring if c not in (ring[ei], ring[gi])])
        keys.append({"id": f"k{lock_n}", "room": r_at[spot]})

    # окно-предвестие: соседство узла дуги-window с целью (не пройти — видно)
    if "window" in roles:
        gx, gy = ring[gi]
        cand = [c for c in r_at
                if abs(c[0] - gx) + abs(c[1] - gy) == 1 and c != ring[gi]]
        if cand:
            edge(r_at[rng.choice(cand)], goal, "window")

    # вложения: подциклы и отростки-награды (тупик всегда осмыслен)
    taken = set(r_at)
    for _ in range(rng.randint(NEST_MIN, NEST_MAX)):
        anchors = [c for c in list(r_at) if c not in (ring[ei], ring[gi])]
        if not anchors:
            break
        a = rng.choice(anchors)
        free = [(a[0] + dx, a[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= a[0] + dx < COARSE_W and 0 <= a[1] + dy < COARSE_H
                and (a[0] + dx, a[1] + dy) not in taken]
        if not free:
            continue
        nest = _pick(rng, cat["nests"])
        c1 = rng.choice(free)
        if nest["key"] == "loop":                     # петля: цепочка + замыкание на СОСЕДА
            dx, dy = c1[0] - a[0], c1[1] - a[1]
            grew = None
            cands = [(c1[0] + dy, c1[1] + dx), (c1[0] - dy, c1[1] - dx),
                     (c1[0] + dx, c1[1] + dy)]        # сперва вбок: там есть к кому замкнуться
            cands = [c for c in cands
                     if 0 <= c[0] < COARSE_W and 0 <= c[1] < COARSE_H and c not in taken]
            for c2 in cands:                          # предпочитаем клетку с соседом-комнатой
                if any(abs(cc[0] - c2[0]) + abs(cc[1] - c2[1]) == 1 and cc != c1
                       for cc in r_at):
                    grew = c2
                    break
            if grew is None and cands:
                grew = cands[0]
            if grew is not None:
                r1 = room(c1)
                r2 = room(grew)
                edge(r_at[a], r1)
                edge(r1, r2)
                taken |= {c1, grew}
                back = [c for c in r_at                # замкнуть на любую другую комнату рядом
                        if abs(c[0] - grew[0]) + abs(c[1] - grew[1]) == 1
                        and r_at[c] not in (r1, r2)]
                if back:
                    edge(r2, r_at[rng.choice(back)])
                continue
            nest = {"key": "stub"}                    # не влезла — честный отросток
        kind = {"stub": "door", "secret_stub": "secret", "locked_stub": "locked"}[nest["key"]]
        lock = None
        if kind == "locked":
            lock_n += 1
            lock = f"k{lock_n}"
            ok_rooms = [r_at[c] for c in ring if c in r_at and c != ring[gi]]
            keys.append({"id": lock, "room": rng.choice(ok_rooms)})  # ключ на кольце — до замка
        r1 = room(c1, tags=["treasure"])
        edge(r_at[a], r1, kind, lock)
        taken.add(c1)

    # Brogue-паттерн «пробитая дверь»: соседи по гриду, ДАЛЁКИЕ по графу → шорткат-цикл
    linked = {frozenset((e["a"], e["b"])) for e in edges}
    cells = list(r_at.items())
    pierced = 0
    order = list(range(len(cells)))
    rng.shuffle(order)
    for oi in order:
        if pierced >= 2:
            break
        c, rid = cells[oi]
        dist = _bfs_dist(rooms, edges, rid)           # честное расстояние от ЭТОЙ комнаты
        for c2, rid2 in cells:
            if abs(c[0] - c2[0]) + abs(c[1] - c2[1]) == 1 \
                    and frozenset((rid, rid2)) not in linked \
                    and dist.get(rid2, 99) >= 3:
                edge(rid, rid2)
                linked.add(frozenset((rid, rid2)))
                pierced += 1
                break

    # ── коридоры на тайлах + гарантии + метрики ──
    for e in edges:
        e["path"] = _corridor(rooms[e["a"]], rooms[e["b"]]) if e["kind"] != "window" else []
    if not _solvable(rooms, edges, keys, ent, goal, use_secret=False):
        return None                                   # критпуть сквозь секретку — брак
    if not _solvable(rooms, edges, keys, ent, goal, use_secret=True):
        return None
    met = _metrics(rooms, edges)
    if met["cyclomatic"] < 2 or met["bad_deadends"]:
        return None
    return {"seed": seed, "env": env, "rooms": rooms, "edges": edges, "keys": keys,
            "entrance": ent, "goal": goal, "metrics": met,
            "tile_w": COARSE_W * CELL, "tile_h": COARSE_H * CELL}


def _corridor(ra, rb) -> list:
    """Прямой коридор между центрами соседних клеток: тайлы от стены до стены."""
    ax, ay = _center(ra)
    bx, by = _center(rb)
    ta, tb = {tuple(t) for t in ra["tiles"]}, {tuple(t) for t in rb["tiles"]}
    path, x, y = [], ax, ay
    while (x, y) != (bx, by):
        if x != bx:
            x += 1 if bx > x else -1
        elif y != by:
            y += 1 if by > y else -1
        if (x, y) not in ta and (x, y) not in tb:
            path.append([x, y])
    return path


def _center(r) -> tuple:
    xs = [t[0] for t in r["tiles"]]
    ys = [t[1] for t in r["tiles"]]
    return (sum(xs) // len(xs), sum(ys) // len(ys))


def _bfs_dist(rooms, edges, src) -> dict:
    adj: dict = {}
    for e in edges:
        if e["kind"] == "window":
            continue
        adj.setdefault(e["a"], []).append(e["b"])
        adj.setdefault(e["b"], []).append(e["a"])
    dist, todo = {src: 0}, [src]
    while todo:
        cur = todo.pop(0)
        for nxt in adj.get(cur, []):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                todo.append(nxt)
    return dist


def _solvable(rooms, edges, keys, ent, goal, use_secret: bool) -> bool:
    """BFS «комната × набор ключей»: цель достижима; без секреток — тоже (критпуть чист)."""
    key_at: dict = {}
    for k in keys:
        key_at.setdefault(k["room"], set()).add(k["id"])
    adj: dict = {}
    for e in edges:
        if e["kind"] == "window" or (e["kind"] == "secret" and not use_secret):
            continue
        adj.setdefault(e["a"], []).append((e["b"], e["lock"]))
        adj.setdefault(e["b"], []).append((e["a"], e["lock"]))
    start = (ent, frozenset(key_at.get(ent, set())))
    seen, todo = {start}, [start]
    while todo:
        node, ks = todo.pop()
        if node == goal:
            return True
        for nxt, lock in adj.get(node, []):
            if lock and lock not in ks:
                continue
            st = (nxt, ks | key_at.get(nxt, set()))
            if st not in seen:
                seen.add(st)
                todo.append(st)
    return False


def _metrics(rooms, edges) -> dict:
    deg: dict = {}
    passable = [e for e in edges if e["kind"] != "window"]
    for e in passable:
        deg[e["a"]] = deg.get(e["a"], 0) + 1
        deg[e["b"]] = deg.get(e["b"], 0) + 1
    dead = [r for r in rooms if deg.get(r["id"], 0) == 1]
    bad = [r["id"] for r in dead
           if r["kind"] not in ("entrance", "goal")
           and not ({"treasure"} & set(r["tags"])) and not r["kind"] == "goal"]
    return {"rooms": len(rooms), "edges": len(passable),
            "cyclomatic": len(passable) - len(rooms) + 1,
            "deadends": len(dead), "bad_deadends": bad}


def generate(seed: str, env: str = "Ruin") -> dict:
    """Данж по сиду: под-сиды до прохождения фильтра качества (детерминированная цепочка)."""
    for i in range(RETRY):
        d = _attempt(f"{seed}|{i}", env)
        if d is not None:
            return d
    raise ValueError(f"данж не собрался за {RETRY} под-сидов: {seed}")  # практически недостижимо


# ── бумажный черновик (полный Dyson-рендер — этап C) ─────────────────────────


def dungeon_svg(d: dict, title: str = "") -> str:
    from .floorart import INK, _defs, _hatch_segments, _outline_segs, _stroke

    rng = random.Random(f"dart|{d['seed']}")
    S = 11                                            # тайл → пиксели
    pad = 26
    W, H = d["tile_w"] * S + pad * 2, d["tile_h"] * S + pad * 2

    def px(t):
        return (pad + t[0] * S, pad + t[1] * S)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'font-family="Georgia, serif">',
           _defs(sum(ord(c) for c in d["seed"])),
           f'<rect width="{W}" height="{H}" fill="#e9dfc6" filter="url(#stains)"/>',
           f'<rect width="{W}" height="{H}" fill="none" filter="url(#grain)"/>']

    # коридоры — двойной штрих вдоль пути
    for e in d["edges"]:
        if e["kind"] == "window" or not e.get("path"):
            continue
        pts = [px(t) for t in [e["path"][0]] + e["path"] + [e["path"][-1]]]
        dash = ' stroke-dasharray="4 5"' if e["kind"] == "secret" else ""
        for off in (-S * 0.38, S * 0.38):
            line = [(x + (off if abs(pts[0][0] - pts[-1][0]) < abs(pts[0][1] - pts[-1][1])
                          else 0),
                     y + (off if abs(pts[0][0] - pts[-1][0]) >= abs(pts[0][1] - pts[-1][1])
                          else 0)) for x, y in pts]
            out.append(f'<polyline points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in line)}" '
                       f'fill="none" stroke="{INK}" stroke-width="1.4"{dash}/>')

    # комнаты: контур + лёгкий хэтч наружу + сетка пола
    for r in d["rooms"]:
        tiles = {tuple(t) for t in r["tiles"]}
        xs = [t[0] for t in tiles]
        ys = [t[1] for t in tiles]
        x0, y0 = px((min(xs), min(ys)))
        x1, y1 = px((max(xs) + 1, max(ys) + 1))
        if r["kind"] == "entrance" or len(tiles) == (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1):
            poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        else:                                         # пещера: контур по границе клеток
            cx = sum(xs) / len(xs) + 0.5
            cy = sum(ys) / len(ys) + 0.5
            border = [t for t in tiles
                      if not all((t[0] + dx, t[1] + dy) in tiles
                                 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
            border.sort(key=lambda t: math.atan2(t[1] + 0.5 - cy, t[0] + 0.5 - cx))
            poly = [px((t[0], t[1])) for t in border] or [(x0, y0)]
        out.append(f'<polygon points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in poly)}" '
                   f'fill="#f2ead6" stroke="none"/>')
        _stroke(out, poly, rng, width=2.0, w=1.3, close=True, passes=2)
        _hatch_segments(out, _outline_segs(poly), rng)
        mx, my = px(_center(r))
        if r["kind"] == "entrance":                   # лестница-гребёнка
            for i in range(4):
                out.append(f'<line x1="{x0 + 4 + i * 2}" y1="{y0 + 5 + i * 4}" '
                           f'x2="{x1 - 4 - i * 2}" y2="{y0 + 5 + i * 4}" '
                           f'stroke="{INK}" stroke-width="1.1"/>')
        if r["kind"] == "goal":
            out.append(f'<text x="{mx}" y="{my - 6}" font-size="15" text-anchor="middle" '
                       f'fill="{INK}">☠</text>')
        if any(k["room"] == r["id"] for k in d["keys"]):
            out.append(f'<text x="{mx}" y="{my + 4}" font-size="12" text-anchor="middle" '
                       f'fill="{INK}">⚷</text>')
        if "treasure" in r["tags"]:
            out.append(f'<rect x="{mx - 4}" y="{my + 6}" width="8" height="6" fill="none" '
                       f'stroke="{INK}" stroke-width="1"/>')
        out.append(f'<text x="{x0 + 5}" y="{y0 + 12}" font-size="9" fill="{INK}" '
                   f'opacity="0.75">{r["id"] + 1}</text>')

    # пометки рёбер: замок / S / окно-решётка
    for e in d["edges"]:
        if e["kind"] == "door" or not (e.get("path") or e["kind"] == "window"):
            continue
        if e["kind"] == "window":
            ax, ay = px(_center(d["rooms"][e["a"]]))
            bx, by = px(_center(d["rooms"][e["b"]]))
            out.append(f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="{INK}" '
                       f'stroke-width="0.8" stroke-dasharray="1.5 4" opacity="0.6"/>')
            continue
        mt = e["path"][len(e["path"]) // 2]
        mx, my = px(mt)
        if e["kind"] == "locked":
            out.append(f'<rect x="{mx - 3.5}" y="{my - 2}" width="7" height="6" fill="{INK}"/>'
                       f'<path d="M {mx - 2} {my - 2} a 2 2.6 0 0 1 4 0" fill="none" '
                       f'stroke="{INK}" stroke-width="1.3"/>')
        elif e["kind"] == "secret":
            out.append(f'<text x="{mx}" y="{my + 4}" font-size="11" text-anchor="middle" '
                       f'font-style="italic" fill="{INK}">S</text>')

    m = d["metrics"]
    out.append(f'<text x="{pad}" y="{H - 9}" font-size="12" font-style="italic" fill="{INK}" '
               f'opacity="0.85">{title or "Подземелье"} · комнат {m["rooms"]} · '
               f'циклов {m["cyclomatic"]}</text>')
    out.append("</svg>")
    return "".join(out)
