"""Дебаг-экран NPC: настройки слева, карта по центру (разместить NPC), таймлайн (тик),
панель мыслей справа (ручной запуск инструментов/апрейзала). Доступ только владельцу.

Состояние сцены процессное (один владелец) — это дебаг-стенд, не прод-механика.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..citygraph import CityParams, generate
from ..mind import (
    ABILITIES,
    EMOTIONS,
    NEEDS,
    TOOLS,
    TRAITS,
    LLMReranker,
    NpcConfig,
    NpcState,
    Scene,
    StubReranker,
    advance,
    appraise,
    run_tool,
)
from .routes_citydebug import Owner

router = APIRouter(tags=["npcdebug"])
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_S: dict = {"scene": None, "npc": None, "model": None}

_SEED_MEMORIES = [
    {"text": "Гундрен Рокссикер ушёл в старый рудник и пропал без вести", "importance": 0.8, "about": ["npc:gundren"]},
    {"text": "Красные плащи открыто угрожают лавочникам на рынке", "importance": 0.7, "about": ["faction:redbrands"]},
    {"text": "Вчера в таверне «Каменный Холм» была пьяная драка", "importance": 0.3, "about": []},
    {"text": "Караван из Невервинтера задержался — на дорогах неспокойно", "importance": 0.5, "about": []},
    {"text": "Сестра Гарэле в святилище расспрашивала про Тундердрев", "importance": 0.5, "about": ["npc:garaele"]},
    {"text": "Я с детства боюсь грозы", "importance": 0.2, "about": []},
    {"text": "Кузнец дерёт втридорога за подковы", "importance": 0.3, "about": []},
    {"text": "Говорят, в холмах объявился виверн", "importance": 0.6, "about": []},
]


def _need():
    return _S["scene"], _S["npc"]


def _err(msg: str):
    return JSONResponse({"error": msg}, status_code=400)


def _reranker(use_llm: bool):
    if not use_llm:
        return StubReranker()
    if _S["model"] is None:
        from ..inference import ModelManager
        _S["model"] = ModelManager()
    return LLMReranker(_S["model"])


@router.get("/npcdebug")
def npcdebug_page(_: Owner) -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "npcdebug.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@router.post("/api/npcdebug/new")
async def npcdebug_new(_: Owner, request: Request) -> dict:
    b = await request.json()
    city = generate(CityParams(seed=int(b.get("seed", 7)), key_buildings=int(b.get("key", 10)),
                               river=bool(b.get("river", True)), walls=bool(b.get("walls", True))))
    cfg = NpcConfig(id="npc:debug", name=b.get("name", "Тест"), race=b.get("race", "human"),
                    role=b.get("role", "горожанин"), level=int(b.get("level", 1)),
                    max_hp=int(b.get("max_hp", 10)),
                    traits={**dict.fromkeys(TRAITS, 0.5), **(b.get("traits") or {})},
                    abilities={**dict.fromkeys(ABILITIES, 10), **(b.get("abilities") or {})})
    npc = NpcState.from_config(cfg, node=city.key_points()[0])
    for m in _SEED_MEMORIES:
        npc.memory.add(m["text"], t=0, importance=m["importance"], about=m["about"])
    _S["scene"], _S["npc"] = Scene(city=city, npcs={cfg.id: npc}), npc
    return {"graph": city.debug_data(), "npc": npc.view(), "clock": 0,
            "tools": [{"name": n, "cls": s["cls"], "params": s["params"]} for n, s in TOOLS.items()],
            "schema": {"traits": list(TRAITS), "abilities": list(ABILITIES),
                       "needs": list(NEEDS), "emotions": list(EMOTIONS)}}


@router.post("/api/npcdebug/config")
async def npcdebug_config(_: Owner, request: Request):
    scene, npc = _need()
    if not npc:
        return _err("сначала создай сцену")
    b = await request.json()
    for f in ("name", "role"):
        if b.get(f) is not None:
            setattr(npc.config, f, b[f])
    npc.config.traits.update({k: float(v) for k, v in (b.get("traits") or {}).items()})
    npc.config.abilities.update({k: int(v) for k, v in (b.get("abilities") or {}).items()})
    npc.needs.update({k: float(v) for k, v in (b.get("needs") or {}).items()})
    npc.emotion.update({k: float(v) for k, v in (b.get("emotion") or {}).items()})
    return {"npc": npc.view()}


@router.post("/api/npcdebug/place")
async def npcdebug_place(_: Owner, request: Request):
    scene, npc = _need()
    if not npc:
        return _err("сначала создай сцену")
    node = int((await request.json()).get("node"))
    if node not in scene.city._xy:                       # noqa: SLF001 — дебаг-стенд
        return _err("нет такого узла")
    npc.node = node
    return {"npc": npc.view()}


@router.post("/api/npcdebug/tick")
async def npcdebug_tick(_: Owner, request: Request):
    scene, npc = _need()
    if not npc:
        return _err("сначала создай сцену")
    ticks = int((await request.json()).get("ticks", 1))
    res = advance(npc, scene, ticks=ticks)
    return {"tick": res, "npc": npc.view(), "clock": scene.clock}


@router.post("/api/npcdebug/tool")
async def npcdebug_tool(_: Owner, request: Request):
    scene, npc = _need()
    if not npc:
        return _err("сначала создай сцену")
    b = await request.json()
    out = run_tool(b.get("name", ""), npc, scene, b.get("params") or {},
                   reranker=_reranker(bool(b.get("rerank"))))
    return {"clock": scene.clock, **out, "npc": npc.view()}


@router.post("/api/npcdebug/memory")
async def npcdebug_memory(_: Owner, request: Request):
    scene, npc = _need()
    if not npc:
        return _err("сначала создай сцену")
    b = await request.json()
    npc.memory.add(str(b.get("text", "")).strip(), t=scene.clock,
                   importance=float(b.get("importance", 0.3)), about=b.get("about") or [])
    return {"memory_count": len(npc.memory.items)}


@router.post("/api/npcdebug/appraise")
async def npcdebug_appraise(_: Owner, request: Request):
    scene, npc = _need()
    if not npc:
        return _err("сначала создай сцену")
    b = await request.json()
    res = appraise(npc, b.get("dims") or {}, source=b.get("source") or None)
    return {"appraise": res, "npc": npc.view()}
