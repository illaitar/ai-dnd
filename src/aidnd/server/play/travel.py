"""Домен ПОХОД (/map /move /enter /exit /room /sign_ack /live) — распил world.py. Позвоночник: граф-путь, прерывания."""

from __future__ import annotations

import random

from fastapi import Request

from ...citygraph.model import NodeKind
from .contracts import _contract_on_move
from .core import (
    _PC_CAP,
    _S,
    PB,
    PLAYER,
    _binfo,
    _city_name,
    _gt,
    _gt_add,
    _here,
    _mark_seen,
    _mt,
    _pc_hp,
    _pc_remember,
    _seen,
    _store,
    _tokens_ru,
    _wid,
    router,
)
from .items import _pc_coins
from .world import _apply_routine, _building_rooms, _play, _scene_dict, _world_tick


def _path_interrupt(route_nodes, cr2b, crof, people, to):
    """Первая помеха на пути (кроме старта и цели): вывеска НЕЗНАКОМОГО ключевого здания
    или естественное событие (NPC с высокой эмоцией/агендой). None — путь чист."""
    for n in route_nodes[1:]:
        if n == to:
            break
        bid = cr2b.get(n)
        if bid and bid.startswith("key:") and bid not in _seen() \
                and not _store().flag_get(_wid(), f"signskip|{bid}"):
            return {"stop": n, "kind": "sign", "bid": bid, "name": _binfo(bid)["name"]}
        hot = next((people[pid] for pid in _here(n, crof)
                    if max(people[pid].state.emotion.get("anger", 0),
                           people[pid].state.emotion.get("fear", 0)) >= PB["path_event_dc"]), None)
        if hot:
            return {"stop": n, "kind": "event",
                    "text": f"На полпути — {hot.name}: что-то стряслось, стоит вмешаться или пройти мимо."}
    return None

@router.get("/api/play/map")
def game_map():
    city, people, crof, cr2b, loc = _play()
    g = _S["geom"]
    pxy = g["_xy"].get(loc, [0, 0])
    return {"viewBox": g["viewBox"], "svg": g["svg"], "h2n": g["h2n"],
            "points": g["points"],
            "keys": [k for k in g["keys"]                            # туман: известные + доска (столб виден)
                     if k["bid"] in _seen() or k["bid"] == "board:plaza"],
            "loc": loc, "player": {"x": pxy[0], "y": pxy[1]}}

@router.post("/api/play/move")
async def move(request: Request):
    city, people, crof, cr2b, loc = _play()
    to = (await request.json()).get("to")
    try:
        to = int(to)
    except (TypeError, ValueError):
        return {"error": "туда нельзя"}
    if to not in _S["geom"]["_xy"] or city.node_kind(to) not in (
            NodeKind.CROSSROAD, NodeKind.POINT, NodeKind.GATE, NodeKind.BRIDGE):
        return {"error": "туда нельзя"}
    xy = _S["geom"]["_xy"]
    r = city.route(loc, to)
    route_nodes = list(r.nodes) if r.found else [loc, to]
    stop = _path_interrupt(route_nodes, cr2b, crof, people, to)
    dest = stop["stop"] if stop else to                    # путь прерывается на помехе
    seg = route_nodes[:route_nodes.index(dest) + 1] if dest in route_nodes else [dest]
    path = [xy[n] for n in seg if n in xy]
    _S["loc"] = dest
    _S["dlg"] = None                                       # ушёл — разговор оборвался
    _gt_add(PB["step_min"] * max(1, len(seg) - 1))         # время дороги: минут за пройденный шаг
    _apply_routine()                                       # за дорогу мир мог перейти в другую фазу
    ct_done = _contract_on_move(dest)                      # visit-уговор: дошёл — исполнил
    sc = _scene_dict(city, people, crof, cr2b, dest)
    t = _world_tick()                                      # мир получает ход (пошаговость)
    extra = {}
    if stop:
        extra["stopped"] = stop["kind"]
        extra["remaining"] = to
        if stop["kind"] == "sign":
            extra["sign"] = {"bid": stop["bid"], "name": stop["name"]}
        else:
            extra["event"] = stop["text"]
    return {**sc, **t, "path": path, "moved": sc["location"]["name"], "gt": _gt(),
            "contract_done": ct_done, "coins": _pc_coins(), **extra}

@router.post("/api/play/sign_ack")
async def sign_ack(request: Request):
    """Реакция на вывеску: записать здание на карту (record) или пройти мимо (signskip)."""
    _play()
    b = await request.json()
    bid, record = b.get("bid"), bool(b.get("record"))
    if record:
        _mark_seen(bid)
    else:
        _store().flag_set(_wid(), f"signskip|{bid}")       # больше не прерывать этой вывеской
    return {"ok": True}

@router.post("/api/play/enter")
async def enter(request: Request):
    """Войти в здание у которого стоишь. Внутри — своё «осмотреться», карта блокируется."""
    city, people, crof, cr2b, loc = _play()
    bid = cr2b.get(loc)
    if not bid:
        return {"error": "тут не во что входить"}
    _S["inside"] = bid
    _S["room"] = None
    _S["dlg"] = None                                       # вошёл внутрь — уличный разговор оборвался
    _gt_add(PB["give_min"])
    _pc_remember(f"вошёл в {_binfo(bid)['name']}", 0.25)
    t = _world_tick()
    return {**_scene_dict(city, people, crof, cr2b, loc), **t, "gt": _gt(), "coins": _pc_coins(),
            "hp": _pc_hp(), "city": _city_name()}

@router.post("/api/play/room")
async def go_room(request: Request):
    """Перейти в суб-помещение здания (или в зал, room=null). Гейты: public — свободно;
    staff — по доверию работника ИЛИ скрытности; locked — по ключу; hidden — уже раскрыто."""
    city, people, crof, cr2b, loc = _play()
    inside = _S.get("inside")
    if not inside:
        return {"error": "ты не внутри здания"}
    want = (await request.json()).get("room")
    out = {"narr": []}
    if not want:                                           # вернуться в общий зал
        _S["room"] = None
    else:
        room = next((r for r in _building_rooms(inside) if r["name"] == want), None)
        if not room:
            return {"error": "такого помещения тут нет"}
        acc = room["access"]
        if acc in ("staff",):                              # служебное — доверие работника или скрытно
            worker = next((people[pid] for pid in _here(loc, crof) if people[pid].work == inside), None)
            trust = worker.state.rel(PLAYER)["trust"] if worker else 0.0
            if trust < 0.3:
                roll = random.Random(f"sneakroom|{inside}|{want}|{_mt()}").randint(1, 20)
                total = roll + _PC_CAP.mod("dex")
                dc = PB["steal_dc_base"]
                out["dice"] = {"die": 20, "roll": roll, "mod": _PC_CAP.mod("dex"), "total": total,
                               "dc": dc, "ok": total >= dc, "label": "Скрытность (Dex) — пройти незаметно"}
                if total < dc:
                    out["narr"].append(f"«{want}» — не для чужих. На тебя косятся, пришлось отступить.")
                    return {**out, **_scene_dict(city, people, crof, cr2b, loc), "gt": _gt()}
        elif acc == "locked":                              # заперто — нужен ключ ЭТОГО здания
            bd = _store().get_building(_wid(), inside) or {}
            local = _tokens_ru(_binfo(inside)["name"]) | _tokens_ru(want)
            for cnt in (bd.get("data", {}).get("containers") or []):
                local |= _tokens_ru(cnt.get("name", ""))   # ключи хозяина ходят по его ёмкостям
            has_key = any(
                it and it["kind"] == "key" and any(
                    m["target"] == "special:opens" and (_tokens_ru(m.get("cond", "")) & local)
                    for m in it.get("mods", []))
                for it in (_store().get_item(r["item_id"])
                           for r in _store().inventory(_wid(), "pc")))
            if not has_key:
                out["narr"].append(f"«{want}» заперто — нужен ключ здешнего хозяина.")
                return {**out, **_scene_dict(city, people, crof, cr2b, loc), "gt": _gt()}
        _S["room"] = want
        out["narr"].append(f"Ты проходишь в: {want}.")
    _S["dlg"] = None                                       # перешёл в другое помещение — беседа прервана
    _gt_add(PB["give_min"])
    return {**out, **_scene_dict(city, people, crof, cr2b, loc), "gt": _gt(), "coins": _pc_coins(),
            "hp": _pc_hp()}

@router.post("/api/play/exit")
async def exit_building(request: Request):
    city, people, crof, cr2b, loc = _play()
    _S["inside"] = None
    _S["dlg"] = None                                       # вышел — разговор в зале оборвался
    _gt_add(PB["give_min"])
    t = _world_tick()
    return {**_scene_dict(city, people, crof, cr2b, loc), **t, "gt": _gt(), "coins": _pc_coins(),
            "hp": _pc_hp(), "city": _city_name()}

@router.post("/api/play/live")
async def live(request: Request):
    """Кнопка «ждать»: потратить время и дать миру ход. (Поллинга больше нет — мир пошаговый.)"""
    _play()
    t = _world_tick()
    return {**t, "gt": _gt(), "coins": _pc_coins(), "hp": _pc_hp()}
