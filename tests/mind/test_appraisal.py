"""Tests for the appraisal function (measurement dims -> emotion deltas).

Key functions
-------------
test_revulsion_raises_disgust : revulsion dim raises disgust emotion + sets emotion_target.
test_body_surface_defaults_and_armed : Body exposes race/squalor/marks + armed() from carrying.
test_race_sentiment : race_sentiment reads the race_relations table (self, authored pair, unknown).
"""

from aidnd.mind.appraisal import load_race_relations, race_sentiment

from aidnd.mind.model import EMOTIONS, NpcConfig, NpcState
from aidnd.mind.tick import appraise
from aidnd.mind.world import Body, Item


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
