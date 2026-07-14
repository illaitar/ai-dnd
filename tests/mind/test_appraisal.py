"""Tests for the appraisal function (measurement dims -> emotion deltas).

Key functions
-------------
test_revulsion_raises_disgust : revulsion dim raises disgust emotion + sets emotion_target.
test_body_surface_defaults_and_armed : Body exposes race/squalor/marks + armed() from carrying.
test_race_sentiment : race_sentiment reads the race_relations table (self, authored pair, unknown).
test_proud_recoils_from_squalor : a proud observer reads a squalid beggar with negative valence.
test_race_enemy_stirs_anger_and_fear : culture (race_sentiment) drives negative valence + desert.
test_personal_bond_overrides_race_hate : an existing personal affinity outweighs race hostility.
test_appraise_present_moves_emotion_and_seeds_prior : appraise_present applies impression emotion
    deltas and seeds a fresh relationship prior from a present body.
test_proxemics_moves_away_from_disliked : move-utility proxemics term scores fleeing a disliked
    other higher than approaching them (Task 7).
test_appraise_present_never_seeds_relationship_for_skip_id : a stranger stays a stranger — the
    player (or any id passed as skip_seed_id) never gets a relationship/memory auto-seeded from
    mere co-presence, even though emotion still moves each tick (regression: brand-new NPC greeted
    the player as an old acquaintance because appraise_present seeded ~0.2-0.3 trust from a single
    first-glance impression, before any real interaction).
"""

from aidnd.mind.act import Action
from aidnd.mind.appraisal import appraise_present, impression, load_race_relations, race_sentiment
from aidnd.mind.goals import Goal
from aidnd.mind.model import EMOTIONS, NpcConfig, NpcState
from aidnd.mind.sim import perceive
from aidnd.mind.tick import appraise
from aidnd.mind.value import utility
from aidnd.mind.world import Body, Item, World


def test_revulsion_raises_disgust():
    assert "disgust" in EMOTIONS
    st = NpcState.from_config(NpcConfig(id="npc:x", traits={"pride": 0.9}))
    appraise(st, {"revulsion": 0.8}, source="beggar")
    assert st.emotion["disgust"] > 0.3
    assert st.emotion_target.get("disgust") == "beggar"


def test_body_surface_defaults_and_armed():
    b = Body(id="x", place="зал", race="орк", squalor=0.7, carrying=[Item("нож", 0.2, kind="weapon")])
    assert b.race == "орк" and b.squalor == 0.7
    assert b.armed() is True
    assert Body(id="y", place="зал").armed() is False   # empty-handed default


def test_race_sentiment():
    rr = load_race_relations()
    assert race_sentiment(rr, "человек", "человек") >= 0.0
    assert race_sentiment(rr, "дворф", "орк") < 0.0      # authored enmity
    assert race_sentiment(rr, "человек", "неведомый") == 0.0   # unknown -> neutral


def test_proud_recoils_from_squalor():
    imp = impression(
        NpcState.from_config(NpcConfig(id="obs", race="человек", traits={"pride": 0.9})),
        Body(id="beg", place="зал", appearance=0.05, squalor=0.8), {})
    assert imp.valence < 0 and imp.emo.get("revulsion", 0) > 0.3


def test_race_enemy_stirs_anger_and_fear():
    rr = load_race_relations()
    dwarf = NpcState.from_config(NpcConfig(id="d", race="дворф", traits={"bravery": 0.4}))
    imp = impression(dwarf, Body(id="o", place="зал", race="орк"), rr)
    assert imp.valence < 0 and imp.emo.get("desert", 0) < 0


def test_personal_bond_overrides_race_hate():
    rr = load_race_relations()
    dwarf = NpcState.from_config(NpcConfig(id="d", race="дворф"))
    dwarf.rel("o")["affinity"] = 0.8            # he saved my life
    imp = impression(dwarf, Body(id="o", place="зал", race="орк"), rr)
    assert imp.valence > 0                       # personal beats culture


def test_appraise_present_moves_emotion_and_seeds_prior():
    w = World(); w.link("зал", "улица")
    obs = NpcState.from_config(NpcConfig(id="obs", race="человек", traits={"pride": 0.9}))
    w.add(Body(id="obs", place="зал")); w.bodies["obs"]  # ensure present
    w.add(Body(id="beg", place="зал", appearance=0.05, squalor=0.8))
    appraise_present(obs, w, perceive(obs, w), load_race_relations())
    assert obs.emotion["disgust"] > 0.2
    assert "beg" in obs.relationships and obs.relationships["beg"]["affinity"] < 0


def test_appraise_present_never_seeds_relationship_for_skip_id():
    w = World(); w.link("зал", "улица")
    obs = NpcState.from_config(NpcConfig(id="obs", race="человек", traits={"sociability": 0.5}))
    w.add(Body(id="obs", place="зал"))
    w.add(Body(id="pc", place="зал", charisma=0.45))       # a brand-new player body, freshly placed
    appraise_present(obs, w, perceive(obs, w), load_race_relations(), skip_seed_id="pc")
    assert "pc" not in obs.relationships             # no mechanical trust/affinity from mere sight
    assert not any("pc" in (m.about or []) for m in obs.memory.items)   # no first-glance memory either

    # sanity: the SAME body, appraised WITHOUT skip_seed_id, seeds normally (proves the skip
    # is what suppresses it, not something else about the player-shaped Body)
    obs2 = NpcState.from_config(NpcConfig(id="obs2", race="человек", traits={"sociability": 0.5}))
    w.add(Body(id="obs2", place="зал"))
    appraise_present(obs2, w, perceive(obs2, w), load_race_relations())
    assert "pc" in obs2.relationships


def test_proxemics_moves_away_from_disliked():
    """A disliked other stands at place A; B is a free place. Fleeing (move->B) must score
    higher than approaching (move->A) under a goal that doesn't itself favor either destination."""
    w = World(); w.link("C", "A"); w.link("C", "B")
    me = NpcState.from_config(NpcConfig(id="me"))
    w.add(Body(id="me", place="C"))
    w.add(Body(id="foe", place="A"))
    me.rel("foe")["affinity"] = -0.7          # disliked (Task 5 would have seeded this)

    percept = perceive(me, w)
    g = Goal(kind="need", target="dummy", value=0.0)   # no source -> move base is destination-agnostic

    u_a = utility(Action("move", to="A"), g, me, w, percept)
    u_b = utility(Action("move", to="B"), g, me, w, percept)

    assert u_b > u_a                          # moving away from the disliked other scores higher
