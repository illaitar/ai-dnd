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
"""

from aidnd.mind.appraisal import appraise_present, impression, load_race_relations, race_sentiment
from aidnd.mind.model import EMOTIONS, NpcConfig, NpcState
from aidnd.mind.sim import perceive
from aidnd.mind.tick import appraise
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
