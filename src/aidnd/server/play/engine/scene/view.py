"""Scene assembly — what the client renders each poll: place, fog, rooms, ambient, visible folk,
and the guild/board/watch extras. Also hosts the /api/play/scene HTTP endpoint.

Key functions
-------------
_scene_locinfo(city, loc, bid, inside, plaza) -> (name, kind) : Scene's display name + kind.
_scene_ambient(here, lvl) -> dict : Time/weather/mood/event ambient line.
_scene_folk(vis_here, people) -> list : Visible people → display cards.
_scene_extras(d, bid, loc, inside, plaza, people, crof) -> None : Guild/board/watch sections, in place.
_scene_rooms(inside, lvl) -> list : Building rooms, hidden ones gated by fog level.
_scene_dict(city, people, crof, cr2b, loc) -> dict : Full scene dict the client renders.
scene() : GET /api/play/scene — scene dict plus player vitals.
"""

from __future__ import annotations

from aidnd.citygraph.model import NodeKind
from aidnd.server.play.engine.core import (
    _COLORS,
    _PHASE_RU,
    _S,
    PB,
    _binfo,
    _city_name,
    _display,
    _emo,
    _fatigue,
    _gt,
    _here,
    _mana,
    _mana_cap,
    _mark_seen,
    _met,
    _pc_hp,
    _pc_name,
    _phase,
    _portrait_url,
    _role_at,
    _store,
    _wid,
    router,
)
from aidnd.server.play.engine.worldbuild.assembly import _play as _play
from aidnd.server.play.engine.worldbuild.building import (
    _building_containers,
    _building_rooms,
)
from aidnd.server.play.mechanics.combat import (
    _guild_bid,
    _guild_board,
    _guild_status,
    _mint_badge,
    _pc_badge,
)
from aidnd.server.play.mechanics.contracts import _board_ads
from aidnd.server.play.mechanics.items import _pc_coins

from .vision import _looked_level, _watch_check


def _scene_locinfo(city, loc, bid, inside, plaza):
    """Resolve the scene's display name + kind: inside a building, at its entrance, the town board
    on the plaza, a crossroad, or plain street. Returns (name, kind)."""
    if inside:
        info = _binfo(inside)
        return info["name"], info["kind"]
    if bid:
        return f"у входа: {_binfo(bid)['name']}", "снаружи"
    if plaza is not None and loc == plaza:
        return "Городская доска", "площадь · объявления горожан"
    if city.node_kind(loc) == NodeKind.CROSSROAD:
        return "Перекрёсток", "городская развилка"
    return "Улица", "мостовая меж домов"


def _scene_ambient(here, lvl):
    """Ambient line for the scene: time-of-day, weather, crowd mood, and a one-line event that
    depends on whether the player has looked around yet."""
    return {
        "time": _PHASE_RU[_phase()],
        "weather": "дождь",
        "mood": "оживлённо" if len(here) > 2 else "тихо",
        "event": ("Народ занят своими делами." if here
                  else "Пусто; лишь ветер гуляет меж домов."),
    }


def _scene_folk(vis_here, people):
    """Visible people in the scene → cards (id, display name, role, initial, colour, portrait).
    A stranger shows by descriptor until introduced."""
    return [
        {
            "id": pid,
            "name": _display(pid, people),  # stranger by descriptor, name after introduction
            "role": (
                people[pid].role if (pid in _met() or people[pid].work) else "кто-то из горожан"
            ),
            "init": _display(pid, people)[0].upper(),
            "color": _COLORS[i % len(_COLORS)],
            "portrait": _portrait_url(people[pid], _emo(people[pid].state)),
        }
        for i, pid in enumerate(vis_here)
    ]


def _scene_extras(d, bid, loc, inside, plaza, people, crof):
    """Append conditional scene sections in place: guild board/rank (minting a newcomer's badge),
    the citizens' notice board at the plaza post, and the watch when the player is highly wanted."""
    if bid and bid == _guild_bid():  # in the guild — board, rank, newcomer intake
        d.setdefault("narr", [])
        if not _pc_badge() and not _store().flag_get(_wid(), "guild_mark|pc"):
            _mint_badge(0)
            d["narr"].append("Тебя приняли в гильдию. Вот жетон приключенца (Медь).")
        d["guild_board"], d["guild_news"] = _guild_board(), (_S.get("guild_news") or [])
        d["guild_status"] = _guild_status()
    if plaza is not None and loc == plaza and not inside:  # at the post — citizens' notices
        d["board_ads"] = _board_ads()
        d["board_news"] = _S.get("board_news") or []
    wc = _watch_check(people, crof, loc)  # the watch, at a high wanted level
    if wc:
        d["watch"] = wc


def _scene_rooms(inside, lvl):
    """Rooms of the building the player is in; hidden ones show only on a keen look (lvl 2)."""
    if not inside:
        return []
    return [r for r in _building_rooms(inside) if not (r["access"] == "hidden" and lvl < 2)]


def _scene_dict(city, people, crof, cr2b, loc):
    """Assemble the full scene dict the client renders: place name/kind, fog level, rooms, the
    location block, ambient, the visible folk, and any guild/board/watch extras."""
    role = _role_at(loc, people, crof, cr2b)
    bid = cr2b.get(loc)
    inside = _S.get("inside")
    if inside and inside != bid:  # stepped away from the building → left it
        inside = _S["inside"] = None
        _S["room"] = None
    _mark_seen(bid)  # arrived — learned the place
    plaza = (_S.get("geom") or {}).get("plaza")
    name, kind = _scene_locinfo(city, loc, bid, inside, plaza)
    here = sorted(_here(loc, crof), key=lambda i: (people[i].work is None, i))
    lvl = _looked_level(loc, inside)
    more = 0  # no cap — the scene shows everyone present
    vis_here = here  # basic vision: who is in the room is ALWAYS visible; a keen look reveals HIDDEN things
    room = _S.get("room") if inside else None
    rooms = _scene_rooms(inside, lvl)
    if inside and room:
        name = f"{_binfo(inside)['name']} · {room}"
    d = {
        "loc": loc,
        "inside": inside,
        "room": room,
        "rooms": rooms,
        "enterable": ({"bid": bid, "name": _binfo(bid)["name"]} if (bid and not inside) else None),
        "looked": lvl,
        "here_more": more,
        "location": {
            "name": name,
            "kind": kind,
            "desc": (
                "Обычное место фронтирного городка — идёт своя жизнь."
                if role
                else "Мимо спешат редкие прохожие; в лужах дрожит свет окон."
            ),
            "containers": (_building_containers(inside, room) if (inside and lvl >= 1) else []),
        },
        "dungeon": ({"name": (_S.get("dungeon") or {}).get("d", {}).get("name"),
                     "room": (_S.get("dungeon") or {}).get("room")}
                    if _S.get("dungeon") else None),
        "ambient": _scene_ambient(here, lvl),
        "here": _scene_folk(vis_here, people),
    }
    _scene_extras(d, bid, loc, inside, plaza, people, crof)
    return d


@router.get("/api/play/scene")
def scene():
    city, people, crof, cr2b, loc = _play()
    out = {
        **_scene_dict(city, people, crof, cr2b, loc),
        "gt": _gt(),
        "coins": _pc_coins(),
        "hp": _pc_hp(),
        "max_hp": PB["pc_max_hp"],
        "city": _city_name(),
        "hero": _pc_name(),
        "mana": _mana(),
        "mana_cap": _mana_cap(),
        "fatigue": _fatigue(),
    }
    return out  # board/guild rank — from _scene_dict
