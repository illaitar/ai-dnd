"""_pc_said_impulse: tier-scaled pull to react when the player speaks aloud — near hearer gets
selected to think (>= live_must_impulse) but never outranks a real event/answer-debt.
"""

from aidnd.server.play.engine.session.config import PB
from aidnd.server.play.engine.world import _pc_said_impulse


def test_impulse_scales_by_tier():
    l1, l2, l3 = _pc_said_impulse("L1"), _pc_said_impulse("L2"), _pc_said_impulse("L3")
    assert l1 > l2 > l3 > 0
    assert l1 == PB["pc_said_impulse"]


def test_impulse_below_event_and_debt_but_above_must_gate():
    # a near hearer is selected to think (>= live_must_impulse) but can't outrank a real event/debt
    assert _pc_said_impulse("L1") >= PB["live_must_impulse"]
    assert _pc_said_impulse("L1") < 3.5   # 'событие'
    assert _pc_said_impulse("L1") < 4.0   # 'долг ответа'


def test_impulse_unknown_tier_zero():
    assert _pc_said_impulse("") == 0.0
