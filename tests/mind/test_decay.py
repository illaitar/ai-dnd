"""decay_lazy: two-speed lazy decay by gt. Emotions FAST→mood_baseline; anchored rels SLOW→faint
prior (scaled by vengefulness per spec §10); unanchored rels LOOSE→0. Rewound/zero dt = no-op.
Numbers traced from spec §5 Example B."""
import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind.decay import decay_lazy


def _state(**traits):
    t = {"bravery": 0.5, "pride": 0.5, "vengefulness": 0.0}
    t.update(traits)
    cfg = NpcConfig(id="npc:x", name="Икс", role="крестьянин", traits=t)
    return NpcState.from_config(cfg)


def test_emotion_fast_decay_to_zero():
    st = _state()
    st.emotion["disgust"] = 0.76
    st.emotion["fear"] = 0.47
    st.last_decay_gt = 10000
    decay_lazy(st, 10000 + 3 * 1440)                      # dt = 3 days
    assert st.emotion["disgust"] == pytest.approx(0.012, abs=0.01)   # 0.76 × 0.5^6
    # bravery 0.5 → fear floor 0.05 (emotion_baseline); relaxes toward that floor, not 0
    assert st.emotion["fear"] == pytest.approx(0.057, abs=0.01)
    assert st.last_decay_gt == 10000 + 3 * 1440


def test_anchored_grudge_slow_persists():
    st = _state()
    st.rel("pc")["affinity"] = -0.50
    st.rel("pc")["anchored"] = True
    st.last_decay_gt = 10000
    decay_lazy(st, 10000 + 3 * 1440)                      # dt = 3 days, hl = 14
    # target = sign×0.10 = -0.10; -0.10 + (-0.50-(-0.10))×0.5^(3/14) = -0.445
    assert st.rel("pc")["affinity"] == pytest.approx(-0.445, abs=0.01)


def test_vengefulness_lengthens_grudge():
    """§10 LOCKED: anchored half-life = 14 × (1 + vengefulness). Vindictive holds longer."""
    hard = _state(vengefulness=0.8)                       # hl ≈ 25.2 days
    soft = _state(vengefulness=0.1)                       # hl ≈ 15.4 days
    for st in (hard, soft):
        st.rel("pc")["affinity"] = -0.50
        st.rel("pc")["anchored"] = True
        st.last_decay_gt = 0
        decay_lazy(st, 3 * 1440)
    assert hard.rel("pc")["affinity"] < soft.rel("pc")["affinity"]   # hard is colder (closer to -0.5)


def test_unanchored_loose_decay_to_zero():
    st = _state()
    st.rel("pc")["fear"] = 0.24
    st.rel("pc")["anchored"] = False
    st.last_decay_gt = 10000
    decay_lazy(st, 10000 + 3 * 1440)                      # dt = 3 days, hl = 2
    assert st.rel("pc")["fear"] == pytest.approx(0.085, abs=0.01)    # 0.24 × 0.5^1.5


def test_zero_and_rewound_dt_are_noops():
    st = _state()
    st.emotion["fear"] = 0.5
    st.last_decay_gt = 10000
    decay_lazy(st, 10000)                                 # dt = 0
    assert st.emotion["fear"] == 0.5
    decay_lazy(st, 9000)                                  # rewound clock (spec §5 E)
    assert st.emotion["fear"] == 0.5 and st.last_decay_gt == 9000     # reset, never amplify
