"""U4: ONE brain-knob registry — mind/tunables.BRAIN is the single source for every brain-affect
knob. PB splices it (PB.update(BRAIN)); decay/project/value read BRAIN directly. This one
splice-guard replaces the four per-mirror sync tests (decay/project/feel_nudge/self_regard): if the
splice ever drops or overrides a brain key, PB[k] != BRAIN[k] and this fails. Spec §4c/§5-U4/§10."""
from aidnd.mind.tunables import BRAIN

from aidnd.server.play.engine.session.config import PB


def test_pb_reexports_brain_tunables():
    # every brain knob is present in PB with the same value — the splice dropped/overrode nothing
    for k in BRAIN:
        assert PB[k] == BRAIN[k], f"PB[{k!r}] ({PB[k]!r}) != BRAIN[{k!r}] ({BRAIN[k]!r})"


def test_pb_carries_new_victim_knobs():
    # the five NEW U1 victim knobs are born in tunables and reach PB through the splice
    for k in ("ev_victim_harm_mult", "ev_victim_gi", "ev_victim_desert",
              "ev_victim_aff", "ev_victim_rel_fear"):
        assert k in PB and PB[k] == BRAIN[k]
