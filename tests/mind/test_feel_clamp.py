"""feel/need tools NUDGE, not overwrite: a channel moves at most ±feel_nudge_cap toward the
requested value (spec §5 E). A model can't zero a grudge in one call."""
from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.llm_agent import apply_actions
from aidnd.mind.world import Body


class _World:
    def __init__(self, me: Body):
        self.bodies = {me.id: me}
        self.ground = {}


def _state():
    st = NpcState.from_config(NpcConfig(id="npc:x", name="Икс", role="страж"))
    return st


def _world_for(st):
    return _World(Body(id=st.config.id, place="square"))


def test_feel_cannot_zero_anger():
    st = _state()
    st.emotion["anger"] = 0.7
    apply_actions([{"tool": "feel", "emotion": "anger", "value": 0.0}], st, _world_for(st), clock=1)
    assert st.emotion["anger"] == 0.45          # 0.7 + clamp(0.0-0.7, -0.25, +0.25) = 0.45


def test_feel_upward_nudge_capped():
    st = _state()
    st.emotion["fear"] = 0.1
    apply_actions([{"tool": "feel", "emotion": "fear", "value": 1.0}], st, _world_for(st), clock=1)
    assert st.emotion["fear"] == 0.35           # 0.1 + 0.25


def test_need_cannot_zero_hunger():
    st = _state()
    st.needs["hunger"] = 0.9
    apply_actions([{"tool": "need", "need": "hunger", "value": 0.0}], st, _world_for(st), clock=1)
    assert st.needs["hunger"] == 0.65           # 0.9 - 0.25
