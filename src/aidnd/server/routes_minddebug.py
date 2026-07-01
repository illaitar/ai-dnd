"""Интерактивный стенд разума ОДНОГО NPC: выбор архетипа + ручная настройка черт/нужд/эмоций,
ввод ситуации (текстом → LLM разбирает в сцену, либо пресеты/сущности вручную) и ПОЛНЫЙ ГРАФ решения
(восприятие → цели → utility по примитивам → выбор). Доступ только владельцу.

Всё считает механическое ядро aidnd.mind (score/propose_goals); LLM — только чтобы разобрать
свободный текст ситуации в структурированную сцену.
"""

from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..mind import (
    EMOTIONS,
    NEEDS,
    TRAITS,
    Body,
    Goal,
    Item,
    NpcConfig,
    NpcState,
    World,
    perceive,
    think,
)
from .routes_citydebug import Owner

router = APIRouter(tags=["minddebug"])
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_MODEL = None

# 15 архетипов (черты + сила + видимое богатство) — как в scripts/archetypes.py
ARCHETYPES = {
    "Крестьянин": ({}, 1, .2),
    "Стражник": ({"lawful": .9, "loyalty": .85, "bravery": .8, "honesty": .8, "malice": .05}, 3, .3),
    "Карманник": ({"greed": .85, "honesty": .1, "lawful": .15, "bravery": .35}, 1, .2),
    "Головорез": ({"greed": .7, "bravery": .8, "pride": .8, "honesty": .25, "lawful": .3, "malice": .35}, 4, .3),
    "Убийца": ({"malice": .9, "greed": .5, "bravery": .85, "honesty": .1, "lawful": .05, "irritability": .2}, 3, .3),
    "Трус": ({"bravery": .1, "honesty": .5, "loyalty": .3}, 1, .2),
    "Верный": ({"loyalty": .95, "bravery": .7, "honesty": .8}, 2, .3),
    "Купец": ({"greed": .85, "honesty": .55, "sociability": .6, "lawful": .6}, 1, .55),
    "Гуляка": ({"sociability": .8, "bravery": .3, "irritability": .5, "curiosity": .5}, 1, .3),
    "Фанатик": ({"lawful": .95, "loyalty": .8, "pride": .7, "bravery": .7, "malice": .2}, 3, .3),
    "Интриган": ({"ambition": .9, "greed": .6, "honesty": .3, "lawful": .3, "sociability": .7, "pride": .8}, 2, .4),
    "Вспыльчивый": ({"irritability": .95, "bravery": .85, "pride": .8, "malice": .4}, 3, .3),
    "Добряк": ({"honesty": .9, "loyalty": .7, "malice": .0, "sociability": .7, "greed": .2}, 1, .3),
    "Отшельник": ({"sociability": .1, "curiosity": .6, "bravery": .5}, 1, .2),
    "Наёмник": ({"bravery": .8, "greed": .65, "honesty": .5, "loyalty": .4, "lawful": .4}, 3, .35),
}


def _model():
    global _MODEL
    if _MODEL is None:
        from ..inference import ModelManager
        _MODEL = ModelManager()
    return _MODEL


def _item(d: dict) -> Item:
    return Item(str(d.get("name", "вещь")), float(d.get("value", .3)),
                satisfies=d.get("satisfies") or None, kind=d.get("kind", "good"),
                amount=float(d.get("amount", 1.0)))


def _build(b: dict):
    """Собрать NPC + мир из запроса {traits, needs, emotion, self, scene}."""
    cfg = NpcConfig(id="я", name=b.get("name", "NPC"),
                    traits={**dict.fromkeys(TRAITS, 0.5), **(b.get("traits") or {})})
    st = NpcState.from_config(cfg)
    for k, v in (b.get("needs") or {}).items():
        st.needs[k] = float(v)
    for k, v in (b.get("emotion") or {}).items():
        st.emotion[k] = float(v)

    sc = b.get("scene") or {}
    self_ = b.get("self") or {}
    w = World()
    here = "тут"
    exits = sc.get("exits") or []
    for e in exits:
        w.link(here, e)
    near_place = None
    if sc.get("nearby"):
        near_place = "рядом"
        w.link(here, near_place)
    w.add(Body(id="я", place=here, power=float(self_.get("power", 1)),
               appearance=float(self_.get("appearance", .2)),
               carrying=[_item(i) for i in (self_.get("carrying") or [])]))

    def add(e, place):
        w.add(Body(id=e["id"], place=place, power=float(e.get("power", 1)),
                   appearance=float(e.get("appearance", .2)), attention=float(e.get("attention", .7)),
                   faction=e.get("faction", "town"), attacking=e.get("attacking") or None,
                   loot=[_item(i) for i in (e.get("loot") or [])]))
        if e.get("ally"):
            st.relationships[e["id"]] = {"trust": .5, "affinity": .8, "fear": 0.0}
        if e.get("fear"):
            st.relationships.setdefault(e["id"], {"trust": 0, "affinity": 0, "fear": 0})["fear"] = float(e["fear"])

    for e in sc.get("here") or []:
        add(e, here)
    for e in sc.get("nearby") or []:
        add(e, near_place)
    w.ground[here] = [_item(i) for i in (sc.get("items") or [])]
    if sc.get("needs_sources"):
        st.needs_sources = {n: {"source": here} for n in sc["needs_sources"]}
    st.extra_goals = [Goal(g["kind"], g.get("target"), float(g.get("value", .5)), g.get("meta") or {})
                      for g in (sc.get("extra_goals") or [])]
    return st, w, here


def _decide(b: dict) -> dict:
    st, w, here = _build(b)
    p = perceive(st, w)
    brain = think(st, w, p, modulate=bool(b.get("modulate", True)))     # граф-мозг: трасса+модуляторы
    brain["perceived"] = {
        "here": [{"id": bd.id, "power": bd.power, "appearance": round(bd.appearance, 2),
                  "attention": round(bd.attention, 2), "faction": bd.faction,
                  "attacking": bd.attacking, "loot": [i.name for i in bd.loot],
                  "rel": st.relationships.get(bd.id)} for bd in p.present],
        "nearby": [{"id": bd.id, "power": bd.power, "appearance": round(bd.appearance, 2)} for bd in p.nearby],
        "exits": p.exits, "items": [i.name for i in w.ground.get(here, [])]}
    brain["state"] = {"needs": {k: round(v, 2) for k, v in st.needs.items()},
                      "emotion": {k: round(v, 2) for k, v in st.emotion.items()}, "traits": st.config.traits}
    return brain


_SCENE_SYS = (
    "Ты разбираешь СВОБОДНОЕ описание ситуации вокруг NPC в СТРУКТУРУ сцены (JSON). Верни только JSON:\n"
    '{"self":{"power":1-4,"appearance":0..1},'
    '"scene":{"here":[{"id":"имя","power":1-4,"appearance":0..1,"attention":0..1,'
    '"faction":"town|monster|outlaw|watch","attacking":"кого или null","ally":true/false,'
    '"loot":[{"name":"кошель","value":0..1}]}],'
    '"nearby":[{"id":"имя","appearance":0..1}],"exits":["выход"],'
    '"items":[{"name":"похлёбка","satisfies":"hunger","value":0.05}],'
    '"extra_goals":[{"kind":"trade","target":"имя","value":0.6}]}}\n'
    "here — кто РЯДОМ (в одном месте), nearby — кто виден в стороне. attacking — если кто-то на кого-то "
    "нападает. ally=true — друг NPC. items — что можно use на месте. exits — куда можно уйти (для бегства "
    "давай хотя бы один). Богатую одежду → высокий appearance. Только факты из текста, без выдумок.")


def _parse(text):
    if not text:
        return None
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", (text or "").strip()).strip()).strip()
    try:
        return json.loads(t[t.find("{"):t.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None


@router.get("/minddebug")
def minddebug_page(_: Owner) -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "minddebug.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@router.get("/api/minddebug/schema")
def minddebug_schema(_: Owner) -> dict:
    return {"traits": list(TRAITS), "needs": list(NEEDS), "emotions": list(EMOTIONS),
            "archetypes": {n: {"traits": t, "power": p, "appearance": a}
                           for n, (t, p, a) in ARCHETYPES.items()}}


@router.post("/api/minddebug/decide")
async def minddebug_decide(_: Owner, request: Request):
    try:
        return _decide(await request.json())
    except Exception as exc:                              # дебаг-стенд: возвращаем ошибку, не 500
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=400)


@router.post("/api/minddebug/scene_from_text")
async def minddebug_scene_from_text(_: Owner, request: Request):
    b = await request.json()
    text = str(b.get("text", "")).strip()
    if not text:
        return _err("пусто")
    mgr = _model()
    if not mgr.available():
        return _err("LLM недоступен — опиши сцену сущностями вручную")
    resp = mgr.call("npc_mind", [{"role": "system", "content": _SCENE_SYS},
                                 {"role": "user", "content": text}],
                    schema=True, options={"temperature": 0.2})
    data = _parse(resp.get("content") if resp else None)
    if not data:
        return _err("не разобрал текст")
    return {"self": data.get("self") or {}, "scene": data.get("scene") or {}}


def _err(msg: str):
    return JSONResponse({"error": msg}, status_code=400)
