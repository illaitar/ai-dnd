"""F5: an incident stamps bid+node onto its contract; incident_jobs appends a real direction to
the pitch; board_take marks the incident's building seen (map flag only — journal is quest-only
now) so F4's move-resolver and the map both point at it."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import core, incidents
from aidnd.server.play.engine.session import persist
from aidnd.worldgen import WorldStore


def _person(pid, name, role, home, work):
    st = NpcState.from_config(NpcConfig(id=pid, name=name, role=role))
    return SimpleNamespace(id=pid, name=name, role=role, home=home, work=work, persona={"a": 1},
                           state=st)


@pytest.fixture
def world(tmp_path, monkeypatch):
    st = WorldStore(str(tmp_path / "live.db"))
    monkeypatch.setattr(persist, "_STORE", st)
    st.save_building(1, "house:medovar", False, 372, "дом семьи Медовар",
                     {"name": "дом семьи Медовар", "type": "жилой дом"})
    people = {"p_med": _person("p_med", "Ольд Медовар", "пасечник", 372, None)}
    cr2b = {372: "house:medovar"}
    d = core._S._d(); saved = dict(d)
    try:
        d.clear()
        d.update(wid=1, gt=600, people=people, cr2b=cr2b, keynode={}, loc=50, city=None)
        yield st
    finally:
        d.clear(); d.update(saved)


def test_home_incident_binds_bid_and_node(world):
    t = {"key": "vermin", "goal": "clear", "env": "cellar", "cr": [1, 2], "victim": "home",
         "foe": "beasts", "title": "твари в подполе — {place}", "pitch": "{patron} зовёт на подмогу"}
    import random
    inc = incidents._try_build(t, {"p_med": core._S["people"]["p_med"]}, set(),
                               random.Random("t"))
    assert inc is not None
    assert inc["bid"] == "house:medovar"
    assert inc["node"] == 372


def test_incident_jobs_appends_direction(world, monkeypatch):
    # a bound incident contract on the board → its pitch carries a geo direction_line
    core._S["people"]["p_med"]  # ensure fixture wired
    world.save_contract(1, "inc|0|vermin", "incident", {
        "type": "vermin", "goal": "clear", "cr": 1.5, "title": "твари в подполе",
        "pitch": "Ольд Медовар зовёт на подмогу", "patron": "p_med", "reward": 8,
        "bid": "house:medovar", "node": 372})

    class _City:
        def route(self, a, b):
            from aidnd.citygraph.model import Nearby, Route
            return Route(found=True, nodes=[50, 60, 372], bearing="З",
                         near_target=Nearby("b_well", "колодец", 30.0), landmarks=[])
    core._S["city"] = _City()
    jobs = incidents.incident_jobs()
    assert jobs and "ходу" in jobs[0]["pitch"]           # direction appended
    assert jobs[0]["bid"] == "house:medovar"


def test_board_take_marks_incident_building_seen(world, monkeypatch):
    from aidnd.server.play.engine.pc.hero import _seen
    from aidnd.server.play.handlers import board as B

    world.save_contract(1, "inc|0|vermin", "incident", {
        "type": "vermin", "goal": "clear", "cr": 1.5, "title": "твари в подполе",
        "pitch": "зов", "patron": "p_med", "reward": 8, "bid": "house:medovar", "node": 372})
    job = {"id": "ct:inc:inc|0|vermin", "lair": "inc|0|vermin", "name": "твари в подполе",
           "cr": 1.5, "reward": 8, "kind": "clear", "pitch": "зов",
           "incident": True, "bid": "house:medovar"}
    monkeypatch.setattr(B, "_guild_board", lambda: [job])
    monkeypatch.setattr(B, "_guild_gate", lambda cr: None)
    monkeypatch.setattr(B, "_accept_contract", lambda *a, **k: "")
    monkeypatch.setattr(B, "_pc_remember", lambda *a, **k: None)

    import asyncio

    class _Req:
        async def json(self):
            return {"id": "ct:inc:inc|0|vermin"}

    monkeypatch.setattr(B, "_play", lambda: (None, {}, {}, {}, 50))
    asyncio.run(B.board_take(_Req()))
    assert "house:medovar" in _seen()                    # map flag set — no journal row (QJ rework)
