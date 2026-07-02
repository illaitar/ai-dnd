"""Игровой контур /api/play — пакет (ТД3-распил routes_play на слои).
Импорт подмодулей регистрирует эндпоинты на общем router.
"""
from .core import router
from . import items, contracts, combat, main   # noqa: F401 — регистрация эндпоинтов

__all__ = ["router"]
