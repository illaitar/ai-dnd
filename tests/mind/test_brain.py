"""Граф-мозг (фазы 1-2 + модуляция): урджи + шина модуляторов + сквозная модуляция скоринга.
Проверяем: НЕЙТРАЛЬНОСТЬ в норме (модуляторы≈0.5, modulate=False == чистое ядро), и что ОДИН сдвиг
состояния СИСТЕМНО меняет решение (голод→торговля, страх→бегство) БЕЗ правил на ситуацию.
"""

from __future__ import annotations

from aidnd.mind import (
    TRAITS,
    Body,
    Goal,
    Item,
    NpcConfig,
    NpcState,
    modulators,
    score,
    think,
    urges,
)
from aidnd.mind.world import World


def _npc(traits=None, needs=None, emotion=None, power=1):
    cfg = NpcConfig(id="я", traits={**dict.fromkeys(TRAITS, 0.5), **(traits or {})})
    st = NpcState.from_config(cfg)
    for k, v in (needs or {}).items():
        st.needs[k] = v
    for k, v in (emotion or {}).items():
        st.emotion[k] = v
    return st, power


def _w(st, power, here=None, exits=None, rel=None):
    w = World()
    for e in (exits or []):
        w.link("тут", e)
    w.add(Body("я", "тут", power=power))
    for e in (here or []):
        w.add(Body(e["id"], "тут", power=e.get("power", 1), appearance=e.get("appearance", .2),
                   attention=e.get("attention", .7), faction=e.get("faction", "town"),
                   attacking=e.get("attacking"), loot=[Item(x, .5) for x in e.get("loot", [])]))
    st.relationships = rel or {}
    return w


# ── шина нейтральна в норме (нужды≈0.2, эмоции 0, черты 0.5) ──
def test_modulators_neutral_at_baseline():
    m = modulators(_npc()[0])
    for k in ("arousal", "valence", "dominance"):          # эти трое двигают решение — должны быть ~0.5
        assert 0.42 <= m[k] <= 0.58, f"{k}={m[k]} не нейтрален"
    for k in ("resolution", "selection_threshold", "securing"):
        assert 0.25 <= m[k] <= 0.7, f"{k}={m[k]} вне разумного"


def test_urges_track_needs():
    st, _ = _npc(needs={"hunger": 0.9})
    u = urges(st)
    assert u["hunger"]["urge"] == 0.9 and u["hunger"]["urgency"] > u["fatigue"]["urgency"]


def test_hunger_raises_arousal_lowers_resolution():
    calm = modulators(_npc(needs={"hunger": 0.15})[0])
    hungry = modulators(_npc(needs={"hunger": 0.95})[0])
    assert hungry["arousal"] > calm["arousal"] + 0.2
    assert hungry["resolution"] < calm["resolution"] - 0.2


# ── modulate=False == чистое ядро (нейтральный фундамент, спека не тронута) ──
def test_modulate_off_equals_core():
    st, p = _npc(traits={"greed": .8, "honesty": .1, "lawful": .1}, power=3)
    w = _w(st, p, here=[{"id": "богач", "appearance": .9, "attention": .8, "loot": ["кошель"]}], exits=["прочь"])
    base = score(st, w, __import__("aidnd.mind", fromlist=["perceive"]).perceive(st, w))
    r = think(st, w, modulate=False)
    assert r["chosen"]["action"] == base[0][0].label()


# ── СИСТЕМНОСТЬ: голод сгибает торговлю (counter→accept) БЕЗ правила «голод в торговле» ──
def test_hunger_bends_trade_systemically():
    def buy(hunger):
        st, p = _npc(traits={"greed": .8, "irritability": .25}, needs={"hunger": hunger})
        st.extra_goals = [Goal("trade", "торговец", .6, {"concession": .3, "prob_concede": .7})]
        w = _w(st, p, here=[{"id": "торговец"}])
        return think(st, w)["chosen"]

    assert buy(0.15)["action"] == "say:counter→торговец"     # сыт → держит цену
    assert buy(0.95)["action"] == "say:accept→торговец"      # голоден → уступает


# ── СИСТЕМНОСТЬ: страх ломает защиту (protect→бегство) через dominance ──
def test_fear_breaks_courage():
    def guard(fear):
        st, p = _npc(traits={"loyalty": .9, "bravery": .7}, emotion={"fear": fear}, power=3)
        w = _w(st, p, exits=["прочь"],
               here=[{"id": "друг", "power": 1},
                     {"id": "тролль", "power": 3, "faction": "monster", "attacking": "друг"}],
               rel={"друг": {"trust": .5, "affinity": .8, "fear": 0.0}})
        return think(st, w)["chosen"]

    assert guard(0.0)["goal"] == "protect"                   # собран → защищает
    assert guard(0.85)["goal"] == "safe"                     # в ужасе → бежит


def test_think_returns_trace():
    st, p = _npc()
    r = think(st, _w(st, p, exits=["прочь"]))
    assert r["trace"] and all("id" in n and "active" in n for n in r["trace"])
    assert any(n["llm"] for n in r["trace"])                 # смысловые узлы помечены LLM
