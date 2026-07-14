# tests/play/test_pin.py
"""Inc4 — unpin: scene NPCs are NO LONGER pinned out of the sim. routine_step has no `pin` param;
a present NPC the routine moves actually leaves (its departure rides Inc1's leaver-diff). The one
exception is polite postpone: a pid mid-conversation with the player (_S['dlg']==pid) has its move
skipped ONE slot, then leaves. No LLM."""
import os
import tempfile

import pytest

from aidnd.server.play.engine import core, worldsim
from aidnd.server.play.engine import world as W
from aidnd.server.play.engine.core import PB
from aidnd.server.play.engine.loop import routine as loop_routine
from aidnd.server.play.engine.session import persist


@pytest.fixture
def world(monkeypatch):
    from aidnd.worldgen import WorldStore
    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None
    saved = dict(core._S._d())
    try:
        W._play()
        # a FRESH world starts with no simulation-derived leftovers from a previous test's world
        # (some fixtures in this suite don't restore _S fully — pids can collide across the
        # shared pool, so a stale transit/postpone entry could otherwise bleed into this world).
        core._S["transit"] = {}
        core._S["depart_postpone"] = {}
        core._S["gt"] = 8 * 60
        yield core._S
    finally:
        d = core._S._d()
        d.clear()
        d.update(saved)


def test_routine_step_has_no_pin_param():
    import inspect
    assert "pin" not in inspect.signature(worldsim.routine_step).parameters


def test_apply_routine_calls_without_pin(world, monkeypatch):
    captured = {}
    monkeypatch.setattr(loop_routine, "routine_step",
                        lambda people, crof: captured.update(called=True))
    core._S["routine_key"] = None
    core._S["gt"] = core._S["gt"] + 60
    W._apply_routine()
    assert captured.get("called")               # invoked with (people, crof) only — no pin kwarg


def test_present_npc_is_moved(world):
    # a present NPC (at the player's loc) is NOT skipped: over enough slots the sim may relocate it
    crof, loc = core._S["crof"], core._S["loc"]
    present = [pid for pid, n in crof.items() if n == loc]
    assert present, "fixture must place someone at the player's node"
    victim = present[0]
    core._S.pop("dlg", None)                     # not in conversation → eligible to move
    moved = False
    for k in range(1, 40):                        # advance several 30-min slots
        core._S["routine_key"] = None
        core._S["gt"] = 8 * 60 + k * 60
        before = crof.get(victim)
        worldsim.routine_step(core._S["people"], crof)
        if crof.get(victim) != before or victim in (core._S.get("transit") or {}):
            moved = True
            break
    assert moved                                  # ring B is free to move a present NPC now


def test_mid_conversation_postpones_one_slot(world):
    crof, loc = core._S["crof"], core._S["loc"]
    victim = next(pid for pid, n in crof.items() if n == loc)
    other = next(n for n in crof.values() if n != loc)   # some other real node in this world
    worldsim.set_commit(victim, "errand", node=other)     # FORCE a real departure this slot — the
                                                            # postpone guard must not depend on the
                                                            # pooled routine's stochastic choice
    core._S["dlg"] = victim                        # talking to the player → polite postpone
    core._S["depart_postpone"] = {}
    before = crof.get(victim)
    worldsim.routine_step(core._S["people"], crof)
    # this slot: skipped (still at loc, not in transit), counter bumped
    assert crof.get(victim) == before and victim not in (core._S.get("transit") or {})
    assert core._S["depart_postpone"].get(victim) == PB["depart_postpone_slots"]
