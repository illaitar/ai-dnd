"""Inc3 review-fix — the «новичок» impulse must reach ACTION, integration-tested through _live_tick
(not just synthetic NpcState): a sociable NPC co-present with an un-met newcomer SEES the fresh face
in its decision ctx (Fix A), and the ≤1-greeter lock fires on the ACTUAL greeting, never on mere
selection (Fix B) — a drawn NPC that does something else leaves the slot OPEN. Stub-manager, no LLM."""
import json
import os
import tempfile

import pytest

from aidnd.server.play.engine.core import PLAYER

_HINT = "новое лицо, к которому ты приглядываешься"    # the surfaced newcomer hint (Fix A)


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


def _stage_one_greeter(world_m, core_m, soc):
    """Reduce the built scene to a single NPC (+ the player) co-present at the entry spot, with a
    controlled sociability and a clean slate (never met the player → the player is a fresh face)."""
    lv = core_m._S["live"]
    w = lv["world"]
    assert lv.get("zones"), "fixture scene must have zones for a deterministic co-presence test"
    ent = lv["ent"]
    g = next(pid for pid in w.npc_minds if not w.bodies[pid].down())
    for pid in list(w.npc_minds):
        w.bodies[pid].place = "__offscene__"               # everyone else leaves — only g + player remain
    w.bodies[g].place = ent
    st = w.npc_minds[g]
    st.config.traits["sociability"] = soc
    st.relationships.clear()                               # g has met NOBODY → player is un-met
    st.familiarity.clear()
    for k in list(st.needs):
        st.needs[k] = 0.0                                  # no competing pull — greet can win «why»
    for k in list(st.emotion):
        st.emotion[k] = 0.0
    st.agendas = []
    lv.pop("salient", None)
    lv["greeted"] = set()
    return g


def _patch_stub(world_m, monkeypatch, decision):
    """Swap the model for a stub that records every prompt and returns a fixed decision. Returns the
    prompt list so a test can assert whether the newcomer hint reached the acting NPC's prompt."""
    prompts: list = []

    class _Stub:
        def call(self, kind, messages, schema=False, options=None):
            prompts.append(messages[-1]["content"])
            return {"content": json.dumps(decision)}

    monkeypatch.setattr(world_m, "_model", lambda: _Stub())
    return prompts


def test_sociable_sees_newcomer_hint_but_waiting_leaves_slot_open(live_scene, monkeypatch):
    # Fix A: the fresh face is surfaced into the sociable NPC's ctx. Fix B: it only WAITS (no
    # greeting) → the ≤1-greeter slot stays OPEN (not consumed on selection).
    world_m, core_m, people = live_scene
    _stage_one_greeter(world_m, core_m, soc=0.95)
    prompts = _patch_stub(world_m, monkeypatch,
                          {"think": "", "does": "стою молча", "actions": [{"tool": "wait"}]})

    world_m._live_tick(people)

    assert any(_HINT in p for p in prompts), "un-met newcomer must be VISIBLE in the sociable NPC's ctx"
    assert PLAYER not in core_m._S["live"]["greeted"], "no greeting happened → slot must stay open (Fix B)"


def test_actual_greeting_locks_the_slot(live_scene, monkeypatch):
    # Fix B: the drawn NPC really addresses the newcomer → the slot LOCKS (persisted, ≤1 greeter).
    world_m, core_m, people = live_scene
    _stage_one_greeter(world_m, core_m, soc=0.95)
    pname = core_m._S["live"]["names"][PLAYER]
    _patch_stub(world_m, monkeypatch,
                {"think": "поздороваюсь", "does": "иду к гостю",
                 "actions": [{"tool": "say", "to": pname, "text": "Будь как дома, странник!"}]})

    world_m._live_tick(people)

    assert PLAYER in core_m._S["live"]["greeted"], "an actual greeting must lock the ≤1-greeter slot (Fix B)"


def test_wary_room_raises_no_greeter_and_no_hint(live_scene, monkeypatch):
    # An unsociable NPC (≤0.5) feels no pull → «новичок» never wins, the newcomer is NOT surfaced,
    # and the slot is untouched (frontier wariness — emergent, never forced).
    world_m, core_m, people = live_scene
    _stage_one_greeter(world_m, core_m, soc=0.2)
    prompts = _patch_stub(world_m, monkeypatch,
                          {"think": "", "does": "занят своим", "actions": [{"tool": "wait"}]})

    world_m._live_tick(people)

    assert not any(_HINT in p for p in prompts), "a wary NPC must NOT be nudged toward the newcomer"
    assert PLAYER not in core_m._S["live"]["greeted"], "no greeter → slot untouched"
