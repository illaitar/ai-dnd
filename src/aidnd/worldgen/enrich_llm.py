"""Модуль использования LLM для насыщения локаций — ОТДЕЛЬНЫЙ от скрипта генерации.

Скрипт/оркестратор знают только интерфейс `Enricher.describe(ctx) -> {name, description, sub_rooms}`.
`LLMEnricher` — реальный путь (переиспользует обученный описатель мест `forge_location`).
`StubEnricher` — детерминированная заглушка (офлайн / тесты / dry-run, без сети).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BuildingCtx:
    """Что слой графа знает о здании-слоте; из этого LLM сочиняет облик и доп-помещения."""
    id: str
    name_hint: str               # стартовая подсказка типа («Таверна», «Дом у реки»…)
    role_hint: str               # «значимое здание…» | «жилой дом…»
    landmarks: list[str] = field(default_factory=list)   # river|wall|gate|bridge
    region: str = "фронтир Фэндалина"


class Enricher:
    """Интерфейс насыщения одной локации."""

    def describe(self, ctx: BuildingCtx) -> dict | None:   # noqa: D401
        raise NotImplementedError


class StubEnricher(Enricher):
    """Без LLM: детерминированный фейк. Для офлайна/тестов/dry-run."""

    def describe(self, ctx: BuildingCtx) -> dict:
        where = ", ".join(ctx.landmarks) if ctx.landmarks else "в глубине квартала"
        significant = "значим" in ctx.role_hint
        return {
            "name": ctx.name_hint,
            "description": f"{ctx.name_hint}. {ctx.role_hint.capitalize()}, {where}. (заглушка)",
            "sub_rooms": ([{"name": "Подвал", "description": "Тёмный подвал под зданием."}]
                          if significant else []),
        }


class LLMEnricher(Enricher):
    """Реальный путь: обученный описатель мест (роль location_writer) → описание + комнаты."""

    def __init__(self, manager):
        self.manager = manager

    def describe(self, ctx: BuildingCtx) -> dict | None:
        from ..inference.agents import forge_location
        res = forge_location(self.manager, ctx.name_hint, type=ctx.role_hint,
                             condition=(", ".join(ctx.landmarks) or None), region=ctx.region)
        if not res:
            return None
        return {"name": ctx.name_hint, "description": res.get("description", ""),
                "sub_rooms": [{"name": r.get("name", ""), "description": r.get("desc", "")}
                              for r in res.get("rooms", [])]}
