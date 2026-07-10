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

_GRAPH = None
_GPATH = os.path.join(os.path.dirname(__file__), "attrgraph.json")


def attr_graph() -> dict:
    global _GRAPH
    if _GRAPH is None:
        with open(_GPATH, encoding="utf-8") as f:
            _GRAPH = json.load(f)
    return _GRAPH
