"""Доразрешение пула сцены: контекст, детерминизм, вечная фиксация (док 06 + main §2)."""

from aidnd import config
from aidnd.bootstrap import new_session
from aidnd.gen.discovery import HIDDEN, PRESENCE, DiscoveryService


def _disc(s):
    return DiscoveryService(s.world, s.dice, s.charts)


def test_location_type_context():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    d = _disc(s)
    assert d.location_type("building:stonehill_inn") == "market"
    assert d.location_type("place:cragmaw_klarg_cave") == "dungeon"
    assert d.location_type("building:tresendar_manor") == "dungeon"     # логово/укрытие


def test_dungeon_far_less_likely_than_town():
    assert PRESENCE["dungeon"] < 0.05 < PRESENCE["frontier_town"]
    assert HIDDEN["dungeon"]["stash"] > HIDDEN["frontier_town"]["stash"]


def test_ask_1000_times_same_answer():
    """Зафиксированный факт не меняется при повторных запросах."""
    s = new_session(seed=1337, roster_size=2, use_model=False)
    d = _disc(s)
    first = d.resolve_observers("place:phandalin_square", "pc:hero")
    assert not first.recorded                       # первый раз — свежее разрешение
    results = {(d.resolve_observers("place:phandalin_square", "pc:hero").present,
                d.resolve_observers("place:phandalin_square", "pc:hero").watching)
               for _ in range(50)}
    assert results == {(first.present, first.watching)}   # 50 запросов → один ответ
    assert "presence:place:phandalin_square" in s.world.resolutions


def test_resolution_is_event_sourced():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    _disc(s).resolve_observers("place:phandalin_square", "pc:hero")
    # зафиксировано событием resolve в логе
    assert any(e.verb == "resolve" for e in s.world.log.all())


def test_fixed_occupants_mean_someone_is_present():
    # в пещере есть Кларг и гоблины → «кто-то рядом» = да
    s = new_session(seed=1337, roster_size=2, use_model=False)
    res = _disc(s).resolve_observers("place:cragmaw_klarg_cave", "pc:hero")
    assert res.present is True and res.npc is not None


def test_hidden_existence_persisted_and_materialized():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    d = _disc(s)
    r1 = d.resolve_hidden("place:cragmaw_klarg_cave", "stash")
    r2 = d.resolve_hidden("place:cragmaw_klarg_cave", "stash")
    assert r2.recorded and r1.exists == r2.exists      # повтор — тот же факт
    if r1.exists:
        assert r1.container in s.world.containers       # лениво материализован


def test_determinism_same_seed():
    a = new_session(seed=2024, roster_size=2, use_model=False)
    b = new_session(seed=2024, roster_size=2, use_model=False)
    ra = _disc(a).resolve_observers("place:phandalin_square", "pc:hero")
    rb = _disc(b).resolve_observers("place:phandalin_square", "pc:hero")
    assert (ra.present, ra.watching) == (rb.present, rb.watching)   # сид → тот же мир


def test_interest_promotes_house_to_key():
    # повторный осмотр дома поднимает индекс важности; на пороге дом становится ключевым
    s = new_session(seed=1337, roster_size=2, use_model=False)
    hid = "house:1337:120_140"
    for _ in range(config.PLACE_IMPORTANCE_KEY):
        s.discovery.materialize_interior(hid, kind_hint="home")
    assert s.world.importance[hid] >= config.PLACE_IMPORTANCE_KEY
    keys = {k["id"] for k in s.view()["key_houses"]}
    assert hid in keys


def test_one_interaction_not_yet_key():
    s = new_session(seed=1337, roster_size=2, use_model=False)
    hid = "house:1337:200_200"
    s.discovery.materialize_interior(hid, kind_hint="home")          # один осмотр < порога
    assert hid not in {k["id"] for k in s.view()["key_houses"]}
