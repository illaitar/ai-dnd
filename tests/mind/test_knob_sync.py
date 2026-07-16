"""Finding D (LOW): PB (session/config.py), decay._K (decay.py), and value.BAL each hold an
INDEPENDENT copy of the same decay/nudge constants — intentional (mind/ stays import-clean of the
play layer, and value.py can't import play-layer PB — see decay.py:12 and value.py:47), but nothing
guarded the three copies stayed equal. A future PB-only tune could silently drift mind/ out of sync
with the play layer it mirrors. This is ONE guard test, not a restructure."""
from aidnd.mind.decay import _K
from aidnd.mind.project import _K as _PK
from aidnd.mind.value import BAL
from aidnd.server.play.engine.session.config import PB

# keys that decay.py and/or value.py mirror from PB (session/config.py:21-27)
_SHARED_DECAY_KEYS = (
    "decay_emo_days", "decay_rel_anchored_days", "decay_rel_loose_days", "rel_faint_prior",
)


def test_decay_knobs_match_pb():
    for k in _SHARED_DECAY_KEYS:
        assert _K[k] == PB[k], f"mind.decay._K[{k!r}] ({_K[k]!r}) != PB[{k!r}] ({PB[k]!r})"


def test_project_knobs_match_pb():
    # every ev_* knob project.py mirrors must equal the canonical PB copy (Inc2, §4.6)
    for k in _PK:
        assert _PK[k] == PB[k], f"mind.project._K[{k!r}] ({_PK[k]!r}) != PB[{k!r}] ({PB[k]!r})"


def test_feel_nudge_cap_matches_pb():
    assert BAL["feel_nudge_cap"] == PB["feel_nudge_cap"]


def test_self_regard_knobs_match_pb():
    # value.BAL mirrors PB's self_regard weights (Inc5) — voice.py reads PB, mind/ reads BAL
    for k in ("sr_pride", "sr_brave", "sr_amb", "sr_span"):
        assert BAL[k] == PB[k], f"value.BAL[{k!r}] ({BAL[k]!r}) != PB[{k!r}] ({PB[k]!r})"
