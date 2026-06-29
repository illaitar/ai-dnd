"""Параметры генерации города. Передаются снаружи (дебаг-экран/игра), детали генератора
скрыты за этим простым контрактом."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CityParams:
    seed: int = 1
    width: int = 980
    height: int = 700
    key_buildings: int = 8          # сколько ключевых зданий расставить (в равномерно разнесённые дома)
    river: bool = True              # рассекает ли город река (→ мосты)
    walls: bool = True              # обнесён ли стеной (→ ворота)
    wards: int | None = None        # число кварталов (None — на усмотрение генератора)
    segment: float | None = None    # целевая длина уличного отрезка (None — авто по медиане)

    def normalized(self) -> CityParams:
        """Защита от мусорных значений."""
        return CityParams(
            seed=int(self.seed),
            width=max(320, min(2000, int(self.width))),
            height=max(240, min(2000, int(self.height))),
            key_buildings=max(0, min(64, int(self.key_buildings))),
            river=bool(self.river),
            walls=bool(self.walls),
            wards=(None if self.wards is None else max(1, min(12, int(self.wards)))),
            segment=(None if self.segment is None else max(8.0, min(80.0, float(self.segment)))),
        )
