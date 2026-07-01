"""Бэкенд пилота /play на НОВОМ стеке: citygraph (город+карта) + play.populate (жители с мозгами
mind) + LLM-озвучка (inference, офлайн-стаб). Процессная пилот-сессия (один мир, одна фигура игрока).

Карта — РЕАЛЬНАЯ (граф citygraph): улицы + ключевые здания. Игрок ходит по зданиям, «кто здесь»
зависит от локации. Карточка NPC — отношение/эмоция ИЗ МОЗГА; реплики — LLM в характере.
"""

from __future__ import annotations

import random

from fastapi import APIRouter, Request

from ..citygraph import CityParams, generate
from ..mind import Body
from ..mind import World as MWorld
from ..mind import think
from ..play import populate

router = APIRouter(tags=["play"])
PLAYER = "pc"
_S: dict = {"city": None, "people": None, "locof": None, "loc": None, "model": None}

_COLORS = ["#c98a52", "#6f8f6a", "#8a6fae", "#a86a6a", "#5f8296", "#b0894a"]
# роль здания → (название места, тип, короткая метка на карте)
_PLACE = {
    "трактирщик": ("Трактир «Пьяный вепрь»", "таверна · тепло, тесно, дымно", "трактир"),
    "кузнец": ("Кузница", "жар горна, звон молота", "кузница"),
    "лавочник": ("Лавка", "полки со всякой всячиной", "лавка"),
    "стражник": ("Караулка", "пост городской стражи", "стража"),
    "жрец": ("Святилище", "тихо, пахнет ладаном", "храм"),
    "знахарка": ("Дом знахарки", "пучки трав, склянки", "знахарка"),
    "бард": ("Помост", "здесь поют и судачат", "помост"),
    "мельник": ("Мельница", "мерный скрип у воды", "мельница"),
    "дубильщик": ("Дубильня", "едкий дух кож", "дубильня"),
    "сапожник": ("Сапожная", "запах кожи и вара", "сапоги"),
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
        city = generate(CityParams(seed=1, key_buildings=8, river=True, walls=True))
        people = populate(city, seed=1, commoners=14, deviants=2)
        keys = sorted(city.key_buildings)
        rng = random.Random("loc|1")
        locof = {}
        for pid, p in people.items():                      # работник → своё здание; прочие → случайный «завсегдатай»
            locof[pid] = p.work if (p.work in city.key_buildings) else rng.choice(keys)
        start = next((p.work for p in people.values() if p.role == "трактирщик" and p.work in keys), keys[0])
        _S.update(city=city, people=people, locof=locof, loc=start)
    return _S["city"], _S["people"], _S["locof"], _S["loc"]


def _role_at(loc, people, locof):
    return next((people[pid].role for pid, l in locof.items()
                 if l == loc and people[pid].work == loc), None)


def _here(loc, people, locof):
    ids = [pid for pid, l in locof.items() if l == loc]
    ids.sort(key=lambda i: (people[i].work != loc, i))     # работник(и) впереди
    return ids


def _emo(st) -> str:
    e = st.emotion
    dom = max(e, key=e.get)
    if e[dom] < 0.15:
        return "спокойное"
    return {"joy": "тёплое", "anger": "раздражённое", "fear": "настороженное",
            "distress": "подавленное"}.get(dom, "ровное")


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


def _scene_dict(city, people, locof, loc):
    role = _role_at(loc, people, locof)
    name, kind, _ = _PLACE.get(role, ("Улица", "городская улица", "улица"))
    here = _here(loc, people, locof)
    return {
        "location": {"name": name, "kind": kind, "desc": _S.get("desc_" + str(loc)) or
                     "Обычное место фронтирного городка — здесь идёт своя жизнь."},
        "ambient": {"time": "вечер", "weather": "дождь", "mood": "оживлённо" if len(here) > 2 else "тихо",
                    "event": "Народ занят своими делами." if here else "Пусто; лишь ветер гуляет."},
        "here": [{"id": pid, "name": people[pid].name, "role": people[pid].role,
                  "init": people[pid].name[0], "color": _COLORS[i % len(_COLORS)]}
                 for i, pid in enumerate(here)],
    }


@router.get("/api/play/scene")
def scene():
    city, people, locof, loc = _play()
    return _scene_dict(city, people, locof, loc)


@router.get("/api/play/map")
def game_map():
    city, people, locof, loc = _play()
    xy = city._xy                                          # noqa: SLF001 — новый контур, дебаг-доступ
    xs = [p[0] for p in xy.values()]
    ys = [p[1] for p in xy.values()]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = max(6.0, (maxx - minx) * 0.06)
    seen, edges = set(), []
    for n, nbs in city._adj.items():                       # noqa: SLF001
        for m in nbs:
            k = (min(n, m), max(n, m))
            if k in seen or n not in xy or m not in xy:
                continue
            seen.add(k)
            edges.append([round(xy[n][0], 1), round(xy[n][1], 1), round(xy[m][0], 1), round(xy[m][1], 1)])
    keys = []
    for bid, kb in sorted(city.key_buildings.items()):
        node = kb.node if kb.node in xy else kb.interior
        if node not in xy:
            continue
        role = _role_at(bid, people, locof)
        keys.append({"id": bid, "label": _PLACE.get(role, (None, None, "здание"))[2],
                     "x": round(xy[node][0], 1), "y": round(xy[node][1], 1), "here": bid == loc})
    pn = next((kb.node if kb.node in xy else kb.interior)
              for b, kb in city.key_buildings.items() if b == loc)
    return {"viewBox": [round(minx - pad, 1), round(miny - pad, 1),
                        round(maxx - minx + 2 * pad, 1), round(maxy - miny + 2 * pad, 1)],
            "edges": edges, "keys": keys, "player": {"x": round(xy[pn][0], 1), "y": round(xy[pn][1], 1)}}


@router.post("/api/play/move")
async def move(request: Request):
    city, people, locof, _loc = _play()
    to = (await request.json()).get("to")
    if to not in city.key_buildings:
        return {"error": "туда нельзя"}
    _S["loc"] = to
    role = _role_at(to, people, locof)
    name = _PLACE.get(role, ("это место",))[0]
    return {**_scene_dict(city, people, locof, to), "moved": name}


@router.post("/api/play/talk")
async def talk(request: Request):
    _city, people, _locof, _loc = _play()
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
    _city, people, _locof, _loc = _play()
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
