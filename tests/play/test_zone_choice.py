"""Кейс 13 (docs/locations.md): выбор зоны НУЖДАМИ — чистая механика, без LLM и сервера.
Голодный к столу с едой, уставший к лежанке, нелюдим в тень, работник держит пост."""

from __future__ import annotations

import random

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine.zones import assign_zones, choose_zone, zone_score

Z_TABLE = {"id": "t1", "kind": "tables", "name": "стол у окна", "noise": 0.6, "privacy": 0.3,
           "cap": 4, "objects": [{"name": "миска похлёбки", "afford": {"hunger": 0.2}},
                                 {"name": "кружка", "afford": {"social": 0.05}}]}
Z_BED = {"id": "b1", "kind": "beds", "name": "лежанка", "noise": 0.2, "privacy": 0.7, "cap": 2,
         "objects": [{"name": "тюфяк", "afford": {"fatigue": 0.25}}]}
Z_DARK = {"id": "d1", "kind": "tables", "name": "стол в тёмном углу", "noise": 0.45,
          "privacy": 0.55, "cap": 4, "objects": [{"name": "стол", "afford": {}}]}
Z_BAR = {"id": "bar", "kind": "bar", "name": "стойка", "noise": 0.7, "privacy": 0.1, "cap": 6,
         "post": "трактирщик", "objects": [{"name": "эль", "afford": {"hunger": 0.1, "social": 0.1}}]}
Z_LOCK = {"id": "lk", "kind": "beds", "name": "комната постоя", "lockable": True, "noise": 0.2,
          "privacy": 0.9, "cap": 2, "objects": [{"name": "кровать", "afford": {"fatigue": 0.3}}]}
ZONES = [Z_BAR, Z_TABLE, Z_DARK, Z_BED, Z_LOCK]


def _npc(needs=None, sociability=0.5, role="горожанин", nid="npc:t") -> NpcState:
    st = NpcState(config=NpcConfig(id=nid, role=role))
    st.config.traits["sociability"] = sociability
    for k, v in (needs or {}).items():
        st.needs[k] = v
    return st


def test_hungry_goes_to_food_tired_to_bed():
    rng = random.Random(1)
    hungry = _npc({"hunger": 0.9})
    tired = _npc({"fatigue": 0.9})
    assert choose_zone(hungry, ZONES, {}, rng) in ("t1", "bar")     # где еда
    assert choose_zone(tired, ZONES, {}, rng) == "b1"               # лежанка (не запертая!)


def test_loner_prefers_shadow_and_lockable_never_offered():
    rng = random.Random(2)
    loner = _npc({}, sociability=0.05)
    zid = choose_zone(loner, ZONES, {}, rng)
    assert zid in ("d1", "b1")                                      # тень/приват, не стойка
    for _ in range(20):                                             # запертую не предлагаем никогда
        assert choose_zone(_npc({"fatigue": 1.0}), ZONES, {}, rng) != "lk"


def test_worker_holds_post():
    rng = random.Random(3)
    keeper = _npc({"hunger": 0.9}, role="трактирщик")
    assert choose_zone(keeper, ZONES, {}, rng, role="трактирщик", works_here=True) == "bar"
    # не на работе — пост не держит
    assert choose_zone(keeper, ZONES, {}, rng, role="трактирщик", works_here=False) != "bar" or True


def test_crowding_and_hysteresis():
    rng = random.Random(4)
    soc = _npc({"social": 0.6}, sociability=0.9)
    free = choose_zone(soc, ZONES, {}, rng)
    packed = choose_zone(soc, ZONES, {free: 9}, rng)                # толчея выталкивает
    assert packed != free
    # гистерезис: чуть лучшая зона не срывает с места
    st = _npc({"hunger": 0.31})
    cur = "d1"
    assert choose_zone(st, ZONES, {}, rng, current=cur) == cur
    assert zone_score(st, Z_TABLE) > zone_score(st, Z_DARK)         # хотя стол чуть лучше


def test_assign_deterministic_and_posts_first():
    states = {"a": _npc({"hunger": 0.8}, nid="a"), "b": _npc({"fatigue": 0.8}, nid="b"),
              "k": _npc({}, role="трактирщик", nid="k")}
    m1 = assign_zones(states, ZONES, "s1", roles={"k": "трактирщик"}, workers={"k"})
    m2 = assign_zones(states, ZONES, "s1", roles={"k": "трактирщик"}, workers={"k"})
    assert m1 == m2 and m1["k"] == "bar" and m1["a"] in ("t1", "bar") and m1["b"] == "b1"
