"""familiarity_k co-presence ticks seed a faint unanchored tie; a never-met newcomer raises a
'новичок' greet impulse on a sociable NPC (emergent, ≤1 greeter). Spec §3/§10."""
import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.server.play.engine import world as W
from aidnd.server.play.engine.session.config import PB


def test_novichok_in_must_why():
    assert "новичок" in W._MUST_WHY                         # greet reason always thinks when picked


def test_greet_impulse_scales_with_sociability():
    hi = W._greet_impulse(0.9)
    lo = W._greet_impulse(0.4)
    assert hi > lo and lo == 0.0                            # unsociable NPC feels no pull
    assert hi == pytest.approx(PB["greet_sociability_base"] * 0.4, abs=1e-6)


def test_familiarity_seeds_faint_unanchored_tie():
    st = NpcState.from_config(NpcConfig(id="npc:o", name="О", role="x"))
    for _ in range(PB["familiarity_k"]):
        W._accrue_familiarity(st, "npc:other")
    rel = st.rel("npc:other")
    assert rel["affinity"] > 0.0 and rel["anchored"] is False   # loose — fades if contact lapses
    # one shy of the threshold → no tie yet, and the player stays out of relationships
    st2 = NpcState.from_config(NpcConfig(id="npc:p", name="П", role="x"))
    for _ in range(PB["familiarity_k"] - 1):
        W._accrue_familiarity(st2, "npc:q")
    assert "npc:q" not in st2.relationships                 # never met until the K-th co-presence tick
    assert st2.rel("npc:q")["affinity"] == 0.0              # (rel() just now created a blank row)


def test_accrue_on_known_person_is_noop():
    # a KNOWN person (a rel row already exists) accrues no familiarity and is never re-seeded
    st = NpcState.from_config(NpcConfig(id="npc:a", name="А", role="x"))
    st.rel("npc:known")["affinity"] = 0.6                   # a real, warm tie
    for _ in range(PB["familiarity_k"] + 3):
        W._accrue_familiarity(st, "npc:known")
    assert st.familiarity.get("npc:known", 0) == 0         # no counter for an acquaintance
    assert st.rel("npc:known")["affinity"] == 0.6          # untouched — accrual never overwrites


def test_pick_newcomer_only_fresh_faces():
    st = NpcState.from_config(NpcConfig(id="npc:h", name="Х", role="x"))
    st.rel("npc:friend")["affinity"] = 0.4                  # known — not a newcomer
    greeted = {"npc:already"}                               # already greeted this scene — no repeat
    assert W._pick_newcomer(st, ["npc:friend", "npc:already", "npc:fresh"], greeted) == "npc:fresh"
    # a room of only known/greeted faces yields no greet candidate
    assert W._pick_newcomer(st, ["npc:friend", "npc:already"], greeted) is None
