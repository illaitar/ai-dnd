"""Items: two-layer factsheet (surface/hidden) + modifiers + inspection with gates.

Public contract:
    from aidnd.items import ItemCtx, LLMSmith, StubSmith, Capability, inspect, view, normalize

Craft/mastery/durability (craft.py, durability.py) — next slice.

Key functions
-------------
ItemCtx : item with surface/hidden layers and inspection gating.
LLMSmith : LLM-powered smith for emergent item creation.
inspect(item, actor, context) -> Result : inspect items with gating rules.
view(item) -> Dict : expose surface (public) or hidden (private) item data.
Capability : enum of item capabilities and properties.
craft(recipe, materials) -> ItemCtx : forge item from recipe with durability.
normalize(item) -> Dict : canonical item representation.
"""

from __future__ import annotations

from . import loot_pool
from .attrs import attr_graph, compose, derive_effects
from .durability import active_mods, condition, use
from .graph import combine, combine_item, item_graph, node_attrs, node_item, node_lookup
from .inspect import inspect, view
from .model import ATTRS, Capability, normalize, rarity_price
from .smith import ItemCtx, LLMSmith, Smith, StubSmith

__all__ = ["ItemCtx", "Smith", "LLMSmith", "StubSmith", "Capability",
           "inspect", "view", "normalize", "rarity_price", "loot_pool",
           "condition", "use", "active_mods",
           "ATTRS", "attr_graph", "compose", "derive_effects",
           "item_graph", "node_attrs", "combine", "combine_item", "node_item", "node_lookup"]
