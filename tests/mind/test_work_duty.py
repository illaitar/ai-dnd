"""Workplace 'keep working' purpose lift (mirrors venue_social pattern for on-shift workers).

Key tests
---------
test_off_shift_hunger_beats_purpose : with no shift lift, an urgent need (hunger) out-competes purpose.
test_on_shift_purpose_beats_hunger  : on the clock, the purpose need's goal value is lifted enough to
    out-compete hunger — a worker stays at the bench instead of wandering off mid-shift.
"""

from aidnd.mind.model import NpcConfig, NpcState


def _state(**needs):
    cfg = NpcConfig(id="w1", name="Смит", traits={})
    st = NpcState.from_config(cfg)
    st.needs.update({"purpose": 0.2, "hunger": 0.5})
    st.needs.update(needs)
    return st


def _goal_val(goals, need):
    g = next((g for g in goals if g.kind == "need" and g.target == need), None)
    return g.value if g else 0.0


def test_off_shift_hunger_beats_purpose():
    from aidnd.mind.goals import standing_needs
    st = _state()
    st.on_shift = 0.0
    goals = standing_needs(st)
    assert _goal_val(goals, "hunger") > _goal_val(goals, "purpose")


def test_on_shift_purpose_beats_hunger():
    from aidnd.mind.goals import standing_needs
    st = _state()
    st.on_shift = 0.6              # on the clock
    goals = standing_needs(st)
    assert _goal_val(goals, "purpose") > _goal_val(goals, "hunger")
