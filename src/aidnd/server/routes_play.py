"""Бэкенд пилота /play на НОВОМ стеке: citygraph (город+карта) + play.populate (жители с мозгами
mind) + LLM-озвучка (inference, офлайн-стаб). Процессная пилот-сессия (один мир, одна фигура игрока).

Карта РЕАЛЬНАЯ и полная: все улицы+дома+река+стены; ходим по ключевым точкам (перекрёсткам) с
пути-поиском (route). «Кто здесь» зависит от перекрёстка. Карточка NPC — отношение/эмоция ИЗ МОЗГА.
"""

from __future__ import annotations

import random

from fastapi import APIRouter, Request

from ..citygraph import CityParams, generate, visual
from ..citygraph.model import NodeKind
from ..mind import Body
from ..mind import World as MWorld
from ..mind import think
from ..play import populate
from ..play.population import KEY_ROLES

router = APIRouter(tags=["play"])
PLAYER = "pc"
_S: dict = {"city": None, "people": None, "crof": None, "cr2b": None, "loc": None,
            "geom": None, "model": None}

_COLORS = ["#c98a52", "#6f8f6a", "#8a6fae", "#a86a6a", "#5f8296", "#b0894a"]
_PLACE = {
    "трактирщик": ("Трактир «Пьяный вепрь»", "таверна · тепло, тесно, дымно", "трактир"),
    "кузнец": ("Кузница", "жар горна, звон молота", "кузница"),
    "лавочник": ("Лавка", "полки со всякой всячиной", "лавка"),
    "стражник": ("Караулка", "пост городской стражи", "стража"),
    "жрец": ("Святилище", "тихо, пахнет ладаном", "храм"),
    "знахарка": ("Дом знахарки", "пучки трав, склянки", "знахарка"),
    "бард": ("Помост", "здесь поют и судачат", "помост"),
    "мельник": ("Мельница", "мерный скрип у воды", "мельница"),
}
_TOPICS = {
    "трактирщик": ["слухи", "что налить", "заказ комнаты", "о дорогах"],
    "бард": ["спой что-нибудь", "новости с трактов", "кто тут кто"],
    "лавочник": ["что на продажу", "цена", "редкости"],
    "кузнец": ["почини снаряжение", "есть работа", "о железе"],
    "жрец": ["благословение", "о богах", "исцеление"],
    "знахарка": ["зелья", "травы", "о хворях"],
    "стражник": ["что тут за место", "есть розыск", "о законе"],
    "бродяга": ["чего пялишься", "есть работа?"],
    "головорез": ["чего надо", "проваливай"],
    "горожанин": ["как дела", "что нового", "о городе"],
}


def _model():
    if _S["model"] is None:
        from ..inference import ModelManager
        _S["model"] = ModelManager()
    return _S["model"]


def _play():
    if _S["city"] is None:
        params = CityParams(seed=1, key_buildings=8, river=True, walls=True, segment=16)
        city = generate(params)
        vis = visual(params, interactive=True)             # богатый визуал + кликабельные дома
        people = populate(city, seed=1, commoners=16, deviants=2)
        xy = {n.id: (n.x, n.y) for n in city.nodes()}
        door2cr = {h.node: h.crossroad for h in city.houses.values()}
        keycr = {bid: kb.crossroad for bid, kb in city.key_buildings.items()}
        kps = city.key_points()
        rng = random.Random("spot|1")
        crof = {}                                          # перекрёсток каждого жителя
        for pid, p in people.items():
            crof[pid] = keycr.get(p.work) or door2cr.get(p.home) or rng.choice(kps)
        cr2b = {}                                          # перекрёсток → ключевое здание (для названия)
        for bid, kb in city.key_buildings.items():
            cr2b.setdefault(kb.crossroad, bid)
        start = keycr.get(next((p.work for p in people.values()
                                if p.role == "трактирщик" and p.work in keycr), None)) or kps[0]
        _S.update(city=city, people=people, crof=crof, cr2b=cr2b, loc=start,
                  geom=_build_geom(city, xy, kps, cr2b, vis))
    return _S["city"], _S["people"], _S["crof"], _S["cr2b"], _S["loc"]


def _build_geom(city, xy, kps, cr2b, vis) -> dict:
    """Лёгкий интерактивный слой поверх богатого визуала: система координат — холст рендера 0 0 W H.
    Дома/улицы/река/стены рисует сам SVG (vis['inner']); клик по любому дому → его перекрёсток
    (h2cr). Метки ключевых зданий подписываем поверх; _xy — узел→xy для маршрута и фигуры игрока."""
    h2cr = {h.id: h.crossroad for h in city.houses.values()}
    keys = []
    for i, (bid, kb) in enumerate(sorted(city.key_buildings.items())):
        role = KEY_ROLES[i % len(KEY_ROLES)]
        keys.append({"cr": kb.crossroad, "x": round(kb.x, 1), "y": round(kb.y, 1),
                     "label": _PLACE.get(role, (None, None, "здание"))[2]})
    return {"viewBox": [0, 0, vis["W"], vis["H"]], "svg": vis["inner"],
            "h2cr": h2cr, "keys": keys,
            "_xy": {n: [round(xy[n][0], 1), round(xy[n][1], 1)] for n in xy}}


def _role_at(cr, people, crof, cr2b):
    bid = cr2b.get(cr)
    if not bid:
        return None
    return next((people[pid].role for pid, c in crof.items()
                 if c == cr and people[pid].work == bid), None)


def _here(cr, crof):
    return [pid for pid, c in crof.items() if c == cr]


def _emo(st) -> str:
    e = st.emotion
    dom = max(e, key=e.get)
    if e[dom] < 0.15:
        return "спокойное"
    return {"joy": "тёплое", "anger": "раздражённое", "fear": "настороженное",
            "distress": "подавленное"}.get(dom, "ровное")


def _scene_dict(city, people, crof, cr2b, loc):
    role = _role_at(loc, people, crof, cr2b)
    name, kind, _ = _PLACE.get(role, ("Перекрёсток", "городская развилка", "перекрёсток"))
    here = sorted(_here(loc, crof), key=lambda i: (people[i].work is None, i))
    return {
        "loc": loc,
        "location": {"name": name, "kind": kind,
                     "desc": ("Обычное место фронтирного городка — идёт своя жизнь." if role
                              else "Развилка городских улиц; мимо спешат прохожие.")},
        "ambient": {"time": "вечер", "weather": "дождь", "mood": "оживлённо" if len(here) > 2 else "тихо",
                    "event": "Народ занят своими делами." if here else "Пусто; лишь ветер гуляет меж домов."},
        "here": [{"id": pid, "name": people[pid].name, "role": people[pid].role,
                  "init": people[pid].name[0], "color": _COLORS[i % len(_COLORS)]}
                 for i, pid in enumerate(here)],
    }


def _mind_scene(npc_id, people) -> MWorld:
    p = people[npc_id]
    w = MWorld()
    w.link("зал", "улица")
    w.add(Body(id=npc_id, place="зал", charisma=p.charisma, appearance=p.appearance))
    w.add(Body(id=PLAYER, place="зал", charisma=0.4, appearance=0.3))
    return w


def _voice(p, rel, kind, player_text=None) -> str:
    mgr = _model()
    if not mgr.available():
        return (f"{p.name} окидывает тебя оценивающим взглядом." if kind == "greet"
                else f"{p.name} неопределённо пожимает плечами.")
    persona = (f"Ты — {p.name}, {p.role} на фронтире (тёмное фэнтези). Отвечай В ХАРАКТЕРЕ, живой "
               f"разговорной речью, 1-2 фразы, без ремарок-описаний. Твоя симпатия к собеседнику "
               f"{rel.get('affinity', 0):.2f} (низкая = суховато/настороже, высокая = тепло).")
    user = ("К тебе подошёл незнакомец и заговорил — брось первую реплику." if kind == "greet"
            else f"Он говорит: «{player_text}». Ответь.")
    resp = mgr.call("narrator", [{"role": "system", "content": persona},
                                 {"role": "user", "content": user}], options={"temperature": 0.85})
    return (resp.get("content") if resp else "").strip() or f"{p.name} молчит."


@router.get("/api/play/scene")
def scene():
    city, people, crof, cr2b, loc = _play()
    return _scene_dict(city, people, crof, cr2b, loc)


@router.get("/api/play/map")
def game_map():
    city, people, crof, cr2b, loc = _play()
    g = _S["geom"]
    pxy = g["_xy"].get(loc, [0, 0])
    return {"viewBox": g["viewBox"], "svg": g["svg"], "h2cr": g["h2cr"], "keys": g["keys"],
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
            NodeKind.CROSSROAD, NodeKind.GATE, NodeKind.BRIDGE):
        return {"error": "туда нельзя"}
    r = city.route(loc, to)
    path = [_S["geom"]["_xy"][n] for n in r.nodes if n in _S["geom"]["_xy"]] if r.found else [_S["geom"]["_xy"][to]]
    _S["loc"] = to
    sc = _scene_dict(city, people, crof, cr2b, to)
    return {**sc, "path": path, "moved": sc["location"]["name"]}


@router.post("/api/play/talk")
async def talk(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    st = p.state
    st.needs["social"] = max(st.needs.get("social", 0.0), 0.4)
    think(st, _mind_scene(npc, people), None)
    rel = st.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    return {"name": p.name, "role": p.role, "init": p.name[0], "color": "#8a6fae",
            "aff": round(rel.get("affinity", 0), 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": _emo(st),
            "topics": _TOPICS.get(p.role, _TOPICS["горожанин"]), "line": _voice(p, rel, "greet")}


@router.post("/api/play/say")
async def say(request: Request):
    _city, people, _crof, _cr2b, _loc = _play()
    b = await request.json()
    npc = b.get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    rel = p.state.relationships.setdefault(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    rel["affinity"] = min(1.0, rel["affinity"] + 0.04)
    line = _voice(p, rel, "reply", str(b.get("text", "")))
    return {"line": line, "aff": round(rel["affinity"], 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": _emo(p.state)}
