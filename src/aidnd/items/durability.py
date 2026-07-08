"""Durability: condition, wear from use, mods degradation, breakage. Exists outside combat —
tools/lockpicks/keys dull and break, potions expire. Defects (weak_at) break earlier.

Key functions
-------------
condition(item: dict) -> dict | None : Calculate item condition ratio and label.
active_mods(item: dict) -> list : Get visible mods accounting for wear/breakage.
use(item: dict, amount: int = 1) -> dict : Apply wear, return break/wear event info.
"""

from __future__ import annotations

_LABEL = ((0.7, "как новый"), (0.34, "потрёпан"), (0.0001, "изношен"))


def condition(item: dict) -> dict | None:
    d = item.get("durability")
    if not d:
        return None
    r = d["current"] / d["max"] if d["max"] else 0.0
    broken = r <= d.get("weak_at", 0.0)
    label = "сломан" if broken else next((lab for thr, lab in _LABEL if r >= thr), "изношен")
    return {"ratio": round(r, 2), "label": label, "broken": broken}


def active_mods(item: dict) -> list:
    """Visible mods accounting for wear: worn items lose their bonuses."""
    c = condition(item)
    if c and (c["broken"] or c["ratio"] < 0.34):
        return [m for m in item.get("mods", []) if m.get("when") == "passive"]
    return item.get("mods", [])


def use(item: dict, amount: int = 1) -> dict:
    """Apply item → wear. Returns event (broke/depleted/worn)."""
    d = item.get("durability")
    if not d:
        return {"broke": False, "worn": False}
    before = condition(item)
    d["current"] = max(0, d["current"] - amount)
    c = condition(item)
    return {"broke": c["broken"] and not before["broken"], "worn": c["label"] != before["label"],
            "label": c["label"], "break_behavior": d["break_behavior"], "ratio": c["ratio"]}
