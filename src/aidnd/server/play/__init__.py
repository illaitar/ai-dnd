"""Игровой контур /api/play — пакет со слоями (см. docs/loop.md):

    engine/     ядро-сцена: core (сессия/состояние/роутер/время/мана) · world (сцена/тик/голос) · worldsim
    mechanics/  домены-механики: items · contracts · combat
    handlers/   доменные хендлеры (эндпоинты): magic · dialogue · trade · crime · inventory ·
                observe · misc · board · travel · freeform

Импорт подмодулей регистрирует эндпоинты на общем router (лежит в engine.core).
"""

from .engine import world  # noqa: F401 — ядро-сцена (тик/живая сцена)
from .engine.core import router
from .handlers import (
    board,
    crime,
    dialogue,
    freeform,
    inventory,
    magic,
    misc,  # noqa: F401
    observe,
    trade,
    travel,
)
from .mechanics import combat, contracts, items  # noqa: F401 — механики

__all__ = ["router"]
