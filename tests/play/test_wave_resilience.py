"""Fragility fix: ThreadPoolExecutor.map (in the LLM decision wave) re-raises the FIRST worker
exception on iteration. decide_hybrid can raise LLMBadOutput/LLMUnavailable per-actor (transient
model hiccup) — before the fix, ONE background NPC's failure aborted the WHOLE tick (502/503 to
the player), even though the failure has nothing to do with the player's own turn.

Fix: think_one retries once, then on a second failure logs a warning and yields (pid, None) —
the actor simply idles this tick (no fabricated action/narration). The wave completes; every
OTHER actor's decision still applies normally."""
import os
import tempfile

import pytest

from aidnd.inference import LLMBadOutput


@pytest.fixture
def live_scene(monkeypatch):
    from aidnd.server.play.engine import core as core_m
    from aidnd.server.play.engine import world as world_m
    from aidnd.server.play.engine.session import persist
    from aidnd.worldgen import WorldStore

    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core_m._S["city"] = None
    monkeypatch.setattr(world_m, "plan_agenda", lambda *a, **k: None)   # LLM-backed — irrelevant here
    saved = dict(core_m._S._d())
    try:
        city, people, crof, cr2b, loc = world_m._play()
        core_m._S["live"] = None
        world_m._live_build(city, people, crof, cr2b, loc)
        yield world_m, core_m, people
    finally:
        d = core_m._S._d()
        d.clear()
        d.update(saved)


def _stage_two(world_m, core_m):
    """Reduce the built scene to exactly two co-present NPCs (+ player), clean slate so both
    get selected to think (small scene => everyone thinks, no LOD gating)."""
    lv = core_m._S["live"]
    w = lv["world"]
    ent = lv["ent"]
    npcs = [pid for pid in w.npc_minds if not w.bodies[pid].down()][:2]
    assert len(npcs) == 2, "fixture scene must have at least 2 living NPCs"
    for pid in list(w.npc_minds):
        w.bodies[pid].place = "__offscene__"
    for pid in npcs:
        w.bodies[pid].place = ent
        st = w.npc_minds[pid]
        for k in list(st.needs):
            st.needs[k] = 0.0
        for k in list(st.emotion):
            st.emotion[k] = 0.0
        st.agendas = []
    lv.pop("salient", None)
    lv["greeted"] = set()
    return npcs


def test_one_actors_llm_failure_does_not_abort_the_wave(live_scene, monkeypatch):
    world_m, core_m, people = live_scene
    bad_pid, good_pid = _stage_two(world_m, core_m)

    def fake_decide(state, world, percept, manager, ctx):
        if state.config.id == bad_pid:
            raise LLMBadOutput("npc_mind: боевая симуляция сбоя модели")
        return {"think": "", "does": "ждёт", "actions": [{"tool": "wait"}], "prefs": [], "src": "llm"}

    monkeypatch.setattr(world_m, "decide_hybrid", fake_decide)

    feed, address = world_m._live_tick(people)  # must NOT raise — the tick survives

    assert isinstance(feed, list)


def test_failed_actor_decision_is_absent_or_none_others_still_applied(live_scene, monkeypatch):
    world_m, core_m, people = live_scene
    bad_pid, good_pid = _stage_two(world_m, core_m)
    calls: list = []

    def fake_decide(state, world, percept, manager, ctx):
        calls.append(state.config.id)
        if state.config.id == bad_pid:
            raise LLMBadOutput("npc_mind: боевая симуляция сбоя модели")
        return {"think": "", "does": "объявляет о себе", "actions": [{"tool": "wait"}],
                "prefs": [], "src": "llm"}

    monkeypatch.setattr(world_m, "decide_hybrid", fake_decide)

    feed, _address = world_m._live_tick(people)

    texts = [e.get("text", "") for e in feed]
    assert any("объявляет о себе" in t for t in texts), "good actor's decision applied to the feed"
    assert not any(e.get("pid") == bad_pid for e in feed), "bad actor produced no fabricated action"


def test_bad_actor_is_retried_once_before_giving_up(live_scene, monkeypatch):
    world_m, core_m, people = live_scene
    bad_pid, good_pid = _stage_two(world_m, core_m)
    attempts = {"n": 0}

    def fake_decide(state, world, percept, manager, ctx):
        if state.config.id == bad_pid:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise LLMBadOutput("first transient failure")
            return {"think": "", "does": "оправился со второй попытки",
                    "actions": [{"tool": "wait"}], "prefs": [], "src": "llm"}
        return {"think": "", "does": "", "actions": [{"tool": "wait"}], "prefs": [], "src": "llm"}

    monkeypatch.setattr(world_m, "decide_hybrid", fake_decide)

    feed, _address = world_m._live_tick(people)

    assert attempts["n"] == 2, "one retry expected after the first transient failure"
    texts = [e.get("text", "") for e in feed]
    assert any("оправился со второй попытки" in t for t in texts), (
        "the actor's SECOND-attempt decision must apply — retry succeeded, no idling"
    )
