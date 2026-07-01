"""Бэкенд пилота /play на НОВОМ стеке: citygraph (город) + play.populate (жители с мозгами mind) +
LLM-озвучка диалога (inference, с офлайн-стабом). Процессная пилот-сессия (один мир).

Заглушки фронта заменяются реальными данными: «кто здесь» — настоящие сгенерированные жители;
карточка NPC — его отношение/эмоция ИЗ МОЗГА; реплики — озвучены LLM в характере (или стаб).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..citygraph import CityParams, generate
from ..mind import Body
from ..mind import World as MWorld
from ..mind import perceive, think
from ..play import populate

router = APIRouter(tags=["play"])
PLAYER = "pc"
_S: dict = {"city": None, "people": None, "here": None, "model": None}

_COLORS = ["#c98a52", "#6f8f6a", "#8a6fae", "#a86a6a", "#5f8296", "#b0894a"]
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
        people = populate(city, seed=1, commoners=10, deviants=2)
        here = []                                          # сцена пилота: народ «в трактире»
        for role in ("трактирщик", "бард", "бродяга", "знахарка"):
            m = next((p for p in people.values() if p.role == role), None)
            if m:
                here.append(m.id)
        for p in people.values():                          # добить горожанами до 4
            if len(here) >= 4:
                break
            if p.id not in here and p.role == "горожанин":
                here.append(p.id)
        _S.update(city=city, people=people, here=here)
    return _S["city"], _S["people"], _S["here"]


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


@router.get("/api/play/scene")
def scene():
    _city, people, here = _play()
    return {
        "location": {"name": "Трактир «Пьяный вепрь»", "kind": "таверна · тепло, тесно, дымно",
                     "desc": "Низкие балки, чад очага, гомон. У стойки наливают тёмный эль."},
        "ambient": {"time": "вечер", "weather": "дождь", "mood": "оживлённо",
                    "event": "У стойки спорят, безопасны ли нынче северные тракты."},
        "here": [{"id": pid, "name": people[pid].name, "role": people[pid].role,
                  "init": people[pid].name[0], "color": _COLORS[i % len(_COLORS)]}
                 for i, pid in enumerate(here)],
    }


@router.post("/api/play/talk")
async def talk(request: Request):
    _city, people, _here = _play()
    npc = (await request.json()).get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    st = p.state
    st.needs["social"] = max(st.needs.get("social", 0.0), 0.4)
    think(st, _mind_scene(npc, people), None)                # мозг «видит» игрока (обновит состояние)
    rel = st.relationships.get(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    return {"name": p.name, "role": p.role, "init": p.name[0], "color": "#8a6fae",
            "aff": round(rel.get("affinity", 0), 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": _emo(st),
            "topics": _TOPICS.get(p.role, _TOPICS["горожанин"]), "line": _voice(p, rel, "greet")}


@router.post("/api/play/say")
async def say(request: Request):
    _city, people, _here = _play()
    b = await request.json()
    npc = b.get("npc")
    if npc not in people:
        return {"error": "нет такого"}
    p = people[npc]
    rel = p.state.relationships.setdefault(PLAYER, {"affinity": 0.0, "trust": 0.0, "fear": 0.0})
    rel["affinity"] = min(1.0, rel["affinity"] + 0.04)       # разговор растит симпатию
    line = _voice(p, rel, "reply", str(b.get("text", "")))
    return {"line": line, "aff": round(rel["affinity"], 2), "trust": round(rel.get("trust", 0), 2),
            "fear": round(rel.get("fear", 0), 2), "emotion": _emo(p.state)}
