"""Слой A (интент-прогноз, docs/citysim.md §A): predict/forecast/crosses + обязательства."""

import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine import worldsim as ws


@pytest.fixture
def world(monkeypatch):
    from aidnd.server.play.engine.world import _play
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(core, "_STORE",
                        WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    _city, people, _crof, _cr2b, _loc = _play()
    core._S["gt"] = 9 * 60
    ws.routine_step(people, core._S["crof"])
    return people


def test_predict_deterministic_and_shaped(world):
    pid = next(iter(world))
    a = ws.predict(pid, "evening")
    b = ws.predict(pid, "evening")
    assert a == b                                      # детерминированный запрос
    assert a["kind"] in (None, "home", "work", "tavern", "temple", "market", "street",
                         "patrol", "prowl")
    assert isinstance(a["route"], list)


def test_forecast_is_a_day(world):
    pid = next(iter(world))
    fc = ws.forecast(pid)
    assert set(fc) == {"morning", "day", "evening", "night"}


def test_follow_pins_to_player_but_yields_to_need(world):
    pid = next(pid for pid, p in world.items() if p.role == "горожанин")
    core._S["loc"] = 500
    world[pid].state.needs["fatigue"] = 0.1           # сыт/бодр — идёт за игроком
    world[pid].state.needs["hunger"] = 0.1
    ws.set_commit(pid, "follow")
    ws.routine_step(world, core._S["crof"])
    assert core._S["crof"][pid] == 500                 # follow: у игрока
    world[pid].state.needs["fatigue"] = 0.95          # валится с ног — критнужда важнее
    ws.routine_step(world, core._S["crof"])
    assert core._S["crof"][pid] != 500                 # отошёл (спать/есть)
    ws.clear_commit(pid)


def test_crosses_interception(world):
    pid = next(iter(world))
    pr = ws.predict(pid, "evening")
    if pr["route"]:
        assert ws.crosses(pid, pr["route"][len(pr["route"]) // 2], "evening")
    assert ws.crosses(pid, pr["node"], "evening") is True
