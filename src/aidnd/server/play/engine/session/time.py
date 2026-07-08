"""Session game clock — in-world time and day phase.

Key functions
-------------
_gt() -> int : Get current game time in minutes from world session.
_gt_add(minutes) -> int : Advance game time by minutes.
_mt() -> int : Memory tick (coarser clock used for memory halflife).
_phase(gt=None) -> str : Day phase ("morning"/"day"/"evening"/"night") for a given (or current) gt.
"""

from __future__ import annotations

from .config import _GT0
from .persist import _store
from .state import _S, _wid


def _gt() -> int:
    v = _S.get("gt")
    if v is None:  # cold start: time — FROM SAVE, not from zero
        row = _store().get_pc(_wid()) or {}  # (else schedule/day phase built on 19:40)
        v = _S["gt"] = int(row.get("gt", _GT0))
    return v


def _gt_add(minutes: int) -> int:
    _S["gt"] = _gt() + max(0, int(minutes))
    return _S["gt"]


def _mt() -> int:
    return _gt() // 10  # memory tick (halflife retrieves 144 ticks ≈ one day)


def _phase(gt: int | None = None) -> str:
    h = ((gt if gt is not None else _gt()) // 60) % 24
    return (
        "night"
        if h < 6
        else "morning"
        if h < 11
        else "day"
        if h < 17
        else "evening"
        if h < 22
        else "night"
    )


_PHASE_RU = {"morning": "утро", "day": "день", "evening": "вечер", "night": "ночь"}
