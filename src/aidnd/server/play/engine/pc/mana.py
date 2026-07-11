"""Player mana — magic resource pool with lazy Int/Wis-based regeneration.

Key functions
-------------
_mana_hardcap() -> float : Growth ceiling for mana cap, from Int.
_mana_load() -> None : Lazy-init mana/fat state in session from save.
_mana_rate() -> float : Mana regen per waking hour, from Int/Wis.
_mana() -> float : Current mana with lazy regen applied.
_mana_sleep(hours) -> None : Extra mana regen for sleep (faster than waking).
_mana_cap() -> float : Current mana cap.
_mana_spend(amount) -> float : Spend mana, floored at 0.
_mana_grow(spent) -> None : Grow mana cap from burning mana (magic as muscle).
"""

from __future__ import annotations

from ..session.config import PB
from ..session.persist import _store
from ..session.state import _S, _wid
from ..session.time import _gt
from .hero import _PC_CAP


# ------------------------------------------------------------ MANA (magic) --- #
def _mana_hardcap() -> float:
    return _PC_CAP.abilities.get("int", 10) * PB["mana_hardcap_per_int"]  # growth ceiling from Int


def _mana_load() -> None:
    if _S.get("mana") is None:
        row = _store().get_pc(_wid()) or {}
        _S["mana"] = float(row.get("mana", PB["mana_start"]))
        _S["mana_cap"] = float(row.get("mana_cap", PB["mana_cap_start"]))
        _S["mana_gt"] = int(row.get("mana_gt", _gt()))
        _S["fat"] = int(row.get("fat", 0))
        _S["fat_until"] = int(row.get("fat_until", 0))


def _mana_rate() -> float:
    """Mana regen per waking hour — from Int/Wis."""
    return max(0.2, PB["mana_regen_base"] + _PC_CAP.mod("int") + _PC_CAP.mod("wis"))


def _mana() -> float:
    """Current mana with LAZY regen from Int/Wis (no per-tick frame)."""
    _mana_load()
    dt_h = max(0, _gt() - _S["mana_gt"]) / 60.0
    if dt_h > 0:
        _S["mana"] = min(_S["mana_cap"], _S["mana"] + _mana_rate() * dt_h)
        _S["mana_gt"] = _gt()
    return round(_S["mana"], 2)


def _mana_sleep(hours: float) -> None:
    """Sleep fills candle faster than waking (×mana_sleep_mult): bonus on top of lazy regen."""
    _mana()  # lazy regen for time asleep — at rate ×1
    bonus = _mana_rate() * max(0.0, hours) * (PB["mana_sleep_mult"] - 1)
    _S["mana"] = min(_S["mana_cap"], _S["mana"] + bonus)


def _mana_cap() -> float:
    _mana_load()
    return round(_S["mana_cap"], 2)


def _mana_spend(amount: float) -> float:
    _S["mana"] = max(0.0, _mana() - float(amount))
    return round(_S["mana"], 2)


def _mana_restore(amount: float) -> float:
    """Restore mana toward the cap (clamped) — e.g. drinking a mana draught."""
    _mana_load()
    _S["mana"] = min(_mana_cap(), _mana() + float(amount))
    return round(_S["mana"], 2)


def _mana_grow(spent: float) -> None:
    """Cap growth from burning (magic as muscle), up to hard limit Int×N."""
    if spent <= 0:
        return
    _S["mana_cap"] = min(
        _mana_hardcap(),
        _S["mana_cap"] + round(PB["mana_grow_frac"] * spent / max(1.0, _S["mana_cap"]), 3),
    )
