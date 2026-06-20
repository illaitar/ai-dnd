"""Сборка готовой к игре сессии (склейка всех слоёв)."""

from __future__ import annotations

from . import config
from .content import build_world, register_quests
from .gen import QuestSystem
from .inference import ModelManager
from .runtime import GameSession


def new_session(seed: int = config.WORLD_SEED, roster_size: int = 12,
                use_model: bool = True, scenario: str | None = None,
                pc_spec: dict | None = None) -> GameSession:
    """Строит мир (пре-ген), регистрирует квесты, возвращает игровую сессию.

    scenario/pc_spec — выбор старта новой игры. ModelManager передаётся всегда; если
    сервер недоступен, агенты возвращают None и движок идёт по детерминированным
    фоллбэкам (док 08 §9). На сессию вешается boot — параметры пре-гена для сейв/лоада.
    """
    from .content.newgame import default_scenario, resolve_pc_spec
    manager = ModelManager() if use_model else None
    model = manager if (manager and manager.available()) else None
    world = build_world(seed=seed, roster_size=roster_size, model=model,
                        scenario=scenario, pc_spec=pc_spec)
    quests = QuestSystem(world)
    register_quests(world, quests)
    session = GameSession(world, model=manager if use_model else None, quest_system=quests)
    session.boot = {"seed": seed, "roster_size": roster_size,
                    "scenario": scenario or default_scenario(),
                    "pc_spec": resolve_pc_spec(pc_spec), "baseline": world.log.count()}
    return session
