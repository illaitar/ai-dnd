"""Провенанс — запись происхождения сущности (док 01 §5).

Источник, генератор, сид, таймстамп, удовлетворённые ограничения. Делает мир
объяснимым: на вопрос игрока про происхождение есть честный ответ из данных.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Provenance:
    source: str                     # authored | pregen | lazy
    generator: str = "manual@1.0"
    seed: int = 0
    tick: int = 0
    satisfied: list[str] = field(default_factory=list)
    parent_ctx: str | None = None
