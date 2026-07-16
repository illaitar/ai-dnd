"""self_regard biases the PERCEIVED pwin the DECISION reads, never the TRUE pwin combat resolves.
An overconfident head tips into a losing fight; a meek NPC over-flees. Spec §4.5 / §5 Example C."""
import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind import value as Vv
from aidnd.mind.goals import Goal
from aidnd.mind.sim import Percept
from aidnd.mind.world import Body


def _state(pride, bravery, ambition, **extra):
    cfg = NpcConfig(id="npc:h", name="Ход", role="головорез",
                    traits={"pride": pride, "bravery": bravery, "ambition": ambition, **extra})
    return NpcState.from_config(cfg)


def test_self_regard_formula():
    st = _state(0.577, 0.876, 0.496)
    assert Vv.self_regard(st) == pytest.approx(0.658, abs=0.005)


def test_self_regard_unbiased_at_half():
    st = _state(0.5, 0.5, 0.5)
    me = Body(id="npc:h", place=0, power=1.1)
    foe = Body(id="vet", place=0, power=0.9)
    # self_regard 0.5 → bias 1.0 → perceived == true
    assert Vv.self_regard(st) == pytest.approx(0.5, abs=0.005)
    assert Vv.perceived_pwin(me, foe, st) == pytest.approx(Vv.pwin(me, foe), abs=1e-6)


def test_overconfident_inflates_perceived_pwin():
    st = _state(0.577, 0.876, 0.496)                          # self_regard 0.658 → bias 1.237
    me = Body(id="npc:h", place=0, power=0.89)
    foe = Body(id="vet", place=0, power=1.335)
    assert Vv.pwin(me, foe) == pytest.approx(0.40, abs=0.01)              # TRUE (unbiased)
    assert Vv.perceived_pwin(me, foe, st) == pytest.approx(0.52, abs=0.02)   # PERCEIVED (inflated)
    assert Vv.perceived_pwin(me, foe, st) > Vv.pwin(me, foe)


def test_meek_discounts_perceived_pwin():
    meek = _state(0.2, 0.25, 0.2)                             # self_regard ~0.22 → bias ~0.66
    me = Body(id="npc:h", place=0, power=1.2)
    foe = Body(id="vet", place=0, power=1.0)
    assert Vv.perceived_pwin(me, foe, meek) < Vv.pwin(me, foe)            # under-confident


class _Attack:
    kind, target, say, item, to = "attack", "vet", None, None, None


def _harm_utility(cfg):
    """The _u_harm decision utility of striking a stronger veteran, one-on-one, no third-party
    witnesses, no moral/lawful brake — so the sign is driven purely by pwin vs selfrisk."""
    st = NpcState.from_config(cfg)
    me = Body(id="npc:h", place=0, power=0.89)
    foe = Body(id="vet", place=0, power=1.5)
    g = Goal(kind="harm", target="vet", value=0.8, meta={})
    percept = Percept(here="sq", exits=[], present=[foe], nearby=[], me=me)

    class _W:
        bodies = {me.id: me, foe.id: foe}

    return Vv._u_harm(_Attack(), g, st, _W(), percept, me), Vv.pwin(me, foe)


def test_example_c_overconfident_picks_a_losing_fight():
    """Spec §5 Example C. Same foe, same real odds — only self-belief differs. The unbiased head
    reads true pwin ≈ 0.37 and declines (attack utility < 0); the braggart perceives a fight he
    wins and strikes (utility > 0). The TRUE pwin combat resolves with is identical for both."""
    braggart = NpcConfig(id="npc:h", name="Ход", role="головорез",
                         traits={"pride": 0.8, "bravery": 0.7, "ambition": 0.7,
                                 "malice": 0.0, "honesty": 0.0, "lawful": 0.0})
    meek = NpcConfig(id="npc:h", name="Тихоня", role="головорез",
                     traits={"pride": 0.5, "bravery": 0.5, "ambition": 0.5,
                             "malice": 0.0, "honesty": 0.0, "lawful": 0.0})

    u_brag, true_brag = _harm_utility(braggart)
    u_meek, true_meek = _harm_utility(meek)

    assert true_brag == pytest.approx(0.372, abs=0.01)   # TRUE pwin — same for both, a losing fight
    assert true_meek == pytest.approx(0.372, abs=0.01)
    assert u_meek < 0.0                                  # unbiased declines the bad fight
    assert u_brag > 0.0                                  # overconfident picks it (and will lose)
