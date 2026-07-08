"""Player vision — fog-of-war cache keys and the town watch's wanted-level confrontation check.

Key functions
-------------
_look_key(loc, inside) -> str : Fog-of-war cache key for a location + room combo.
_looked_level(loc, inside) -> int : 0=unseen, 1=looked around, 2=keen-checked fog level for a spot.
_watch_check(people, crof, loc) -> dict | None : Guard confrontation when wanted level is high.
"""

from __future__ import annotations

from ..core import _S, PB, _here, _store, _wanted, _wid


def _look_key(loc, inside) -> str:
    return f"{loc}|{inside or 'out'}"


def _looked_level(loc, inside) -> int:
    """0 = not examined (fog: can't distinguish people/containers), 1 = looked around, 2 = keen check."""
    return int((_S.setdefault("looked", {})).get(_look_key(loc, inside), 0))


def _watch_check(people, crof, loc):
    """Guard binds: if wanted ≥ threshold AND guard at location — confrontation."""
    if _wanted() < PB["wanted_confront"]:
        return None
    guard = next((pid for pid in _here(loc, crof) if people[pid].role == "стражник"), None)
    if not guard:
        return None
    crimes = (_store().flag_get(_wid(), "crimes|pc") or "тёмные дела").split("; ")
    return {
        "guard": guard,
        "name": people[guard].name,
        "wanted": _wanted(),
        "crimes": ", ".join(crimes[-2:]),
        "fine": _wanted() * PB["watch_fine_per_pt"],
    }
