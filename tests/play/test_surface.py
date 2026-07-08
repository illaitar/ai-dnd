"""Проекция видимой поверхности (раса/грязь/метки) на Body сцены (Task 6, docs/mind.md)."""

import os
import tempfile

import pytest

from aidnd.server.play.engine import core
from aidnd.server.play.engine.session import persist


@pytest.fixture
def world(monkeypatch):
    from aidnd.server.play.engine import world as world_m
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(persist, "_STORE",
                        WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None                              # форс пересборки мира в СВЕЖИЙ store
    # agenda planning is LLM-backed and irrelevant here — stub it so the fixture is deterministic
    monkeypatch.setattr(world_m, "plan_agenda", lambda *a, **k: None)
    city, people, crof, cr2b, loc = world_m._play()      # трактир заведён стартовой точкой
    world_m._live_build(city, people, crof, cr2b, loc)   # собрать живую сцену (mind-world)
    return people


def test_present_npc_body_has_visible_surface(world):
    people = world
    w = core._S["live"]["world"]
    npc_ids = [pid for pid in w.bodies if pid != "pc"]
    assert npc_ids, "в живой сцене нет ни одного горожанина"
    pid = min(npc_ids, key=lambda i: people[i].appearance)  # беднейший из присутствующих
    body, persona = w.bodies[pid], people[pid].persona or {}
    assert body.race == (persona.get("race") or "человек")
    assert body.race != "human"                           # не дефолт датакласса Body — из персоны
    assert 0.0 <= body.squalor <= 1.0
    assert body.squalor > 0.0                              # бедный горожанин читается грязнее нуля
    assert body.marks == list((persona.get("look") or {}).get("marks") or [])


def test_player_body_has_race(world):
    w = core._S["live"]["world"]
    assert w.bodies["pc"].race == "человек"
