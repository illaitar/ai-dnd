"""build_prompt renders the «Чужак сказал» line only when ctx carries pc_said for this NPC.
"""

import pytest

from aidnd.mind.llm_agent import build_prompt
from aidnd.mind.model import NpcConfig, NpcState
from aidnd.mind.sim import perceive
from aidnd.mind.world import Body, World


@pytest.fixture
def minimal_state_world_percept():
    w = World()
    w.link("square", "alley")
    cfg = NpcConfig(id="npc1", name="Марта", traits={})
    st = NpcState.from_config(cfg)
    w.add(Body(id="npc1", place="square"))
    percept = perceive(st, w)
    return st, w, percept


def _text(state, world, percept, ctx):
    return "\n".join(m["content"] for m in build_prompt(state, world, percept, ctx, prefs=[]))


def test_pc_said_line_rendered(minimal_state_world_percept):
    st, w, pc = minimal_state_world_percept
    t = _text(st, w, pc, {"pc_said": {st.config.id: "нет ли работы?"}})
    assert "нет ли работы?" in t and "Чужак" in t


def test_pc_said_line_absent(minimal_state_world_percept):
    st, w, pc = minimal_state_world_percept
    assert "Чужак" not in _text(st, w, pc, {"pc_said": {}})
