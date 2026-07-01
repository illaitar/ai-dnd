"""Эмерджентное ядро решений: 10 сценариев поведения ВЫПАДАЮТ из ОДНОЙ utility над общими
примитивами (move/attack/take/give/say/use/wait). Ни «follow», ни «flee», ни «ambush» нигде не
зашиты — это какой примитив выиграл под конкретной целью. Никакого ветвления «по сценарию» в
решающем коде: все тесты ходят через mind.decide().

Тесты ОДНОВРЕМЕННО — спека поведения: то, к чему калибруются коэффициенты BAL (а не 50 скриптов).
"""

from __future__ import annotations

from aidnd.mind import (
    TRAITS,
    Body,
    Goal,
    Item,
    NpcConfig,
    NpcState,
    decide,
    perceive,
)
from aidnd.mind.world import World


def _npc(nid, place, world, traits=None, needs=None, **body):
    cfg = NpcConfig(id=nid, name=nid,
                    traits={**dict.fromkeys(TRAITS, 0.5), **(traits or {})})
    st = NpcState.from_config(cfg)
    for k, v in (needs or {}).items():
        st.needs[k] = v
    world.add(Body(id=nid, place=place, **body))
    return st


def _choose(st, world):
    (a, g, u), ranked = decide(st, world, perceive(st, world))
    return a, g, ranked


# ── 1. БЕГСТВО: слабый перед сильным врагом → move ПРОЧЬ (не примитив flee) ──
def test_flee_emerges_as_move_away():
    w = World()
    w.link("square", "alley")
    st = _npc("rogue", "square", w, traits={"bravery": 0.2}, power=1)
    w.add(Body("beast", "square", power=5, faction="monster", appearance=0.1))
    a, g, _ = _choose(st, w)
    assert a.kind == "move" and a.to == "alley"
    assert g.kind == "safe"


# ── 2. ЖАДНЫЙ УБИЙЦА: в толпе ВЫЖИДАЕТ, один-на-один — бьёт насмерть и обирает (malice) ──
def test_lurk_then_kill_then_loot():
    w = World()
    w.link("square", "alley")
    st = _npc("killer", "square", w,
              traits={"greed": 0.9, "honesty": 0.1, "lawful": 0.1, "bravery": 0.8, "malice": 0.8},
              power=3)
    w.add(Body("mark", "square", power=1, appearance=0.9, attention=0.8,
               loot=[Item("кошель", 0.6)]))
    w.add(Body("townA", "square"))
    w.add(Body("townB", "square"))

    a, _, _ = _choose(st, w)
    assert a.kind == "wait"                                  # при свидетелях — терпит

    del w.bodies["townA"]
    del w.bodies["townB"]
    a, _, _ = _choose(st, w)
    assert a.kind == "attack" and a.target == "mark"          # безлюдно — наносит удар

    w.bodies["mark"].hp = 0
    w.bodies["mark"].alive = False
    a, _, _ = _choose(st, w)
    assert a.kind == "take" and a.target == "mark"            # добив — обирает


# ── 2b. КОНТРАСТ: жадный, но НЕ злонравный (malice низ) — наедине ВЫМОГАЕТ, а не убивает ──
def test_greedy_without_malice_extorts_not_kills():
    w = World()
    st = _npc("extortionist", "square", w,
              traits={"greed": 0.9, "honesty": 0.1, "lawful": 0.1, "bravery": 0.8, "malice": 0.2},
              power=3)
    w.add(Body("mark", "square", power=1, appearance=0.9, attention=0.8,
               loot=[Item("кошель", 0.6)]))
    a, g, _ = _choose(st, w)                                 # один-на-один, без свидетелей
    assert a.kind == "say" and a.say == "threat"             # шантаж дешевле клинка
    assert g.kind == "acquire"


# ── 3. КРАЖА: бесчестный крадёт у ротозея; честный-законопослушный — нет (та же ситуация) ──
def test_theft_only_when_dishonest():
    def stand(traits):
        w = World()
        st = _npc("x", "sq", w, traits=traits, power=1)
        w.add(Body("mark", "sq", power=1, appearance=0.5, attention=0.2,
                   loot=[Item("монеты", 0.4)]))     # ротозей, спокойный момент: дискриминатор — честность
        return _choose(st, w)

    a1, _, _ = stand({"greed": 0.8, "honesty": 0.1, "lawful": 0.1})
    assert a1.kind == "take" and a1.target == "mark"

    a2, _, _ = stand({"greed": 0.8, "honesty": 0.9, "lawful": 0.7})
    assert a2.kind != "take"


# ── 4. ЗАПУГИВАНИЕ: сильный против слабого податливого → say(threat) дешевле драки ──
def test_intimidation_beats_assault():
    w = World()
    st = _npc("thug", "sq", w,
              traits={"greed": 0.7, "honesty": 0.2, "lawful": 0.2, "pride": 0.6}, power=4)
    w.add(Body("victim", "sq", power=1, appearance=0.6, attention=0.7,
               loot=[Item("товар", 0.5)]))
    a, g, _ = _choose(st, w)
    assert a.kind == "say" and a.say == "threat"
    assert g.kind == "acquire"


# ── 5. ТОРГ: терпеливый жадный держит цену; бедняк (нужда wealth) соглашается ──
def test_haggle_patience_vs_poverty():
    def stand(traits, needs):
        w = World()
        st = _npc("buyer", "shop", w, traits=traits, needs=needs)
        st.extra_goals = [Goal("trade", "merchant", 0.6,
                               {"concession": 0.3, "prob_concede": 0.7})]
        w.add(Body("merchant", "shop", power=1))
        return _choose(st, w)

    a1, _, _ = stand({"greed": 0.8, "irritability": 0.2}, {"wealth": 0.1})
    assert a1.kind == "say" and a1.say == "counter"

    a2, _, _ = stand({"greed": 0.8, "irritability": 0.8}, {"wealth": 0.9})
    assert a2.kind == "say" and a2.say == "accept"


# ── 6. ПОДКУП: нужна кооперация дотошного стража (глух к лести) → give (жертва ради позиции) ──
def test_bribe_emerges_for_cooperation():
    w = World()
    st = _npc("smuggler", "gate", w, traits={"greed": 0.4, "sociability": 0.2},
              carrying=[Item("кошель", 0.5)])
    st.extra_goals = [Goal("affiliate", "guard", 0.9, {"flatter_recept": 0.1})]
    w.add(Body("guard", "gate", faction="watch", power=2))
    a, g, _ = _choose(st, w)
    assert a.kind == "give" and a.target == "guard"
    assert g.kind == "affiliate"


# ── 7. ЗАЩИТА СОЮЗНИКА: верный храбрец бьёт нападающего; трус-нелояльный — нет ──
def test_protect_ally_depends_on_loyalty_and_bravery():
    def stand(traits):
        w = World()
        st = _npc("guard", "sq", w, traits=traits, power=3)
        st.relationships["friend"] = {"trust": 0.5, "affinity": 0.8, "fear": 0.0}
        w.add(Body("friend", "sq", hp=8, power=1))
        w.add(Body("thug", "sq", power=2, faction="outlaw", attacking="friend"))
        return _choose(st, w)

    a1, g1, _ = stand({"loyalty": 0.9, "bravery": 0.8})
    assert a1.kind == "attack" and a1.target == "thug" and g1.kind == "protect"

    a2, _, _ = stand({"loyalty": 0.1, "bravery": 0.2})
    assert not (a2.kind == "attack" and a2.target == "thug")


# ── 8. ОБХОД: к еде два равных пути, один через опасный узел → длинный безопасный сосед ──
def test_detour_around_risky_node():
    w = World()
    for a, b in [("sq", "alley"), ("sq", "market"), ("alley", "tavern"), ("market", "tavern")]:
        w.link(a, b)
    st = _npc("walker", "sq", w, needs={"hunger": 0.9}, power=1)
    st.needs_sources = {"hunger": {"source": "tavern"}}
    w.add(Body("bandit", "market", power=3, faction="bandit"))
    a, g, _ = _choose(st, w)
    assert a.kind == "move" and a.to == "alley"              # не через market с бандитом
    assert g.kind == "need"


# ── 9. РАЗВЕДКА: любопытный с неопределённостью идёт к источнику слухов (а не действует вслепую) ──
def test_information_seeking():
    w = World()
    w.link("alley", "square")
    st = _npc("nosy", "alley", w, traits={"curiosity": 0.9})
    st.extra_goals = [Goal("inform", "gossip", 0.8, {"source": "square"})]
    a, g, _ = _choose(st, w)
    assert a.kind == "move" and a.to == "square"
    assert g.kind == "inform"


# ── 10. СМЕНА ЦЕЛИ: хищник крадётся за добычей, но голод дозревает → бросает, идёт есть ──
def test_goal_switch_under_rising_need():
    w = World()
    w.link("sq", "gate")
    w.link("sq", "tavern")
    st = _npc("stalker", "sq", w,
              traits={"greed": 0.9, "honesty": 0.1, "lawful": 0.1, "bravery": 0.8},
              power=3, needs={"hunger": 0.2})
    st.needs_sources = {"hunger": {"source": "tavern"}}
    w.add(Body("mark", "gate", power=1, appearance=0.9, attention=0.8))

    a, g, _ = _choose(st, w)
    assert g.kind == "acquire" and a.kind == "move" and a.to == "gate"   # крадётся к добыче

    st.needs["hunger"] = 0.97
    a, g, _ = _choose(st, w)
    assert g.kind == "need" and a.kind == "move" and a.to == "tavern"     # голод перевесил
