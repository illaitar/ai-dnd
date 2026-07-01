"""Предметы: фактшит в два слоя (surface/hidden) + модификаторы + осмотр с гейтами.

Публичный контракт:
    from aidnd.items import ItemCtx, LLMSmith, StubSmith, Capability, inspect, view, normalize

Крафт/мастерство/прочность (craft.py, durability.py) — следующий срез.
"""

from __future__ import annotations

from .craft import Recipe, craft, mastery, repair
from .durability import active_mods, condition, use
from .inspect import inspect, view
from .model import Capability, normalize
from .smith import ItemCtx, LLMSmith, Smith, StubSmith

__all__ = ["ItemCtx", "Smith", "LLMSmith", "StubSmith", "Capability",
           "inspect", "view", "normalize",
           "Recipe", "craft", "mastery", "repair", "condition", "use", "active_mods"]
