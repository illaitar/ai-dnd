"""E2 (time, docs/citysim.md §E): OPEN HOURS — single source for when venues are open.

Canonical hours for frontier town by venue type (opening_hour, closing_hour); closing
> 24 = past midnight (tavern until 01:00, gambling den until 04:00). Gates PLAYER access to services/
trade (B2): at night shop is locked, market works during day, tavern — evening-night. Same canon
feeds narrative ('shop closed until morning') and market display (open/closed-until).

Key functions
-------------
hours_for(info: str) -> tuple[int, int] | None : Query venue hours by name.
is_open(info: str, gt: int) -> bool : Check if venue is open at game time.
opens_at(info: str) -> int | None : Get opening hour for narrative text.
"""

from __future__ import annotations

# by substring of type/name → (opening, closing); closing>24 ⇒ past midnight
_HOURS: dict[str, tuple[int, int]] = {
    "таверн": (11, 25), "трактир": (11, 25),          # 11:00 – 01:00
    "игорн": (18, 28),                                 # 18:00 – 04:00 (night den)
    "рынок": (7, 17), "рыноч": (7, 17),
    "лавк": (8, 18), "склад": (8, 18), "мастерск": (8, 18), "лавч": (8, 18),
    "кузн": (7, 18), "оружейн": (8, 18), "дубиль": (8, 18), "сапож": (8, 18), "коже": (8, 18),
    "мельниц": (6, 16), "мельн": (6, 16), "пекарн": (6, 15),
    "храм": (6, 21), "молельн": (6, 21), "часовн": (6, 21), "святил": (6, 21),  # services; always open
    "гильд": (8, 19),
    "лечебн": (7, 20), "знахар": (7, 20), "травниц": (7, 20),
}


def hours_for(info: str) -> tuple[int, int] | None:
    """Venue hours by string 'type name' (first substring match), else None (no hours)."""
    low = (info or "").lower()
    return next((h for k, h in _HOURS.items() if k in low), None)


def is_open(info: str, gt: int) -> bool:
    """Is venue open at game time gt (minutes). No hours ⇒ True (housing/other — always open)."""
    hrs = hours_for(info)
    if hrs is None:
        return True
    h = (gt // 60) % 24
    open_h, close_h = hrs
    if close_h > 24:                                   # window past midnight: [open,24) ∪ [0,close-24)
        return h >= open_h or h < (close_h - 24)
    return open_h <= h < close_h


def opens_at(info: str) -> int | None:
    """Opening hour (for narrative 'closed until 8'), else None."""
    hrs = hours_for(info)
    return hrs[0] if hrs else None
