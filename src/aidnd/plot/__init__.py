"""Основной сюжет: библия (тема/правда/каст 30+ с иерархией≠важностью), архитектор, кастинг.
Игрок — регрессор. См. docs/PLOT.md."""

from __future__ import annotations

from .architect import StubArchitect
from .bible import ARCHETYPES, CATEGORIES, validate_bible
from .casting import match_cast

__all__ = ["StubArchitect", "validate_bible", "match_cast", "ARCHETYPES", "CATEGORIES"]
