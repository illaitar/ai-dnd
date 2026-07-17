"""U3: feel/need = a deliberate self-event through the SAME door. actor==target==me → the sink's
self-feeling arm NUDGES the named channel by ±feel_nudge_cap (self-regulation, NOT an appraisal of
an external act), preserving the grudge/hunger the model cannot erase in one call. Clamp result is
byte-identical to the old _nudge; the emotion channel now also self-targets. Spec §5-U3."""
from __future__ import annotations

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.llm_agent import apply_actions
from aidnd.mind.world import Body


class _World:
    def __init__(self, me):
        self.bodies = {me.id: me}
        self.ground = {}


def _st():
    return NpcState.from_config(NpcConfig(id="npc:x", name="Икс", role="страж"))


def test_feel_over_nudge_capped_and_self_targeted():
    st = _st()
    st.emotion["anger"] = 0.2
    apply_actions([{"tool": "feel", "emotion": "anger", "value": 0.9}],
                  st, _World(Body(id="npc:x", place="sq")), clock=1)
    assert st.emotion["anger"] == 0.45                 # 0.2 + clamp(0.7, ±0.25) = 0.45 (byte-identical)
    assert st.emotion_target["anger"] == "npc:x"       # self-event self-targets (new, in-band)


def test_need_self_event_nudges_no_target():
    st = _st()
    st.needs["hunger"] = 0.9
    apply_actions([{"tool": "need", "need": "hunger", "value": 0.0}],
                  st, _World(Body(id="npc:x", place="sq")), clock=1)
    assert st.needs["hunger"] == 0.65                  # 0.9 − 0.25 (byte-identical)
    assert "hunger" not in st.emotion_target           # needs are not emotions — no target
