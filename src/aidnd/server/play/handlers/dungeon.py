"""Домен ПОДЗЕМЕЛЬЕ — обход данжа комната-за-комнатой (docs/dungeons.md, этап C).

Логово карты = настоящий данж (worldgen/dungeongen + бриф из пула). Состояние обхода в
_S["dungeon"]: позиция, туман (seen), зачищенные/обысканные комнаты, ключи, найденные
секретки. Информированный выбор двери (Hades): намёк по СОДЕРЖИМОМУ соседней комнаты —
рычание/блеск/сквозняк. Ловушки телеграфируют и бьют одноразово; клады лутаются обыском;
машины-виньетки будят стражей; ключи открывают замки с lock_flavor брифа; блуждающие —
давление времени (1-к-6 каждые 2 перехода). Бой комнаты — существующий Encounter, арена
из ФОРМЫ комнаты. Босс — контур логова (гильдия/cleared/трофеи) без изменений.
"""

from __future__ import annotations

import random

from fastapi import Request

from aidnd.combat import Encounter
from aidnd.combat.encounters import pick_encounter
from aidnd.server.play.engine.core import (
    _PC_CAP,
    _S,
    PB,
    _gt,
    _gt_add,
    _mt,
    _pc_hp,
    _pc_remember,
    _pool,
    _store,
    _wid,
    router,
)
from aidnd.server.play.mechanics.combat import _pc_combatant
from aidnd.server.play.mechanics.items import _pool_add_new, _pool_draw, _rar_tag
from aidnd.worldgen.dungeongen import dungeon_svg, generate


def _inc_active() -> list:
    from aidnd.server.play.engine.incidents import incidents_active
    return incidents_active()

_HINTS = {"monster": "из-за прохода — возня и рык", "trap": "",
          "special": "оттуда тянет странным отсветом", "treasure": "в темноте что-то блестит",
          "empty": "тихо, тянет сквозняком"}


def _dng() -> dict | None:
    return _S.get("dungeon")


def build_dungeon(l: dict) -> dict:
    """Данж логова: скелет+наполнение по сиду мира, бриф из пула по среде (LLM в рантайме нет)."""
    briefs = [r["data"] for r in _pool().pool_buildings("dungeon") if r["btype"] == l["env"]]
    brief = random.Random(f"dbrief|{_wid()}|{l['id']}").choice(briefs) if briefs else None
    return generate(f"dng|{_wid()}|{l['id']}", l["env"], cr=l["cr"], brief=brief)


def incident_delve(inc: dict) -> dict:
    """Вход в ГОРОДСКОЕ происшествие: маленький данж; шайка = РЕАЛЬНЫЕ горожане по комнатам
    (глава — в комнате цели), пленник — в кладовой; резолв цели закрывает происшествие."""
    people = _S.get("people") or {}
    briefs = [r["data"] for r in _pool().pool_buildings("dungeon")
              if r["btype"] == inc["env"]]
    brief = (random.Random(f"ibrief|{_wid()}|{inc['id']}").choice(briefs)
             if briefs else None)
    d = generate(f"inc|{_wid()}|{inc['id']}", inc["env"], cr=inc["cr"], brief=brief,
                 small=True)
    d["name"] = inc["title"]
    st = {"lair": {"id": inc["id"], "name": inc["title"], "cr": inc["cr"],
                   "env": inc["env"]},
          "d": d, "room": d["entrance"], "seen": {d["entrance"]}, "cleared": set(),
          "looted": set(), "keys": set(), "found": set(), "sprung": set(), "steps": 0,
          "inc": inc["id"], "is_lair": False, "npc_at": {}, "captive_at": None}
    dead = {k.split("|", 1)[1] for k in _store().flags_prefix(_wid(), "dead|")}
    members = [m for m in (inc.get("members") or []) if m in people and m not in dead]
    if members:                                       # горожане-разбойники по комнатам
        chief = inc.get("chief") if inc.get("chief") in members else members[0]
        st["npc_at"][d["goal"]] = [chief]
        rest = [m for m in members if m != chief]
        mob_rooms = [r["id"] for r in d["rooms"]
                     if (r.get("content") or {}).get("kind") == "monster"
                     and r["kind"] == "room"]
        for m, rid in zip(rest, mob_rooms):
            st["npc_at"][rid] = st["npc_at"].get(rid, []) + [m]
        for r in d["rooms"]:                          # прочих тварей из дома выметаем
            c = r.get("content") or {}
            if c.get("kind") == "monster" and r["id"] not in st["npc_at"]:
                r["content"] = {"kind": "empty"}
    if inc.get("captive"):                            # пленник — в кладовой/схроне
        spot = next((r["id"] for r in d["rooms"]
                     if "treasure" in r["tags"] or r.get("frole") == "склад"), d["goal"])
        st["captive_at"] = spot
    _S["dungeon"] = st
    _gt_add(PB["lair_travel_min"])
    narr = [f"{inc['title']}: {inc['pitch']}",
            (d["rooms"][d["entrance"]].get("desc") or "").strip()]
    _pc_remember(f"взялся: {inc['title']}", 0.5)
    return {**dungeon_payload(), "narr": [n for n in narr if n], "gt": _gt()}


def delve_enter(l: dict) -> dict:
    """Вход в логово: строим данж, ставим игрока на лестницу входа."""
    d = build_dungeon(l)
    _S["dungeon"] = {"lair": l, "d": d, "room": d["entrance"], "seen": {d["entrance"]},
                     "cleared": set(), "looted": set(), "keys": set(), "found": set(),
                     "sprung": set(), "steps": 0, "is_lair": True, "npc_at": {},
                     "captive_at": None}
    _gt_add(PB["lair_travel_min"])
    r0 = d["rooms"][d["entrance"]]
    narr = [f"{d.get('name', l['name'])}: вниз уводят стёртые ступени. "
            f"{(d.get('history') or {}).get('now', '')}".strip()]
    if r0.get("desc"):
        narr.append(r0["desc"])
    _pc_remember(f"спустился: {d.get('name', l['name'])}", 0.5)
    return {**dungeon_payload(), "narr": narr, "gt": _gt()}


def _exits(st: dict) -> list:
    d, cur = st["d"], st["room"]
    out = []
    for eid, e in enumerate(d["edges"]):
        if e["kind"] == "window" or cur not in (e["a"], e["b"]):
            continue
        if e["kind"] == "secret" and eid not in st["found"]:
            continue                                  # секретка невидима, пока не найдена
        other = e["b"] if e["a"] == cur else e["a"]
        ro = d["rooms"][other]
        locked = bool(e["kind"] == "locked" and e["lock"] not in st["keys"])
        known = other in st["seen"]
        hint = "" if known else _HINTS.get((ro.get("content") or {}).get("kind", ""), "")
        if not known and (ro.get("content") or {}).get("boss"):
            hint = "оттуда веет силой — логово хозяина"
        out.append({"room": other, "eid": eid, "kind": e["kind"], "locked": locked,
                    "known": known, "name": ro.get("name") if known else None, "hint": hint})
    return out


def dungeon_payload(narr: list | None = None) -> dict:
    st = _dng()
    d = st["d"]
    cur = d["rooms"][st["room"]]
    nxt = {x["room"] for x in _exits(st) if not x["locked"]}
    svg = dungeon_svg(d, game={"seen": st["seen"], "cur": st["room"], "next": nxt,
                               "cleared": st["cleared"]})
    return {"dungeon": {"name": d.get("name"), "svg": svg, "room": st["room"],
                        "room_name": cur.get("name"), "exits": _exits(st),
                        "cleared": d["metrics"]["rooms"] and st["lair"]["id"] in
                        {k.split("|", 1)[1] for k in _store().flags_prefix(_wid(), "cleared|")}},
            "narr": narr or [], "gt": _gt(), "hp": _pc_hp()}


def _room_obstacles(r: dict) -> set:
    """Форма комнаты → арена 12×9: тайлы масштабируются, вне пола — стены; тесно — зал."""
    tiles = {tuple(t) for t in r["tiles"]}
    xs = [t[0] for t in tiles]
    ys = [t[1] for t in tiles]
    w = max(xs) - min(xs) + 1
    h = max(ys) - min(ys) + 1
    obs = set()
    for gx in range(12):
        for gy in range(9):
            tx = min(xs) + int(gx * w / 12)
            ty = min(ys) + int(gy * h / 9)
            if (tx, ty) not in tiles:
                obs.add((gx, gy))
    return obs if 12 * 9 - len(obs) >= 25 else set()  # совсем тесно — честный зал


def _room_fight(rid: int, units, head_sub: str, boss: bool) -> dict:
    st = _dng()
    r = st["d"]["rooms"][rid]
    enc = Encounter([_pc_combatant()], units, seed=f"dfight|{st['d']['seed']}|{rid}|{_mt()}",
                    obstacles=_room_obstacles(r))
    cb = {"enc": enc, "droom": rid,
          "head": {"name": r.get("name") or f"Комната {rid + 1}", "sub": head_sub}}
    if boss:
        cb["lair"] = st["lair"]                       # босс = контур логова (гильдия/cleared)
    _S["combat"] = cb
    guard = 0
    while enc.status() == "active" and guard < 50:    # докрутить ИИ до хода игрока
        c0 = enc.current()
        if c0 is None or c0.id == "pc":
            break
        enc.ai_turn(c0)
        guard += 1
    pc_u = enc.units.get("pc")
    if pc_u:
        _pc_hp(set_to=max(0, pc_u.hp))
    return {"combat": enc.view(), "gt": _gt(), "hp": _pc_hp()}


def _spring_trap(rid: int, t: dict) -> tuple:
    """Ловушка бьёт одноразово: спас-бросок, урон кубиками из данных."""
    st = _dng()
    st["sprung"].add(rid)
    n = random.Random(f"trap|{st['d']['seed']}|{rid}")
    roll = n.randint(1, 20)
    mod = _PC_CAP.mod(t.get("save", "dex"))
    num, _, die = t.get("dmg", "1d4").partition("d")
    dmg = sum(n.randint(1, int(die or 4)) for _ in range(int(num or 1))) if die else 0
    dice = {"roll": roll, "mod": mod, "dc": t["dc"], "label": f"Спас ({t.get('save', 'dex')})"}
    if roll + mod >= t["dc"]:
        return [f"{t['name']}: {t['effect']} — но ты успеваешь отпрянуть "
                f"({roll}+{mod} против {t['dc']})."], dice
    _pc_hp(delta=-max(1, dmg))
    return [f"{t['name']}: {t['effect']}! {dmg} урона "
            f"({roll}+{mod} против {t['dc']}). Телеграф был: {t['telegraph']}."], dice


@router.post("/api/play/dungeon_move")
async def dungeon_move(request: Request):
    st = _dng()
    if not st:
        return {"error": "ты не в подземелье"}
    if _S.get("combat"):
        return {"error": "сначала закончи бой"}
    to = int((await request.json()).get("room", -1))
    ex = next((x for x in _exits(st) if x["room"] == to), None)
    if ex is None:
        return {"error": "туда отсюда не пройти"}
    if ex["locked"]:
        return {"narr": [f"Заперто. {st['d'].get('lock_flavor') or 'Нужен ключ.'}"],
                "gt": _gt()}
    _gt_add(PB["dungeon_step_min"])
    st["room"] = to
    first = to not in st["seen"]
    st["seen"].add(to)
    st["steps"] += 1
    r = st["d"]["rooms"][to]
    c = r.get("content") or {}
    narr = []
    if first and r.get("name"):
        narr.append(f"{r['name']}." + (f" {r.get('desc', '')}" if r.get("desc") else ""))
    if c.get("kind") == "trap" and to not in st["sprung"]:
        if c["trap"].get("telegraph") and first:
            narr.append(f"Глаз цепляет: {c['trap']['telegraph']}.")
        lines, dice = _spring_trap(to, c["trap"])
        narr += lines
        if _pc_hp() <= 0:
            from aidnd.server.play.mechanics.combat import _death
            return {**_death(f"Ловушка в {st['d'].get('name', 'подземелье')} стала последней."),
                    "narr": narr}
        return {**dungeon_payload(narr), "dice": dice}
    if c.get("kind") == "empty" and c.get("flavor") and first:
        narr.append(f"{c['flavor']['name']}: {c['flavor']['note']}.")
    if c.get("kind") == "special" and first:
        narr.append(f"{c['machine']['name']}: {c['machine']['note']}.")
    if to == st.get("captive_at") and first:
        people = _S.get("people") or {}
        inc = next((x for x in _inc_active() if x["id"] == st.get("inc")), {})
        nm = inc.get("captive_name") or "пленник"
        narr.append(f"В углу, связанный — {nm}. Живой. Глаза кричат: доведи дело до конца.")
    if to in (st.get("npc_at") or {}) and to not in st["cleared"]:
        people = _S.get("people") or {}
        from aidnd.server.play.mechanics.combat import _combatant_from_npc

        pids = [p_ for p_ in st["npc_at"][to] if p_ in people]
        units = [_combatant_from_npc(p_, people[p_]) for p_ in pids]
        for u in units:
            u.side = "foes"
        if units:
            names = ", ".join(people[p_].name for p_ in pids)
            narr.append(f"Здесь СВОИ — {names}. Узнав тебя, хватаются за оружие: "
                        f"свидетели им не нужны.")
            st.setdefault("fall_pending", {})[to] = pids
            return {**_room_fight(to, units, st["d"].get("name", ""),
                                  bool(to == st["d"]["goal"] and st.get("is_lair", True))),
                    "narr": narr}
    if c.get("kind") == "monster" and to not in st["cleared"] \
            and to not in (st.get("npc_at") or {}):
        seed = (f"boss|{st['d']['seed']}" if c.get("boss")
                else f"mob|{st['d']['seed']}|{to}")
        cr = st["lair"]["cr"] * (1.0 if c.get("boss") else 0.35)
        units = pick_encounter(max(0.2, cr), st["d"]["env"], seed=seed)
        if units:
            narr.append("Хозяева комнаты поднимаются навстречу!" if not c.get("boss")
                        else f"{st['d'].get('chief') or 'Хозяин логова'} здесь.")
            return {**_room_fight(to, units, st["d"].get("name", ""),
                                  bool(c.get("boss")) and st.get("is_lair", True)),
                    "narr": narr}
        st["cleared"].add(to)
    # блуждающие: цена времени (1-к-6 каждые 2 перехода)
    if st["steps"] % PB["dungeon_wander_n"] == 0 and not _S.get("combat"):
        if random.Random(f"wander|{st['d']['seed']}|{st['steps']}").random() < 1 / 6:
            units = pick_encounter(max(0.2, st["lair"]["cr"] * 0.25), st["d"]["env"],
                                   seed=f"wander|{st['d']['seed']}|{st['steps']}")
            if units:
                narr.append("Из темноты коридора на шум выходят обитатели.")
                return {**_room_fight(to, units, "блуждающие", False), "narr": narr}
    return dungeon_payload(narr)


@router.post("/api/play/dungeon_loot")
async def dungeon_loot(request: Request):
    """Обыск комнаты: клад (по сокрытию), ключ, машины-виньетки (риск!), поиск секреток."""
    st = _dng()
    if not st:
        return {"error": "ты не в подземелье"}
    if _S.get("combat"):
        return {"error": "сначала закончи бой"}
    rid = st["room"]
    r = st["d"]["rooms"][rid]
    c = r.get("content") or {}
    if c.get("kind") == "monster" and rid not in st["cleared"]:
        return {"error": "тут ещё хозяева — не до обыска"}
    _gt_add(PB["dungeon_loot_min"])
    narr, dice = [], None
    if rid not in st["looted"]:
        st["looted"].add(rid)
        m = c.get("machine")
        if m and m.get("risk") == "monsters":
            units = pick_encounter(max(0.2, st["lair"]["cr"] * 0.4), st["d"]["env"],
                                   seed=f"mach|{st['d']['seed']}|{rid}")
            if units and rid not in st["cleared"]:
                narr.append(f"{m['name']}: потревожил — и {m['note'].split('—')[0].strip()} "
                            f"оборачивается бедой!")
                return {**_room_fight(rid, units, m["name"], False), "narr": narr}
        t = c.get("treasure")
        if t:
            coins = t["worth"]
            total = _store().purse_add(_wid(), "pc", coins)
            narr.append(f"Клад ({t['concealment']}, {t['container']}): "
                        f"+{coins} зм (кошель: {total}).")
            if random.Random(f"dloot|{st['d']['seed']}|{rid}").random() < 0.4:
                it = _pool_draw(f"dloot|{st['d']['seed']}|{rid}", holder="pc")
                if it:
                    narr.append(f"И ещё — «{it['name']}»{_rar_tag(it)}.")
                    _pool_add_new(it)
        elif m:
            narr.append(f"{m['name']}: {m['note']}.")
        else:
            narr.append("Ничего ценного — пыль да тени.")
        for k in st["d"]["keys"]:                     # ключ лежит здесь — забираем
            if k["room"] == rid and k["id"] not in st["keys"]:
                st["keys"].add(k["id"])
                narr.append(f"Находишь ключ. {st['d'].get('lock_flavor') or ''}".strip())
    else:
        narr.append("Здесь ты уже всё перетряс.")
    # поиск секреток из этой комнаты — бросок восприятия
    hidden = [eid for eid, e in enumerate(st["d"]["edges"])
              if e["kind"] == "secret" and rid in (e["a"], e["b"])
              and eid not in st["found"]]
    if hidden:
        n = int(_store().flag_get(_wid(), f"dsearch|{rid}") or 0) + 1
        _store().flag_set(_wid(), f"dsearch|{rid}", str(n))
        roll = random.Random(f"dsecret|{st['d']['seed']}|{rid}|{n}").randint(1, 20)
        mod = _PC_CAP.mod("wis")
        dice = {"roll": roll, "mod": mod, "dc": 13, "label": "Восприятие"}
        if roll + mod >= 13:
            st["found"].add(hidden[0])
            narr.append("За кладкой — пустота: потайной ход!")
        else:
            narr.append("Стены как стены… но что-то тут нечисто.")
    out = dungeon_payload(narr)
    if dice:
        out["dice"] = dice
    return out


@router.post("/api/play/dungeon_exit")
async def dungeon_exit(request: Request):
    st = _dng()
    if not st:
        return {"error": "ты не в подземелье"}
    if _S.get("combat"):
        return {"error": "сначала закончи бой"}
    _gt_add(PB["lair_travel_min"])
    name = st["d"].get("name", "подземелье")
    _S["dungeon"] = None
    _pc_remember(f"выбрался из: {name}", 0.4)
    return {"narr": [f"Ты выбираешься из «{name}» на свет."], "gt": _gt(),
            "dungeon": None, "refresh": True}


@router.get("/api/play/dungeon")
async def dungeon_state(request: Request):
    st = _dng()
    if not st:
        return {"dungeon": None}
    return dungeon_payload()
