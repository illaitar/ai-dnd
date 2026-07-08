"""Converse crowd-repulsion + nearby-friend seeking (tavern playtest). A converse target already
surrounded draws less than a free acquaintance, so NPCs form small groups across the room instead of
mobbing the one popular person; and in a leisure venue an idle NPC seeks a NEARBY acquaintance (goes
to sit with a friend), not only same-zone bodies.

Key tests
---------
test_free_friend_beats_crowded_magnet   : a lone friend out-draws a crowded high-charisma magnet.
test_leisure_seeks_nearby_acquaintance  : a leisure venue makes an idle NPC seek a nearby friend
    (without the venue lift, an NPC alone in its zone gets no converse target).
"""

from aidnd.mind import Body, perceive
from aidnd.mind import World as MWorld
from aidnd.mind.goals import propose_goals
from aidnd.mind.model import NpcConfig, NpcState


def _tavern():
    w = MWorld()
    for z in ("зал", "бар", "угол"):
        for z2 in ("зал", "бар", "угол"):
            if z != z2:
                w.link(z, z2)
    return w


def _npc(w, i, place, charisma=0.3, lz=0.0):
    cfg = NpcConfig(id=i, name=i, role="горожанин", level=1, max_hp=10, traits={"sociability": 0.6})
    st = NpcState(config=cfg)
    st.needs["social"] = 0.6
    st.venue_social = lz
    w.add(Body(id=i, place=place, charisma=charisma))
    return st


def test_free_friend_beats_crowded_magnet():
    w = _tavern()
    a = _npc(w, "A", "зал", lz=3.0)
    _npc(w, "M", "бар", charisma=0.6)                    # high-charisma magnet...
    for k in range(6):
        _npc(w, f"c{k}", "бар")                          # ...already surrounded by six
    _npc(w, "F", "угол")                                 # a friend alone in the corner
    for who in ("M", "F"):
        a.relationships[who] = {"affinity": 0.3, "trust": 0.15, "fear": 0.0}
    draw = {g.target: g.value for g in propose_goals(a, w, perceive(a, w)) if g.kind == "converse"}
    assert draw.get("F", 0.0) > draw.get("M", 0.0)       # peel off to the free friend, not the mob


def test_leisure_seeks_nearby_acquaintance():
    w = _tavern()
    a = _npc(w, "A", "зал", lz=3.0)                      # alone in зал
    _npc(w, "F", "угол")                                 # a friend a zone away
    a.relationships["F"] = {"affinity": 0.3, "trust": 0.15, "fear": 0.0}
    convs = [g.target for g in propose_goals(a, w, perceive(a, w)) if g.kind == "converse"]
    assert "F" in convs                                  # venue lift → seek out the nearby friend
