"""Рутина из нужд: каталоги валидны, нужды растут/гаснут, здания рекламируют нужды, выбор места
эмерджентен (работник днём — на работу, ночью — домой; сонного клонит спать; лихого ночью — в
промысел). БЕЗ хардкода ролей — только needs×traits×time."""

from __future__ import annotations

from aidnd import society
from aidnd.society import Candidate


def _needs(**kw):
    n = society.fresh()
    n.update(kw)
    return n


def _state(needs, **traits):
    """Мини-NpcState-подобный объект: .needs + .config.traits + .config.id."""
    from types import SimpleNamespace
    t = {k: 0.5 for k in ("sociability", "greed", "ambition", "lawful", "malice",
                          "curiosity", "loyalty", "honesty", "bravery")}
    t.update(traits)
    return SimpleNamespace(needs=needs, config=SimpleNamespace(traits=t, id="npc:test"))


def test_catalogs_consistent():
    assert {n.id for n in society.NEEDS} >= {"hunger", "fatigue", "social", "wealth", "purpose"}
    # каждая нужда, что рекламируют места, существует в каталоге нужд
    need_ids = {n.id for n in society.NEEDS}
    for pk in society.PLACES:
        assert set(pk.sates) <= need_ids, f"{pk.id} рекламирует несуществующую нужду"


def test_needs_grow_and_place_sates():
    n = _needs(fatigue=0.5, hunger=0.5)
    society.advance(n, 60, sated={"fatigue": 0.16})        # час в месте, что гасит усталость
    assert n["fatigue"] < 0.5                              # усталость спала (спал)
    assert n["hunger"] > 0.5                               # голод вырос (не ел)


def test_building_advertises_from_catalog():
    tav = {"type": "таверна", "services": ["eat", "drink", "lodging"]}
    adv = society.advertises(tav)
    assert adv.get("hunger", 0) > 0 and adv.get("social", 0) > 0   # трактир кормит и даёт общение
    assert society.advertises({"type": "жилой дом"}) == {}          # обычный дом ничего не рекламирует


def _cands():
    return [Candidate("home", 1), Candidate("work", 2), Candidate("tavern", 3),
            Candidate("patrol", 4), Candidate("prowl", 5), Candidate("street", 6)]


def test_worker_day_vs_night():
    import random
    rng = random.Random(0)
    tired_evening = _state(_needs(fatigue=0.85, wealth=0.2), ambition=0.6)
    assert society.choose(tired_evening.needs, tired_evening.config.traits,
                          [Candidate("home", 1), Candidate("work", 2)], "night", rng) == 1  # домой спать
    keen_day = _state(_needs(fatigue=0.2, wealth=0.8, purpose=0.7), ambition=0.7, lawful=0.6)
    assert society.choose(keen_day.needs, keen_day.config.traits,
                          [Candidate("home", 1), Candidate("work", 2)], "day", rng) == 2     # на работу


def test_personality_splits_evening():
    # общение — свинг-нужда (голод низкий, чтобы не гнал за едой): характер решает, к людям или домой
    import random
    rng = random.Random(1)
    cands = [Candidate("home", 1), Candidate("tavern", 3)]
    social = _state(_needs(social=0.8, hunger=0.2), sociability=0.95)
    hermit = _state(_needs(social=0.8, hunger=0.2, fatigue=0.6), sociability=0.05)
    assert society.choose(social.needs, social.config.traits, cands, "evening", rng) == 3   # к людям
    assert society.choose(hermit.needs, hermit.config.traits, cands, "evening", rng) == 1   # домой


def test_rogue_prowls_at_night():
    import random
    rng = random.Random(2)
    rogue = _state(_needs(wealth=0.7, novelty=0.6), greed=0.9, malice=0.8, honesty=0.1)
    got = society.choose(rogue.needs, rogue.config.traits,
                         [Candidate("home", 1), Candidate("prowl", 5), Candidate("street", 6)],
                         "night", rng)
    assert got == 5                                        # ночью тянет на промысел
