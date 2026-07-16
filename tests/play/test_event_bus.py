"""The Event bus end to end (МОЗГ Inc2): a staged act projects onto every perceiving witness via
`project_and_apply`, and their affect SPLITS by worldview — a Багровый-type barely stirs (faint
grim joy, no disgust) while a peasant-type recoils in fear + disgust. A far witness who can't
perceive gets nothing; co-presence stays a separate channel (a bare «видит» event is inert, so it
never double-counts the appraise_present read); a gift warms only the recipient's view of the giver.
Mirrors spec §5A + §7, as a unit test over the fan-out. Zero LLM.
"""

from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.event import Event
from aidnd.mind.project import project_and_apply


def _st(name, traits, wv, node=1):
    s = NpcState.from_config(NpcConfig(id="npc:" + name, name=name, role="x",
                                       traits=traits, worldview=wv))
    s.node = node
    return s


def test_kill_splits_crowd_by_worldview():
    """One kill, two lenses: the cultist ally is faintly glad (joy, no disgust); the peasant
    shopkeeper recoils (disgust + fear). One signature row, two lands — worldview alone."""
    merek = _st("merek", {"empathy": 0.16, "bravery": 0.78, "pride": 0.45},
                {"morals": {"death": 0.84, "violence": 0.83}, "taboos": []})
    selma = _st("selma", {"empathy": 0.49, "bravery": 0.52},
                {"morals": {"death": -0.23, "violence": -0.18}, "taboos": []})
    ev = Event("pc", "npc:beggar", 0.9, 0.7, 1.0, ["убийство", "насилие", "смерть"], zone="зал")
    project_and_apply(ev, [merek, selma], perceive=lambda w: 1.0)   # same zone → 1.0
    assert merek.emotion["joy"] > 0.0
    assert merek.emotion["disgust"] == pytest.approx(0.0, abs=0.02)
    assert selma.emotion["disgust"] > 0.15
    assert selma.emotion["fear"] > 0.3
    assert selma.rel("pc")["fear"] > 0.0
    assert selma.rel("pc")["anchored"] is False              # a bystander grudge stays loose


def test_actor_never_appraises_own_act():
    """The killer is in the witness list but must not react to its own deed via the bus."""
    killer = _st("killer", {"bravery": 0.6}, {"morals": {"death": -0.5}})
    killer.config.id = "pc"
    ev = Event("pc", "npc:beggar", 0.9, 0.7, 1.0, ["убийство"], zone="зал")
    project_and_apply(ev, [killer], perceive=lambda w: 1.0)
    assert all(v == 0.0 for v in killer.emotion.values())


def test_far_witness_untouched():
    """A witness out of earshot (audibility → None → perc 0) gets no affect and no relationship."""
    far = _st("far", {"bravery": 0.5}, {"morals": {"death": -0.5}}, node=99)
    ev = Event("pc", "npc:beggar", 0.9, 0.7, 1.0, ["убийство"], zone="зал")
    project_and_apply(ev, [far], perceive=lambda w: 0.0)
    assert all(v == 0.0 for v in far.emotion.values())
    assert "pc" not in far.relationships


def test_copresence_event_is_inert_no_double_count():
    """Co-presence stays its own channel (appraise_present). Routing a bare «видит» surface event
    through the bus yields ZERO affect (no threat/harm/moral-tag) — so the two channels can coexist
    without double-counting the co-presence read."""
    w = _st("w", {"bravery": 0.5}, {"morals": {"death": -0.5}})
    seen = Event("npc:other", "npc:w", 0.05, 0.0, 0.0, ["видит"], zone="зал")
    project_and_apply(seen, [w], perceive=lambda x: 1.0)
    assert all(v == 0.0 for v in w.emotion.values())


def test_gift_warms_only_recipient_view_of_giver():
    """A gift (target_harm 0) warms ONLY the recipient's affinity toward the giver; a bystander
    who merely watches is unmoved toward the giver."""
    giver, recipient, bystander = "npc:giver", "npc:recip", "npc:bystd"
    r = _st("recip", {"empathy": 0.6}, {})
    r.config.id = recipient
    b = _st("bystd", {"empathy": 0.6}, {})
    b.config.id = bystander
    gift = Event(giver, recipient, 0.2, 0.0, 0.0, ["дар"], zone="зал")
    project_and_apply(gift, [r, b], perceive=lambda x: 1.0)
    assert r.rel(giver)["affinity"] > 0.0                    # recipient warms to the giver
    assert r.rel(giver)["anchored"] is True                  # gift acceptance is anchored (spec §4.3)
    assert giver not in b.relationships or b.rel(giver)["affinity"] == 0.0  # bystander unmoved
    assert all(v == 0.0 for v in r.emotion.values())         # a gift stirs no emotion channel


def test_targetless_menace_splits_crowd_by_worldview():
    """A drawn weapon aimed at NO ONE still radiates fear to the room: target="" → aff_t=0,
    target_warmth=0, but the VISCERAL channel (harm = physical_threat × rel(actor).fear-prior ×
    (1 − viol_damp × violence_approval)) fires purely off physical_threat. A peasant (violence
    morals negative) flinches; a violence-approving cutthroat barely reacts."""
    peasant = _st("peasant", {"empathy": 0.5, "bravery": 0.3},
                  {"morals": {"violence": -0.4}, "taboos": []})
    cutthroat = _st("cutthroat", {"empathy": 0.2, "bravery": 0.8},
                     {"morals": {"violence": 0.9}, "taboos": []})
    ev = Event("pc", "", 0.5, 0.5, 0.0, ["угроза", "насилие"], zone="зал")
    project_and_apply(ev, [peasant, cutthroat], perceive=lambda w: 1.0)
    assert peasant.emotion["fear"] > 0.1
    assert cutthroat.emotion["fear"] < peasant.emotion["fear"]
    assert peasant.rel("pc")["fear"] > 0.0
    assert peasant.rel("pc")["anchored"] is False           # ambient menace stays a loose read
    assert "" not in peasant.relationships                  # empty target never gets a rel entry


def test_gift_warmth_clamped_and_stays_anchored():
    """Repeated gifts must not blow past affinity's ±1.0 ceiling (spec §4.3 anchored write), and the
    tie stays anchored (slow decay) rather than reverting to a loose bystander-style read."""
    giver, recipient = "npc:giver", "npc:recip"
    r = _st("recip", {"empathy": 0.9}, {})
    r.config.id = recipient
    gift = Event(giver, recipient, 0.9, 0.0, 0.0, ["дар"], zone="зал")
    for _ in range(6):
        project_and_apply(gift, [r], perceive=lambda x: 1.0)
    assert r.rel(giver)["affinity"] <= 1.0
    assert r.rel(giver)["affinity"] >= -1.0
    assert r.rel(giver)["anchored"] is True
