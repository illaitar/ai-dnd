"""U1: the victim = a signature-driven branch of project_event (event.target == witness.id). ONE
formula reproduces both raw victim blocks (attack + theft) within ±0.1. The whole affect lands
through project_and_apply (the same door as bystanders); the act sites keep only their memory line.
Bystander numbers are byte-identical (branch not taken — guarded in test_project_event.py). Spec
§3b/§4b/§5-U1."""
from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.event import Event
from aidnd.mind.project import project_and_apply, project_event


def _victim(vid, morals):
    cfg = NpcConfig(id=vid, name=vid, role="x", worldview={"morals": morals})
    return NpcState.from_config(cfg)   # NpcConfig defaults every trait to 0.5


def test_attack_victim_dims_reproduce_today_within_band():
    """A attacks B (12→6 hp): Event(A,B, intensity 0.6, threat 0.5, harm 0.5, [«насилие»]).
    Victim branch: visceral harm 0.30×1.8=0.54, gi floor −0.8, desert floor −0.75, control 0."""
    ev = Event("npc:att", "npc:vic", 0.6, 0.5, 0.5, ["насилие"])
    b = _victim("npc:vic", {"violence": -0.3})
    d = project_event(ev, b, perc=1.0, affinity_target=0.0)["dims"]
    assert d["harm"] == pytest.approx(0.54, abs=0.01)
    assert d["goal_impact"] == pytest.approx(-0.8, abs=0.01)
    assert d["desert"] == pytest.approx(-0.75, abs=0.01)
    assert d["control"] == pytest.approx(0.0, abs=0.001)


def test_attack_victim_end_to_end_grudge_and_emotion():
    """Through the real door (project_and_apply): B's tier reproduces today's 0.6/0.6/0.85/−0.3
    within ±0.1 → anger 0.66, fear 0.59, rel-fear 0.85, affinity −0.40, anchored."""
    ev = Event("npc:att", "npc:vic", 0.6, 0.5, 0.5, ["насилие"])
    b = _victim("npc:vic", {"violence": -0.3})
    project_and_apply(ev, [b], perceive=lambda w: 1.0)
    assert b.emotion["anger"] == pytest.approx(0.66, abs=0.02)
    assert b.emotion["fear"] == pytest.approx(0.59, abs=0.02)
    assert b.emotion["distress"] == pytest.approx(0.68, abs=0.03)   # in-band addition (being attacked IS distressing)
    assert b.emotion["disgust"] == pytest.approx(0.20, abs=0.03)    # in-band addition
    assert b.emotion_target["anger"] == "npc:att"
    r = b.rel("npc:att")
    assert r["affinity"] == pytest.approx(-0.40, abs=0.001)
    assert r["fear"] == pytest.approx(0.85, abs=0.001)
    assert r["anchored"] is True


def test_theft_victim_no_fear_anger_from_desert_floor():
    """Pickpocket: Event(PLAYER,npc, intensity 0.4, threat 0, harm 0, [«воровство»]). Threatless →
    visceral harm 0×1.8=0 → NO fear (matches today). Anger still fires from the desert floor;
    grudge affinity −0.40, anchored."""
    ev = Event("pc", "npc:vic", 0.4, 0.0, 0.0, ["воровство"])
    v = _victim("npc:vic", {"theft": -0.5})
    project_and_apply(ev, [v], perceive=lambda w: 1.0)
    assert v.emotion["fear"] == pytest.approx(0.0, abs=0.001)       # no fear on a pickpocket (exact)
    assert v.emotion["anger"] == pytest.approx(0.66, abs=0.02)
    r = v.rel("pc")
    assert r["affinity"] == pytest.approx(-0.40, abs=0.001)
    assert r["fear"] == pytest.approx(0.0, abs=0.001)               # threat 0 → rel-fear NOT set
    assert r["anchored"] is True
