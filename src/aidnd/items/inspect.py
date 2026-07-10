"""Inspection: resolve gate of each hidden property by observer Capability. Different `via` reveals
different properties; expert delegates to foreign abilities (NPC-expert). view() — what observer
KNOWS about the item (surface + revealed), with true worth only after revealing true_worth/forgery.

Key functions
-------------
inspect(item, cap, via, **opts) -> dict : Reveal hidden properties by inspection method.
view(item, known) -> dict : Query known item facts (surface + revealed).
"""

from __future__ import annotations

from random import Random

from .model import Capability


def _roll(seed: str) -> int:
    return Random(seed).randint(1, 20)                     # stable d20 (can't re-roll by re-examining)


_VIA_GROUP = {"craft_eye": "attr:phys", "appraise": "attr:value", "lore": "attr:arcane"}
_GROUP_COMPS = {"attr:phys": {"metalwork", "leather", "gems", "herbs"},
                "attr:value": {"trade", "gems"},
                "attr:arcane": {"lore", "faith"}}
_ATTR_DC = 12


def _attr_reveal(item: dict, cap: Capability, via: str, seed: str) -> list:
    """Attribute GROUPS this inspection reveals as true. Expert assesses fully; a trained eye
    (competency) sees at a glance; else appraise/lore fall to an ability roll; phys needs the hand."""
    if not item.get("attrs"):
        return []
    if via == "expert":
        return list(_VIA_GROUP.values())
    grp = _VIA_GROUP.get(via)
    if not grp:
        return []
    if cap.competencies & _GROUP_COMPS[grp]:
        return [grp]
    if grp == "attr:phys":
        return []                                          # physical truth needs the trained hand
    abil = max(cap.mod("int"), cap.mod("wis")) if via == "appraise" else cap.mod("int")
    return [grp] if abil + _roll(seed) >= _ATTR_DC else []


def _gate(g: dict, cap: Capability, via: str, tool, context, seed: str) -> str:
    """'pass' | 'near' | 'fail'."""
    if via in ("glance", "handle"):
        return "pass"
    if via == "craft_eye":
        return "pass" if g["req"] and g["req"] in cap.competencies else "fail"
    if via == "tool":
        return "pass" if g["req"] and (g["req"] in cap.tools or (tool and g["req"] in {tool})) else "fail"
    if via == "context":
        return "pass" if g["req"] and context and g["req"] in context else "fail"
    if via == "use":
        return "fail"                                      # revealed by use, not inspection
    if via == "lore" and g["req"] and g["req"] in cap.competencies:
        return "pass"                                      # expert sees immediately
    abil = max(cap.mod("int"), cap.mod("wis")) if via == "appraise" else cap.mod("int")
    total = abil + _roll(seed)
    return "pass" if total >= g["dc"] else "near" if total >= g["dc"] - 3 else "fail"


def inspect(item: dict, cap: Capability, via: str, *, tool=None, context=None,
            observer: str = "pc", known=None) -> dict:
    """Inspect item by method `via`. Returns {revealed:[hidden], hints:[fact], via}.
    via='expert' — expert tries NATIVE method of each property by their ability."""
    known = set(known or [])
    base = f"{item.get('id') or item.get('name')}|{observer}"
    revealed, hints = [], []
    for h in item.get("hidden", []):
        if h["prop"] in known:
            continue
        g = h["gate"]
        used = g["via"] if via == "expert" else via
        if via != "expert" and used != g["via"]:
            continue                                       # can't reveal this hidden property with this inspection method
        res = _gate(g, cap, used, tool, context, f"{base}|{h['prop']}|{used}")
        if res == "pass":
            revealed.append(h)
        elif res == "near":
            hints.append("что-то не так с предметом — нужен иной осмотр или знаток")
    attr_groups = [g for g in _attr_reveal(item, cap, via, f"{base}|attrs|{via}") if g not in known]
    return {"revealed": revealed, "hints": hints, "via": via, "attr_groups": attr_groups}


def view(item: dict, known=None) -> dict:
    """What observer KNOWS about the item (for UI/negotiation)."""
    known = set(known or [])
    worth_known = any((h["prop"] in ("true_worth", "forgery"))
                      or any(m["target"] == "worth" for m in h.get("mods", []))
                      for h in item.get("hidden", []) if h["prop"] in known)
    facts = [h["fact"] for h in item.get("hidden", []) if h["prop"] in known and h.get("fact")]
    rmods = [m for h in item.get("hidden", []) if h["prop"] in known for m in h.get("mods", [])]
    unknown = sum(1 for h in item.get("hidden", []) if h["prop"] not in known)
    return {"name": item["name"], "kind": item["kind"], "slot": item["slot"],
            "material": item["material"], "quality": item["quality"], "weight": item["weight"],
            "worth": item["worth"] if worth_known else item["apparent_worth"], "worth_known": worth_known,
            "tags": item["tags"], "mods": [m for m in item["mods"] if not m.get("hidden")] + rmods,
            "facts": facts, "unknown": unknown, "durability": item.get("durability")}
