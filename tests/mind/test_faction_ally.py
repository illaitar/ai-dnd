"""Своя фракция = союзник: NPC делящие allegiance (стража/гильдия/культ/клан/шайка — see
Body.faction, seeded from the 1354-NPC pool) count each other as in-group allies even with
no прежней relationship — so guild-mates/guards/cultists defend their own (see _u_protect via
propose_goals' protect-goal gate in goals.py, which filters candidates through _is_ally).
"""

from __future__ import annotations

from aidnd.mind.value import _is_ally
from aidnd.mind.world import Body


class _StubState:
    """Minimal stand-in — _is_ally only reads .relationships."""
    def __init__(self, relationships=None):
        self.relationships = relationships or {}


def test_shared_real_faction_is_ally_with_no_relationship():
    state = _StubState()
    me = Body(id="guard1", place="gate", faction="стража")
    b = Body(id="guard2", place="gate", faction="стража")
    assert _is_ally(state, me, b) is True


def test_shared_default_faction_town_is_not_ally():
    state = _StubState()
    me = Body(id="citizen1", place="square")          # faction defaults to "town"
    b = Body(id="citizen2", place="square")
    assert _is_ally(state, me, b) is False


def test_different_real_factions_not_ally():
    state = _StubState()
    me = Body(id="guard1", place="gate", faction="стража")
    b = Body(id="cultist1", place="gate", faction="культ-тени")
    assert _is_ally(state, me, b) is False


def test_high_affinity_without_shared_faction_still_ally():
    state = _StubState(relationships={"friend": {"affinity": 0.5}})
    me = Body(id="me", place="square")                # faction "town" (default)
    b = Body(id="friend", place="square")              # faction "town" too, but affinity carries it
    assert _is_ally(state, me, b) is True
