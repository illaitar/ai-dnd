"""Attribute graph: materials/forms/treatments → intrinsic attribute vector → derived effects.
Pure & deterministic; code owns the math. Composition = materials (max per attr) + treatment deltas,
quality-scaled, clamped 0–100. derive_effects projects the TRUE vector (form-gated) into game mods.

Key functions
-------------
attr_graph() -> dict : Load/cache the authored materials/forms/treatments graph.
compose(parts, quality) -> dict : Composition → {attr:int} true vector (0–100).
derive_effects(item, rules) -> dict : Attribute vector + form → {mods, worth, durability}.
"""

from __future__ import annotations

import json
import os

from .model import ATTRS

_GRAPH = None
_GPATH = os.path.join(os.path.dirname(__file__), "attrgraph.json")


def attr_graph() -> dict:
    global _GRAPH
    if _GRAPH is None:
        with open(_GPATH, encoding="utf-8") as f:
            _GRAPH = json.load(f)
    return _GRAPH


QUALITY_MUL = {"crude": 0.85, "plain": 1.0, "fine": 1.12, "exquisite": 1.25}


def _clamp(v) -> int:
    return max(0, min(100, int(round(v))))


def compose(parts, quality: str = "plain", graph: dict | None = None) -> dict:
    """parts=[{role,material,treatments[]}] → {attr:int} true vector (0–100). Strongest part wins
    per attribute (max); treatment deltas sum; quality-scaled; clamped; zero attrs omitted."""
    g = graph or attr_graph()
    mats, treats = g["materials"], g["treatments"]
    acc: dict = {}
    for part in parts or []:
        for a, v in mats.get(part.get("material", ""), {}).items():
            acc[a] = max(acc.get(a, 0), v)                 # the sharpest/hardest part defines the attr
    for part in parts or []:
        for t in part.get("treatments") or []:
            for a, dv in treats.get(t, {}).items():
                acc[a] = acc.get(a, 0) + dv
    mul = QUALITY_MUL.get(quality, 1.0)
    return {a: _clamp(v * mul) for a, v in acc.items() if a in ATTRS and _clamp(v * mul) > 0}


# Effect-rule coefficients — code owns the math (pure module; PB override seam lands in Phase 3).
DEFAULT_RULES = {
    "attack":     {"bands": [(80, 3), (60, 2), (40, 1)], "when": "equipped"},
    "defense":    {"bands": [(80, 3), (60, 2), (40, 1)], "when": "equipped"},
    "appearance": {"attr": "краса", "bands": [(88, 3), (70, 2), (45, 1)],
                   "target": "social:appearance", "when": "worn"},
    "poison":     {"attr": "скверна", "bands": [(75, 3), (50, 2), (20, 1)],
                   "target": "special:poison", "when": "on_use"},
    "mana":       {"attr": "мана", "bands": [(75, 3), (50, 2), (25, 1)], "target": "special:mana"},
    "worth":      {"w": {"ценность": 0.6, "краса": 0.25, "чара": 0.15}, "k": 0.6, "min": 1},
    "durability": {"attr": "прочность", "k": 0.5, "min": 4},
}
FOCUS_FORMS = ("оправа", "посох", "жезл", "амулет", "талисман")


def _true(attrs: dict, a: str) -> int:
    return int((attrs.get(a) or {}).get("true", 0))


def _band(v: float, bands: list) -> int:
    for thr, amt in bands:                                 # bands ordered high→low
        if v >= thr:
            return amt
    return 0


def _score(attrs: dict, w: dict) -> float:
    return sum(_true(attrs, a) * k for a, k in w.items())


def derive_effects(item: dict, rules: dict | None = None) -> dict:
    """Attribute TRUE vector + form → {mods, worth, durability}. Form gates attack/defense."""
    r = rules or DEFAULT_RULES
    attrs = item.get("attrs") or {}
    form = item.get("form") or ""
    kind = item.get("kind") or ""
    expresses = ((attr_graph()["forms"].get(form) or {}).get("expresses")) or {}
    mods: list = []
    for key in ("attack", "defense"):                      # form-gated: weights come from the form
        w = expresses.get(key)
        if w:
            amt = _band(_score(attrs, w), r[key]["bands"])
            if amt:
                mods.append({"target": key, "op": "add", "amount": amt, "when": r[key]["when"]})
    ap = r["appearance"]                                    # universal: appearance
    amt = _band(_true(attrs, ap["attr"]), ap["bands"])
    if amt:
        mods.append({"target": ap["target"], "op": "add", "amount": amt, "when": ap["when"]})
    po = r["poison"]                                        # universal: toxicity (hidden)
    amt = _band(_true(attrs, po["attr"]), po["bands"])
    if amt:
        mods.append({"target": po["target"], "op": "add", "amount": amt, "when": po["when"], "hidden": True})
    mn = r["mana"]                                          # mana: focus (equipped) or consumable (on_use)
    amt = _band(_true(attrs, mn["attr"]), mn["bands"])
    if amt and (kind == "consumable" or form in FOCUS_FORMS):
        mods.append({"target": mn["target"], "op": "add", "amount": amt,
                     "when": "on_use" if kind == "consumable" else "equipped"})
    wr = r["worth"]
    worth = max(wr["min"], round(_score(attrs, wr["w"]) * wr["k"]))
    du = r["durability"]
    pr = _true(attrs, du["attr"])
    durability = {"max": max(du["min"], round(pr * du["k"]))} if pr else None
    return {"mods": mods, "worth": worth, "durability": durability}
