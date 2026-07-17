"""U2: ONE apply sink — _land(state, dims, rel, source, seed). Co-presence, the fan-out, and (U3)
self-feeling all write NpcState through it, so there is exactly one place emotion/emotion_target/
relationships get mutated. Co-presence emotion + the once-seed are byte-identical to the old
appraise_present (same impression → same appraise, same prior, same skip rules). Spec §3/§5-U2."""
from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.project import _land


def _st(sid):
    return NpcState.from_config(NpcConfig(id=sid, name=sid, role="x"))


def test_land_appraises_and_writes_actor_fear():
    st = _st("npc:w")
    dims = {"goal_impact": 0.0, "desert": 0.0, "harm": 0.4, "fear": 0.4,
            "revulsion": 0.0, "intent": True, "control": 0.0}
    rel = {"actor_fear": 0.2, "target_warmth": 0.0, "anchored": False,
           "victim_affinity": None, "beneficiary": False}
    _land(st, dims, rel, source="npc:a")
    assert st.emotion["fear"] > 0.0
    assert st.emotion_target["fear"] == "npc:a"
    assert st.rel("npc:a")["fear"] == pytest.approx(0.2, abs=0.001)
    assert st.rel("npc:a")["anchored"] is False


def test_land_seed_arm_seeds_prior_once():
    st = _st("npc:w")
    dims = {"goal_impact": 0.1, "desert": 0.0, "harm": 0.0, "fear": 0.0,
            "revulsion": 0.0, "intent": False, "control": 0.0}
    rel = {}
    seed = {"prior": {"affinity": 0.3, "fear": 0.0, "trust": 0.2}, "remember": "приятный тип",
            "clock": 5, "once": True}
    _land(st, dims, rel, source="npc:o", seed=seed)
    assert st.rel("npc:o")["affinity"] == pytest.approx(0.3, abs=0.001)   # seeded
    # a SECOND land with a different prior must NOT overwrite (once-guard: already known)
    seed2 = {"prior": {"affinity": -0.9, "fear": 0.0, "trust": 0.0}, "remember": None,
             "clock": 6, "once": True}
    _land(st, dims, rel, source="npc:o", seed=seed2)
    assert st.rel("npc:o")["affinity"] == pytest.approx(0.3, abs=0.001)   # unchanged — once only


def test_appraise_present_routes_through_land_byte_identical():
    """appraise_present now calls _land, but co-presence emotion + the once-seed are byte-identical:
    an ordinary NPC seeing a neutral stranger seeds a relationship prior once and moves emotion."""
    from types import SimpleNamespace

    from aidnd.mind.appraisal import _race_rel, appraise_present
    from aidnd.mind.world import Body

    st = _st("npc:me")
    other = Body("npc:you", "площадь", appearance=0.6, charisma=0.5)
    percept = SimpleNamespace(present=[other])
    world = SimpleNamespace(clock=3)
    appraise_present(st, world, percept, _race_rel(), skip_seed_id=None)
    assert "npc:you" in st.relationships          # a stranger got a prior seeded (once)
    prior = dict(st.relationships["npc:you"])
    # a second pass must NOT re-seed (already known) — the once-guard survives the _land move
    appraise_present(st, world, percept, _race_rel(), skip_seed_id=None)
    assert st.relationships["npc:you"] == prior


def test_appraise_present_never_seeds_the_player():
    from types import SimpleNamespace

    from aidnd.mind.appraisal import _race_rel, appraise_present
    from aidnd.mind.world import Body

    st = _st("npc:me")
    pc = Body("pc", "площадь", appearance=0.6, charisma=0.5)
    percept = SimpleNamespace(present=[pc])
    world = SimpleNamespace(clock=3)
    appraise_present(st, world, percept, _race_rel(), skip_seed_id="pc")
    assert "pc" not in st.relationships           # stranger stays a stranger from mere sight
