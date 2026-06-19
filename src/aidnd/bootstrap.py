"""Сборка готовой к игре сессии (склейка всех слоёв)."""

from __future__ import annotations

from . import config
from .content import build_world, register_quests
from .gen import QuestSystem
from .inference import ModelManager
from .runtime import GameSession


def new_session(seed: int = config.WORLD_SEED, roster_size: int = 12,
                use_model: bool = True) -> GameSession:
    """Строит мир (пре-ген), регистрирует квесты, возвращает игровую сессию.

    ModelManager передаётся всегда; если сервер недоступен, агенты возвращают None
    и движок идёт по детерминированным фоллбэкам (док 08 §9).
    """
    manager = ModelManager() if use_model else None
    model = manager if (manager and manager.available()) else None
    world = build_world(seed=seed, roster_size=roster_size, model=model)
    quests = QuestSystem(world)
    register_quests(world, quests)
    return GameSession(world, model=manager if use_model else None, quest_system=quests)
