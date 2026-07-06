"""Кейсы происшествий: рождение из симуляции, шайка ворует, резолв платит из кошельков."""

import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine import incidents as inc_m


@pytest.fixture
def world(monkeypatch):
    from aidnd.worldgen import WorldStore

    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(core, "_STORE", WorldStore(os.path.join(tmp, "live.db")))
    monkeypatch.setitem(core.PB, "incident_p", 1.0)   # утро обязано родить происшествие
    from aidnd.server.play.engine.world import _play

    _city, people, _crof, _cr2b, _loc = _play()       # настоящий мир сессии (пул)
    core._S["gt"] = 8 * 60
    return people


def _force_type(monkeypatch, key):
    t = next(x for x in inc_m._cat() if x["key"] == key)
    monkeypatch.setattr(inc_m, "_cat", lambda: [dict(t)])


def test_vermin_binds_to_real_home(world, monkeypatch):
    _force_type(monkeypatch, "vermin")
    news = inc_m.incident_spawn()
    assert news, "происшествие не родилось"
    inc = inc_m.incidents_active()[0]
    assert inc["patron"] in world                      # заказчик — живой горожанин
    assert inc["giver"] == inc["patron"]               # платит из СВОЕГО кошелька
    fam = world[inc["patron"]].name.split()[-1]
    assert fam in inc["title"] or "дом" in inc["title"]
    jobs = inc_m.incident_jobs()
    assert jobs and jobs[0]["incident"] and jobs[0]["giver_name"] == world[inc["patron"]].name


def test_gang_members_are_citizens_and_steal(world, monkeypatch):
    _force_type(monkeypatch, "gang")
    assert inc_m.incident_spawn()
    inc = inc_m.incidents_active()[0]
    assert inc["members"] and all(m in world for m in inc["members"])
    for m in inc["members"]:                           # шайка — из горожан с гнильцой
        assert world[m].state.config.traits.get("malice", 0) >= core.PB["incident_gang_malice"]
    mark_purses = {pid: core._store().purse_get(core._wid(), pid) for pid in world}
    core._S["gt"] = core._gt() + 1440                  # следующее утро
    news = inc_m.gang_morning()
    assert news and "обчистили" in news[0]
    inc2 = inc_m.incidents_active()[0]
    assert inc2["stash"] > 0 and inc2["reward"] > inc["reward"]  # общак и цена растут
    dd = core._store().deeds(core._wid(), verb="theft")
    assert dd and dd[0]["actor"] in inc["members"]     # кража — деянием РЕАЛЬНОГО горожанина


def test_missing_captive_leaves_and_returns(world, monkeypatch):
    _force_type(monkeypatch, "missing")
    if not inc_m.incident_spawn():
        pytest.skip("в пуле не нашлось родни для похищения")
    inc = inc_m.incidents_active()[0]
    cap = inc["captive"]
    assert cap in world
    assert core._store().flag_get(core._wid(), f"captive|{cap}")  # исчез из сцен города
    core._store().purse_add(core._wid(), inc["giver"], 50)
    narr = inc_m.incident_resolve(inc["id"], [])
    assert any("платит" in n for n in narr)
    assert not core._store().flag_get(core._wid(), f"captive|{cap}")  # вернулся
    assert all(x["id"] != inc["id"] for x in inc_m.incidents_active())


def test_resolve_pays_from_patron_purse(world, monkeypatch):
    _force_type(monkeypatch, "vermin")
    assert inc_m.incident_spawn()
    inc = inc_m.incidents_active()[0]
    core._store().purse_add(core._wid(), inc["giver"], 100)
    before = core._store().purse_get(core._wid(), inc["giver"])
    pc0 = core._store().purse_get(core._wid(), "pc")
    inc_m.incident_resolve(inc["id"], [])
    assert core._store().purse_get(core._wid(), inc["giver"]) == before - inc["reward"]
    assert core._store().purse_get(core._wid(), "pc") == pc0 + inc["reward"]
    p = world[inc["patron"]]
    assert p.state.rel("pc")["affinity"] > 0           # город помнит добро
