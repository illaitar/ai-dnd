"""Социальная ось: цель converse (заговорить с человеком) + развод КРАСОТЫ (charisma) и БОГАТСТВА
(appearance). Красивую-но-небогатую заговаривают, а не грабят; богатую хищник по-прежнему видит
мишенью; без соц-нужды не пристают.
"""

from __future__ import annotations

from aidnd.mind import TRAITS, Body, NpcConfig, NpcState, think
from aidnd.mind.world import World


def _npc(traits=None, needs=None):
    cfg = NpcConfig(id="я", traits={**dict.fromkeys(TRAITS, 0.5), **(traits or {})})
    st = NpcState.from_config(cfg)
    for k, v in (needs or {}).items():
        st.needs[k] = v
    return st


def _w(st, girl):
    w = World()
    w.link("таверна", "улица")
    w.add(Body("я", "таверна"))
    w.add(Body("девушка", "таверна", **girl))
    return w


PRETTY = {"appearance": .2, "charisma": .75, "attention": .7}   # красива, но не богата
RICH = {"appearance": .9, "charisma": .3, "attention": .8, "loot": [__import__("aidnd.mind", fromlist=["Item"]).Item("кошель", .6)]}


def test_pretty_girl_gets_conversation_not_robbery():
    st = _npc({"sociability": .6}, {"social": .5})
    r = think(st, _w(st, PRETTY))
    assert r["chosen"]["goal"] == "converse" and r["chosen"]["action"].startswith("say:")


def test_greedy_does_not_rob_beauty():
    st = _npc({"greed": .9, "honesty": .1, "lawful": .1}, {"social": .4})
    r = think(st, _w(st, PRETTY))              # красива, но БЕДНА → не мишень
    assert not (r["chosen"]["action"].startswith("say:threat") or r["chosen"]["action"].startswith("take"))


def test_predation_still_fires_on_actually_rich():
    st = _npc({"greed": .9, "honesty": .1, "lawful": .1}, {"social": .2})
    r = think(st, _w(st, RICH))                # реально богата → хищник видит мишень
    goals = [g["kind"] for g in r["goals"]]
    assert "acquire" in goals


def test_no_pestering_without_social_need():
    st = _npc({"sociability": .5}, {"social": .05})     # соц-нужда закрыта
    r = think(st, _w(st, PRETTY))
    assert r["chosen"]["goal"] != "converse"
