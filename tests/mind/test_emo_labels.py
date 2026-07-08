"""Regression: every mechanical emotion/need channel must have a Russian label, so build_prompt's
`_emo_line` / `_needs_line` never KeyError when that channel is actually felt. Guards the 'disgust'
live-tick crash: disgust was added to EMOTIONS but not to EMO_RU, so any NPC feeling disgust ≥ 0.15
killed the whole live scene (the crash was swallowed by _world_tick → empty feed).

Key tests
---------
test_every_emotion_labelled   : EMOTIONS ⊆ EMO_RU (disgust included).
test_every_need_labelled      : NEEDS ⊆ NEED_RU.
test_emo_line_renders_disgust : a felt disgust renders a label, no KeyError.
"""

from aidnd.mind.llm_agent import EMO_RU, NEED_RU, _emo_line
from aidnd.mind.model import EMOTIONS, NEEDS


def test_every_emotion_labelled():
    assert set(EMOTIONS) <= set(EMO_RU), f"unlabelled emotions: {set(EMOTIONS) - set(EMO_RU)}"


def test_every_need_labelled():
    assert set(NEEDS) <= set(NEED_RU), f"unlabelled needs: {set(NEEDS) - set(NEED_RU)}"


def test_emo_line_renders_disgust():
    assert "отвращение" in _emo_line({"disgust": 0.5}, {})
