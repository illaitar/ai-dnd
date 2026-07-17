"""U5: familiarity/greet → mind/social.py, attention → mind/attention.py — PURE moves (behavior
unchanged; the world.py tests are the guard). The moved modules are import-clean of the play layer
(only aidnd.mind.tunables), and the clock/knob dependencies are threaded as parameters. Spec §5-U5."""
from __future__ import annotations

import pytest

from aidnd.mind import NpcConfig, NpcState


def test_social_module_is_import_clean_of_play():
    import aidnd.mind.social as social
    src = social.__file__
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert "aidnd.server" not in text and "engine" not in text   # no play-layer import


def test_attention_module_is_import_clean_of_play():
    import aidnd.mind.attention as attention
    src = attention.__file__
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert "aidnd.server" not in text and "engine" not in text


def test_activity_of_takes_gt_and_phase():
    from aidnd.mind.attention import _activity_of
    st = NpcState.from_config(NpcConfig(id="npc:t", role="горожанин", perception={"vigilance": 0.7}))
    st.mode = "routine"
    assert _activity_of(st, gt=3 * 60, phase="night") == "asleep"     # abed in the dark
    assert _activity_of(st, gt=12 * 60, phase="day") == "alert"       # up and about by day


def test_greet_impulse_moved_logic_parity():
    from aidnd.mind.social import _greet_impulse

    from aidnd.mind.tunables import BRAIN
    assert _greet_impulse(0.9) == pytest.approx(BRAIN["greet_sociability_base"] * 0.4, abs=1e-6)
    assert _greet_impulse(0.4) == 0.0
