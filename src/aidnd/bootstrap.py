"""Сборка готовой к игре сессии (склейка всех слоёв)."""

from __future__ import annotations

from . import config
from .content import build_world, register_quests
from .gen import QuestSystem
from .inference import ModelManager
from .runtime import GameSession

# роль LLM → короткая подпись для ползунка генерации (что именно делает модель сейчас)
_ROLE_RU = {
    "lore_keeper": "знания мира", "cognition": "память жителей", "narrator": "описания",
    "location_writer": "описания мест", "loremaster": "слухи",
    "faction_gen": "фракции", "item_smith": "предметы", "quest_writer": "квесты",
    "campaign_architect": "сюжет", "campaign_director": "сюжет", "character_gen": "характеры",
    "plausibility": "проверка", "arbiter": "арбитр", "consequence": "последствия",
}


class _Progress:
    """Единый ползунок генерации новой игры: этапы задают КОНТЕКСТ-лейбл (что делаем), а каждый
    LLM-вызов двигает бар на шаг (видно прогресс между вызовами модели). total — оценка числа
    вызовов; бар не показывает 100% до завершения (фронт прячет ползунок на первом look)."""

    def __init__(self, cb, total: int) -> None:
        self.cb, self.total, self.n, self.label = cb, max(2, total), 0, "Строю мир"

    def __call__(self, done, total, label) -> None:       # этап сменил контекст (что генерим)
        if label:
            self.label = str(label).rstrip(" …")
        self._emit()

    def step(self, role=None, model=None) -> None:        # один вызов модели — двигаем бар
        self.n += 1
        self._emit(role)

    def _emit(self, role=None) -> None:
        if not self.cb:
            return
        sub = _ROLE_RU.get(role) if role else None
        self.cb(min(self.n, self.total - 1), self.total, self.label + (f" · {sub}" if sub else ""))


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
    bus = None
    if model is not None and progress is not None:        # единый ползунок: шаг на каждый LLM-вызов + лейблы этапов
        bus = _Progress(progress, total=max(40, 14 + roster_size * 3))
        manager.on_call = bus.step
    world = build_world(seed=seed, roster_size=roster_size, model=model,
                        scenario=scenario, pc_spec=pc_spec, progress=bus)
    quests = QuestSystem(world)
    register_quests(world, quests)
    session = GameSession(world, model=manager if use_model else None, quest_system=quests)
    if model is not None and bus is not None:             # жадное обогащение на старте
        from .gen.faction_gen import enrich_all
        enrich_all(world, session.charts, model, bus)
        from .gen.economy import enrich_economy            # лавки/пулы лута/новые предметы
        enrich_economy(world, model, bus)
        from .gen.locations import enrich_locations        # полные описания локаций (контекст нарратора)
        enrich_locations(world, model, bus)
    from .gen.campaign import forge_main_quest, plan_to_quest   # сюжет — ПОСЛЕ обогащения (богаче лидеры/цели)
    if bus:
        bus(0, 0, "Пишу сюжет кампании")
    main_plan = forge_main_quest(world, model)
    if manager is not None:
        manager.on_call = None                            # снять хук — в игре модель не двигает ползунок
    quests.register(plan_to_quest(main_plan))
    session.boot = {"seed": seed, "roster_size": roster_size,
                    "scenario": scenario or default_scenario(),
                    "pc_spec": resolve_pc_spec(pc_spec), "baseline": world.log.count(),
                    "main_quest": main_plan}                # план в boot → переживает сейв/лоад
    return session
