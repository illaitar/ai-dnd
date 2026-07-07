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

Key functions
-------------
generate(seed, env, cr, brief, small) -> dict : Generate a fully realized dungeon
    with skeleton, contents (monsters/traps), and optional lore—deterministic from seed.
stock(d, cr) -> None : Fill dungeon skeleton with monsters, traps, treasures
    using B/X quotas and encounter scaling by challenge rating.
dungeon_svg(d, title, game, floor) -> str : Render dungeon as parchment-style SVG
    with game fog-of-war and per-floor layers.
"""

from __future__ import annotations

import json
import math
import os
import random

COARSE_W, COARSE_H = 9, 7          # курс-грид узлов
CELL = 7                           # клетка курс-грида = 7×7 тайлов
NEST_MIN, NEST_MAX = 2, 4          # вложений на данж
RETRY = 24                         # под-сидов до сдачи (аккреция капризнее)
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


# ── геометрия: порт Watabou (worldgen/watabou.py) + Planner-драматургия ─────


def _attempt(seed: str, env: str, small: bool = False) -> dict | None:
    """Watabou-укладка ПО ЭТАЖАМ (корень этажа N+1 = клетка лестницы этажа N — честное
    XY-совмещение) → единый граф комнат (floor — поле комнаты, межэтажные связи — рёбра
    stairs/chute/collapse; chute односторонний) → Planner: цель на НИЖНЕМ этаже,
    секретные крылья, замки, ступени. Гарантии: solvable туда И ОБРАТНО."""
    from .watabou import layout

    rng = random.Random(f"dgen|{seed}")
    types = [t for t in _dtypes() if env in t["envs"]] or _dtypes()
    dt = rng.choices(types, weights=[t["w"] for t in types])[0]
    n_floors = 1 if small else rng.randint(*dt.get("floors", [1, 1]))
    per_floor = (10 if small else
                 rng.randint(12, 17) if n_floors > 1 else rng.randint(16, 26))

    floors, stairs_pts = [], []
    origin = (0, 0)
    for fi in range(n_floors):
        lay = layout(f"{seed}|f{fi}", rooms_target=per_floor,
                     order_p=dt["order_p"], corridor_p=dt["corridor_p"],
                     string=(fi == 0 and rng.random() < dt.get("string_p", 0)),
                     hall_p=dt["hall_p"], rotunda_p=dt["rotunda_p"],
                     water_p=dt["water_p"], origin=origin)
        if lay is None:
            return None
        floors.append(lay)
        if fi < n_floors - 1:                         # лестница вниз — в дальней комнате
            adjf: dict = {}
            for e in lay["edges"]:
                adjf.setdefault(e["a"], []).append(e["b"])
                adjf.setdefault(e["b"], []).append(e["a"])
            distf = {0: 0}
            qf = [0]
            while qf:
                cur = qf.pop(0)
                for nb in adjf.get(cur, []):
                    if nb not in distf:
                        distf[nb] = distf[cur] + 1
                        qf.append(nb)
            cand = [r for r in lay["rooms"] if r["size"] < 2]
            sr = max(cand, key=lambda r: distf.get(r["id"], 0))
            ts = sr["tiles"]
            cx = sorted(t[0] for t in ts)[len(ts) // 2]
            cy = sorted(t[1] for t in ts)[len(ts) // 2]
            stairs_pts.append((sr["id"], (cx, cy)))
            origin = (cx, cy)                         # корень следующего этажа — здесь

    # ── склейка этажей в единый граф ──
    rooms: list = []
    edges: list = []
    offs = []
    for fi, lay in enumerate(floors):
        off = len(rooms)
        offs.append(off)
        for r in lay["rooms"]:
            r2 = dict(r)
            r2["id"] = r["id"] + off
            r2["parent"] = (r["parent"] + off) if r.get("parent") is not None else None
            r2["floor"] = fi
            r2["tags"] = r.get("tags") or []
            rooms.append(r2)
        for e in lay["edges"]:
            edges.append({**e, "a": e["a"] + off, "b": e["b"] + off})
    for fi, (srid, cell) in enumerate(stairs_pts):    # лестницы: XY совпадает на этажах
        edges.append({"a": srid + offs[fi], "b": 0 + offs[fi + 1], "kind": "stairs",
                      "lock": None, "door": [cell[0], cell[1], cell[0], cell[1]],
                      "path": []})
    # вторая разнотипная связь (Jaquays): пересечение этажей по XY → жёлоб/шахта/пролом
    for fi in range(n_floors - 1):
        conns = dt.get("connectors") or []
        if not conns or rng.random() < 0.25:
            continue
        up = {tuple(t): r["id"] + offs[fi]
              for r in floors[fi]["rooms"] if r["size"] < 2 for t in r["tiles"]}
        stair_cell = stairs_pts[fi][1]
        best = None
        for r in floors[fi + 1]["rooms"]:
            if r["size"] >= 2:
                continue
            for t in r["tiles"]:
                tt = tuple(t)
                if tt in up and abs(tt[0] - stair_cell[0]) + abs(tt[1] - stair_cell[1]) > 6:
                    best = (up[tt], r["id"] + offs[fi + 1], tt)
                    break
            if best:
                break
        if best:
            kind = rng.choice(conns)
            edges.append({"a": best[0], "b": best[1], "kind": kind, "lock": None,
                          "door": [best[2][0], best[2][1], best[2][0], best[2][1]],
                          "path": [], "one_way": kind == "chute"})

    # нормировка ОДНИМ сдвигом (XY этажей физически совмещены)
    all_t = [t for r in rooms for t in r["tiles"]]
    mx = min(t[0] for t in all_t) - 1
    my = min(t[1] for t in all_t) - 1
    for r in rooms:
        r["tiles"] = [[x - mx, y - my] for x, y in r["tiles"]]
    for e in edges:
        e["door"] = [e["door"][0] - mx, e["door"][1] - my,
                     e["door"][2] - mx, e["door"][3] - my]
    water, columns = [], []
    for lay in floors:
        water += [[x - mx, y - my] for x, y in lay["water"]]
        columns += [[x - mx, y - my] for x, y in lay["columns"]]

    # ── виды, цель (на нижнем этаже), драматургия ──
    for r in rooms:
        r["kind"] = ("corridor" if r["size"] >= 2 else
                     "hall" if r["size"] == 1 else "room")
    rooms[0]["kind"] = "entrance"
    adj: dict = {}
    for e in edges:
        adj.setdefault(e["a"], []).append((e["b"], e))
        if not e.get("one_way"):
            adj.setdefault(e["b"], []).append((e["a"], e))
    cost = {0: 0}
    todo = [(0, 0)]
    while todo:
        todo.sort()
        c, cur = todo.pop(0)
        for nb, _e in adj.get(cur, []):
            w_ = 3 if rooms[nb]["size"] == 1 else 1
            if nb not in cost or c + w_ < cost[nb]:
                cost[nb] = c + w_
                todo.append((c + w_, nb))
    last_floor = max(r["floor"] for r in rooms)
    goal_pool = [r["id"] for r in rooms
                 if r["size"] <= 1 and r["id"] != 0 and r["floor"] == last_floor]
    goal = max(goal_pool or [len(rooms) - 1], key=lambda i: cost.get(i, -1))
    rooms[goal]["kind"] = "goal"

    prev = {0: None}
    q = [0]
    qi = 0
    while qi < len(q):
        cur = q[qi]
        qi += 1
        for nb, _e in adj.get(cur, []):
            if nb not in prev:
                prev[nb] = cur
                q.append(nb)
    crit = set()
    cur = goal
    while cur is not None:
        crit.add(cur)
        cur = prev.get(cur)

    kids: dict = {}
    for r in rooms:
        if r.get("parent") is not None:
            kids.setdefault(r["parent"], []).append(r["id"])

    def subtree(root):
        out, st_q = [root], [root]
        while st_q:
            c0 = st_q.pop()
            for k in kids.get(c0, []):
                out.append(k)
                st_q.append(k)
        return out

    wings = [r["id"] for r in rooms
             if r.get("parent") is not None and r["id"] not in crit
             and 1 <= len(subtree(r["id"])) <= 4
             and all(x not in crit for x in subtree(r["id"]))]
    rng.shuffle(wings)
    for wroot in wings[:dt.get("secret_wings", 1)]:
        e = next((e for e in edges
                  if frozenset((e["a"], e["b"])) ==
                  frozenset((wroot, rooms[wroot]["parent"]))), None)
        if e is None or e["kind"] != "door":
            continue
        e["kind"] = "secret"
        wing = subtree(wroot)
        for x in wing:
            if "secret_wing" not in rooms[x]["tags"]:
                rooms[x]["tags"].append("secret_wing")
        if "treasure" not in rooms[wing[-1]]["tags"]:
            rooms[wing[-1]]["tags"].append("treasure")

    keys: list = []
    lock_n = 0
    seq, cur = [], goal
    while cur is not None:
        seq.append(cur)
        cur = prev.get(cur)
    seq = seq[::-1]
    lockable = [e for e in edges if e["kind"] == "door"
                and frozenset((e["a"], e["b"])) in
                {frozenset((seq[i], seq[i + 1])) for i in range(len(seq) // 2,
                                                                len(seq) - 1)}]
    rng.shuffle(lockable)
    chosen = lockable[:rng.randint(0, 1) + (1 if not small else 0)]
    for e in chosen:
        lock_n += 1
        e["kind"], e["lock"] = "locked", f"k{lock_n}"
    for e in list(chosen):
        reach = _reachable_without(rooms, edges, None)
        spots = [x for x in reach if x != 0 and rooms[x]["kind"] not in ("goal",)]
        if not spots:
            e["kind"], e["lock"] = "door", None
            continue
        keys.append({"id": e["lock"], "room": rng.choice(spots)})

    before_goal = prev.get(goal)
    if before_goal is not None and rooms[before_goal]["kind"] in ("room", "hall"):
        rooms[before_goal]["tags"].append("approach")
    for fi, lay in enumerate(floors):
        if lay.get("backdoor") is not None and fi == 0 \
                and lay["backdoor"] + offs[fi] != goal:
            rooms[lay["backdoor"] + offs[fi]]["tags"].append("backdoor")
    for e in edges:
        if e["kind"] == "door" and rng.random() < dt["steps_p"]:
            e["kind"] = "steps"
    deg: dict = {}
    for e in edges:
        deg[e["a"]] = deg.get(e["a"], 0) + 1
        deg[e["b"]] = deg.get(e["b"], 0) + 1
    for r in rooms:
        if deg.get(r["id"], 0) == 1 and r["kind"] in ("room", "hall") \
                and r["id"] != goal and "treasure" not in r["tags"]:
            r["tags"].append("treasure")
    for r in rooms:
        if r["kind"] in ("corridor", "entrance"):
            continue
        props = []
        if r["id"] == goal:
            props.append(dt["goal_prop"])
        if "treasure" in r["tags"] and rng.random() < 0.7:
            props.append("chest")
        for glyph, pp in dt["props"].items():
            if rng.random() < pp and glyph not in props:
                props.append(glyph)
        r["props"] = props[:3]

    if not _solvable(rooms, edges, keys, 0, goal, use_secret=False):
        return None
    if not _solvable(rooms, edges, keys, 0, goal, use_secret=True):
        return None
    if not _solvable_back(rooms, edges, goal):        # односторонние жёлобы не запирают
        return None
    met = _metrics(rooms, edges)
    if met["cyclomatic"] < 1 or met["bad_deadends"]:
        return None
    tw = max(t[0] for r in rooms for t in r["tiles"]) + 2
    th = max(t[1] for r in rooms for t in r["tiles"]) + 2
    return {"seed": seed, "env": env, "dtype": dt["key"], "dtype_name": dt["name"],
            "floors": n_floors, "rooms": rooms, "edges": edges, "keys": keys,
            "entrance": 0, "goal": goal, "metrics": met,
            "water": water, "columns": columns, "tile_w": tw, "tile_h": th}


def _solvable_back(rooms, edges, goal) -> bool:
    """С цели можно ВЕРНУТЬСЯ ко входу (жёлобы односторонние — лестницы выводят)."""
    adj: dict = {}
    for e in edges:
        if e["kind"] in ("window", "portcullis"):
            continue
        adj.setdefault(e["a"], []).append(e["b"])
        if not e.get("one_way"):
            adj.setdefault(e["b"], []).append(e["a"])
        else:
            adj.setdefault(e["b"], [])                # вверх по жёлобу нельзя
    # обратный обход: из goal по рёбрам, где переход b→a разрешён
    radj: dict = {}
    for e in edges:
        if e["kind"] in ("window", "portcullis"):
            continue
        radj.setdefault(e["b"], []).append(e["a"])
        if not e.get("one_way"):
            radj.setdefault(e["a"], []).append(e["b"])
    seen, q = {goal}, [goal]
    while q:
        cur = q.pop()
        if cur == 0:
            return True
        for nb in radj.get(cur, []):
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    return False


_DT: list | None = None


def _dtypes() -> list:
    global _DT
    if _DT is None:
        p = os.path.join(os.path.dirname(__file__), "..", "content", "dungeon_types.json")
        with open(p, encoding="utf-8") as f:
            _DT = json.load(f)["types"]
    return _DT


def _reachable_without(rooms, edges, cut) -> set:
    """Достижимо от входа БЕЗ прохода НИ ОДНОЙ запертой двери (Watabou spawnKeys)."""
    adj: dict = {}
    for e in edges:
        if e is cut or e["kind"] in ("window", "portcullis", "locked"):
            continue
        adj.setdefault(e["a"], []).append(e["b"])
        adj.setdefault(e["b"], []).append(e["a"])
    seen, q = {0}, [0]
    while q:
        cur = q.pop()
        for nb in adj.get(cur, []):
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    return seen


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
        if e["kind"] in ("window", "portcullis") or \
                (e["kind"] == "secret" and not use_secret):
            continue
        adj.setdefault(e["a"], []).append((e["b"], e["lock"]))
        if not e.get("one_way"):
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
    passable = [e for e in edges if e["kind"] not in ("window", "portcullis")]
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


def generate(seed: str, env: str = "Ruin", cr: float = 1.0, brief: dict | None = None,
             small: bool = False) -> dict:
    """Данж по сиду: под-сиды до прохождения фильтра качества (детерминированная цепочка);
    скелет сразу НАПОЛНЯЕТСЯ (stock — квоты B/X + машины + фракция), бриф из пула (если
    дан) раздаёт комнатам имена/описания/улики истории (apply_brief, детерминированно)."""
    for i in range(RETRY):
        d = _attempt(f"{seed}|{i}", env, small)
        if d is not None:
            stock(d, cr)
            if brief:
                from .dungeonlore import apply_brief
                apply_brief(d, brief, random.Random(f"brief|{seed}"))
            return d
    raise ValueError(f"данж не собрался за {RETRY} под-сидов: {seed}")  # практически недостижимо


_MCAT: dict | None = None


def _machines() -> dict:
    global _MCAT
    if _MCAT is None:
        p = os.path.join(os.path.dirname(__file__), "..", "content", "dungeon_machines.json")
        with open(p, encoding="utf-8") as f:
            _MCAT = json.load(f)
    return _MCAT


# Квоты наполнения B/X (Молдвей 1981): треть монстры, шестая ловушки, шестая особенности,
# треть пусто; шанс клада при каждом виде — классика (см. docs/dungeons.md).
_STOCK_Q = (("monster", 0.33), ("trap", 0.17), ("special", 0.17), ("empty", 0.33))
_TREASURE_P = {"monster": 0.5, "trap": 0.33, "special": 0.17, "empty": 0.17}


def stock(d: dict, cr: float = 1.0) -> None:
    """Наполнение скелета: КВОТЫ — таблица, содержимое — из данных (машины/ловушки/бестиарий).
    Теги дуг двигают вероятности (danger → монстры), тупики-награды всегда с кладом,
    зал цели — вождь на полном CR. Фракционные роли комнат — пост/склад/логово вождя."""
    from aidnd.combat.encounters import pick_encounter

    rng = random.Random(f"stock|{d['seed']}")
    cat = _machines()
    env = d["env"]
    deg: dict = {}
    for e in d["edges"]:
        if e["kind"] != "window":
            deg[e["a"]] = deg.get(e["a"], 0) + 1
            deg[e["b"]] = deg.get(e["b"], 0) + 1
    post_done = False
    for r in d["rooms"]:
        if r.get("size", 0) >= 2:                     # коридор — пусто (изредка ловушка)
            r["content"] = ({"kind": "trap", "trap": dict(rng.choice(cat["traps"]))}
                            if rng.random() < 0.06 else {"kind": "empty"})
            continue
        if r["kind"] == "entrance":
            r["content"] = {"kind": "empty", "flavor": dict(rng.choice(cat["flavors"]))}
            continue
        if r["kind"] == "goal":                       # логово вождя: полный CR + клад логова
            units = pick_encounter(cr, env, seed=f"boss|{d['seed']}")
            r["content"] = {"kind": "monster", "boss": True, "units": _unit_names(units),
                            "cr": cr, "treasure": _treasure(rng, cr, guarded=True)}
            r["frole"] = "вождь"
            continue
        if "approach" in r["tags"] and rng.random() < 0.6:
            units = pick_encounter(cr * 0.45, env, seed=f"guard|{d['seed']}|{r['id']}")
            r["content"] = {"kind": "monster", "units": _unit_names(units)}
            r["frole"] = "пост"
            continue
        roll, acc, kind = rng.random(), 0.0, "empty"
        for k, q in _STOCK_Q:
            acc += q
            if roll < acc:
                kind = k
                break
        if "danger" in r["tags"] and kind == "empty":
            kind = "monster"                          # опасная дуга не пустует
        if "treasure" in r["tags"]:
            kind = "treasure"                         # тупик-награда осмыслен по построению
        c: dict = {"kind": kind}
        if kind == "monster":
            fmul = 1 + 0.25 * r.get("floor", 0)       # глубже — злее (ярусы напряжения)
            units = pick_encounter(cr * rng.uniform(0.25, 0.5) * fmul, env,
                                   seed=f"mob|{d['seed']}|{r['id']}")
            c["units"] = _unit_names(units)
            if not post_done and deg.get(r["id"], 0) >= 2:
                r["frole"] = "пост"                   # первый обитаемый узел — сторожевой
                post_done = True
        elif kind == "trap":
            t = dict(rng.choice(cat["traps"]))
            c["trap"] = t                             # телеграф в САМОЙ комнате — честно
        elif kind == "special":
            c["machine"] = dict(_pick(rng, cat["machines"]))
        elif kind == "empty":
            c["flavor"] = dict(rng.choice(cat["flavors"]))
        if kind == "treasure" or rng.random() < _TREASURE_P.get(kind, 0):
            c["treasure"] = _treasure(rng, cr, guarded=(kind == "monster"))
            if kind == "treasure":
                r["frole"] = "склад"
        r["content"] = c


def _unit_names(units) -> list:
    out: dict = {}
    for u in units:                                   # pick_encounter отдаёт Combatant-ов
        nm = getattr(u, "name", None) or "тварь"
        out[nm] = out.get(nm, 0) + 1
    return [f"{nm} ×{n}" if n > 1 else nm for nm, n in out.items()]


def _treasure(rng, cr: float, guarded: bool) -> dict:
    """Клад по классике: контейнер × сокрытие; ценность от CR (материализация — этап C)."""
    return {"worth": max(2, int(cr * rng.uniform(6, 14))),
            "container": rng.choice(("сундук", "урна", "мешок", "россыпь", "ларец")),
            "concealment": rng.choice(("на виду", "под плитой", "двойное дно",
                                       "в нише за камнем", "среди мусора", "на дне воды")),
            "guarded": guarded}


# ── бумажный черновик (полный Dyson-рендер — этап C) ─────────────────────────


def _glyph(out, kind, cx, cy, S, rng, ink):
    """Чернильные глифы реквизита (drawings.* оригинала), вид сверху."""
    if kind == "sarcophagus":
        w, h = S * 1.7, S * 0.95
        out.append(f'<rect x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" width="{w:.1f}" '
                   f'height="{h:.1f}" fill="#f3ecd8" stroke="{ink}" stroke-width="1.4"/>'
                   f'<rect x="{cx - w / 2 + 3:.1f}" y="{cy - h / 2 + 3:.1f}" '
                   f'width="{w - 6:.1f}" height="{h - 6:.1f}" fill="none" stroke="{ink}" '
                   f'stroke-width="0.8"/>')
    elif kind == "throne":
        out.append(f'<rect x="{cx - S * 0.35:.1f}" y="{cy - S * 0.3:.1f}" '
                   f'width="{S * 0.7:.1f}" height="{S * 0.6:.1f}" fill="none" '
                   f'stroke="{ink}" stroke-width="1.3"/>'
                   f'<line x1="{cx - S * 0.45:.1f}" y1="{cy - S * 0.3:.1f}" '
                   f'x2="{cx + S * 0.45:.1f}" y2="{cy - S * 0.3:.1f}" stroke="{ink}" '
                   f'stroke-width="2.4"/>')
    elif kind == "altar":
        out.append(f'<rect x="{cx - S * 0.6:.1f}" y="{cy - S * 0.35:.1f}" '
                   f'width="{S * 1.2:.1f}" height="{S * 0.7:.1f}" fill="#f3ecd8" '
                   f'stroke="{ink}" stroke-width="1.4"/>')
        for dx in (-S * 0.3, 0, S * 0.3):
            out.append(f'<circle cx="{cx + dx:.1f}" cy="{cy:.1f}" r="1.1" fill="{ink}"/>')
    elif kind == "statue":
        out.append(f'<rect x="{cx - S * 0.3:.1f}" y="{cy - S * 0.3:.1f}" '
                   f'width="{S * 0.6:.1f}" height="{S * 0.6:.1f}" fill="none" '
                   f'stroke="{ink}" stroke-width="0.9"/>'
                   f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{S * 0.16:.1f}" fill="{ink}"/>')
    elif kind == "chest":
        out.append(f'<rect x="{cx - S * 0.42:.1f}" y="{cy - S * 0.28:.1f}" '
                   f'width="{S * 0.84:.1f}" height="{S * 0.56:.1f}" fill="#f3ecd8" '
                   f'stroke="{ink}" stroke-width="1.3"/>'
                   f'<line x1="{cx - S * 0.42:.1f}" y1="{cy - S * 0.08:.1f}" '
                   f'x2="{cx + S * 0.42:.1f}" y2="{cy - S * 0.08:.1f}" stroke="{ink}" '
                   f'stroke-width="0.9"/>')
    elif kind == "barrel":
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{S * 0.3:.1f}" fill="none" '
                   f'stroke="{ink}" stroke-width="1.2"/>'
                   f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{S * 0.12:.1f}" fill="none" '
                   f'stroke="{ink}" stroke-width="0.7"/>')
    elif kind == "box":
        out.append(f'<rect x="{cx - S * 0.28:.1f}" y="{cy - S * 0.28:.1f}" '
                   f'width="{S * 0.56:.1f}" height="{S * 0.56:.1f}" fill="none" '
                   f'stroke="{ink}" stroke-width="1.1"/>'
                   f'<line x1="{cx - S * 0.28:.1f}" y1="{cy - S * 0.28:.1f}" '
                   f'x2="{cx + S * 0.28:.1f}" y2="{cy + S * 0.28:.1f}" stroke="{ink}" '
                   f'stroke-width="0.7"/>')
    elif kind in ("fountain", "well"):
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{S * 0.42:.1f}" fill="none" '
                   f'stroke="{ink}" stroke-width="1.3"/>')
        if kind == "fountain":
            out.append(f'<path d="M {cx - S * 0.22:.1f} {cy:.1f} q {S * 0.11:.1f} -2.4 '
                       f'{S * 0.22:.1f} 0 t {S * 0.22:.1f} 0" fill="none" stroke="{ink}" '
                       f'stroke-width="0.8"/>')
        else:
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{S * 0.2:.1f}" '
                       f'fill="{ink}" opacity="0.75"/>')
    elif kind == "dais":
        for k2, wd in ((0.7, 1.1), (0.45, 0.8)):
            out.append(f'<rect x="{cx - S * wd / 2:.1f}" y="{cy - S * k2 / 2:.1f}" '
                       f'width="{S * wd:.1f}" height="{S * k2:.1f}" fill="none" '
                       f'stroke="{ink}" stroke-width="0.9"/>')
    elif kind == "boulder":
        pts = []
        for a2 in range(6):
            ang = a2 * 1.047 + rng.uniform(-0.2, 0.2)
            rr = S * rng.uniform(0.22, 0.38)
            pts.append(f"{cx + rr * math.cos(ang):.1f},{cy + rr * math.sin(ang):.1f}")
        out.append(f'<polygon points="{" ".join(pts)}" fill="none" stroke="{ink}" '
                   f'stroke-width="1.1"/>')


def dungeon_svg(d: dict, title: str = "", game: dict | None = None,
                floor: int | None = None) -> str:
    """Watabou-одностраничник на пергаменте: плотный комплекс, сетка пола, ТОЛСТЫЕ стены,
    двери-коробки, хэтч по силуэту. ЭТАЖ = представление (лист-на-этаж): рисуются комнаты
    одного яруса, межэтажные связи — знаками (веер лестницы / зев жёлоба / пролом).
    game: туман (seen), призраки у дверей (межэтажные — стрелкой), маркер, зум."""
    from .floorart import INK, _defs

    rng = random.Random(f"dart|{d['seed']}")
    if floor is None:
        floor = (d["rooms"][game["cur"]].get("floor", 0) if game else 0)
    fl_rooms = {r["id"] for r in d["rooms"] if r.get("floor", 0) == floor}
    seen = (set(game["seen"]) if game else set(fl_rooms)) & fl_rooms
    found = set(game.get("found") or ()) if game else None

    def _vis_edge(eid, e) -> bool:
        if e["kind"] == "secret" and found is not None and eid not in found:
            return False
        if not game:
            return True
        if e["kind"] == "window":
            return e["a"] in seen and e["b"] in seen
        return e["a"] in seen or e["b"] in seen

    # ── пол и владельцы клеток ──
    owner: dict = {}
    room_tiles: dict = {}
    for r in d["rooms"]:
        if r["id"] in seen:
            t = {tuple(x) for x in r["tiles"]}
            room_tiles[r["id"]] = t
            for c in t:
                owner[c] = r["id"]
    openings: set = set()                             # пары клеток, где стены НЕТ (проём)
    door_marks: list = []                             # (cellA, cellB, kind)
    ghost_at: dict = {}                               # rid → якорь призрака
    corr_cells: set = set()
    interfloor: list = []                             # (cell, kind, направление, other_rid)
    for eid, e in enumerate(d["edges"]):
        if e["kind"] in ("stairs", "chute", "collapse"):
            fa = d["rooms"][e["a"]].get("floor", 0)
            fb = d["rooms"][e["b"]].get("floor", 0)
            here_rid = e["a"] if fa == floor else (e["b"] if fb == floor else None)
            if here_rid is None or (game and here_rid not in seen):
                continue
            other = e["b"] if here_rid == e["a"] else e["a"]
            down = d["rooms"][other].get("floor", 0) > floor
            if e.get("one_way") and here_rid == e["b"]:
                other = None                          # снизу жёлоб — только знак, не ход
            interfloor.append(((e["door"][0], e["door"][1]), e["kind"], down, other))
            continue
        if e["kind"] == "window" or not _vis_edge(eid, e):
            continue
        both = e["a"] in seen and e["b"] in seen
        if e.get("door"):
            x1, y1, x2, y2 = e["door"]
            a_c, b_c = (x1, y1), (x2, y2)
            if both:
                openings.add(frozenset((a_c, b_c)))
                door_marks.append((a_c, b_c, e["kind"]))
            else:
                unseen = e["b"] if e["a"] in seen else e["a"]
                ghost_at[unseen] = a_c if a_c not in owner else b_c
                door_marks.append((a_c, b_c, e["kind"]))
        elif e.get("path"):
            path = [tuple(t) for t in e["path"]]
            cut = path if both else (path[:max(1, len(path) // 2)]
                                     if e["a"] in seen else path[len(path) // 2:])
            for c in cut:
                owner[c] = ("c", eid)
                corr_cells.add(c)
            ends = []
            for end, rid in ((path[0], e["a"]), (path[-1], e["b"])):
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nb = (end[0] + dx, end[1] + dy)
                    if owner.get(nb) == rid:
                        openings.add(frozenset((end, nb)))
                        ends.append((end, nb))
            for i2 in range(len(cut) - 1):
                openings.add(frozenset((cut[i2], cut[i2 + 1])))
            if not both:
                unseen = e["b"] if e["a"] in seen else e["a"]
                ghost_at[unseen] = cut[-1] if e["a"] in seen else cut[0]
            if both and ends and e["kind"] in ("locked", "secret"):
                door_marks.append((*ends[-1], e["kind"]))
    floor_cells = set(owner)
    floor_tiles_all = {tuple(t) for r in d["rooms"]
                       if r.get("floor", 0) == (floor if isinstance(floor, int) else 0)
                       for t in r["tiles"]}

    S = 15
    pad = 34
    if floor_cells:
        gx = [g[0] for g in ghost_at.values()]
        gy = [g[1] for g in ghost_at.values()]
        xs = [t[0] for t in floor_cells] + [x - 2 for x in gx] + [x + 2 for x in gx]
        ys = [t[1] for t in floor_cells] + [y - 2 for y in gy] + [y + 2 for y in gy]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
    else:
        bx0, by0, bx1, by1 = 0, 0, d["tile_w"], d["tile_h"]
    W = (bx1 - bx0) * S + pad * 2
    H = (by1 - by0) * S + pad * 2 + 18

    def px(t):
        return (pad + (t[0] - bx0) * S, pad + (t[1] - by0) * S)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'font-family="Georgia, serif">',
           _defs(sum(ord(c) for c in d["seed"])),
           f'<rect width="{W}" height="{H}" fill="#e9dfc6" filter="url(#stains)"/>',
           f'<rect width="{W}" height="{H}" fill="none" filter="url(#grain)"/>']

    # drop shadow: смещённый силуэт — «карта лежит на бумаге» (Watabou)
    for t in sorted(floor_cells):
        x, y = px(t)
        out.append(f'<rect x="{x + S * 0.22:.1f}" y="{y + S * 0.3:.1f}" width="{S}" '
                   f'height="{S}" fill="#c9bfa2" opacity="0.55"/>')
    # пол: сетка клеток (коридоры чуть темнее)
    for t in sorted(floor_cells):
        x, y = px(t)
        fill = "#e4d9ba" if t in corr_cells else "#f3ecd8"
        out.append(f'<rect x="{x}" y="{y}" width="{S}" height="{S}" fill="{fill}" '
                   f'stroke="{INK}" stroke-width="0.3" opacity="0.95"/>')

    # вода (шум+порог, только в комнатах) и колонны
    wat = {tuple(t) for t in (d.get("water") or [])} & floor_cells
    for t in sorted(wat):
        x, y = px(t)
        out.append(f'<rect x="{x}" y="{y}" width="{S}" height="{S}" fill="#d6dbd2"/>')
        yy = y + S * (0.35 + rng.random() * 0.3)
        out.append(f'<path d="M {x + 2} {yy:.1f} q {S / 4:.0f} -2.2 {S / 2:.0f} 0 '
                   f't {S / 2 - 4:.0f} 0" fill="none" stroke="{INK}" stroke-width="0.8" '
                   f'opacity="0.6"/>')
    for t in (d.get("columns") or []):
        if tuple(t) not in floor_cells:
            continue
        x, y = px(t)
        out.append(f'<circle cx="{x + S / 2}" cy="{y + S / 2}" r="{S * 0.2:.1f}" '
                   f'fill="{INK}"/>')

    # ── стены: наружные (с хэтчем) и межкомнатные ──
    ext_edges, int_edges = [], []
    for t in floor_cells:
        for dx, dy, nx, ny in ((0, -1, 0, -1), (0, 1, 0, 1), (-1, 0, -1, 0), (1, 0, 1, 0)):
            nb = (t[0] + dx, t[1] + dy)
            if nb not in floor_cells:
                ext_edges.append((t, (dx, dy), (nx, ny)))
            elif owner[nb] != owner[t] and frozenset((t, nb)) not in openings:
                if (dx, dy) in ((1, 0), (0, 1)):      # каждую внутреннюю — один раз
                    int_edges.append((t, (dx, dy)))

    def _edge_px(t, dxy):
        x, y = px(t)
        if dxy == (0, -1):
            return (x, y), (x + S, y)
        if dxy == (0, 1):
            return (x, y + S), (x + S, y + S)
        if dxy == (-1, 0):
            return (x, y), (x, y + S)
        return (x + S, y), (x + S, y + S)

    for (t, dxy, _nrm) in ext_edges:
        (x1, y1), (x2, y2) = _edge_px(t, dxy)
        out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK}" '
                   f'stroke-width="3" stroke-linecap="square"/>')

    # дайсон-хэтч по Watabou: точки Пуассона вокруг силуэта → кластеры изогнутых штрихов,
    # угол на ближайшего соседа, длина до соседа, подрезка друг о друга (упрощённая: кап)
    pts = []
    for (t, dxy, nrm) in ext_edges:
        (x1, y1), (x2, y2) = _edge_px(t, dxy)
        for f in (0.25, 0.75):
            pts.append((x1 + (x2 - x1) * f + nrm[0] * rng.uniform(3, 7),
                        y1 + (y2 - y1) * f + nrm[1] * rng.uniform(3, 7), nrm))
    keep = []
    for p_ in pts:                                    # пуассон-прореживание
        if all((p_[0] - q[0]) ** 2 + (p_[1] - q[1]) ** 2 > 7 ** 2 for q in keep):
            keep.append(p_)
    for (px_, py_, nrm) in keep:
        near = min((q for q in keep if q is not (px_, py_, nrm)
                    and (q[0] - px_) ** 2 + (q[1] - py_) ** 2 > 0.1),
                   key=lambda q: (q[0] - px_) ** 2 + (q[1] - py_) ** 2,
                   default=None)
        dist_n = math.hypot(near[0] - px_, near[1] - py_) if near else 10
        ang = math.atan2(near[1] - py_, near[0] - px_) if near else \
            math.atan2(nrm[1], nrm[0])
        ang += rng.uniform(-0.3, 0.3)
        ln = min(11.0, max(4.0, dist_n * 0.8))
        step = ln / 3.2
        for j3 in range(rng.randint(2, 4)):           # кластер изогнутых штрихов
            ox_ = px_ + math.cos(ang + 1.5708) * (j3 - 1) * step
            oy_ = py_ + math.sin(ang + 1.5708) * (j3 - 1) * step
            l2 = ln * rng.uniform(0.7, 1.0)
            mx_ = ox_ + math.cos(ang) * l2 / 2 + rng.uniform(-1, 1)
            my_ = oy_ + math.sin(ang) * l2 / 2 + rng.uniform(-1, 1)
            ex_ = ox_ + math.cos(ang) * l2
            ey_ = oy_ + math.sin(ang) * l2
            out.append(f'<path d="M {ox_:.1f} {oy_:.1f} Q {mx_:.1f} {my_:.1f} '
                       f'{ex_:.1f} {ey_:.1f}" fill="none" stroke="{INK}" '
                       f'stroke-width="{rng.uniform(0.7, 1.1):.2f}" opacity="0.6"/>')

    for (t, dxy) in int_edges:
        (x1, y1), (x2, y2) = _edge_px(t, dxy)
        out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK}" '
                   f'stroke-width="2.6" stroke-linecap="square"/>')

    # двери-коробки на общих стенах
    for (a_c, b_c, kind) in door_marks:
        if a_c not in floor_cells and b_c not in floor_cells:
            continue
        ax, ay = px(a_c)
        bx2, by2 = px(b_c)
        mxp, myp = (ax + bx2) / 2 + S / 2, (ay + by2) / 2 + S / 2
        horiz = a_c[1] == b_c[1]
        dw, dh = (S * 0.36, S * 0.6) if horiz else (S * 0.6, S * 0.36)
        dash = ' stroke-dasharray="3 3"' if kind == "secret" else ""
        if kind not in ("steps", "portcullis"):
            out.append(f'<rect x="{mxp - dw / 2:.1f}" y="{myp - dh / 2:.1f}" '
                       f'width="{dw:.1f}" height="{dh:.1f}" fill="#f3ecd8" stroke="{INK}" '
                       f'stroke-width="1.7"{dash}/>')
        if kind == "steps":                       # перепад: три черты поперёк проёма
            for i3 in (-1, 0, 1):
                if horiz:
                    out.append(f'<line x1="{mxp + i3 * 3.2:.1f}" y1="{myp - S * 0.28:.1f}" '
                               f'x2="{mxp + i3 * 3.2:.1f}" y2="{myp + S * 0.28:.1f}" '
                               f'stroke="{INK}" stroke-width="1.1"/>')
                else:
                    out.append(f'<line x1="{mxp - S * 0.28:.1f}" y1="{myp + i3 * 3.2:.1f}" '
                               f'x2="{mxp + S * 0.28:.1f}" y2="{myp + i3 * 3.2:.1f}" '
                               f'stroke="{INK}" stroke-width="1.1"/>')
        elif kind == "portcullis":                    # решётка: три точки
            for i3 in (-1, 0, 1):
                dx3, dy3 = (i3 * 3.4, 0) if not horiz else (0, i3 * 3.4)
                out.append(f'<circle cx="{mxp + dx3:.1f}" cy="{myp + dy3:.1f}" r="1.1" '
                           f'fill="{INK}"/>')
        elif kind == "locked":
            out.append(f'<rect x="{mxp - 3.2}" y="{myp - 1.5}" width="6.4" height="5.4" '
                       f'fill="{INK}"/><path d="M {mxp - 2} {myp - 1.5} a 2 2.6 0 0 1 4 0" '
                       f'fill="none" stroke="{INK}" stroke-width="1.3"/>')
        elif kind == "secret":
            out.append(f'<text x="{mxp}" y="{myp + 3.8}" font-size="10.5" '
                       f'text-anchor="middle" font-style="italic" fill="{INK}">S</text>')
            tw_, th_ = (2.6, S * 0.9) if horiz else (S * 0.9, 2.6)  # гобелен ЗАКРЫВАЕТ ход
            out.append(f'<rect x="{mxp - tw_ / 2:.1f}" y="{myp - th_ / 2:.1f}" '
                       f'width="{tw_:.1f}" height="{th_:.1f}" fill="none" stroke="{INK}" '
                       f'stroke-width="1" stroke-dasharray="1.5 1.8"/>')

    # межэтажные знаки: веер лестницы / зев жёлоба / пролом (+клик-переход в game)
    for (cell, kind, down, other) in interfloor:
        if cell not in floor_tiles_all:
            continue
        x, y = px(cell)
        cxp, cyp = x + S / 2, y + S / 2
        g_open = ""
        g_close = ""
        if game and other is not None and other in (game.get("next") or ()):
            g_open = (f'<g data-room="{other}" class="droom" style="cursor:pointer">')
            g_close = "</g>"
        out.append(g_open)
        if kind == "stairs":
            for i4 in range(4):
                ww = S * (0.85 - i4 * 0.18)
                out.append(f'<line x1="{cxp - ww / 2:.1f}" y1="{y + 2.5 + i4 * 3.2:.1f}" '
                           f'x2="{cxp + ww / 2:.1f}" y2="{y + 2.5 + i4 * 3.2:.1f}" '
                           f'stroke="{INK}" stroke-width="1.3"/>')
        elif kind == "chute":
            out.append(f'<circle cx="{cxp}" cy="{cyp}" r="{S * 0.36:.1f}" fill="{INK}" '
                       f'opacity="0.85"/><circle cx="{cxp}" cy="{cyp}" r="{S * 0.36:.1f}" '
                       f'fill="none" stroke="{INK}" stroke-width="1.2"/>')
        else:                                         # пролом: россыпь обломков
            for _ in range(6):
                bx3 = cxp + rng.uniform(-S * 0.35, S * 0.35)
                by3 = cyp + rng.uniform(-S * 0.35, S * 0.35)
                out.append(f'<circle cx="{bx3:.1f}" cy="{by3:.1f}" '
                           f'r="{rng.uniform(0.8, 1.6):.1f}" fill="{INK}"/>')
        out.append(f'<text x="{cxp + S * 0.55:.1f}" y="{cyp + 4:.1f}" font-size="11" '
                   f'fill="{INK}">{"↓" if down else "↑"}</text>')
        out.append(g_close)

    # нумерация по ЧАСОВОЙ вокруг центра карты (Watabou), коридоры не нумеруются
    ctr_x = sum(t[0] for t in floor_cells) / max(1, len(floor_cells))
    ctr_y = sum(t[1] for t in floor_cells) / max(1, len(floor_cells))
    numbered = [r for r in d["rooms"] if r.get("size", 0) < 2 and r["id"] in seen]
    numbered.sort(key=lambda r: math.atan2(
        sum(t[0] for t in r["tiles"]) / len(r["tiles"]) - ctr_x,
        -(sum(t[1] for t in r["tiles"]) / len(r["tiles"]) - ctr_y)))
    room_no = {r["id"]: i + 1 for i, r in enumerate(numbered)}

    # ── комнаты: значки/номера/маркер ──
    for r in d["rooms"]:
        if r["id"] not in seen:
            if game and r["id"] in ghost_at:
                gxp, gyp = px(ghost_at[r["id"]])
                click = (' class="droom" style="cursor:pointer"'
                         if r["id"] in (game.get("next") or ()) else "")
                out.append(f'<g data-room="{r["id"]}"{click}>'
                           f'<rect x="{gxp - S * 0.8:.0f}" y="{gyp - S * 0.8:.0f}" '
                           f'width="{S * 2.4:.0f}" height="{S * 2.4:.0f}" fill="none" '
                           f'stroke="{INK}" stroke-width="1.3" stroke-dasharray="5 5" '
                           f'opacity="0.55" rx="4"/>'
                           f'<text x="{gxp + S * 0.4:.0f}" y="{gyp + S * 0.62:.0f}" '
                           f'font-size="{S * 1.1:.0f}" text-anchor="middle" fill="{INK}" '
                           f'opacity="0.6">?</text></g>')
            continue
        tiles = room_tiles[r["id"]]
        xs_ = [t[0] for t in tiles]
        ys_ = [t[1] for t in tiles]
        x0, y0 = px((min(xs_), min(ys_)))
        x1, y1 = px((max(xs_) + 1, max(ys_) + 1))
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        w_ = max(xs_) - min(xs_) + 1
        h_ = max(ys_) - min(ys_) + 1
        c = r.get("content") or {}
        if w_ >= 5 and h_ >= 5 and len(tiles) >= 22 and r["kind"] != "entrance":
            for cx2 in (min(xs_) + 1, max(xs_) - 1):  # колонны большого зала
                for cy2 in (min(ys_) + 1, max(ys_) - 1):
                    if (cx2, cy2) in tiles:
                        cpx, cpy = px((cx2, cy2))
                        out.append(f'<circle cx="{cpx + S / 2}" cy="{cpy + S / 2}" '
                                   f'r="{S * 0.22:.1f}" fill="{INK}"/>')
        if r["kind"] == "entrance":
            for i2 in range(4):
                ww = (x1 - x0) * (0.72 - i2 * 0.13)
                out.append(f'<line x1="{mx - ww / 2:.0f}" y1="{y0 + 4 + i2 * 5}" '
                           f'x2="{mx + ww / 2:.0f}" y2="{y0 + 4 + i2 * 5}" '
                           f'stroke="{INK}" stroke-width="1.5"/>')
        for pi, prop in enumerate(r.get("props") or []):
            if pi == 0 and r["kind"] == "goal":
                gxp, gyp = mx, my + S * 0.9
            else:
                corners = [(x0 + S * 1.1, y0 + S * 1.1), (x1 - S * 1.1, y0 + S * 1.1),
                           (x0 + S * 1.1, y1 - S * 1.1), (x1 - S * 1.1, y1 - S * 1.1)]
                gxp, gyp = corners[(pi + r["id"]) % 4]
            _glyph(out, prop, gxp, gyp, S, rng, INK)
        if c.get("boss"):
            out.append(f'<text x="{mx}" y="{my - S * 0.25}" font-size="{S * 1.15:.0f}" '
                       f'text-anchor="middle" fill="{INK}">☠</text>')
        elif c.get("kind") == "monster":
            out.append(f'<text x="{mx}" y="{my - S * 0.2}" font-size="{S * 0.85:.0f}" '
                       f'text-anchor="middle" fill="{INK}" opacity="0.9">⚔</text>')
        elif c.get("kind") == "trap":
            out.append(f'<text x="{mx}" y="{my - S * 0.15}" font-size="{S * 0.9:.0f}" '
                       f'text-anchor="middle" fill="{INK}">^</text>')
        elif c.get("kind") == "special":
            out.append(f'<text x="{mx}" y="{my - S * 0.15}" font-size="{S * 0.85:.0f}" '
                       f'text-anchor="middle" fill="{INK}">✷</text>')
        if c.get("treasure"):
            out.append(f'<rect x="{mx + S * 0.4:.0f}" y="{my + S * 0.3:.0f}" '
                       f'width="{S * 0.5:.0f}" height="{S * 0.4:.0f}" fill="none" '
                       f'stroke="{INK}" stroke-width="1.2"/>')
        if any(k["room"] == r["id"] for k in d["keys"]):
            out.append(f'<text x="{mx}" y="{my + S * 0.6:.0f}" font-size="{S * 0.8:.0f}" '
                       f'text-anchor="middle" fill="{INK}">⚷</text>')
        if r["id"] in room_no:
            out.append(f'<text x="{x0 + 4}" y="{y0 + 12}" font-size="{S * 0.6:.0f}" '
                       f'fill="{INK}" opacity="0.8">{room_no[r["id"]]}</text>')
        if game and r["id"] == game.get("cur"):
            out.append(f'<circle cx="{mx}" cy="{my}" r="{S * 0.4:.0f}" fill="none" '
                       f'stroke="#7a1f1f" stroke-width="2.6"/>'
                       f'<circle cx="{mx}" cy="{my}" r="{S * 0.15:.0f}" fill="#7a1f1f"/>')
        if r.get("name") or game:
            tip = f"{r['id'] + 1}. {r.get('name') or 'комната'} — {r.get('desc', '')}"
            click = (' class="droom" style="cursor:pointer"'
                     if game and r["id"] in (game.get("next") or ()) else "")
            out.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" '
                       f'fill="transparent" data-room="{r["id"]}"{click}>'
                       f'<title>{tip}</title></rect>')

    for eid, e in enumerate(d["edges"]):              # окна-предвестия
        if e["kind"] != "window" or not _vis_edge(eid, e):
            continue
        if e["a"] in room_tiles and e["b"] in room_tiles:
            ca, cb = _center(d["rooms"][e["a"]]), _center(d["rooms"][e["b"]])
            if abs(ca[0] - cb[0]) + abs(ca[1] - cb[1]) > 9:
                continue                              # окно — только меж БЛИЗКИМИ комнатами
            ax, ay = px(ca)
            bx2, by2 = px(cb)
            out.append(f'<line x1="{ax}" y1="{ay}" x2="{bx2}" y2="{by2}" stroke="{INK}" '
                       f'stroke-width="0.9" stroke-dasharray="2 5" opacity="0.55"/>')

    m = d["metrics"]
    label = d.get("name") or title or "Подземелье"
    if d.get("floors", 1) > 1:
        label += f" · ярус {floor + 1}/{d['floors']}"
    hist = (d.get("history") or {}).get("now", "")
    out.append(f'<text x="{pad}" y="{H - 8}" font-size="13" font-style="italic" '
               f'fill="{INK}" opacity="0.85">{label} · комнат {m["rooms"]} · '
               f'циклов {m["cyclomatic"]}'
               + (f' — {hist[:70]}' if hist and not game else "") + '</text>')
    out.append("</svg>")
    return "".join(out)
