"""Игровой контур /api/play — пакет. Слои: core (ядро) < items/contracts/combat (домены-механики)
< world (ядро-сцена: сессия/тик/живая сцена/голос) < доменные хендлеры (регистрируют эндпоинты).
См. docs/LOOP.md. Импорт подмодулей регистрирует эндпоинты на общем router.
"""
from . import (  # noqa: F401 — ядро-сцена + механики  # noqa: F401 — доменные хендлеры
    board,
    combat,
    contracts,
    crime,
    dialogue,
    freeform,
    item,
    items,
    magic,
    misc,
    observe,
    trade,
    travel,
    world,
)
from .core import router

__all__ = ["router"]
