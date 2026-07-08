"""Tests for the appraisal function (measurement dims -> emotion deltas).

Key functions
-------------
test_revulsion_raises_disgust : revulsion dim raises disgust emotion + sets emotion_target.
"""

from aidnd.mind.model import EMOTIONS, NpcConfig, NpcState
from aidnd.mind.tick import appraise


def test_revulsion_raises_disgust():
    assert "disgust" in EMOTIONS
    st = NpcState.from_config(NpcConfig(id="npc:x", traits={"pride": 0.9}))
    appraise(st, {"revulsion": 0.8}, source="beggar")
    assert st.emotion["disgust"] > 0.3
    assert st.emotion_target.get("disgust") == "beggar"
