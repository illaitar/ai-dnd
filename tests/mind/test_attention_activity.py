"""Attention Pillar 2 (Inc6): Body.attention = perception.vigilance × current-activity multiplier.
An asleep/absorbed target dips below the value.py 0.4 theft window → the DEAD take_distracted (0.78)
primitive fires and a thief's opportunistic pickpocket beats the attack alternative; an alert target
(×1.3, capped 1.0) stays above the window, take_alert (0.15) leaves attack the better bet. Spec §6/§3c."""
from types import SimpleNamespace

import pytest

from aidnd.mind import NpcConfig, NpcState
from aidnd.mind import value as Vv
from aidnd.mind.goals import Goal
from aidnd.mind.sim import Percept
from aidnd.mind.world import Body
from aidnd.server.play.engine import world as W
from aidnd.server.play.engine.session.config import PB


# ── the multiplier table (the _activity= seam bypasses the runtime derivation) ────────────────
def test_multiplier_table_scales_vigilance():
    cfg = SimpleNamespace(perception={"vigilance": 0.7})
    alert = W._body_attention(cfg, _activity="alert")
    drunk = W._body_attention(cfg, _activity="drunk")
    absorbed = W._body_attention(cfg, _activity="absorbed")
    asleep = W._body_attention(cfg, _activity="asleep")
    assert alert == pytest.approx(min(1.0, 0.7 * PB["att_alert"]), abs=1e-6)     # 0.91, guard raised
    assert drunk == pytest.approx(0.7 * PB["att_drunk"], abs=1e-6)               # 0.28
    assert absorbed == pytest.approx(0.7 * PB["att_absorbed"], abs=1e-6)         # 0.42
    assert asleep == pytest.approx(0.7 * PB["att_asleep"], abs=1e-6)             # 0.14
    assert asleep < drunk < 0.4 <= alert            # sleep/drunk cross the theft window, alert doesn't


def test_alert_caps_at_one_and_floor_holds():
    hi = SimpleNamespace(perception={"vigilance": 0.95})
    assert W._body_attention(hi, _activity="alert") == pytest.approx(1.0)        # 0.95×1.3 clamped to 1.0
    lo = SimpleNamespace(perception={"vigilance": 0.1})
    assert W._body_attention(lo, _activity="asleep") == pytest.approx(0.05)      # 0.1×0.2=0.02 floored to 0.05


# ── the runtime derivation from the REAL NpcState signals ─────────────────────────────────────
def _state(role="горожанин", mode="leisure", on_shift=0.0, fear=0.0):
    st = NpcState.from_config(NpcConfig(id="npc:t", role=role, perception={"vigilance": 0.7}))
    st.mode = mode
    st.on_shift = on_shift
    st.emotion["fear"] = fear
    return st


def test_activity_derivation_maps_real_signals():
    day, night = 12 * 60, 3 * 60          # gt in minutes: noon vs 03:00
    assert W._activity_of(_state(mode="routine"), night) == "asleep"            # abed at home in the dark
    assert W._activity_of(_state(mode="routine"), day) == "alert"              # up and about by day (not asleep)
    assert W._activity_of(_state(mode="converse"), day) == "absorbed"          # deep in talk
    assert W._activity_of(_state(on_shift=0.5), day) == "absorbed"             # heads-down at the bench
    assert W._activity_of(_state(role="стражник", on_shift=0.5), day) == "alert"  # a watchman on his beat, NOT absorbed
    assert W._activity_of(_state(mode="threat"), day) == "alert"               # under threat
    assert W._activity_of(_state(fear=0.7), day) == "alert"                    # frightened
    assert W._activity_of(_state(mode="leisure"), day) == "alert"              # ordinary watchfulness (else)


def test_absorbed_and_asleep_open_the_theft_window():
    """A naturally vigilant NPC (vig 0.5) stayed static & un-pickable before Inc6; now heads-down at
    work (absorbed 0.5×0.6=0.30) or abed (asleep 0.5×0.2=0.10) they drop below the 0.4 theft window,
    while alert (0.5×1.3=0.65, capped) stays shut. The derivation reads the real on_shift/mode/night."""
    st_work = _state(on_shift=0.4)                               # heads-down at the bench, any daylight
    assert W._activity_of(st_work, 12 * 60) == "absorbed"
    st_sleep = _state(mode="routine")                           # abed at home at 03:00
    assert W._activity_of(st_sleep, 3 * 60) == "asleep"
    cfg = SimpleNamespace(perception={"vigilance": 0.5})
    assert W._body_attention(cfg, _activity="absorbed") < 0.4    # window OPEN (0.30)
    assert W._body_attention(cfg, _activity="asleep") < 0.4      # window OPEN (0.10)
    assert W._body_attention(cfg, _activity="alert") >= 0.4      # window SHUT (0.65)


# ── the theft window wakes: value.py take branch reads the (now dynamic) attention ────────────
class _Take:
    kind, target, say, item, to = "take", "vet", None, None, None


class _Attack:
    kind, target, say, item, to = "attack", "vet", None, None, None


def _thief_state():
    # honest=0, lawful=0 → no moral/legal brake; neutral pride/bravery/ambition → perceived == true pwin;
    # greed 0.5 → pay = value·(0.3+0.5). Drives the branch purely by the target's attention.
    return NpcState.from_config(NpcConfig(
        id="npc:h", role="головорез",
        traits={"greed": 0.5, "honesty": 0.0, "lawful": 0.0,
                "pride": 0.5, "bravery": 0.5, "ambition": 0.5, "irritability": 0.5}))


def _acquire_utils(target_attention):
    """(_u_acquire take, _u_acquire attack) against a WEAKER target at the given attention.
    A weak target makes the attack alternative genuinely attractive (pwin 0.7) — so only a low
    attention lets the quiet pickpocket beat it. One-on-one, zero third-party witnesses."""
    st = _thief_state()
    me = Body(id="npc:h", place=0, power=1.4)
    foe = Body(id="vet", place=0, power=0.6, attention=target_attention)
    g = Goal(kind="acquire", target="vet", value=0.8, meta={})
    percept = Percept(here="sq", exits=[], present=[foe], nearby=[], me=me)

    class _W:
        bodies = {me.id: me, foe.id: foe}

    take = Vv._u_acquire(_Take(), g, st, _W(), percept, me)
    attack = Vv._u_acquire(_Attack(), g, st, _W(), percept, me)
    return take, attack


def test_low_attention_opens_pickpocket_window_high_does_not():
    take_lo, attack_lo = _acquire_utils(0.28)     # distracted target (e.g. asleep/absorbed/drunk)
    take_hi, attack_hi = _acquire_utils(0.85)     # alert target
    # distracted: the quiet take (take_distracted 0.78) beats knocking them down — pickpocket EMERGES
    assert take_lo > attack_lo
    # alert: grabbing risks a fight (take_alert 0.15) — attacking the weakling wins instead
    assert take_hi < attack_hi
    # same greed & payoff — the ONLY difference is the target's (now dynamic) attention
    assert take_lo > take_hi
    assert take_lo == pytest.approx(Vv.BAL["take_distracted"] * 0.8 * (0.3 + 0.5), abs=1e-6)
    assert take_hi == pytest.approx(Vv.BAL["take_alert"] * 0.8 * (0.3 + 0.5), abs=1e-6)


def test_bal_theft_reward_ordering():
    """The seam value.py relies on: a distracted grab pays far more than an alert one (spec §3c)."""
    assert Vv.BAL["take_down"] > Vv.BAL["take_distracted"] > Vv.BAL["take_alert"]
