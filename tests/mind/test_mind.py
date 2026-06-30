"""Тесты ядра разума: SOTA-ретрива (top-k, скор, освежение), вытаскивание контекстов
инструментами (perceive/recall/assess/locate/move), ход мира (тик), апрейзал эмоций."""

from __future__ import annotations

import pytest

from aidnd.citygraph import CityParams, generate
from aidnd.mind import NpcConfig, NpcState, Scene, advance, appraise, run_tool


@pytest.fixture()
def scene():
    city = generate(CityParams(seed=7, key_buildings=6, river=True, walls=True))
    npc = NpcState.from_config(NpcConfig(id="npc:x", name="Тест"), node=city.key_points()[0])
    npc.memory.add("Гундрен ушёл в рудник и пропал без вести", t=0, importance=0.8, about=["npc:gundren"])
    npc.memory.add("Вчера в таверне была пьяная драка", t=1, importance=0.3)
    npc.memory.add("Красные плащи угрожают лавочникам на рынке", t=2, importance=0.6, about=["faction:redbrands"])
    npc.memory.add("Я люблю свежий эль по вечерам", t=3, importance=0.1)
    npc.rel("npc:gundren").update({"trust": 0.4, "affinity": 0.2})
    sc = Scene(city=city, npcs={npc.config.id: npc})
    sc.clock = 5
    return sc, npc


# ----------------------------------------------------------- ретрива -------- #
def test_recall_targets_question(scene):
    sc, npc = scene
    r = run_tool("recall", npc, sc, {"query": "что с рудником и Гундреном?"})["result"]
    texts = [m["text"] for m in r["memories"]]
    assert any("Гундрен" in t for t in texts)
    assert texts[0].startswith("Гундрен")            # самый релевантный — первым


def test_recall_top_k_and_refresh(scene):
    sc, npc = scene
    r = run_tool("recall", npc, sc, {"query": "эль таверна", "k": 2})["result"]
    assert len(r["memories"]) <= 2
    # обращение освежает last_access у возвращённых
    accessed = [m for m in npc.memory.items if m.last_access == sc.clock]
    assert accessed


def test_recall_empty_memory():
    city = generate(CityParams(seed=1, key_buildings=3))
    npc = NpcState.from_config(NpcConfig(), node=city.key_points()[0])
    assert run_tool("recall", npc, Scene(city=city), {"query": "что угодно"})["result"]["memories"] == []


# --------------------------------------------------- контексты READ --------- #
def test_perceive(scene):
    sc, npc = scene
    r = run_tool("perceive", npc, sc)["result"]
    assert r["node"] == npc.node
    assert isinstance(r["exits"], list) and r["exits"]      # есть легальные выходы
    assert all("kind" in e for e in r["exits"])


def test_assess(scene):
    sc, npc = scene
    r = run_tool("assess", npc, sc, {"entity": "npc:gundren"})["result"]
    assert r["relationship"]["trust"] == 0.4
    assert any("Гундрен" in f for f in r["facts"])           # факты о нём


def test_locate(scene):
    sc, npc = scene
    r = run_tool("locate", npc, sc, {"target": "key:4"})["result"]
    assert r["known"] and r["found"]
    assert r["bearing"] in {"С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"}
    assert isinstance(r["landmarks"], list)


def test_locate_unknown(scene):
    sc, npc = scene
    assert run_tool("locate", npc, sc, {"target": "нет-такого"})["result"]["known"] is False


# --------------------------------------------------- WRITE: move ------------ #
def test_move_steps_toward_target(scene):
    sc, npc = scene
    start = npc.node
    r = run_tool("move", npc, sc, {"target": "key:5"})["result"]
    assert r["moved"] and npc.node != start                  # шагнул на узел ближе
    assert r["remaining"] >= 0


# ------------------------------------------------------- тик/эмоции --------- #
def test_tick_needs_and_emotion_decay(scene):
    sc, npc = scene
    npc.emotion["anger"] = 0.8
    h0 = npc.needs["hunger"]
    advance(npc, sc, ticks=3)
    assert npc.needs["hunger"] > h0                          # нужды растут
    assert npc.emotion["anger"] < 0.8                        # эмоции спадают к базе


def test_appraise_anger_and_target(scene):
    sc, npc = scene
    appraise(npc, {"goal_impact": -0.4, "desert": -0.6, "intent": "deliberate"}, source="npc:foe")
    assert npc.emotion["anger"] > 0
    assert npc.emotion_target.get("anger") == "npc:foe"      # зол НА конкретного


def test_appraise_norm_resolves_anger(scene):
    sc, npc = scene
    npc.emotion["anger"] = 0.5
    appraise(npc, {"goal_impact": 0.5, "desert": 0.6, "norm": 0.8, "intent": "deliberate"}, source="npc:foe")
    assert npc.emotion["joy"] > 0
    assert npc.emotion["anger"] < 0.5                        # обида снята адресно


# ------------------------------------------------------- граф состояний ----- #
def _calm(npc, **over):
    npc.needs.update(dict.fromkeys(npc.needs, 0.2))
    npc.needs.update(over)


def test_default_leisure(scene):
    sc, npc = scene
    _calm(npc)
    advance(npc, sc, ticks=1)
    assert npc.mode == "leisure"                             # мягкие нужды → досуг


def test_threat_preempts(scene):
    sc, npc = scene
    _calm(npc)
    npc.emotion["fear"] = 0.85
    advance(npc, sc, ticks=1)
    assert npc.mode == "threat"


def test_strong_need_builds_routine(scene):
    sc, npc = scene
    _calm(npc, hunger=0.85)
    advance(npc, sc, ticks=1)
    assert npc.mode == "routine"
    assert npc.plan and "голод" in npc.plan.goal             # план под доминирующую нужду


def test_routine_holds_trivia_but_threat_interrupts(scene):
    sc, npc = scene
    _calm(npc, fatigue=0.9)                                  # важный план (importance 0.7)
    advance(npc, sc, ticks=1)
    assert npc.mode == "routine"
    advance(npc, sc, ticks=1, stim={"addressed": True, "addresser_importance": 0.2})
    assert npc.mode == "routine"                             # мелочь не сорвала рутину
    npc.emotion["fear"] = 0.9
    advance(npc, sc, ticks=1)
    assert npc.mode == "threat"                              # угроза сорвала


def test_addressed_enters_converse(scene):
    sc, npc = scene
    _calm(npc)
    advance(npc, sc, ticks=1, stim={"addressed": True, "addresser_importance": 0.7})
    assert npc.mode == "converse"


def test_routine_plan_advances(scene):
    sc, npc = scene
    _calm(npc, hunger=0.85)
    advance(npc, sc, ticks=1)                                # вход в routine, план 2 шага
    assert npc.plan.cursor == 0
    advance(npc, sc, ticks=2)
    assert npc.plan.done()                                   # шаги выполнены


def test_mode_history_is_route(scene):
    sc, npc = scene
    advance(npc, sc, ticks=4)
    assert len(npc.mode_history) >= 4
    assert all(len(h) == 4 for h in npc.mode_history)        # [tick, mode, switched, reason]
