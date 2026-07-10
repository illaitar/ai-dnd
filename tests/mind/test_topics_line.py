"""Per-persona ТВОИ ТЕМЫ line: build_prompt surfaces THIS NPC's own rumors/wants (via
ctx["topics_of"]), not just the shared town rumor/news — so NPCs raise their own material.
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


def _prompt_text(state, world, percept, ctx):
    msgs = build_prompt(state, world, percept, ctx, prefs=[])
    return "\n".join(m["content"] for m in msgs)


def test_topics_line_rendered_when_present(minimal_state_world_percept):
    state, world, percept = minimal_state_world_percept
    ctx = {"topics_of": {state.config.id: ["пропавший караван", "новая пошлина"]}}
    text = _prompt_text(state, world, percept, ctx)
    assert "ТВОИ ТЕМЫ" in text
    assert "пропавший караван" in text


def test_topics_line_absent_when_empty(minimal_state_world_percept):
    state, world, percept = minimal_state_world_percept
    text = _prompt_text(state, world, percept, {"topics_of": {}})
    assert "ТВОИ ТЕМЫ" not in text
