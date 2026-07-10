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
