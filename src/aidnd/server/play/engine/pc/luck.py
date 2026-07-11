"""Player luck & inspiration — the two dials that move the craft spark roll.

Karma moves slowly by deed tags (crime ↓, gifts/quests/mercy ↑); luck is a smoothed, bounded read of
it. Inspiration spikes when the player witnesses something unusual and decays to nothing over minutes.
Pure core (`luck_from_karma` / `inspiration_decay`) is unit-testable; the `_pc_*` wrappers thread
session state + PB. State persists in pc_state (see hero._pc_save).

Key functions
-------------
luck_from_karma(karma, per_luck, cap) -> float : karma → bounded luck modifier (pure).
inspiration_decay(insp, dt_min, minutes) -> float : linear decay to 0 (pure).
_pc_karma(), _pc_karma_add(delta) : read / move the karma scalar (bounded).
_pc_luck() -> float : current luck.
_pc_inspire(amount=None), _pc_inspiration() -> float : spark / read decayed inspiration.
"""

from __future__ import annotations

from ..session.config import PB
from ..session.persist import _store
from ..session.state import _S, _wid
from ..session.time import _gt


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def luck_from_karma(karma: float, per_luck: float, cap: float) -> float:
    """Karma → a bounded luck modifier (pure, deterministic)."""
    return round(_clamp(karma / max(1.0, per_luck), -cap, cap), 2)


def inspiration_decay(insp: float, dt_min: float, minutes: float) -> float:
    """Inspiration decayed linearly to 0 over `minutes` since it was set (pure)."""
    if insp <= 0 or dt_min < 0:
        return round(max(0.0, insp), 2) if dt_min <= 0 else 0.0
    return round(max(0.0, insp * (1.0 - dt_min / max(1.0, minutes))), 2)


def _luck_load() -> None:
    if _S.get("karma") is None:
        row = _store().get_pc(_wid()) or {}
        _S["karma"] = int(row.get("karma", 0))
        _S["insp"] = float(row.get("insp", 0.0))
        _S["insp_gt"] = int(row.get("insp_gt", _gt()))


def _pc_karma() -> int:
    _luck_load()
    return _S["karma"]


def _pc_karma_add(delta: int) -> int:
    """Move karma by a deed weight, bounded to ±[karma_floor, karma_ceil]."""
    _luck_load()
    _S["karma"] = int(_clamp(_S["karma"] + int(delta), -PB["karma_floor"], PB["karma_ceil"]))
    return _S["karma"]


def _pc_luck() -> float:
    _luck_load()
    return luck_from_karma(_S["karma"], PB["karma_per_luck"], PB["luck_cap"])


def _pc_inspire(amount: float | None = None) -> None:
    """An unusual sighting sparks inspiration (a fresh spike; overwrites a fading one)."""
    _luck_load()
    _S["insp"] = float(PB["insp_spark"] if amount is None else amount)
    _S["insp_gt"] = _gt()


def _pc_inspiration() -> float:
    _luck_load()
    return inspiration_decay(_S["insp"], _gt() - _S["insp_gt"], PB["insp_minutes"])
