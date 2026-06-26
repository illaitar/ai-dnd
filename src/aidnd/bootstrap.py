"""Сборка готовой к игре сессии (склейка всех слоёв)."""

from __future__ import annotations

from . import config
from .content import build_world, register_quests
from .gen import QuestSystem
from .inference import ModelManager
from .runtime import GameSession


def new_session(seed: int = config.WORLD_SEED, roster_size: int = 12,
                use_model: bool = True, scenario: str | None = None,
                pc_spec: dict | None = None, progress=None) -> GameSession:
    """Строит мир (пре-ген), регистрирует квесты, возвращает игровую сессию.

    scenario/pc_spec — выбор старта новой игры. ModelManager передаётся всегда; если
    сервер недоступен, агенты возвращают None и движок идёт по детерминированным
    фоллбэкам (док 08 §9). На сессию вешается boot — параметры пре-гена для сейв/лоада.
    """
    from .content.newgame import default_scenario, resolve_pc_spec
    manager = ModelManager() if use_model else None
    available = bool(manager and manager.available())
    if config.LLM_REQUIRED and not available:             # режим без фоллбэков — модель обязательна
        raise RuntimeError(
            f"LLM_REQUIRED: сервер моделей недоступен ({config.OLLAMA_HOST}). "
            "Подними Ollama (bash scripts/setup_local.sh) или сними флаг --require-llm.")
    model = manager if available else None
    world = build_world(seed=seed, roster_size=roster_size, model=model,
                        scenario=scenario, pc_spec=pc_spec)
    quests = QuestSystem(world)
    register_quests(world, quests)
    session = GameSession(world, model=manager if use_model else None, quest_system=quests)
    if model is not None and progress is not None:        # жадное обогащение на старте (под ползунок загрузки)
        from .gen.faction_gen import enrich_all
        enrich_all(world, session.charts, model, progress)
    from .gen.campaign import forge_main_quest, plan_to_quest   # сюжет — ПОСЛЕ обогащения (богаче лидеры/цели)
    if progress:
        progress(-1, -1, "Пишу сюжет кампании…")
    main_plan = forge_main_quest(world, model)
    quests.register(plan_to_quest(main_plan))
    session.boot = {"seed": seed, "roster_size": roster_size,
                    "scenario": scenario or default_scenario(),
                    "pc_spec": resolve_pc_spec(pc_spec), "baseline": world.log.count(),
                    "main_quest": main_plan}                # план в boot → переживает сейв/лоад
    return session
