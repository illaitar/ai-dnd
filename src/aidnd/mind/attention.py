"""Attention Pillar 2 (Inc6): Body.attention = perception.vigilance × current-activity multiplier,
clamped [0.05, 1.0], back in mind/ (U5). Pure: reads only aidnd.mind.tunables.BRAIN; the play clock
(gt / day-phase) is threaded in as parameters so mind/ stays import-clean of play. world.py's
call-through supplies _gt()/_phase(). Spec §5-U5/§6/§3c."""

from __future__ import annotations

from .tunables import BRAIN

_ATT_MULT = {"asleep": "att_asleep", "drunk": "att_drunk",
             "absorbed": "att_absorbed", "alert": "att_alert"}


def _phase(gt: int) -> str:
    """Day phase for the activity label — pure arithmetic (mind-local copy of the play clock's phase
    thresholds; identical boundaries). Used only when the caller does not pass a resolved `phase`."""
    h = (gt // 60) % 24
    return ("night" if h < 6 else "morning" if h < 11 else "day"
            if h < 17 else "evening" if h < 22 else "night")


def _activity_of(state, gt: int, phase: str | None = None) -> str:
    """Coarse current-activity label driving the attention multiplier (§6/§3c). Derived from the REAL
    runtime signals on NpcState — mode / on_shift / the day phase / current fear / role. `phase` may
    be supplied (world.py passes _phase(gt)); else it is derived from `gt`. No drunkenness signal yet,
    so the 'drunk' arm is unreachable (knob kept for the set + the _activity= unit seam)."""
    ph = phase if phase is not None else _phase(gt)
    mode = getattr(state, "mode", "leisure")
    if mode == "routine" and ph == "night":                        # abed at home in the dark
        return "asleep"
    if (mode == "threat" or state.emotion.get("fear", 0.0) >= 0.6  # frightened / on-guard / watchman
            or state.config.role == "стражник"):
        return "alert"
    if mode == "converse" or getattr(state, "on_shift", 0.0) > 0.0:  # deep in talk / heads-down at bench
        return "absorbed"
    return "alert"                                                  # up-and-about, ordinary watchfulness


def _body_attention(cfg, state=None, _activity=None, gt=None, phase=None) -> float:
    """Vigilance (§3.9 → C11) × current-activity multiplier (§6, Pillar 2), clamped [0.05, 1.0]. A
    sleeping/absorbed target dips below the value.py 0.4 theft window; an alert guard caps at 1.0.
    `_activity` overrides the derivation (unit seam); `gt`/`phase` feed the runtime derivation when a
    live `state` is given (world.py supplies them). Un-enriched vig → 0.5."""
    vig = float((getattr(cfg, "perception", None) or {}).get("vigilance", 0.5))
    act = _activity or (_activity_of(state, gt if gt is not None else 0, phase)
                        if state is not None else "alert")
    return max(0.05, min(1.0, vig * BRAIN[_ATT_MULT.get(act, "att_alert")]))
