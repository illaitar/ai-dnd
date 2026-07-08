"""Ring A / ring B separation: NPCs present in the player's live scene are pinned OUT of the
world simulation (routine_step), so the two rings never both move the same NPC.

Key tests
---------
test_apply_routine_pins_present : _apply_routine passes exactly the present-set (NPCs at the
    player's node) as `pin`, so routine_step skips them.
test_routine_step_skips_pinned : routine_step leaves a pinned NPC's crof node untouched.
"""

import os
import tempfile

import pytest

from aidnd.server.play.engine import core, worldsim
from aidnd.server.play.engine import world as W
from aidnd.server.play.engine.session import persist


@pytest.fixture
def world(monkeypatch):
    from aidnd.worldgen import WorldStore
    monkeypatch.setattr(persist, "_STORE", WorldStore(os.path.join(tempfile.mkdtemp(), "live.db")))
    core._S["city"] = None
    W._play()
    core._S["gt"] = 8 * 60
    return core._S


def test_apply_routine_pins_present(world, monkeypatch):
    """_apply_routine hands routine_step the set of NPCs at the player's node as `pin`."""
    captured = {}
    monkeypatch.setattr(W, "routine_step", lambda people, crof, pin=None: captured.update(pin=pin))
    core._S["routine_key"] = None                 # force a routine step this call
    core._S["gt"] = core._S["gt"] + 60            # cross a 30-min bucket
    W._apply_routine()
    loc, crof = core._S["loc"], core._S["crof"]
    present = {pid for pid, n in crof.items() if n == loc}
    assert captured["pin"] == present             # exactly the present-set is pinned out


def test_routine_step_skips_pinned(world):
    """A pinned NPC keeps its node — routine_step does not move it."""
    crof = core._S["crof"]
    victim = next(iter(crof))
    before = crof[victim]
    worldsim.routine_step(core._S["people"], crof, pin={victim})
    assert crof[victim] == before                 # ring B left the pinned NPC where ring A holds it
