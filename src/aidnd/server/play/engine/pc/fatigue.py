"""Player fatigue — stat penalty from burning mana, fades over time.

Key functions
-------------
_fatigue() -> int : Current fatigue penalty to all stats (fades over time).
_fat_add(spent) -> None : Add burnout after a cast, from burned mana.
"""

from __future__ import annotations

from ..session.config import PB
from ..session.state import _S
from ..session.time import _gt
from .mana import _mana_load


def _fatigue() -> int:
    """Current fatigue penalty to ALL stats (fades over time)."""
    _mana_load()
    if _gt() >= _S.get("fat_until", 0):
        _S["fat"], _S["fat_until"] = 0, 0
    return int(_S.get("fat", 0))


def _fat_add(spent: float) -> None:
    """Burnout after cast: fatigue from burned mana, lasts longer with bigger burnout."""
    pts = 1 + int(spent) // PB["fatigue_div"]
    _S["fat"] = _fatigue() + pts
    _S["fat_until"] = _gt() + pts * PB["fatigue_min_per_pt"]
