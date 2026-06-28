"""Контекст одного тика арбитра: что произошло и что вокруг.

Stimulus — событие/намерение, запустившее цикл (крик, угроза, просьба игрока, тик мира).
Context — обстановка: время, место, кто рядом, уровень опасности + опц. хук LLM-суждения.

Поля `stim.data` — это и есть входы «субъективного суждения» (точка LLM №3): онлайн их
заполняет оценщик («насколько серьёзна угроза», «поверит ли лжи», «сочна ли сплетня»),
офлайн/в тестах — передаются прямо. Так модель остаётся самодостаточной и детерминированной.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Stimulus:
    kind: str                                  # тип события/намерения (см. capabilities)
    source: str = ""                           # кто/что вызвал
    target: str = ""                           # на кого направлено
    data: dict = field(default_factory=dict)   # полезная нагрузка + LLM-оценки


@dataclass
class Context:
    stim: Stimulus
    time_hhmm: int = 1200                       # время суток HHMM (1430 = 14:30)
    place: str = ""
    here: list[str] = field(default_factory=list)   # присутствующие NPC (имена)
    allies_near: int = 0                        # сколько союзников рядом
    danger: float = 0.0                         # фоновая угроза 0..1
    world: object = None                        # реальный мир при интеграции (опц.)
    judge: object = None                        # callable(question:str, default:float)->float

    def k(self) -> str:
        return self.stim.kind

    def d(self, key: str, default=None):
        return self.stim.data.get(key, default)

    def estimate(self, question: str, default: float) -> float:
        """Точка LLM №3: субъективная оценка → скаляр. Офлайн → default."""
        if callable(self.judge):
            try:
                return float(self.judge(question, default))
            except Exception:
                return default
        return default
